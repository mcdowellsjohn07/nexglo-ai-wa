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
from datetime import datetime, timezone
from typing import Any, Optional

from app.reseller_bot import normalize_phone_sl, phone_matches

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
        admin_shortcuts = {"STATUS", "MODELS", "HANDOFFS", "SYNC CRM", "ADMIN HELP"}
        is_shortcut = upper in admin_shortcuts

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
            "• *ADMIN MODEL* — View active & free models\n"
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
            synced = 0
            for r in rows:
                wa = str(r.get("wa_id") or "").strip()
                if not wa:
                    continue
                lead = LeadRecord(
                    lead_id=f"LEAD-SYNC-{int(time.time())}-{synced}",
                    wa_id=wa,
                    phone_e164=normalize_phone_sl(wa),
                    name=r.get("profile_name") or f"WhatsApp Contact {wa[-4:]}",
                    source="whatsapp",
                    lead_stage="ACTIVE_CHAT",
                    last_message_at=str(r.get("last_user_at") or r.get("updated_at") or ""),
                )
                if provider.upsert_lead(lead):
                    synced += 1

            return f"✅ *Lark CRM Sync Complete!*\nSynchronized {synced} customer records to Lark Base `01_Leads`."
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
