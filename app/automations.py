"""NexgloTV Automated Follow-up, Trial Expiry, Payment & Renewal Engine.

Runs periodic or on-demand CRM & WhatsApp automations while strictly enforcing:
1. WhatsApp's 24-hour customer service window (free-form messages are only sent
   when the customer wrote within the last 24 hours; outside the window, a
   FollowUpRecord with ``status="manual_pending"`` and ``suppressed_reason`` is
   logged to the CRM for staff / template follow-up).
2. Opt-out compliance (contacts who sent STOP/BAJA are never messaged).
3. Idempotency per conversation draft state so a contact is never spammed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from .clock import from_db
from .crm_sheets import FollowUpRecord, TrialRecord
from .nexglo_catalog import t
from .nexglo_state import Conversation, State

log = logging.getLogger("nexglo.automations")

WINDOW = timedelta(hours=24)

STALLED_FLOW_STATES: frozenset[str] = frozenset({
    State.PRICES_SENT,
    State.PACKAGE_SELECTED,
    State.PAYMENT_READINESS,
    State.DEVICE_SELECTED,
    State.INSTALL_METHOD,
    State.APP_LINK_SENT,
})


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        elif len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.fromisoformat(s + "T00:00:00+00:00")
        else:
            dt = from_db(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


class AutomationRunner:
    """Executes NexgloTV lifecycle automations across SQLite state and CRM."""

    def __init__(self, services):
        self.services = services
        self.store = services.store
        self.wa = services.wa
        self.crm = services.crm
        self.clock = services.clock
        self.last_run_at: Optional[str] = None
        self.last_report: Optional[dict[str, Any]] = None

    # ---------------------------------------------------------------- helpers
    def _in_window(self, conv: Conversation, now: datetime) -> bool:
        if conv.opted_out or not conv.last_user_at:
            return False
        last = _parse_iso_dt(conv.last_user_at)
        if not last:
            return False
        return (now - last) < WINDOW

    def _send_auto(self, conv: Conversation, body: str) -> bool:
        if self.wa.send_text(conv.wa_id, body) is None:
            return False
        self.store.add_message(conv.wa_id, "assistant", body, author="bot")
        return True

    def _record_followup(
        self,
        conv: Conversation,
        reason: str,
        sent: bool,
        now: datetime,
        suppressed_reason: str = "",
        template_name: str = "",
    ) -> None:
        lead = self.crm.ensure_lead(
            conv.wa_id,
            conv.wa_id,
            profile_name=conv.profile_name,
        )
        now_iso = now.isoformat(timespec="seconds")
        fu = FollowUpRecord(
            followup_id=f"ACT-{uuid4().hex[:8].upper()}",
            lead_id=lead.lead_id,
            wa_id=conv.wa_id,
            reason=reason,
            consent_basis="24h_service_window" if sent else "template_required",
            due_at=now_iso,
            template_name_if_required=template_name,
            status="sent" if sent else "manual_pending",
            sent_at=now_iso if sent else "",
            suppressed_reason=suppressed_reason,
        )
        try:
            self.crm.provider.upsert_followup(fu)
        except Exception as exc:
            log.warning("Failed to record follow-up in CRM for %s: %s", conv.wa_id, exc)

    # ------------------------------------------------ 1. Stalled quote/setup
    def run_stalled_quote_followups(
        self,
        now: Optional[datetime] = None,
        stalled_after_hours: float = 2.0,
    ) -> dict[str, Any]:
        now = now or self.clock()
        threshold = timedelta(hours=stalled_after_hours)
        sent_list: list[str] = []
        queued_list: list[str] = []

        for conv in self.store.list_conversations(states=set(STALLED_FLOW_STATES)):
            if conv.opted_out or conv.handoff:
                continue
            if conv.draft.get("_auto_followup_quote_sent"):
                continue
            ref_ts = _parse_iso_dt(conv.last_user_at) or _parse_iso_dt(conv.updated_at)
            if not ref_ts or (now - ref_ts) < threshold:
                continue

            in_win = self._in_window(conv, now)
            sent = False
            if in_win:
                body = t("auto_followup_quote", conv.lang)
                sent = self._send_auto(conv, body)

            self.store.update_draft(conv.wa_id, {"_auto_followup_quote_sent": now.isoformat(timespec="seconds")})
            self._record_followup(
                conv,
                reason=f"stalled_{conv.state}_followup",
                sent=sent,
                now=now,
                suppressed_reason="" if sent else "outside_24h_window",
                template_name="" if sent else "nexglotv_quote_followup",
            )
            if sent:
                sent_list.append(conv.wa_id)
            else:
                queued_list.append(conv.wa_id)

        return {"sent": sent_list, "queued_for_staff": queued_list}

    # ------------------------------------------------ 2. Free trial expiry
    def run_trial_expiry_checks(self, now: Optional[datetime] = None) -> dict[str, Any]:
        now = now or self.clock()
        expired_notified: list[str] = []
        expired_queued: list[str] = []

        for conv in self.store.list_conversations(states={State.TRIAL_ACTIVE}):
            if conv.draft.get("_auto_trial_expired_handled"):
                continue
            lead = self.crm.provider.get_lead_by_wa_id(conv.wa_id)
            expires_str = conv.draft.get("trial_ends_at") or ( getattr(lead, "trial_ends_at", "") if lead else "" ) or (lead.followup_due_at if lead else "")
            expires_dt = _parse_iso_dt(expires_str)
            if not expires_dt or now < expires_dt:
                continue

            # Update CRM lead & trial record
            self.crm.update_lead_stage(
                conv.wa_id,
                "trial_expired",
                trial_status="expired",
            )
            if lead:
                try:
                    self.crm.provider.upsert_trial(
                        TrialRecord(
                            trial_id=conv.draft.get("trial_id", ""),
                            lead_id=lead.lead_id,
                            requested_at=lead.updated_at or now.isoformat(timespec="seconds"),
                            approval_status="approved",
                            trial_status="expired",
                            end_at=expires_str or now.isoformat(timespec="seconds"),
                            converted_to_paid=False,
                            note="Auto-expired by AutomationRunner",
                        )
                    )
                except Exception as exc:
                    log.warning("Failed to upsert expired trial for %s: %s", conv.wa_id, exc)

            # Move conversation to PAYMENT_READINESS (or PRICES_SENT)
            next_state = State.PAYMENT_READINESS if (lead and lead.months) else State.PRICES_SENT
            self.store.set_state(conv.wa_id, next_state)
            self.store.update_draft(conv.wa_id, {"_auto_trial_expired_handled": now.isoformat(timespec="seconds")})

            sent = False
            if not conv.opted_out and self._in_window(conv, now):
                body = t("auto_trial_expired", conv.lang)
                sent = self._send_auto(conv, body)

            self._record_followup(
                conv,
                reason="trial_expired_conversion",
                sent=sent,
                now=now,
                suppressed_reason="opted_out" if conv.opted_out else ("" if sent else "outside_24h_window"),
                template_name="" if sent else "nexglotv_trial_expired",
            )
            if sent:
                expired_notified.append(conv.wa_id)
            else:
                expired_queued.append(conv.wa_id)

        return {"expired_notified": expired_notified, "expired_queued": expired_queued}

    # ------------------------------------------------ 3. Payment due reminder
    def run_payment_reminders(
        self,
        now: Optional[datetime] = None,
        remind_after_hours: float = 1.0,
    ) -> dict[str, Any]:
        now = now or self.clock()
        threshold = timedelta(hours=remind_after_hours)
        sent_list: list[str] = []
        queued_list: list[str] = []

        for conv in self.store.list_conversations(states={State.PAYMENT_DUE}):
            if conv.opted_out or conv.handoff:
                continue
            if conv.draft.get("_auto_payment_reminder_sent"):
                continue
            ref_ts = _parse_iso_dt(conv.updated_at) or _parse_iso_dt(conv.last_user_at)
            if not ref_ts or (now - ref_ts) < threshold:
                continue

            sent = False
            if self._in_window(conv, now):
                body = t("auto_payment_reminder", conv.lang)
                sent = self._send_auto(conv, body)

            self.store.update_draft(conv.wa_id, {"_auto_payment_reminder_sent": now.isoformat(timespec="seconds")})
            self._record_followup(
                conv,
                reason="payment_due_reminder",
                sent=sent,
                now=now,
                suppressed_reason="" if sent else "outside_24h_window",
                template_name="" if sent else "nexglotv_payment_reminder",
            )
            if sent:
                sent_list.append(conv.wa_id)
            else:
                queued_list.append(conv.wa_id)

        return {"sent": sent_list, "queued_for_staff": queued_list}

    # ------------------------------------------------ 4. Renewal reminder
    def run_renewal_reminders(
        self,
        now: Optional[datetime] = None,
        days_before_expiry: int = 3,
    ) -> dict[str, Any]:
        now = now or self.clock()
        horizon = timedelta(days=days_before_expiry)
        sent_list: list[str] = []
        queued_list: list[str] = []

        for conv in self.store.list_conversations():
            if not conv.is_existing_customer:
                continue
            customer = self.crm.provider.get_customer_by_wa_id(conv.wa_id)
            if not customer or not customer.subscription_expires_at:
                continue
            if conv.draft.get("_auto_renewal_reminded_for") == customer.subscription_expires_at:
                continue

            exp_dt = _parse_iso_dt(customer.subscription_expires_at)
            if not exp_dt:
                continue
            remaining = exp_dt - now
            if remaining > horizon:
                continue

            # Update customer status in CRM to renewal_due (or expired if past due)
            customer.account_status = "expired" if remaining.total_seconds() < 0 else "renewal_due"
            try:
                self.crm.provider.upsert_customer(customer)
            except Exception as exc:
                log.warning("Failed to update customer renewal status for %s: %s", conv.wa_id, exc)

            pkg_label = f"{customer.subscription_months}m × {customer.device_count}d"
            sent = False
            if not conv.opted_out and not conv.handoff and self._in_window(conv, now):
                body = t(
                    "auto_renewal_reminder",
                    conv.lang,
                    package=pkg_label,
                    expires=customer.subscription_expires_at[:10],
                )
                sent = self._send_auto(conv, body)

            self.store.update_draft(
                conv.wa_id,
                {"_auto_renewal_reminded_for": customer.subscription_expires_at},
            )
            self._record_followup(
                conv,
                reason="subscription_renewal_reminder",
                sent=sent,
                now=now,
                suppressed_reason="opted_out" if conv.opted_out else ("" if sent else "outside_24h_window"),
                template_name="" if sent else "nexglotv_renewal_reminder",
            )
            if sent:
                sent_list.append(conv.wa_id)
            else:
                queued_list.append(conv.wa_id)

        return {"sent": sent_list, "queued_for_staff": queued_list}

    # ------------------------------------------------ Aggregate runner
    def run_all(
        self,
        now: Optional[datetime] = None,
        stalled_after_hours: float = 2.0,
        payment_remind_after_hours: float = 1.0,
        renewal_days_before: int = 3,
    ) -> dict[str, Any]:
        now = now or self.clock()
        stalled = self.run_stalled_quote_followups(now=now, stalled_after_hours=stalled_after_hours)
        trials = self.run_trial_expiry_checks(now=now)
        payments = self.run_payment_reminders(now=now, remind_after_hours=payment_remind_after_hours)
        renewals = self.run_renewal_reminders(now=now, days_before_expiry=renewal_days_before)

        report = {
            "ran_at": now.isoformat(timespec="seconds"),
            "stalled_quotes": stalled,
            "trial_expiries": trials,
            "payment_reminders": payments,
            "renewal_reminders": renewals,
            "total_messages_sent": (
                len(stalled["sent"])
                + len(trials["expired_notified"])
                + len(payments["sent"])
                + len(renewals["sent"])
            ),
            "total_queued_for_staff": (
                len(stalled["queued_for_staff"])
                + len(trials["expired_queued"])
                + len(payments["queued_for_staff"])
                + len(renewals["queued_for_staff"])
            ),
        }
        self.last_run_at = report["ran_at"]
        self.last_report = report
        return report

    def status(self) -> dict[str, Any]:
        convs = self.store.list_conversations()
        return {
            "stalled_candidates": sum(
                1 for c in convs
                if c.state in STALLED_FLOW_STATES and not c.opted_out and not c.handoff
                and not c.draft.get("_auto_followup_quote_sent")
            ),
            "active_trials": sum(
                1 for c in convs
                if c.state == State.TRIAL_ACTIVE and not c.draft.get("_auto_trial_expired_handled")
            ),
            "pending_payments": sum(
                1 for c in convs
                if c.state == State.PAYMENT_DUE and not c.opted_out and not c.handoff
                and not c.draft.get("_auto_payment_reminder_sent")
            ),
            "existing_customers": sum(1 for c in convs if c.is_existing_customer),
            "last_run_at": self.last_run_at,
            "last_report": self.last_report,
        }
