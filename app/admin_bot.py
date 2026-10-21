"""NexgloTV Admin WhatsApp Command Engine.

Enables authorized system administrators to perform operational and management tasks
directly through WhatsApp chat:
- Check live system status, dyno health, active LLM model, handoff counts, and DB connection
- Hot-swap LLM models (e.g. free NVIDIA NIM models like meta/llama-3.3-70b-instruct)
- Switch auto-reply mode between 'live' (AI active for all) and 'selective' (AI for unassigned leads)
- Toggle WhatsApp dry-run mode on/off
- Inspect pending human handoffs and resolve/takeover customer chats
- Manually verify customer payments and convert leads to active subscribers
- Manage reseller partner authorizations and toggle prepaid wallet models
- Authorize and manage admin phone numbers
- Trigger CRM sync and database backups

Security Guarantees:
- Strict sender verification against saved admin phone numbers (environment, DB, and Lark Base).
- ZERO information disclosure to unauthorized contacts: if an unauthorized user texts an admin command,
  the engine returns False immediately with no response or hints, letting the message fall through
  to standard customer service workflows.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.nexglo_pricing import calculate_price
from app.reseller_bot import (
    normalize_phone_sl,
    parse_direct_sale_text,
    phone_matches,
    validate_sale_inputs,
)

log = logging.getLogger("nexglo.admin_bot")


def _mask_phone(phone: str) -> str:
    """Mask middle digits of a phone number for privacy display."""
    raw = str(phone or "").strip()
    if len(raw) <= 5:
        return raw
    return f"{raw[:4]} *** {raw[-3:]}"


def parse_phone_number(text: str) -> str:
    """Extract and normalize a Sierra Leone or international phone number from text."""
    m = re.search(r"(?:(?:\+|00)?232[\s\.\-]*)?[0-9]{2}[\s\.\-]*[0-9]{3}[\s\.\-]*[0-9]{3,4}\b|\b\d{8,15}\b", str(text or ""))
    if m:
        return normalize_phone_sl(m.group(0))
    return ""


def parse_package_spec(text: str) -> tuple[int, int]:
    """Parse duration in months and device count from user/admin text."""
    clean = str(text or "").lower()
    months = 1
    devices = 1
    if "12m" in clean or "1 year" in clean or "12 month" in clean or "1y" in clean:
        months = 12
    elif "6m" in clean or "6 month" in clean:
        months = 6
    elif "3m" in clean or "3 month" in clean:
        months = 3
    elif "1m" in clean or "1 month" in clean:
        months = 1

    d_match = re.search(r"(\d+)\s*(?:device|screen|dev|tv|d\b)", clean)
    if d_match:
        try:
            devices = max(1, min(5, int(d_match.group(1))))
        except Exception:
            devices = 1
    return months, devices


class AdminBotManager:
    """Handles admin commands issued via WhatsApp chat from verified admin phone numbers."""

    def __init__(
        self,
        settings,
        store,
        llm=None,
        wa=None,
        crm=None,
        reseller_mgr=None,
        installer_mgr=None,
    ):
        self.settings = settings
        self.store = store
        self.llm = llm
        self.wa = wa
        self.crm = crm
        self.reseller_mgr = reseller_mgr
        if installer_mgr is None:
            from .installer_engine import InstallerManager
            installer_mgr = InstallerManager(crm=crm, reseller_mgr=reseller_mgr, store=store, wa=wa)
        self.installer_mgr = installer_mgr

    # =========================================================================
    # Verification & Admin Number Management
    # =========================================================================

    def get_authorized_admin_numbers(self) -> list[str]:
        """Aggregate admin phone numbers from Settings (env) and persistent Store (DB)."""
        numbers: set[str] = set()

        # 1. From environment settings
        env_raw = getattr(self.settings, "admin_phone_numbers", "") or ""
        for p in env_raw.split(","):
            clean = p.strip()
            if clean:
                numbers.add(clean)

        # 2. From persistent store / Turso DB
        if self.store and hasattr(self.store, "get_setting"):
            db_raw = self.store.get_setting("admin_phone_numbers", "") or ""
            for p in db_raw.split(","):
                clean = p.strip()
                if clean:
                    numbers.add(clean)

        return sorted(numbers)

    def is_admin(self, wa_id: str) -> bool:
        """Check if wa_id matches any registered admin number strictly."""
        if not wa_id:
            return False

        for admin_phone in self.get_authorized_admin_numbers():
            if phone_matches(wa_id, admin_phone):
                return True

        # Check Lark Base 15_Staff if CRM is connected
        if self.crm and hasattr(self.crm, "provider") and hasattr(self.crm.provider, "_get_by_wa"):
            try:
                row = self.crm.provider._get_by_wa("15_Staff", wa_id)
                if row:
                    role = str(row.get("Role") or row.get("Staff Role") or "").lower()
                    if "admin" in role or "super" in role or "manager" in role:
                        return True
            except Exception as exc:
                log.debug("Lark staff lookup check error: %s", exc)

        return False

    def add_admin_number(self, phone: str) -> bool:
        """Authorize a new admin phone number and persist to DB."""
        norm = normalize_phone_sl(phone)
        if not norm or len(re.sub(r"[^\d]", "", norm)) < 8:
            return False

        existing = set(self.get_authorized_admin_numbers())
        existing.add(norm)
        if self.store and hasattr(self.store, "set_setting"):
            self.store.set_setting("admin_phone_numbers", ",".join(sorted(existing)))
        return True

    def remove_admin_number(self, phone: str) -> bool:
        """Remove an admin phone number from persistent DB storage."""
        existing = self.get_authorized_admin_numbers()
        filtered = [p for p in existing if not phone_matches(phone, p)]
        if self.store and hasattr(self.store, "set_setting"):
            self.store.set_setting("admin_phone_numbers", ",".join(filtered))
        return True

    # =========================================================================
    # Entry Point & Dispatch
    # =========================================================================

    def handle_if_admin(self, conv, text: str) -> bool:
        """Process message if sender is a verified admin and text is an admin instruction.
        
        Security: Returns False immediately if sender is not verified, without sending any reply.
        """
        wa_id = conv.wa_id
        if not self.is_admin(wa_id):
            return False

        clean_text = (text or "").strip()
        upper = clean_text.upper()

        # Check if text is intended as an admin instruction
        is_explicit_admin = upper.startswith("ADMIN") or upper.startswith("/ADMIN")
        admin_shortcuts = {"STATUS", "MODELS", "HANDOFFS", "SYNC CRM", "ADMIN HELP", "CRM STATS", "STATS", "TOTALS", "CRM TOTALS"}
        is_shortcut = (
            upper in admin_shortcuts or
            upper.startswith("CRM ") or
            upper.startswith("SALE ") or
            upper.startswith("DIRECT SALE ") or
            upper.startswith("NEW SALE ") or
            upper.startswith("RECORD SALE ") or
            upper.startswith("ADD SALE ") or
            upper.startswith("RENEW ") or
            upper.startswith("RESUBSCRIBE ") or
            upper.startswith("RENEWAL ") or
            upper.startswith("ACTIVATE ") or
            upper.startswith("WALLET ACTIVATE ") or
            upper.startswith("CREDENTIALS ") or
            upper.startswith("SET CREDENTIALS ") or
            upper.startswith("SEND CREDENTIALS ") or
            upper.startswith("SEND LOGIN ") or
            upper.startswith("EDIT SALE ") or
            upper.startswith("UPDATE SALE ") or
            upper.startswith("INSTALL ") or
            upper.startswith("ASSIGN ") or
            upper.startswith("VERIFY INSTALL ") or
            upper.startswith("VERIFY FEE ") or
            upper.startswith("INSTALLER ") or
            upper.startswith("INSTALLERS") or
            upper.startswith("PARTNERS") or
            upper.startswith("LOCK MONTH")
        )

        if not (is_explicit_admin or is_shortcut):
            return False

        # Execute instruction
        reply = self._execute_admin_command(conv, clean_text)
        if reply:
            self._send(wa_id, reply)
            return True

        return False

    def _send(self, wa_id: str, text: str) -> None:
        """Send outbound WhatsApp message to the admin."""
        if self.wa and hasattr(self.wa, "send_text"):
            self.wa.send_text(wa_id, text)
        if self.store and hasattr(self.store, "add_message"):
            self.store.add_message(wa_id, "assistant", text, author="bot")

    # =========================================================================
    # Command Execution
    # =========================================================================

    def _execute_admin_command(self, conv, raw_text: str) -> str:
        clean = re.sub(r"^(?:/)?ADMIN\s*[:,]?\s*", "", raw_text, flags=re.IGNORECASE).strip()
        upper = clean.upper()

        # 1. ADMIN HELP
        if not upper or upper in ("HELP", "?", "COMMANDS"):
            return self._cmd_help()

        # 2. ADMIN STATUS
        if upper in ("STATUS", "INFO", "HEALTH"):
            return self._cmd_status()

        # 2b. ADMIN TOTALS / STATS / METRICS
        if upper in ("TOTALS", "STATS", "METRICS", "CRM STATS", "CRM TOTALS"):
            return self._cmd_crm_stats()

        # 3. ADMIN MODEL
        if upper.startswith("MODEL"):
            parts = clean.split(maxsplit=1)
            model_arg = parts[1].strip() if len(parts) > 1 else ""
            return self._cmd_model(model_arg)

        # 4. ADMIN MODE / POLICY
        if upper.startswith("MODE") or upper.startswith("POLICY"):
            parts = clean.split(maxsplit=1)
            mode_arg = parts[1].strip().lower() if len(parts) > 1 else ""
            return self._cmd_mode(mode_arg)

        # 5. ADMIN DRYRUN
        if upper.startswith("DRYRUN") or upper.startswith("DRY_RUN") or upper.startswith("DRY"):
            parts = clean.split(maxsplit=1)
            flag_arg = parts[1].strip().lower() if len(parts) > 1 else ""
            return self._cmd_dryrun(flag_arg)

        # 6. ADMIN HANDOFFS
        if upper in ("HANDOFFS", "QUEUE", "PENDING"):
            return self._cmd_handoffs()

        # 7. ADMIN RESOLVE <phone>
        if upper.startswith("RESOLVE"):
            parts = clean.split(maxsplit=1)
            phone_arg = parts[1].strip() if len(parts) > 1 else ""
            return self._cmd_resolve(phone_arg)

        # 8. ADMIN PAUSE / TAKEOVER <phone>
        if upper.startswith("PAUSE") or upper.startswith("TAKEOVER"):
            parts = clean.split(maxsplit=1)
            phone_arg = parts[1].strip() if len(parts) > 1 else ""
            return self._cmd_pause(phone_arg)

        # 9. ADMIN VERIFY (INSTALL / FEE / <phone>)
        if upper.startswith("VERIFY INSTALL") or upper.startswith("VERIFY_INSTALL"):
            arg = re.sub(r"^VERIFY\s+INSTALL\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_verify_install(arg)

        if upper.startswith("VERIFY FEE") or upper.startswith("VERIFY_FEE"):
            arg = re.sub(r"^VERIFY\s+FEE\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_verify_fee(arg)

        if upper.startswith("VERIFY"):
            parts = clean.split(maxsplit=1)
            phone_arg = parts[1].strip() if len(parts) > 1 else ""
            return self._cmd_verify_payment(phone_arg)

        # 10. ADMIN RESELLER
        if upper.startswith("RESELLER"):
            parts = clean.split(maxsplit=2)
            sub = parts[1].upper() if len(parts) > 1 else ""
            args = parts[2] if len(parts) > 2 else ""
            return self._cmd_reseller(sub, args)

        # 11. ADMIN WALLET <ON/OFF>
        if upper.startswith("WALLET"):
            parts = clean.split(maxsplit=1)
            flag_arg = parts[1].strip().lower() if len(parts) > 1 else ""
            return self._cmd_wallet(flag_arg)

        # 12. ADMIN NUMBERS / LIST
        if upper in ("NUMBERS", "ADMINS", "LIST"):
            return self._cmd_list_admins()

        # 13. ADMIN ADD <phone>
        if upper.startswith("ADD"):
            parts = clean.split(maxsplit=1)
            phone_arg = parts[1].strip() if len(parts) > 1 else ""
            return self._cmd_add_admin(phone_arg)

        # 14. ADMIN REMOVE <phone>
        if upper.startswith("REMOVE") or upper.startswith("DEL"):
            parts = clean.split(maxsplit=1)
            phone_arg = parts[1].strip() if len(parts) > 1 else ""
            return self._cmd_remove_admin(phone_arg)

        # 15. ADMIN SYNC
        if upper.startswith("SYNC"):
            return self._cmd_sync_lark()

        # 16. ADMIN BACKUP
        if upper.startswith("BACKUP"):
            return self._cmd_backup()

        # 17. ADMIN SALE / DIRECT SALE / NEW SALE / RECORD SALE / ADD SALE
        sale_prefixes = (
            "DIRECT SALE", "DIRECT_SALE", "DIRECT-SALE",
            "NEW SALE", "NEW_SALE",
            "RECORD SALE", "RECORD_SALE",
            "ADD SALE", "ADD_SALE",
            "SALE",
        )
        for prefix in sale_prefixes:
            if upper.startswith(prefix):
                arg = re.sub(f"^{prefix}\\s*[:,]?\\s*", "", clean, flags=re.IGNORECASE).strip()
                return self._cmd_sale(arg, is_renewal=False)

        # 18. ADMIN RENEW / RESUBSCRIBE / RENEWAL
        renew_prefixes = (
            "RESUBSCRIBE", "RESUBSCRIPTION",
            "RENEWAL", "RENEW", "RENOVAR", "RENOVACION",
        )
        for prefix in renew_prefixes:
            if upper.startswith(prefix):
                arg = re.sub(f"^{prefix}\\s*[:,]?\\s*", "", clean, flags=re.IGNORECASE).strip()
                return self._cmd_sale(arg, is_renewal=True)

        # 18b. ADMIN SET CREDENTIALS / CREDENTIALS
        if upper.startswith("SET CREDENTIALS") or upper.startswith("SET_CREDENTIALS") or upper.startswith("CREDENTIALS") or upper.startswith("ACC ") or upper.startswith("ACCOUNT "):
            arg = re.sub(r"^(?:SET\s+)?(?:CREDENTIALS|CRED|ACC|ACCOUNT)\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_set_credentials(arg)

        # 18c. ADMIN SEND CREDENTIALS
        if upper.startswith("SEND CREDENTIALS") or upper.startswith("SEND_CREDENTIALS") or upper.startswith("SEND CRED") or upper.startswith("SEND LOGIN"):
            arg = re.sub(r"^SEND\s+(?:CREDENTIALS|CRED|LOGIN|ACC)\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_send_credentials(arg)

        # 18d. ADMIN EDIT SALE / UPDATE SALE
        if upper.startswith("EDIT SALE") or upper.startswith("EDIT_SALE") or upper.startswith("UPDATE SALE") or upper.startswith("UPDATE_SALE"):
            arg = re.sub(r"^(?:EDIT|UPDATE)\s+SALE\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_edit_sale(arg)

        # 19. ADMIN CRM <subcommand>
        if upper.startswith("CRM"):
            parts = clean.split(maxsplit=2)
            sub = parts[1].upper() if len(parts) > 1 else "HELP"
            args = parts[2] if len(parts) > 2 else ""
            return self._cmd_crm(sub, args)

        # 20. ADMIN INSTALL <phone> <name> <zone> [fee] [device]
        if upper.startswith("INSTALL"):
            arg = re.sub(r"^INSTALL\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_install(arg)

        # 21. ADMIN ASSIGN <install_id> <reseller_id>
        if upper.startswith("ASSIGN"):
            arg = re.sub(r"^ASSIGN\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_assign(arg)

        # 24. ADMIN INSTALLER STATS / STATS
        if upper.startswith("INSTALLER STATS") or upper.startswith("INSTALLER_STATS"):
            arg = re.sub(r"^INSTALLER\s+STATS\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_installer_stats(arg)

        # 25. ADMIN INSTALLERS / PARTNERS
        if upper in ("INSTALLERS", "PARTNERS", "INSTALLER LIST", "PARTNER LIST"):
            return self._cmd_list_installers()

        # 26. ADMIN LOCK MONTH <reseller_id> <YYYY-MM>
        if upper.startswith("LOCK MONTH") or upper.startswith("LOCK_MONTH"):
            arg = re.sub(r"^LOCK\s+MONTH\s*[:,]?\s*", "", clean, flags=re.IGNORECASE).strip()
            return self._cmd_lock_month(arg)

        return (
            f"⚠️ Unknown admin instruction: `{clean}`\n\n"
            "Reply with *ADMIN HELP* to view the list of supported instructions."
        )

    # =========================================================================
    # Command Implementations
    # =========================================================================

    def _cmd_help(self) -> str:
        return (
            "🛠️ *NexgloTV WhatsApp Admin Console*\n\n"
            "• *ADMIN STATUS* — System health, model, DB, handoffs\n"
            "• *ADMIN SALE <phone>, <name>, <pkg>, <method>, <ref>* — Record direct sale\n"
            "• *ADMIN RENEW <phone>, <pkg>, <method>, <ref>* — Record direct renewal\n"
            "• *ADMIN CREDENTIALS <phone> <user> <pass> [server]* — Assign IPTV login details\n"
            "• *ADMIN SEND CREDENTIALS <phone>* — Send credentials directly to customer via WhatsApp\n"
            "• *ADMIN EDIT SALE <phone> [field: val]* — Update recorded sale details\n"
            "• *ADMIN CRM CUSTOMER <phone>* — Inspect subscriber in Lark Base\n"
            "• *ADMIN CRM LEAD <phone>* — Inspect lead in Lark Base\n"
            "• *ADMIN CRM STAGE <phone> <stage>* — Update lead funnel stage\n"
            "• *ADMIN CRM PAYMENT <ref>* — Inspect payment record in Lark\n"
            "• *ADMIN CRM STATS* — Summary statistics across Lark tables\n"
            "• *ADMIN MODEL <name>* — Hot-swap active LLM model\n"
            "• *ADMIN MODE <live/selective>* — Switch bot auto-reply mode\n"
            "• *ADMIN DRYRUN <on/off>* — Toggle Meta outbound API dry run\n"
            "• *ADMIN HANDOFFS* — List contacts waiting for human staff\n"
            "• *ADMIN RESOLVE <phone>* — Resolve handoff & resume AI bot\n"
            "• *ADMIN PAUSE <phone>* — Pause AI bot for a specific customer\n"
            "• *ADMIN VERIFY <phone>* — Confirm payment & activate subscriber\n"
            "• *ADMIN RESELLER LIST* — List authorized resellers & balances\n"
            "• *ADMIN RESELLER ADD <phone> <code>* — Register a partner\n"
            "• *ADMIN WALLET <on/off>* — Toggle prepaid wallet model\n"
            "• *ADMIN NUMBERS* — List authorized admin phone numbers\n"
            "• *ADMIN ADD <phone>* — Authorize a new admin phone\n"
            "• *ADMIN REMOVE <phone>* — Revoke an admin phone\n"
            "• *ADMIN SYNC* — Trigger Turso DB to Lark CRM sync\n"
            "• *ADMIN BACKUP* — Trigger full database backup\n\n"
            "💡 _All configuration changes are persisted across server reboots._"
        )

    def _cmd_status(self) -> str:
        current_model = getattr(self.llm, "model", "default")
        provider = getattr(self.settings, "llm_provider", "nvidia")
        dry_run = getattr(self.wa, "dry_run", False)
        mode = "selective"
        if self.store and hasattr(self.store, "get_setting"):
            mode = self.store.get_setting("auto_reply_mode", getattr(self.settings, "auto_reply_mode", "all"))

        conv_count = 0
        handoff_count = 0
        if self.store:
            try:
                convs = self.store.list_conversations() if hasattr(self.store, "list_conversations") else []
                conv_count = len(convs)
                handoff_count = sum(1 for c in convs if getattr(c, "handoff", False))
            except Exception:
                pass

        lark_status = "Connected (E8jOb...)" if getattr(self.settings, "lark_base_token", "") else "Not configured"
        turso_status = "Connected (Cloud)" if getattr(self.settings, "turso_database_url", "") else "Local SQLite"

        wallet_status = "Active" if getattr(self.reseller_mgr, "wallet_enabled", False) else "Disabled"

        return (
            "📊 *NexgloTV System Status Statement*\n\n"
            f"• *AI Model:* `{current_model}` ({provider})\n"
            f"• *Auto-Reply Policy:* *{mode.upper()}*\n"
            f"• *WhatsApp Dry-Run:* *{'ON (Outbox only)' if dry_run else 'OFF (Live Meta API)'}*\n"
            f"• *Database:* {turso_status} ({conv_count} customer threads)\n"
            f"• *Pending Staff Handoffs:* *{handoff_count}*\n"
            f"• *Lark Base CRM:* {lark_status}\n"
            f"• *Reseller Wallet Model:* {wallet_status}\n"
            f"• *Timestamp:* {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

    def _cmd_model(self, model_arg: str) -> str:
        free_models = [
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "deepseek-ai/deepseek-r1",
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "mistralai/mistral-large-2-instruct",
        ]

        if not model_arg:
            cur = getattr(self.llm, "model", "default")
            options = "\n".join([f"• `{m}`" for m in free_models])
            return (
                f"🧠 *Current Active Model:* `{cur}`\n\n"
                f"*Available Free NVIDIA NIM Models:*\n{options}\n\n"
                "To switch models, reply:\n`ADMIN MODEL meta/llama-3.3-70b-instruct`"
            )

        new_model = model_arg.strip()
        if self.llm and hasattr(self.llm, "set_model"):
            try:
                applied = self.llm.set_model(new_model)
                if self.store and hasattr(self.store, "set_setting"):
                    self.store.set_setting("active_model", applied)
                return f"✅ *Model Switched Successfully!*\n\n• Active LLM: `{applied}`\n• Persisted in Turso DB."
            except Exception as exc:
                return f"❌ Failed to set model: {exc}"

        return "⚠️ LLM service does not support dynamic model switching."

    def _cmd_mode(self, mode_arg: str) -> str:
        if mode_arg not in ("live", "all", "selective"):
            return (
                "⚠️ Invalid mode. Choose:\n"
                "• *ADMIN MODE LIVE* — AI replies to all incoming customer chats automatically.\n"
                "• *ADMIN MODE SELECTIVE* — AI replies only to unassigned leads; staff handles escalated chats."
            )

        applied = "all" if mode_arg in ("live", "all") else "selective"
        if self.store and hasattr(self.store, "set_setting"):
            self.store.set_setting("auto_reply_mode", applied)

        return f"✅ *Auto-Reply Mode Updated!*\n• Mode: *{applied.upper()}*\n• Persisted across reboots."

    def _cmd_dryrun(self, flag_arg: str) -> str:
        if flag_arg in ("on", "1", "true", "yes"):
            enable = True
        elif flag_arg in ("off", "0", "false", "no"):
            enable = False
        else:
            cur = getattr(self.wa, "dry_run", False)
            return (
                f"ℹ️ Current Dry-Run Mode: *{'ON' if cur else 'OFF'}*\n\n"
                "Usage:\n• `ADMIN DRYRUN ON` (Messages saved to outbox, not sent to Meta)\n"
                "• `ADMIN DRYRUN OFF` (Live delivery to WhatsApp)"
            )

        if self.wa and hasattr(self.wa, "set_dry_run"):
            self.wa.set_dry_run(enable)
        if self.store and hasattr(self.store, "set_setting"):
            self.store.set_setting("dry_run", "1" if enable else "0")

        return f"✅ *WhatsApp Dry-Run Mode Set To:* *{'ON (Outbox Only)' if enable else 'OFF (Live Delivery)'}*"

    def _cmd_handoffs(self) -> str:
        if not self.store or not hasattr(self.store, "list_conversations"):
            return "⚠️ State store unavailable."

        convs = self.store.list_conversations()
        handoffs = [c for c in convs if getattr(c, "handoff", False)]
        if not handoffs:
            return "✅ *No Pending Handoffs!* All conversations are currently managed by the bot or resolved."

        lines = [f"🚨 *Pending Staff Handoff Queue ({len(handoffs)}):*"]
        for c in handoffs[:10]:
            name = getattr(c, "profile_name", "") or c.wa_id
            lines.append(f"• `{c.wa_id}` ({name}) — State: `{c.state}`")

        lines.append("\nTo resolve a chat and resume the bot:\n`ADMIN RESOLVE <phone>`")
        return "\n".join(lines)

    def _cmd_resolve(self, phone: str) -> str:
        clean = re.sub(r"[^\d]", "", phone or "")
        if not clean:
            return "⚠️ Please provide the customer phone number to resolve:\n`ADMIN RESOLVE 076123456`"

        norm = normalize_phone_sl(clean)
        # Search conversation
        target_wa = None
        if self.store and hasattr(self.store, "list_conversations"):
            for c in self.store.list_conversations():
                if phone_matches(clean, c.wa_id):
                    target_wa = c.wa_id
                    break

        target_wa = target_wa or norm
        if self.store:
            self.store.set_handoff(target_wa, False)
            if hasattr(self.store, "resolve_handoffs"):
                self.store.resolve_handoffs(target_wa, by="admin_whatsapp")

        return f"✅ *Handoff Resolved for {target_wa}!*\nAI Bot has resumed automatic replies for this customer."

    def _cmd_pause(self, phone: str) -> str:
        clean = re.sub(r"[^\d]", "", phone or "")
        if not clean:
            return "⚠️ Please provide the customer phone number to pause:\n`ADMIN PAUSE 076123456`"

        norm = normalize_phone_sl(clean)
        target_wa = None
        if self.store and hasattr(self.store, "list_conversations"):
            for c in self.store.list_conversations():
                if phone_matches(clean, c.wa_id):
                    target_wa = c.wa_id
                    break

        target_wa = target_wa or norm
        if self.store:
            self.store.set_handoff(target_wa, True)
            if hasattr(self.store, "create_handoff"):
                self.store.create_handoff(target_wa, reason="admin_pause")

        return f"⏸️ *Bot Paused for {target_wa}!*\nThe customer is now in human staff mode. Bot will remain silent."

    def _cmd_verify_payment(self, phone: str) -> str:
        clean = (phone or "").strip()
        if not clean:
            return "⚠️ Please provide the customer phone number:\n`ADMIN VERIFY 076123456 [user: ...] [pass: ...]`"

        norm = parse_phone_number(clean) or normalize_phone_sl(clean)
        if not norm:
            return "⚠️ Could not detect customer phone number in instruction."

        target_wa = None
        if self.store and hasattr(self.store, "list_conversations"):
            for c in self.store.list_conversations():
                if phone_matches(norm, c.wa_id):
                    target_wa = c.wa_id
                    break

        target_wa = target_wa or norm

        username = ""
        password = ""
        server_url = ""
        u_match = re.search(r"(?:user(?:name)?|acc(?:ount)?|login)[:\s]+([a-zA-Z0-9_.@\-]+)", clean, re.I)
        if u_match:
            username = u_match.group(1).strip()
        p_match = re.search(r"(?:pass(?:word)?|pwd)[:\s]+([a-zA-Z0-9_.@\-!#%]+)", clean, re.I)
        if p_match:
            password = p_match.group(1).strip()
        s_match = re.search(r"(?:server(?:_url)?|portal|url)[:\s]+(https?://[^\s,;]+|[a-zA-Z0-9.\-]+:\d+)", clean, re.I)
        if s_match:
            server_url = s_match.group(1).strip()

        if self.crm and hasattr(self.crm, "confirm_payment_and_convert"):
            customer = self.crm.confirm_payment_and_convert(
                wa_id=target_wa,
                payment_id=f"PAY-ADM-{int(time.time())}",
                verified_by="admin_whatsapp",
                account_username=username,
                account_password=password,
                server_url=server_url,
            )
            if customer:
                if self.store:
                    self.store.set_customer_flag(target_wa, True, customer.customer_id)
                    self.store.set_handoff(target_wa, False)

                cred_line = ""
                if customer.account_username:
                    cred_line = (
                        f"\n• IPTV Username: `{customer.account_username}`\n"
                        f"• IPTV Password: `{customer.account_password}`\n"
                        f"• Server URL: `{customer.server_url or 'Default'}`\n\n"
                        f"💡 To send login details to customer via WhatsApp:\n`ADMIN SEND CREDENTIALS {target_wa}`"
                    )
                else:
                    cred_line = (
                        f"\n\n💡 To set customer IPTV credentials:\n`ADMIN CREDENTIALS {target_wa} <username> <password>`"
                    )

                return (
                    f"✅ *Payment Confirmed & Subscriber Activated!*\n\n"
                    f"• Customer: {customer.name} ({target_wa})\n"
                    f"• ID: `{customer.customer_id}`\n"
                    f"• Duration: {customer.subscription_months} month(s)\n"
                    f"• Expiry: {customer.subscription_expires_at}{cred_line}\n"
                    f"• Synced to Lark Base `03_Customers` and `05_Subscriptions`."
                )

        return f"⚠️ Could not complete payment verification for {target_wa}. Ensure lead exists in CRM."

    def _cmd_reseller(self, sub: str, args: str) -> str:
        if not self.reseller_mgr:
            return "⚠️ Reseller manager not initialized."

        if sub == "LIST":
            resellers = list(self.reseller_mgr._resellers_by_code.values())
            if not resellers:
                return "ℹ️ No resellers currently registered."
            lines = [f"🤝 *Registered Reseller Partners ({len(resellers)}):*"]
            for r in resellers:
                lines.append(
                    f"• *{r.name}* (`{r.reseller_code}`)\n"
                    f"  Phone: `{r.phone}` | Wallet: Le{r.wallet_balance:,} | Comm: Le{r.approved_commissions:,}"
                )
            return "\n".join(lines)

        if sub == "ADD":
            # Usage: ADMIN RESELLER ADD <phone> <code> [name]
            parts = args.split()
            if len(parts) < 2:
                return "Usage: `ADMIN RESELLER ADD <phone> <reseller_code> [Business Name]`\nExample: `ADMIN RESELLER ADD 076123456 RES-KOROMA Koroma Ent`"
            phone = parts[0]
            code = parts[1].upper()
            name = " ".join(parts[2:]) if len(parts) > 2 else f"Partner {code}"
            from app.reseller_bot import ResellerProfile
            norm_phone = normalize_phone_sl(phone)
            res_id = f"RES-{int(time.time())}"
            profile = ResellerProfile(
                reseller_id=res_id,
                reseller_code=code,
                name=name,
                phone=norm_phone,
                wallet_balance=1000,
            )
            self.reseller_mgr.register_reseller(profile)

            # Sync to Lark Base 09_Resellers
            if self.crm and hasattr(self.crm, "provider") and hasattr(self.crm.provider, "_upsert_by_key"):
                try:
                    self.crm.provider._upsert_by_key("09_Resellers", {
                        "Reseller ID": res_id,
                        "Reseller Code": code,
                        "Business or Full Name": name,
                        "Primary Contact": name,
                        "WhatsApp Number": norm_phone,
                        "Status": "Active",
                        "Operating Model": "DIRECT_TO_NEXGLOTV",
                        "Default Commission Rate %": 20,
                        "Default Commission Method": "Percentage",
                        "Joined At": datetime.now(timezone.utc).isoformat(),
                        "Onboarding Verified": True,
                    })
                except Exception as exc:
                    log.warning("Failed to sync new reseller to Lark 09_Resellers: %s", exc)

            return f"✅ *Reseller Added Successfully!*\n• Code: `{code}`\n• Name: {name}\n• Phone: `{profile.phone}`\n• Synced to Lark Base `09_Resellers`."

        return "Usage:\n• `ADMIN RESELLER LIST`\n• `ADMIN RESELLER ADD <phone> <code> [name]`"

    def _cmd_wallet(self, flag: str) -> str:
        if not self.reseller_mgr:
            return "⚠️ Reseller manager not initialized."

        if flag in ("on", "1", "true", "yes", "enable"):
            self.reseller_mgr.wallet_enabled = True
            if self.store and hasattr(self.store, "set_setting"):
                self.store.set_setting("wallet_model_enabled", "1")
            return "✅ *Reseller Prepaid Wallet Model ENABLED!* Partners can now activate lines via `ACTIVATE`."
        elif flag in ("off", "0", "false", "no", "disable"):
            self.reseller_mgr.wallet_enabled = False
            if self.store and hasattr(self.store, "set_setting"):
                self.store.set_setting("wallet_model_enabled", "0")
            return "⏸️ *Reseller Prepaid Wallet Model DISABLED.* Direct customer sales only."
        else:
            cur = self.reseller_mgr.wallet_enabled
            return f"ℹ️ Reseller Wallet Model Status: *{'ENABLED' if cur else 'DISABLED'}*\nUse `ADMIN WALLET ON` or `ADMIN WALLET OFF`."

    def _cmd_list_admins(self) -> str:
        admins = self.get_authorized_admin_numbers()
        if not admins:
            return "⚠️ No admin numbers currently saved. Set `ADMIN_PHONE_NUMBERS` in environment or use `ADMIN ADD <phone>`."
        lines = [f"🔐 *Authorized Admin Phone Numbers ({len(admins)}):*"]
        for p in admins:
            lines.append(f"• `{_mask_phone(p)}`")
        lines.append("\nTo add or revoke numbers:\n• `ADMIN ADD <phone>`\n• `ADMIN REMOVE <phone>`")
        return "\n".join(lines)

    def _cmd_add_admin(self, phone: str) -> str:
        clean = re.sub(r"[^\d]", "", phone or "")
        if not clean or len(clean) < 8:
            return "⚠️ Please provide a valid phone number to authorize as admin:\n`ADMIN ADD 076123456`"

        norm = normalize_phone_sl(clean)
        self.add_admin_number(norm)
        return f"✅ *Admin Number Authorized!*\n`{_mask_phone(norm)}` can now issue administrative commands."

    def _cmd_remove_admin(self, phone: str) -> str:
        clean = re.sub(r"[^\d]", "", phone or "")
        if not clean:
            return "⚠️ Please provide a phone number to revoke:\n`ADMIN REMOVE 076123456`"

        norm = normalize_phone_sl(clean)
        self.remove_admin_number(norm)
        return f"🗑️ *Admin Privileges Revoked for `{_mask_phone(norm)}`.*"

    def _cmd_sync_lark(self) -> str:
        if not self.crm or not hasattr(self.crm, "provider"):
            return "⚠️ Lark CRM provider unavailable."

        provider = self.crm.provider
        if not hasattr(provider, "upsert_lead"):
            return "⚠️ CRM provider does not support direct lead sync."

        # Perform sync
        try:
            sql = "SELECT wa_id, state, profile_name, last_user_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 100"
            rows = []
            if self.store and hasattr(self.store, "_connect"):
                with self.store._connect() as con:
                    rows = [dict(r) for r in con.execute(sql).fetchall()]

            from app.crm_sheets import LeadRecord
            leads: list[LeadRecord] = []
            for idx, r in enumerate(rows):
                wa = str(r.get("wa_id") or "").strip()
                if not wa:
                    continue
                leads.append(LeadRecord(
                    lead_id=f"LEAD-SYNC-{int(time.time())}-{idx}",
                    wa_id=wa,
                    phone_e164=normalize_phone_sl(wa),
                    name=r.get("profile_name") or f"WhatsApp Contact {wa[-4:]}",
                    source="whatsapp",
                    lead_stage="ACTIVE_CHAT",
                    last_message_at=str(r.get("last_user_at") or r.get("updated_at") or ""),
                ))

            synced = 0
            last_err = ""
            if hasattr(provider, "batch_upsert_leads"):
                synced, errors, last_err = provider.batch_upsert_leads(leads)
            else:
                for lead in leads:
                    try:
                        if provider.upsert_lead(lead):
                            synced += 1
                    except Exception as e:
                        last_err = str(e)

            if synced > 0:
                return f"✅ *Lark CRM Sync Complete!*\nSynchronized {synced} customer records to Lark Base `01_Leads`."
            elif last_err:
                return f"❌ *Lark CRM Sync Error:*\n{last_err}"
            return "ℹ️ No records needed synchronization."
        except Exception as exc:
            return f"❌ CRM Sync failed: {exc}"


    def _cmd_backup(self) -> str:
        if not self.store or not hasattr(self.store, "export_backup"):
            return "⚠️ Backup function unavailable."

        try:
            data = self.store.export_backup()
            conv_count = len(data.get("conversations", []))
            msg_count = len(data.get("messages", []))
            return (
                "💾 *Database Backup Exported Successfully!*\n\n"
                f"• Conversations: *{conv_count}*\n"
                f"• Messages: *{msg_count}*\n"
                f"• Settings: *{len(data.get('settings', {}))}*\n"
                "Data is backed up in Turso Cloud DB and local disk storage."
            )
        except Exception as exc:
            return f"❌ Backup failed: {exc}"

    # =========================================================================
    # Direct Sales & Renewals (Non-Reseller Organic Sales)
    # =========================================================================

    def _cmd_sale(self, arg: str, is_renewal: bool = False) -> str:
        if not arg or not arg.strip():
            if is_renewal:
                return (
                    "ℹ️ *NexgloTV Direct Renewal Command*\n\n"
                    "You can record a renewal in any flexible format:\n"
                    "• `ADMIN RENEW 076123456, 1mo 1dev, Orange Money, OM778899`\n"
                    "• `ADMIN RENEW 076123456 1 month Orange Money OM1234`\n"
                    "• `ADMIN RENEW +23278999888 3 months Afrimoney`\n\n"
                    "The bot automatically identifies customer phone, renewal package, payment method, and reference!"
                )
            return (
                "ℹ️ *NexgloTV Direct Sale Command*\n\n"
                "You can record a sale in any flexible format (commas, spaces, or labels):\n"
                "• `ADMIN SALE 076123456, John Kamara, 1mo 1dev, Orange Money, OM123456`\n"
                "• `ADMIN SALE 076123456 John Kamara 1m 1d Orange Money OM123456`\n"
                "• `ADMIN SALE John Kamara 076123456 3 months Afrimoney`\n"
                "• `ADMIN SALE +23278999888 Fatmata Sesay 1 year cash`\n\n"
                "The bot automatically identifies customer phone, package, payment method, reference, and name in ANY order!"
            )

        parsed = parse_direct_sale_text(arg, is_renewal=is_renewal)
        if not parsed:
            if is_renewal:
                return (
                    "⚠️ Could not detect a valid customer phone number for renewal.\n\n"
                    "Usage:\n"
                    "• `ADMIN RENEW <phone> <package> <method> <reference>`\n\n"
                    "Examples:\n"
                    "• `ADMIN RENEW 076123456 1m 1dev Orange Money OM778899`\n"
                    "• `ADMIN RENEW +23278999888 3 months Afrimoney`"
                )
            else:
                return (
                    "⚠️ Could not detect a valid customer phone number in your instruction.\n\n"
                    "Usage:\n"
                    "• `ADMIN SALE <phone>, <name>, <package>, <method>, <reference>`\n\n"
                    "Examples in any order:\n"
                    "• `ADMIN SALE 076123456 John Kamara 1m 1d Orange Money OM123456`\n"
                    "• `ADMIN SALE John Kamara 076123456 3 months 2 devices Afrimoney AF554433`\n"
                    "• `ADMIN SALE +23278999888 Fatmata Sesay 1 year cash`"
                )

        phone = parsed["customer_phone"]
        existing = self._get_customer(phone)
        is_resub = is_renewal or parsed.get("is_renewal", False) or (existing is not None)
        if existing and (not parsed.get("customer_name") or parsed.get("customer_name").startswith("Customer ")):
            parsed["customer_name"] = existing.name or parsed.get("customer_name")

        # Validate commercial parameters
        is_valid, err = validate_sale_inputs(
            customer_phone=parsed["customer_phone"],
            customer_name=parsed["customer_name"],
            months=parsed["months"],
            devices=parsed["devices"],
            payment_method=parsed["payment_method"],
            payment_reference=parsed["payment_reference"],
            is_renewal=is_resub,
        )
        if not is_valid:
            return err

        return self._process_direct_sale_record(parsed, is_renewal=is_resub)

    def _process_direct_sale_record(self, parsed: dict, is_renewal: bool = False) -> str:
        from app.crm_sheets import CustomerRecord, PaymentRecord, LeadRecord

        phone = parsed["customer_phone"]
        name = parsed["customer_name"]
        months = parsed["months"]
        devices = parsed["devices"]
        method = parsed["payment_method"]
        ref = parsed["payment_reference"]

        existing = self._get_customer(phone)
        is_resub = is_renewal or (existing is not None)
        resolved_name = name or (existing.name if existing else "Direct Customer")

        quote = calculate_price(months, devices)
        sale_amount = quote.final_price
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        event_ts = int(time.time())

        if is_resub and existing:
            customer_id = existing.customer_id
            lead_id = existing.source_lead_id or f"LEAD-DIR-{event_ts}"
            renewal_count = (existing.renewal_count or 0) + 1
            base_exp = now_dt
            if existing.subscription_expires_at:
                try:
                    cur_exp = datetime.fromisoformat(existing.subscription_expires_at.replace("Z", "+00:00"))
                    if cur_exp > now_dt:
                        base_exp = cur_exp
                except Exception:
                    pass
            expires_iso = (base_exp + timedelta(days=months * 30)).isoformat()
        else:
            customer_id = f"CUST-DIR-{event_ts}"
            lead_id = f"LEAD-DIR-{event_ts}"
            renewal_count = 0
            expires_iso = (now_dt + timedelta(days=months * 30)).isoformat()

        # 1. Upsert Customer to 03_Customers (and 05_Subscriptions)
        customer = CustomerRecord(
            customer_id=customer_id,
            source_lead_id=lead_id,
            wa_id=phone,
            phone_e164=phone,
            name=resolved_name,
            device_count=devices,
            subscription_months=months,
            package_code=f"{months}m_{devices}d",
            amount_paid_le=sale_amount,
            payment_method=method,
            transaction_reference=ref,
            payment_verified_at=now_iso,
            activation_at=now_iso,
            subscription_expires_at=expires_iso,
            account_status="active",
            reseller_code="DIRECT",
            renewal_count=renewal_count,
            last_renewed_at=now_iso if renewal_count > 0 else "",
            created_at=existing.created_at if existing and existing.created_at else now_iso,
            updated_at=now_iso,
            account_username=parsed.get("account_username") or (getattr(existing, "account_username", "") if existing else ""),
            account_password=parsed.get("account_password") or (getattr(existing, "account_password", "") if existing else ""),
            server_url=parsed.get("server_url") or (getattr(existing, "server_url", "") if existing else ""),
        )
        self._upsert_customer(customer)

        # 2. Upsert Payment to 06_Payments
        payment = PaymentRecord(
            payment_id=f"PAY-DIR-{event_ts}",
            lead_id=lead_id,
            customer_id=customer_id,
            phone_e164=phone,
            expected_amount_le=sale_amount,
            method=method,
            transaction_reference=ref,
            proof_received_at=now_iso,
            status="confirmed",
            verified_by="admin_whatsapp",
            verified_at=now_iso,
            note=f"Admin direct {'renewal' if is_resub else 'sale'} recorded via WhatsApp ({method})",
            created_at=now_iso,
        )
        self._upsert_payment(payment)

        # 3. Upsert Lead to 01_Leads marked CONVERTED
        lead = LeadRecord(
            lead_id=lead_id,
            wa_id=phone,
            phone_e164=phone,
            name=resolved_name,
            source="direct_sale",
            lead_stage="CONVERTED",
            subscription_quote_le=sale_amount,
            months=months,
            device_count=devices,
            payment_status="confirmed",
            reseller_code="DIRECT",
            updated_at=now_iso,
        )
        self._upsert_lead(lead)

        # 4. Update Turso DB conversation state
        if self.store:
            if hasattr(self.store, "set_customer_flag"):
                self.store.set_customer_flag(phone, True, customer_id)
            if hasattr(self.store, "set_handoff"):
                self.store.set_handoff(phone, False)

        cred_info = ""
        if customer.account_username:
            cred_info = f"\n• IPTV Username: `{customer.account_username}`\n• IPTV Password: `{customer.account_password}`\n• Server URL: `{customer.server_url or 'Default'}`"

        # Format confirmation response
        if is_resub and renewal_count > 0:
            return (
                "✅ *Direct Renewal Recorded & Subscription Extended!*\n\n"
                f"• Customer: *{resolved_name}* (`{phone}`)\n"
                f"• Customer ID: `{customer_id}`\n"
                f"• Plan: {months} month(s) × {devices} device(s)\n"
                f"• Renewal Count: *{renewal_count}*\n"
                f"• Amount Paid: Le{sale_amount:,} ({method})\n"
                f"• Reference: `{ref}`\n"
                f"• New Expiry: {expires_iso[:10]}{cred_info}\n"
                "• Synced to Lark Base `03_Customers` & `05_Subscriptions`."
            )
        else:
            return (
                "✅ *Direct Sale Recorded & Customer Activated!*\n\n"
                f"• Customer: *{resolved_name}* (`{phone}`)\n"
                f"• Customer ID: `{customer_id}`\n"
                f"• Plan: {months} month(s) × {devices} device(s)\n"
                f"• Amount Paid: Le{sale_amount:,} ({method})\n"
                f"• Reference: `{ref}`\n"
                f"• Expiry Date: {expires_iso[:10]}{cred_info}\n"
                "• Reseller: `DIRECT` (No commission)\n"
                "• Synced to Lark Base `01_Leads`, `03_Customers`, `05_Subscriptions`, & `06_Payments`."
            )

    def _cmd_set_credentials(self, arg: str) -> str:
        if not arg or not arg.strip():
            return (
                "ℹ️ *Set Customer Account Credentials*\n\n"
                "Assign IPTV login credentials to a customer account:\n"
                "• `ADMIN CREDENTIALS <phone> <username> <password> [server_url]`\n"
                "• `ADMIN CREDENTIALS 076123456 foday77 pass88 http://stream.nexglotv.com:8080`\n"
                "• `ADMIN CREDENTIALS 076123456 user: foday77 pass: pass88`\n\n"
                "Credentials will be synced directly to Lark Base `03_Customers`."
            )

        phone = parse_phone_number(arg)
        if not phone:
            return "⚠️ Could not detect a valid customer phone number in your instruction."

        customer = self._get_customer(phone)
        if not customer:
            return f"⚠️ No customer record found for `{phone}`. Please register the customer first with `ADMIN SALE`."

        username = ""
        password = ""
        server_url = ""

        u_match = re.search(r"(?:user(?:name)?|acc(?:ount)?|iptv_user)[:\s]+([a-zA-Z0-9_.@\-]+)", arg, re.I)
        if u_match:
            username = u_match.group(1).strip()
        p_match = re.search(r"(?:pass(?:word)?|pwd|iptv_pass)[:\s]+([a-zA-Z0-9_.@\-!#%]+)", arg, re.I)
        if p_match:
            password = p_match.group(1).strip()
        s_match = re.search(r"(?:server(?:_url)?|portal|url|host)[:\s]+(https?://[^\s,;]+|[a-zA-Z0-9.\-]+:\d+)", arg, re.I)
        if s_match:
            server_url = s_match.group(1).strip()

        if not username or not password:
            clean_arg = arg
            phone_raw = re.search(r"(?:(?:\+|00)?232[\s\.\-]*)?[0-9]{2}[\s\.\-]*[0-9]{3}[\s\.\-]*[0-9]{3,4}\b|\b\d{8,15}\b", clean_arg)
            if phone_raw:
                clean_arg = clean_arg.replace(phone_raw.group(0), " ")
            tokens = [t.strip(",.:;#-()\"'") for t in clean_arg.split() if t.strip(",.:;#-()\"'")]
            if len(tokens) >= 2:
                if not username:
                    username = tokens[0]
                if not password:
                    password = tokens[1]
                if not server_url and len(tokens) >= 3:
                    server_url = tokens[2]

        if not username or not password:
            return (
                "⚠️ Username and password are required.\n"
                "Usage: `ADMIN CREDENTIALS <phone> <username> <password> [server_url]`"
            )

        if not server_url:
            server_url = customer.server_url or "http://stream.nexglotv.com:8080"

        customer.account_username = username
        customer.account_password = password
        customer.server_url = server_url
        self._upsert_customer(customer)

        return (
            "✅ *Account Credentials Saved & Synced!*\n\n"
            f"• Customer: *{customer.name}* (`{customer.wa_id}`)\n"
            f"• IPTV Username: `{username}`\n"
            f"• IPTV Password: `{password}`\n"
            f"• Server URL: `{server_url}`\n"
            "• Synced to Lark Base `03_Customers`.\n\n"
            f"💡 To send to customer via WhatsApp:\n`ADMIN SEND CREDENTIALS {phone}`"
        )

    def _cmd_send_credentials(self, phone_arg: str) -> str:
        clean = (phone_arg or "").strip()
        if not clean:
            return "⚠️ Please specify customer phone:\n`ADMIN SEND CREDENTIALS 076123456`"

        phone = parse_phone_number(clean) or normalize_phone_sl(clean)
        customer = self._get_customer(phone)
        if not customer:
            return f"⚠️ No customer found for `{phone}`."

        if not customer.account_username or not customer.account_password:
            return (
                f"⚠️ Customer *{customer.name}* has no credentials saved yet.\n"
                f"Set credentials first:\n`ADMIN CREDENTIALS {phone} <username> <password>`"
            )

        server = customer.server_url or "http://stream.nexglotv.com:8080"
        exp_str = customer.subscription_expires_at[:10] if customer.subscription_expires_at else "Active"
        msg = (
            "📺 *Your NexgloTV Subscription Credentials*\n\n"
            "Here are your official login details to access all channels and movies:\n\n"
            f"• *Server URL:* `{server}`\n"
            f"• *Username:* `{customer.account_username}`\n"
            f"• *Password:* `{customer.account_password}`\n"
            f"• *Subscription:* {customer.subscription_months} Month(s) × {customer.device_count} Screen(s)\n"
            f"• *Status:* Active (Expires: {exp_str})\n\n"
            "📱 Enter these details into your NexgloTV App, IPTV Smarters, or XCIPTV to start streaming immediately!\n"
            "If you need setup assistance or a download link, reply *HELP* anytime."
        )
        self._send(customer.wa_id, msg)

        return (
            f"✅ *Credentials Successfully Delivered to Customer!*\n\n"
            f"• Recipient: *{customer.name}* (`{customer.wa_id}`)\n"
            f"• Username: `{customer.account_username}`\n"
            f"• Delivered via WhatsApp Meta API."
        )

    def _cmd_edit_sale(self, arg: str) -> str:
        if not arg or not arg.strip():
            return (
                "ℹ️ *Edit Recorded Sale Command*\n\n"
                "Update specific fields of an existing customer sale:\n"
                "• `ADMIN EDIT SALE 076123456 name: John Koroma`\n"
                "• `ADMIN EDIT SALE 076123456 user: jkoroma pass: secret99`\n"
                "• `ADMIN EDIT SALE 076123456 package: 3 months 2 devices`\n"
                "• `ADMIN EDIT SALE 076123456 ref: OM998877 method: Afrimoney`\n\n"
                "Updates are synced to Lark Base `03_Customers`, `05_Subscriptions`, and `06_Payments`."
            )

        phone = parse_phone_number(arg)
        if not phone:
            return "⚠️ Could not detect customer phone number in your instruction."

        customer = self._get_customer(phone)
        if not customer:
            return f"⚠️ No customer record found for `{phone}`. Use `ADMIN SALE` to register a new sale."

        updated_fields = []

        # 1. Name
        label_m = re.search(r"(?:name|customer|nombre)[:\s]+(.+?)(?=\s+(?:user|pass|server|pkg|package|ref|method|price)|$)", arg, re.I)
        if label_m:
            new_name = label_m.group(1).strip()
            if new_name and len(new_name) >= 2:
                customer.name = new_name
                updated_fields.append(f"Name: *{new_name}*")

        # 2. Credentials
        u_match = re.search(r"(?:user(?:name)?|acc(?:ount)?|iptv_user)[:\s]+([a-zA-Z0-9_.@\-]+)", arg, re.I)
        if u_match:
            customer.account_username = u_match.group(1).strip()
            updated_fields.append(f"Username: `{customer.account_username}`")

        p_match = re.search(r"(?:pass(?:word)?|pwd|iptv_pass)[:\s]+([a-zA-Z0-9_.@\-!#%]+)", arg, re.I)
        if p_match:
            customer.account_password = p_match.group(1).strip()
            updated_fields.append(f"Password: `{customer.account_password}`")

        s_match = re.search(r"(?:server(?:_url)?|portal|url|host)[:\s]+(https?://[^\s,;]+|[a-zA-Z0-9.\-]+:\d+)", arg, re.I)
        if s_match:
            customer.server_url = s_match.group(1).strip()
            updated_fields.append(f"Server URL: `{customer.server_url}`")

        # 3. Package
        if any(w in arg.lower() for w in ("month", "year", "dev", "screen", "pkg", "package", "1m", "3m", "6m", "12m")):
            months, devices = parse_package_spec(arg)
            if months != customer.subscription_months or devices != customer.device_count:
                customer.subscription_months = months
                customer.device_count = devices
                quote = calculate_price(months, devices)
                customer.amount_paid_le = quote.final_price
                customer.package_code = f"{months}m_{devices}d"
                now_dt = datetime.now(timezone.utc)
                customer.subscription_expires_at = (now_dt + timedelta(days=months * 30)).isoformat()
                updated_fields.append(f"Plan: {months}m × {devices}d (Le{quote.final_price:,})")

        # 4. Payment Reference
        ref_match = re.search(r"(?:ref(?:erence)?|txn(?:\s*id)?|code)[:\s]+([a-zA-Z0-9\-_]{4,32})", arg, re.I)
        if ref_match:
            customer.transaction_reference = ref_match.group(1).strip()
            updated_fields.append(f"Payment Ref: `{customer.transaction_reference}`")

        # 5. Payment Method
        if "orange" in arg.lower():
            customer.payment_method = "Orange Money"
            updated_fields.append("Method: Orange Money")
        elif "afri" in arg.lower():
            customer.payment_method = "Afrimoney"
            updated_fields.append("Method: Afrimoney")
        elif "bank" in arg.lower() or "transfer" in arg.lower():
            customer.payment_method = "Bank Transfer"
            updated_fields.append("Method: Bank Transfer")
        elif "cash" in arg.lower():
            customer.payment_method = "Cash"
            updated_fields.append("Method: Cash")

        if not updated_fields:
            return "⚠️ No valid field updates detected. Use `name: ...`, `user: ...`, `pass: ...`, `ref: ...`, or `package: ...`."

        self._upsert_customer(customer)

        summary = "\n".join([f"• {f}" for f in updated_fields])
        return (
            f"✅ *Customer Sale Info Updated!*\n\n"
            f"• Customer: *{customer.name}* (`{customer.wa_id}`)\n"
            f"{summary}\n\n"
            "• Synced to Lark Base `03_Customers` & `05_Subscriptions`."
        )

    # =========================================================================
    # Lark CRM WhatsApp Actions
    # =========================================================================

    def _cmd_crm(self, sub: str, args: str) -> str:
        sub_upper = (sub or "").strip().upper()
        clean_args = (args or "").strip()

        if not sub_upper or sub_upper in ("HELP", "?"):
            return self._cmd_crm_help()

        if sub_upper in ("CUSTOMER", "CUST"):
            return self._cmd_crm_customer(clean_args)

        if sub_upper == "LEAD":
            return self._cmd_crm_lead(clean_args)

        if sub_upper == "STAGE":
            return self._cmd_crm_stage(clean_args)

        if sub_upper in ("PAYMENT", "PAY"):
            return self._cmd_crm_payment(clean_args)

        if sub_upper in ("STATS", "SUMMARY"):
            return self._cmd_crm_stats()

        return (
            f"⚠️ Unknown CRM subcommand: `{sub}`\n\n"
            "Supported CRM commands:\n"
            "• `ADMIN CRM CUSTOMER <phone>`\n"
            "• `ADMIN CRM LEAD <phone>`\n"
            "• `ADMIN CRM STAGE <phone> <new_stage>`\n"
            "• `ADMIN CRM PAYMENT <ref_or_phone>`\n"
            "• `ADMIN CRM STATS`\n"
            "• `ADMIN CRM HELP`"
        )

    def _cmd_crm_help(self) -> str:
        return (
            "📋 *NexgloTV Lark CRM Admin Console*\n\n"
            "• *ADMIN CRM CUSTOMER <phone>*\n"
            "  Inspect customer profile, subscription status, and expiry.\n\n"
            "• *ADMIN CRM LEAD <phone>*\n"
            "  Inspect lead funnel stage, quotes, and notes.\n\n"
            "• *ADMIN CRM STAGE <phone> <new_stage>*\n"
            "  Update lead funnel stage in Lark Base (e.g. QUOTED, TRIAL, CONVERTED, LOST).\n\n"
            "• *ADMIN CRM PAYMENT <ref_or_phone>*\n"
            "  Inspect payment status, verification, and transaction details.\n\n"
            "• *ADMIN CRM STATS*\n"
            "  Display live statistics across all Lark CRM tables.\n\n"
            "• *ADMIN SALE <phone>, <name>, <pkg>, <method>, <ref>*\n"
            "  Record a direct organic customer sale (non-reseller).\n\n"
            "• *ADMIN RENEW <phone>, <pkg>, <method>, <ref>*\n"
            "  Record an organic subscription renewal."
        )

    def _cmd_crm_customer(self, phone: str) -> str:
        clean = re.sub(r"[^\d]", "", phone or "")
        if not clean:
            return "⚠️ Please provide a customer phone number:\n`ADMIN CRM CUSTOMER 076123456`"
        norm = normalize_phone_sl(clean)
        cust = self._get_customer(norm)
        if not cust:
            return (
                f"ℹ️ No customer record found for `{norm}` in Lark Base `03_Customers`.\n\n"
                f"Try `ADMIN CRM LEAD {phone}` to check lead status or `ADMIN SALE` to register a sale."
            )

        status_note = cust.account_status.upper()
        if cust.subscription_expires_at:
            try:
                exp_dt = datetime.fromisoformat(cust.subscription_expires_at.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                diff = (exp_dt - now_dt).days
                if diff > 0:
                    status_note = f"ACTIVE ({diff} days left)"
                elif diff == 0:
                    status_note = "EXPIRING TODAY"
                else:
                    status_note = f"EXPIRED ({abs(diff)} days ago)"
            except Exception:
                pass

        return (
            f"👤 *Lark CRM Customer Profile*\n\n"
            f"• Name: *{cust.name}*\n"
            f"• Customer ID: `{cust.customer_id}`\n"
            f"• WhatsApp: `{cust.wa_id}`\n"
            f"• Account Status: *{status_note}*\n"
            f"• Subscription Plan: {cust.subscription_months} month(s) × {cust.device_count} device(s)\n"
            f"• Amount Paid: Le{cust.amount_paid_le:,} ({cust.payment_method or 'Direct'})\n"
            f"• Payment Ref: `{cust.transaction_reference or 'N/A'}`\n"
            f"• Expiry Date: {cust.subscription_expires_at[:10] if cust.subscription_expires_at else 'N/A'}\n"
            f"• IPTV Username: `{cust.account_username or 'Not Set'}`\n"
            f"• IPTV Password: `{cust.account_password or 'Not Set'}`\n"
            f"• Server URL: `{cust.server_url or 'Default'}`\n"
            f"• Renewal Count: {cust.renewal_count}\n"
            f"• Reseller / Origin: `{cust.reseller_code or 'DIRECT'}`\n"
            "• Synced to Lark Base `03_Customers` & `05_Subscriptions`."
        )

    def _cmd_crm_lead(self, phone: str) -> str:
        clean = re.sub(r"[^\d]", "", phone or "")
        if not clean:
            return "⚠️ Please provide a lead phone number:\n`ADMIN CRM LEAD 076123456`"
        norm = normalize_phone_sl(clean)
        lead = self._get_lead(norm)
        if not lead:
            return f"ℹ️ No lead record found for `{norm}` in Lark Base `01_Leads`."

        return (
            f"🎯 *Lark CRM Lead Profile*\n\n"
            f"• Name: *{lead.name}*\n"
            f"• Lead ID: `{lead.lead_id}`\n"
            f"• WhatsApp: `{lead.wa_id}`\n"
            f"• Stage: *{lead.lead_stage}*\n"
            f"• Lead Source: {lead.source}\n"
            f"• Quote: Le{lead.subscription_quote_le:,} ({lead.months}mo × {lead.device_count}dev)\n"
            f"• Payment Status: {lead.payment_status or 'N/A'}\n"
            f"• Partner / Referrer: `{lead.reseller_code or lead.referrer_code or 'DIRECT'}`\n"
            f"• Notes: {lead.notes or 'None'}\n"
            "• Synced to Lark Base `01_Leads`."
        )

    def _cmd_crm_stage(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return (
                "⚠️ Usage:\n`ADMIN CRM STAGE <phone> <new_stage>`\n\n"
                "Stages: NEW, CONTACTED, QUOTED, TRIAL, PAYMENT_PENDING, CONVERTED, LOST, NURTURING\n"
                "Example: `ADMIN CRM STAGE 076123456 QUOTED`"
            )
        phone, stage = parts[0], parts[1].strip().upper()
        norm = normalize_phone_sl(phone)
        if not norm:
            return "⚠️ Invalid phone number."

        if self.crm and hasattr(self.crm, "update_lead_stage"):
            lead = self.crm.update_lead_stage(norm, stage)
            if lead:
                return (
                    f"✅ *Lark CRM Lead Stage Updated!*\n\n"
                    f"• Contact: {lead.name} (`{norm}`)\n"
                    f"• New Stage: *{stage}*\n"
                    "• Synced to Lark Base `01_Leads`."
                )

        lead = self._get_lead(norm)
        if lead:
            lead.lead_stage = stage
            self._upsert_lead(lead)
            return (
                f"✅ *Lark CRM Lead Stage Updated!*\n\n"
                f"• Contact: {lead.name} (`{norm}`)\n"
                f"• New Stage: *{stage}*\n"
                "• Synced to Lark Base `01_Leads`."
            )

        return f"⚠️ Could not update lead stage for `{norm}`. Ensure CRM is connected."

    def _cmd_crm_payment(self, ref_or_phone: str) -> str:
        clean = (ref_or_phone or "").strip()
        if not clean:
            return "⚠️ Please provide a transaction reference, payment ID, or phone:\n`ADMIN CRM PAYMENT OM123456`"

        payment = self._get_payment(clean)
        if not payment:
            return f"ℹ️ No payment found matching `{clean}` in Lark Base `06_Payments`."

        return (
            f"💳 *Lark CRM Payment Record*\n\n"
            f"• Payment ID: `{payment.payment_id}`\n"
            f"• Customer ID: `{payment.customer_id or 'N/A'}`\n"
            f"• Lead ID: `{payment.lead_id or 'N/A'}`\n"
            f"• Amount: Le{payment.expected_amount_le:,}\n"
            f"• Method: {payment.method}\n"
            f"• Reference: `{payment.transaction_reference}`\n"
            f"• Status: *{payment.status.upper()}*\n"
            f"• Verified By: {payment.verified_by or 'N/A'}\n"
            f"• Date: {payment.created_at[:10] if payment.created_at else 'N/A'}\n"
            f"• Notes: {payment.note or 'N/A'}\n"
            "• Synced to Lark Base `06_Payments`."
        )

    def _cmd_crm_stats(self) -> str:
        leads_count = 0
        cust_count = 0
        pay_count = 0
        resellers_count = 0
        handoff_count = 0
        sales_count = 0
        comm_count = 0
        sub_count = 0
        trials_count = 0
        receipts_count = 0

        if self.crm and hasattr(self.crm, "provider"):
            p = self.crm.provider
            if hasattr(p, "get_table_counts"):
                counts = p.get_table_counts()
                if counts:
                    leads_count = counts.get("01_Leads", 0)
                    cust_count = counts.get("03_Customers", 0)
                    pay_count = counts.get("06_Payments", 0)
                    resellers_count = counts.get("09_Resellers", 0)
                    sales_count = counts.get("10_Reseller_Sales", 0)
                    comm_count = counts.get("11_Commissions", 0)
                    sub_count = counts.get("05_Subscriptions", 0)
                    trials_count = counts.get("02_Free_Trials", 0)
                    receipts_count = counts.get("19_Receipts", 0)
            if not leads_count and hasattr(p, "leads") and isinstance(p.leads, dict):
                leads_count = len(p.leads)
            if not cust_count and hasattr(p, "customers") and isinstance(p.customers, dict):
                cust_count = len(p.customers)
            if not pay_count and hasattr(p, "payments") and isinstance(p.payments, list):
                pay_count = len(p.payments)

        if not resellers_count and self.reseller_mgr:
            resellers_count = len(getattr(self.reseller_mgr, "_resellers_by_code", {}))

        if self.store and hasattr(self.store, "list_conversations"):
            convs = self.store.list_conversations()
            handoff_count = len([c for c in convs if getattr(c, "handoff", False)])
            if not leads_count:
                leads_count = len(convs)

        admin_count = len(self.get_authorized_admin_numbers())

        return (
            f"📊 *NexgloTV Lark CRM & Operations Summary*\n\n"
            f"• 🎯 Total Leads: *{leads_count}* (`01_Leads`)\n"
            f"• 👤 Active Customers: *{cust_count}* (`03_Customers`)\n"
            f"• 📦 Subscriptions: *{sub_count}* (`05_Subscriptions`)\n"
            f"• 💳 Recorded Payments: *{pay_count}* (`06_Payments`)\n"
            f"• 🧾 Receipts Issued: *{receipts_count}* (`19_Receipts`)\n"
            f"• 🆓 Free Trials: *{trials_count}* (`02_Free_Trials`)\n"
            f"• 🤝 Registered Resellers: *{resellers_count}* (`09_Resellers`)\n"
            f"• 📈 Reseller Sales: *{sales_count}* (`10_Reseller_Sales`)\n"
            f"• 💰 Reseller Commissions: *{comm_count}* (`11_Commissions`)\n"
            f"• 🚨 Pending Handoffs: *{handoff_count}*\n"
            f"• 🛡️ Authorized Admins: *{admin_count}*\n\n"
            f"🔗 Lark Base ID: `E8jObNOAeaZqUHsyxRHjR9VcpBg`\n"
            "🗄️ Database: Turso Cloud DB (Operational)"
        )

    # =========================================================================
    # CRM Data Access Helpers
    # =========================================================================

    def _get_customer(self, phone: str):
        norm = normalize_phone_sl(phone)
        digits = re.sub(r"[^\d]", "", norm)
        candidates = [norm, digits, f"+{digits}"]

        provider = self.crm.provider if (self.crm and hasattr(self.crm, "provider")) else None
        if not provider and self.reseller_mgr and getattr(self.reseller_mgr, "crm_provider", None):
            provider = self.reseller_mgr.crm_provider

        if provider and hasattr(provider, "get_customer_by_wa_id"):
            for cand in candidates:
                try:
                    c = provider.get_customer_by_wa_id(cand)
                    if c:
                        return c
                except Exception:
                    pass

        if provider and hasattr(provider, "_get_by_wa"):
            try:
                row = provider._get_by_wa("03_Customers", norm)
                if row:
                    from app.crm_sheets import CustomerRecord
                    return CustomerRecord(
                        customer_id=str(row.get("Customer ID", "")),
                        source_lead_id=str(row.get("Original Lead ID", "")),
                        wa_id=norm,
                        phone_e164=norm,
                        name=str(row.get("Customer Name", "Valued Customer")),
                        device_count=int(row.get("Device Count") or 1),
                        subscription_months=int(row.get("Subscription Months") or 1),
                        amount_paid_le=int(row.get("Amount Paid SLE") or 0),
                        payment_method=str(row.get("Payment Method", "")),
                        transaction_reference=str(row.get("Transaction Reference", "")),
                        subscription_expires_at=str(row.get("Subscription Expiry", "")),
                        account_status=str(row.get("Subscription Status", "active")).lower(),
                        renewal_count=int(row.get("Renewal Count") or 0),
                        reseller_code=str(row.get("Reseller Code", "DIRECT")),
                        account_username=str(row.get("Account Username", "")),
                        account_password=str(row.get("Account Password", "")),
                        server_url=str(row.get("Server URL", "")),
                    )
            except Exception as exc:
                log.debug("Lark live customer lookup error: %s", exc)

        return None

    def _get_lead(self, phone: str):
        norm = normalize_phone_sl(phone)
        digits = re.sub(r"[^\d]", "", norm)
        candidates = [norm, digits, f"+{digits}"]

        provider = self.crm.provider if (self.crm and hasattr(self.crm, "provider")) else None
        if not provider and self.reseller_mgr and getattr(self.reseller_mgr, "crm_provider", None):
            provider = self.reseller_mgr.crm_provider

        if provider and hasattr(provider, "get_lead_by_wa_id"):
            for cand in candidates:
                try:
                    lead = provider.get_lead_by_wa_id(cand)
                    if lead:
                        return lead
                except Exception:
                    pass

        if provider and hasattr(provider, "_get_by_wa"):
            try:
                row = provider._get_by_wa("01_Leads", norm)
                if row:
                    from app.crm_sheets import LeadRecord
                    return LeadRecord(
                        lead_id=str(row.get("Lead ID", "")),
                        wa_id=norm,
                        phone_e164=norm,
                        name=str(row.get("Contact Name", "WhatsApp Lead")),
                        lead_stage=str(row.get("Lead Stage", "NEW_LEAD")),
                        source=str(row.get("Lead Source", "whatsapp")),
                        subscription_quote_le=int(row.get("Quote Total SLE") or 0),
                        months=int(row.get("Quote Duration Months") or 1),
                        device_count=int(row.get("Device Count") or 1),
                        payment_status=str(row.get("Payment Status", "pending")),
                        referrer_code=str(row.get("Referral Code", "")),
                        reseller_code=str(row.get("Reseller ID", "")),
                        notes=str(row.get("Lead Notes", "")),
                    )
            except Exception as exc:
                log.debug("Lark live lead lookup error: %s", exc)

        return None

    def _get_payment(self, ref_or_phone: str):
        clean = (ref_or_phone or "").strip()
        provider = self.crm.provider if (self.crm and hasattr(self.crm, "provider")) else None
        if not provider and self.reseller_mgr and getattr(self.reseller_mgr, "crm_provider", None):
            provider = self.reseller_mgr.crm_provider

        if provider and hasattr(provider, "get_payment_by_ref"):
            p = provider.get_payment_by_ref(clean)
            if p:
                return p

        norm = normalize_phone_sl(clean)
        if norm and provider and hasattr(provider, "get_payment_by_ref"):
            p = provider.get_payment_by_ref(norm)
            if p:
                return p

        return None

    def _upsert_customer(self, customer) -> bool:
        provider = self.crm.provider if (self.crm and hasattr(self.crm, "provider")) else None
        if not provider and self.reseller_mgr and getattr(self.reseller_mgr, "crm_provider", None):
            provider = self.reseller_mgr.crm_provider
        if provider and hasattr(provider, "upsert_customer"):
            try:
                return bool(provider.upsert_customer(customer))
            except Exception as exc:
                log.warning("Admin customer upsert error: %s", exc)
        return False

    def _upsert_payment(self, payment) -> bool:
        provider = self.crm.provider if (self.crm and hasattr(self.crm, "provider")) else None
        if not provider and self.reseller_mgr and getattr(self.reseller_mgr, "crm_provider", None):
            provider = self.reseller_mgr.crm_provider
        if provider and hasattr(provider, "upsert_payment"):
            try:
                return bool(provider.upsert_payment(payment))
            except Exception as exc:
                log.warning("Admin payment upsert error: %s", exc)
        return False

    def _upsert_lead(self, lead) -> bool:
        provider = self.crm.provider if (self.crm and hasattr(self.crm, "provider")) else None
        if not provider and self.reseller_mgr and getattr(self.reseller_mgr, "crm_provider", None):
            provider = self.reseller_mgr.crm_provider
        if provider and hasattr(provider, "upsert_lead"):
            try:
                return bool(provider.upsert_lead(lead))
            except Exception as exc:
                log.warning("Admin lead upsert error: %s", exc)
        return False

    # =========================================================================
    # Reseller + Installer Program Operations
    # =========================================================================

    def _cmd_install(self, arg: str) -> str:
        from app.installer_engine import calculate_installer_earning
        if not arg or not arg.strip() or arg.upper() in ("HELP", "?"):
            return (
                "ℹ️ *Admin Installation Booking Command*\n\n"
                "Register a customer installation booking:\n"
                "• `ADMIN INSTALL <phone> <name> <zone> [fee] [notes]`\n"
                "• `ADMIN INSTALL 076123456 Lansana Sesay Freetown West End 120 Smart TV 2 screens`\n\n"
                "Standard physical visit fee is minimum SLE 100."
            )

        phone = parse_phone_number(arg)
        if not phone:
            return "⚠️ Could not detect customer phone number in instruction."

        clean = arg
        raw_m = re.search(r"(?:(?:\+|00)?232[\s\.\-]*)?[0-9]{2}[\s\.\-]*[0-9]{3}[\s\.\-]*[0-9]{3,4}|\b\d{8,15}\b", clean)
        clean_no_phone = clean
        if raw_m:
            clean_no_phone = clean[:raw_m.start()] + " " + clean[raw_m.end():]
        if phone:
            clean_no_phone = clean_no_phone.replace(phone, " ")

        fee = 100
        fee_m = re.search(r"\b(?:fee|sle|le)?[:\s]*(\d{3,5})\b", clean_no_phone, re.I)
        if fee_m:
            try:
                fee = int(fee_m.group(1))
                clean_no_phone = clean_no_phone[:fee_m.start()] + " " + clean_no_phone[fee_m.end():]
            except Exception:
                fee = 100

        months, devices = parse_package_spec(clean)
        tokens = [t for t in clean_no_phone.split() if t.strip()]
        name = "Customer"
        area = "Western Area"
        if len(tokens) >= 2:
            name = f"{tokens[0]} {tokens[1]}"
            area = " ".join(tokens[2:]) if len(tokens) > 2 else "Western Area"
        elif len(tokens) == 1:
            name = tokens[0]

        inst = self.installer_mgr.create_installation_job(
            customer_phone=phone,
            customer_name=name,
            area=area,
            quoted_fee_sle=fee,
            device_count=devices,
            install_mode="Paid Physical",
            staff_id="ADMIN",
        )

        quote = calculate_installer_earning(inst.approved_fee_sle)
        return (
            f"🛠️ *Installation Booking Created*\n\n"
            f"• *Job ID:* `{inst.installation_id}`\n"
            f"• *Customer:* {inst.customer_name} (`{inst.wa_id}`)\n"
            f"• *Location:* {inst.area}\n"
            f"• *Screens:* {inst.device_count} × {inst.device_platform}\n"
            f"• *Approved Fee:* SLE {inst.approved_fee_sle:,}\n"
            f"• *40% Installer Cut:* SLE {int(quote['installer_earning_sle']):,}\n"
            f"• *60% Company Retained:* SLE {int(quote['company_retained_sle']):,}\n\n"
            f"👉 To assign an installer partner:\n`ADMIN ASSIGN {inst.installation_id} <reseller_id>`"
        )

    def _cmd_assign(self, arg: str) -> str:
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            return (
                "ℹ️ *Assign Installation Command*\n\n"
                "Offer an installation job to an approved partner:\n"
                "• `ADMIN ASSIGN <install_id> <reseller_id_or_phone>`\n"
                "• `ADMIN ASSIGN INS-101 RES-PILOT-001`"
            )
        install_id = parts[0].strip()
        partner_id = parts[1].strip()
        ok, reply = self.installer_mgr.offer_job(install_id, partner_id, staff_id="ADMIN")
        return reply

    def _cmd_verify_install(self, arg: str) -> str:
        install_id = arg.strip()
        if not install_id:
            return "⚠️ Please specify Installation ID:\n`ADMIN VERIFY INSTALL INS-101`"
        ok, reply = self.installer_mgr.staff_verify_completion(install_id, staff_id="ADMIN")
        return reply

    def _cmd_verify_fee(self, arg: str) -> str:
        parts = arg.split()
        if len(parts) < 2:
            return (
                "ℹ️ *Verify Installation Fee Command*\n\n"
                "Confirm collection of physical installation fee:\n"
                "• `ADMIN VERIFY FEE <install_id> <amount> [reference]`\n"
                "• `ADMIN VERIFY FEE INS-101 120 OM998877`"
            )
        install_id = parts[0].strip()
        try:
            amount = int(parts[1].strip())
        except Exception:
            return f"⚠️ Invalid amount `{parts[1]}`. Must be a number."
        ref = parts[2].strip() if len(parts) > 2 else ""
        ok, reply = self.installer_mgr.finance_verify_fee(install_id, amount, payment_reference=ref, staff_id="FINANCE")
        return reply

    def _cmd_installer_stats(self, arg: str) -> str:
        clean = (arg or "").strip()
        if not clean:
            return "⚠️ Please specify partner ID, code, or phone:\n`ADMIN INSTALLER STATS RES-PILOT-001`"
        stats = self.installer_mgr.get_installer_stats(clean)
        if not stats.get("found"):
            return f"❌ Partner `{clean}` not found."
        return (
            f"📊 *Installer Performance Summary: {stats['name']}*\n\n"
            f"• Partner ID: `{stats['reseller_id']}` ({stats['reseller_code']})\n"
            f"• Role: *{stats['partner_role']}* (Status: {stats['approval_status']})\n"
            f"• Month: *{stats['target_month']}*\n"
            f"• Qualifying Physical Installs: *{stats['month_qualifying_jobs']}*\n"
            f"• Performance Band: *{stats['provisional_band']}*\n"
            f"• Provisional Monthly Bonus: *SLE {stats['provisional_bonus_sle']:,}*\n"
            f"• Unpaid Installation Earnings: *SLE {stats['unpaid_installer_earnings_sle']:,}*\n"
            f"• Unpaid Sales Commissions: *SLE {stats['subscription_commissions_unpaid_sle']:,}*\n"
            f"• Prepaid Wallet Balance: *SLE {stats['wallet_balance_sle']:,}*"
        )

    def _cmd_lock_month(self, arg: str) -> str:
        parts = arg.split()
        if len(parts) < 2:
            return (
                "ℹ️ *Lock Month Performance Command*\n\n"
                "Close an installer month and award one approved bonus:\n"
                "• `ADMIN LOCK MONTH <reseller_id> <YYYY-MM>`\n"
                "• `ADMIN LOCK MONTH RES-PILOT-001 2026-10`"
            )
        reseller_id = parts[0].strip()
        month = parts[1].strip()
        ok, reply = self.installer_mgr.lock_month_and_award_bonus(reseller_id, month, locked_by="FINANCE")
        return reply

    def _cmd_list_installers(self) -> str:
        partners = []
        if self.reseller_mgr:
            for p in self.reseller_mgr._resellers_by_code.values():
                if p not in partners:
                    partners.append(p)
        if not partners:
            return "ℹ️ No registered partners in database."

        lines = ["👥 *NexgloTV Partner & Installer Directory*:\n"]
        for p in partners:
            role = getattr(p, "partner_role", "Reseller Only")
            status = getattr(p, "installer_approval_status", "Not Applied")
            lines.append(f"• *{p.name}* (`{p.reseller_id}` / `{p.reseller_code}`)")
            lines.append(f"  Phone: `{p.phone}` | Role: *{role}* | Installer: *{status}*")
            lines.append(f"  Wallet: SLE {p.wallet_balance:,} | Unpaid Sales Comm: SLE {p.unpaid_commissions:,} | Unpaid Install: SLE {getattr(p, 'unpaid_installer_earnings', 0):,}\n")
        return "\n".join(lines)
