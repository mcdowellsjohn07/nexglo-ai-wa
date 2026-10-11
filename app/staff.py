"""The staff side of human handoff for NexgloTV.

``StaffDesk`` holds everything a person on the team does: see the open handoff
queue, read a transcript, reply to the customer through the same WhatsApp
client the bot uses, give the conversation back to the bot, and manage
subscriptions/payments. The HTTP API (``app/admin.py``) and the chat simulator
both call it, so the rules live in one place:

- Staff may only send free-form messages inside WhatsApp's 24-hour customer
  service window (counted from the customer's last message). Outside it Meta
  requires an approved template, so the reply is refused with an explanation.
- Nobody messages a contact who opted out (BAJA/STOP).
- A staff reply takes the conversation over (handoff on) so the bot never talks
  over a person. ``resolve`` hands it back to the bot.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Optional

from .clock import from_db
from .crm_sheets import TrialRecord
from .nexglo_catalog import t
from .nexglo_state import State

WINDOW = timedelta(hours=24)


class StaffError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _pretty(iso: str, lang: str) -> str:
    try:
        day = date_cls.fromisoformat(iso)
    except ValueError:
        return iso
    from .nexglo_catalog import DAY_ABBR, MONTH_ABBR
    return f"{DAY_ABBR[lang][day.weekday()]} {day.day} {MONTH_ABBR[lang][day.month - 1]}"


class StaffDesk:
    def __init__(self, services):
        self.services = services
        self.store = services.store
        self.wa = services.wa
        self.settings = services.settings
        self.clock = services.clock
        self.crm = services.crm

    # ------------------------------------------------------------ helpers
    def _conversation(self, wa_id: str):
        if not self.store.conversation_exists(wa_id):
            raise StaffError(404, "not_found", f"No conversation with {wa_id}")
        return self.store.get_conversation(wa_id)

    def window(self, conv) -> dict:
        """Where the contact stands with WhatsApp's 24-hour service window."""
        if not conv.last_user_at:
            return {"open": False, "last_user_at": None, "hours_since": None, "closes_at": None}
        last = from_db(conv.last_user_at)
        since = self.clock() - last
        return {
            "open": since < WINDOW,
            "last_user_at": conv.last_user_at,
            "hours_since": round(since.total_seconds() / 3600, 1),
            "closes_at": (last + WINDOW).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _can_message(self, conv) -> tuple[bool, Optional[str]]:
        if conv.opted_out:
            return False, "The customer opted out (BAJA/STOP); do not message them."
        window = self.window(conv)
        if not window["open"]:
            ago = f"{window['hours_since']} h ago" if window["hours_since"] is not None else "never"
            return False, (
                f"Outside WhatsApp's 24-hour window (the customer last wrote {ago}). "
                "Free-form messages are not allowed; send an approved message template "
                "instead (see docs/meta-setup.md, section 7)."
            )
        return True, None

    def _send(self, wa_id: str, body: str, author: str) -> None:
        if self.wa.send_text(wa_id, body) is None:
            raise StaffError(502, "send_failed", "The WhatsApp API did not accept the message.")
        self.store.add_message(wa_id, "assistant", body, author=author)

    def _summary(self, conv) -> dict:
        return {
            "wa_id": conv.wa_id,
            "profile_name": conv.profile_name,
            "lang": conv.lang,
            "state": conv.state,
            "handoff": conv.handoff,
            "opted_out": conv.opted_out,
            "window": self.window(conv),
            "is_existing_customer": conv.is_existing_customer,
            "customer_id": conv.customer_id,
            "lead_id": conv.lead_id,
        }

    # -------------------------------------------------------------- queue
    def queue(self, last_messages: int = 5) -> list[dict]:
        items = []
        for row in self.store.open_handoffs():
            conv = self.store.get_conversation(row["wa_id"])
            item = self._summary(conv)
            item.update(
                {
                    "handoff_id": row["id"],
                    "reason": row["reason"],
                    "queued_at": row["created_at"],
                    "last_messages": self.store.transcript(row["wa_id"], limit=last_messages),
                }
            )
            items.append(item)
        return items

    def conversation(self, wa_id: str, limit: int = 50) -> dict:
        conv = self._conversation(wa_id)
        out = self._summary(conv)
        out["draft"] = {k: v for k, v in conv.draft.items() if not k.startswith("_")}
        # Get CRM lead info
        lead = self.crm.provider.get_lead_by_wa_id(wa_id) if hasattr(self.crm.provider, 'get_lead_by_wa_id') else None
        if lead:
            out["lead"] = {
                "lead_id": lead.lead_id,
                "stage": lead.lead_stage,
                "months": lead.months,
                "device_count": lead.device_count,
                "quote": lead.subscription_quote_le,
                "device_types": lead.device_types,
                "device_model": lead.device_model,
                "install_method": lead.install_method,
                "area": lead.area,
                "payment_status": lead.payment_status,
                "trial_status": lead.trial_status,
            }
        customer = self.crm.provider.get_customer_by_wa_id(wa_id) if hasattr(self.crm.provider, 'get_customer_by_wa_id') else None
        if customer:
            out["customer"] = {
                "customer_id": customer.customer_id,
                "subscription_months": customer.subscription_months,
                "device_count": customer.device_count,
                "amount_paid_le": customer.amount_paid_le,
                "account_status": customer.account_status,
                "subscription_expires_at": customer.subscription_expires_at,
            }
        out["messages"] = self.store.transcript(wa_id, limit=limit)
        return out

    # ------------------------------------------------------------- actions
    def reply(self, wa_id: str, text: str) -> dict:
        text = text.strip()
        if not text:
            raise StaffError(422, "empty", "The reply text is empty.")
        conv = self._conversation(wa_id)
        ok, why = self._can_message(conv)
        if not ok:
            code = "opted_out" if conv.opted_out else "template_required"
            raise StaffError(409, code, why or "")
        if not conv.handoff:
            # Staff stepped in on their own: silence the bot until resolved.
            self.store.set_handoff(wa_id, True)
            self.store.set_state(wa_id, State.HUMAN)
            self.store.clear_draft(wa_id)
            self.store.create_handoff(wa_id, "staff")
        self._send(wa_id, text, author="staff")
        return {"wa_id": wa_id, "sent": True, "window": self.window(self.store.get_conversation(wa_id))}

    def resolve(self, wa_id: str, notify: bool = True) -> dict:
        conv = self._conversation(wa_id)
        closed = self.store.resolve_handoffs(wa_id, by="staff")
        notified, note = False, None
        if not (conv.handoff or closed):
            # Nothing to hand back; leave whatever the customer is doing alone.
            return {"wa_id": wa_id, "resolved": 0, "bot_active": True, "notified": False,
                    "note": "There was no open handoff."}
        self.store.set_handoff(wa_id, False)
        self.store.set_state(wa_id, State.IDLE)
        self.store.clear_draft(wa_id)
        if notify:
            ok, why = self._can_message(conv)
            if ok:
                self._send(wa_id, t("handoff_resolved", conv.lang, business=self.settings.business_name), author="bot")
                notified = True
            else:
                note = why
        return {"wa_id": wa_id, "resolved": closed, "bot_active": True, "notified": notified, "note": note}

    # ------------------------------------------------------------ payment/lead actions
    def verify_payment(self, wa_id: str, payment_id: str, verified_by: str) -> dict:
        """Mark payment as verified and convert lead to customer."""
        conv = self._conversation(wa_id)
        lead = self.crm.provider.get_lead_by_wa_id(wa_id) if hasattr(self.crm.provider, 'get_lead_by_wa_id') else None
        if not lead:
            raise StaffError(404, "not_found", "No lead found for this contact")

        customer = self.crm.confirm_payment_and_convert(
            wa_id=wa_id,
            payment_id=payment_id,
            verified_by=verified_by,
        )
        if not customer:
            raise StaffError(500, "conversion_failed", "Failed to convert lead to customer")

        # Resolve handoff if active
        if conv.handoff:
            self.store.set_handoff(wa_id, False)
            self.store.set_state(wa_id, State.IDLE)
            self.store.clear_draft(wa_id)
            self.store.resolve_handoffs(wa_id, by="staff")

        return {
            "wa_id": wa_id,
            "customer_id": customer.customer_id,
            "subscription_months": customer.subscription_months,
            "account_status": customer.account_status,
            "converted": True,
        }

    def approve_trial(self, wa_id: str, duration_hours: int, approved_by: str) -> dict:
            """Approve a free trial for a lead."""
            conv = self._conversation(wa_id)
            lead = self.crm.provider.get_lead_by_wa_id(wa_id) if hasattr(self.crm.provider, 'get_lead_by_wa_id') else None
            if not lead:
                raise StaffError(404, "not_found", "No lead found for this contact")

            # Update lead
            self.crm.update_lead_stage(
                wa_id,
                "TRIAL_APPROVAL",
                trial_status="approved",
                approval_status="approved",
                approved_by=approved_by,
            )

            # Record trial
            trial = TrialRecord(
                trial_id="",
                lead_id=lead.lead_id,
                requested_at=lead.last_message_at,
                offered_at=datetime.utcnow().isoformat(),
                approval_status="approved",
                approved_by=approved_by,
                duration_policy=f"{duration_hours}h",
                start_at=datetime.utcnow().isoformat(),
                end_at=(datetime.utcnow() + timedelta(hours=duration_hours)).isoformat(),
                trial_status="active",
                converted_to_paid=False,
                note=f"Approved by {approved_by}",
            )
            self.crm.provider.upsert_trial(trial)

            return {"wa_id": wa_id, "trial_approved": True, "duration_hours": duration_hours}

    def issue_visit_quote(self, wa_id: str, fee_le: int, approved_by: str) -> dict:
        """Issue a visit fee quote for a lead."""
        conv = self._conversation(wa_id)
        lead = self.crm.provider.get_lead_by_wa_id(wa_id) if hasattr(self.crm.provider, 'get_lead_by_wa_id') else None
        if not lead:
            raise StaffError(404, "not_found", "No lead found for this contact")

        self.crm.update_lead_stage(
            wa_id,
            "AREA_CAPTURED",
            visit_fee_quote_le=fee_le,
            quote_approved_by=approved_by,
        )

        return {"wa_id": wa_id, "visit_fee_quote_le": fee_le, "approved_by": approved_by}

    def confirm_setup(self, wa_id: str, staff_name: str) -> dict:
        """Confirm that setup is working on customer's device."""
        conv = self._conversation(wa_id)
        lead = self.crm.provider.get_lead_by_wa_id(wa_id) if hasattr(self.crm.provider, 'get_lead_by_wa_id') else None
        if not lead:
            raise StaffError(404, "not_found", "No lead found for this contact")

        self.crm.record_setup_verified(wa_id, staff_name)

        # If handoff was active, resolve it
        if conv.handoff:
            self.store.set_handoff(wa_id, False)
            self.store.set_state(wa_id, State.SETUP_VERIFIED)
            self.store.clear_draft(wa_id)
            self.store.resolve_handoffs(wa_id, by="staff")

        # Send payment due message
        from .nexglo_pricing import PriceQuote
        quote = PriceQuote(
            months=lead.months,
            device_count=lead.device_count,
            base_price=0,
            discount_pct=lead.discount_pct,
            discount_amount=0,
            final_price=lead.subscription_quote_le,
        )
        from .nexglo_catalog import pluralize
        months_plural = pluralize(lead.months, conv.lang)
        devices_plural = pluralize(lead.device_count, conv.lang)
        body = t(
            "payment_due", conv.lang,
            months=lead.months, months_plural=months_plural,
            devices=lead.device_count, devices_plural=devices_plural,
            total=f"Le{lead.subscription_quote_le:,}",
        )
        self._send(wa_id, body, author="bot")

        return {"wa_id": wa_id, "setup_verified": True, "payment_due_sent": True}