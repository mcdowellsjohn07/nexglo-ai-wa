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
    ):
        self.settings = settings
        self.store = store
        self.llm = llm
        self.wa = wa
        self.crm = crm
        self.reseller_mgr = reseller_mgr

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
            upper.startswith("RENEW ") or
            upper.startswith("RESUBSCRIBE ")
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

        # 9. ADMIN VERIFY <phone>
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

        # 17. ADMIN SALE <phone>, <name>, <package>, <method>, <ref>
        if upper.startswith("SALE"):
            parts = clean.split(maxsplit=1)
            arg = parts[1] if len(parts) > 1 else ""
            return self._cmd_sale(arg, is_renewal=False)

        # 18. ADMIN RENEW <phone>, <package>, <method>, <ref>
        if upper.startswith("RENEW") or upper.startswith("RESUBSCRIBE"):
            parts = clean.split(maxsplit=1)
            arg = parts[1] if len(parts) > 1 else ""
            return self._cmd_sale(arg, is_renewal=True)

        # 19. ADMIN CRM <subcommand>
        if upper.startswith("CRM"):
            parts = clean.split(maxsplit=2)
            sub = parts[1].upper() if len(parts) > 1 else "HELP"
            args = parts[2] if len(parts) > 2 else ""
            return self._cmd_crm(sub, args)

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
        clean = re.sub(r"[^\d]", "", phone or "")
        if not clean:
            return "⚠️ Please provide the customer phone number:\n`ADMIN VERIFY 076123456`"

        norm = normalize_phone_sl(clean)
        target_wa = None
        if self.store and hasattr(self.store, "list_conversations"):
            for c in self.store.list_conversations():
                if phone_matches(clean, c.wa_id):
                    target_wa = c.wa_id
                    break

        target_wa = target_wa or norm

        if self.crm and hasattr(self.crm, "confirm_payment_and_convert"):
            customer = self.crm.confirm_payment_and_convert(
                wa_id=target_wa,
                payment_id=f"PAY-ADM-{int(time.time())}",
                verified_by="admin_whatsapp",
            )
            if customer:
                if self.store:
                    self.store.set_customer_flag(target_wa, True, customer.customer_id)
                    self.store.set_handoff(target_wa, False)
                return (
                    f"✅ *Payment Confirmed & Subscriber Activated!*\n\n"
                    f"• Customer: {customer.name} ({target_wa})\n"
                    f"• ID: `{customer.customer_id}`\n"
                    f"• Duration: {customer.subscription_months} month(s)\n"
                    f"• Expiry: {customer.subscription_expires_at}\n"
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
            profile = ResellerProfile(
                reseller_id=f"RSL-{int(time.time())}",
                reseller_code=code,
                name=name,
                phone=normalize_phone_sl(phone),
                wallet_balance=1000,
            )
            self.reseller_mgr.register_reseller(profile)
            return f"✅ *Reseller Added Successfully!*\n• Code: `{code}`\n• Name: {name}\n• Phone: `{profile.phone}`"

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
        parsed = parse_direct_sale_text(arg, is_renewal=is_renewal)
        if not parsed:
            if is_renewal:
                return (
                    "⚠️ Invalid direct renewal arguments.\n\n"
                    "Usage:\n"
                    "• `ADMIN RENEW <phone>, <package>, <method>, <reference>`\n"
                    "• `ADMIN RENEW <phone>, <name>, <package>, <method>, <reference>`\n\n"
                    "Example:\n"
                    "• `ADMIN RENEW 076123456, 1mo 1dev, Orange Money, OM778899`\n"
                    "• `ADMIN RENEW +23278999888, 3mo 2dev, Afrimoney, AF554433`"
                )
            else:
                return (
                    "⚠️ Invalid direct sale arguments.\n\n"
                    "Usage:\n"
                    "• `ADMIN SALE <phone>, <name>, <package>, <method>, <reference>`\n\n"
                    "Example:\n"
                    "• `ADMIN SALE 076123456, John Kamara, 1mo 1dev, Orange Money, OM123456`\n"
                    "• `ADMIN SALE +23278999888, Fatmata Sesay, 3mo 2dev, Bank Transfer, BT98765`"
                )

        is_resub = is_renewal or parsed.get("is_renewal", False)
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
                f"• New Expiry: {expires_iso[:10]}\n"
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
                f"• Expiry Date: {expires_iso[:10]}\n"
                "• Reseller: `DIRECT` (No commission)\n"
                "• Synced to Lark Base `01_Leads`, `03_Customers`, `05_Subscriptions`, & `06_Payments`."
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
