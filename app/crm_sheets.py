"""NexgloTV Google Sheets CRM integration with mock mode for testing.

Supports Leads, Customers, Payments, Installations, Trials, StaffHandoffs, FollowUps, Referrals worksheets.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any
from uuid import uuid4

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:  # pragma: no cover
    gspread = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment]

from .nexglo_pricing import PriceQuote
from .nexglo_state import State

log = logging.getLogger("nexglo_crm")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



# --- Data classes for CRM records ---------------------------------------------

@dataclass
class LeadRecord:
    lead_id: str
    wa_id: str
    phone_e164: str
    name: str = ""
    source: str = "whatsapp"
    campaign: str = ""
    referrer_code: str = ""
    reseller_code: str = ""
    lead_stage: str = "NEW_LEAD"
    first_contact_at: str = ""
    last_message_at: str = ""
    content_interest: str = ""
    months: int = 0
    device_count: int = 0
    subscription_quote_le: int = 0
    discount_pct: int = 0
    quote_version: str = ""
    device_types: str = ""
    device_model: str = ""
    device_os: str = ""
    internet_type: str = ""
    area: str = ""
    install_method: str = ""
    visit_fee_quote_le: int = 0
    app_name: str = ""
    app_url_sent: str = ""
    app_sent_at: str = ""
    app_installed_reported: bool = False
    ready_to_pay_after_setup: bool = False
    trial_offered: bool = False
    trial_requested: bool = False
    trial_status: str = ""
    handoff_status: str = ""
    assigned_staff: str = ""
    staff_setup_verified: bool = False
    payment_status: str = ""
    followup_consent: bool = False
    followup_due_at: str = ""
    opted_out: bool = False
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class CustomerRecord:
    customer_id: str
    source_lead_id: str
    wa_id: str
    phone_e164: str
    name: str = ""
    location_area: str = ""
    device_types: str = ""
    device_count: int = 0
    subscription_months: int = 0
    package_code: str = ""
    amount_paid_le: int = 0
    payment_method: str = ""
    transaction_reference: str = ""
    payment_verified_at: str = ""
    activation_at: str = ""
    subscription_expires_at: str = ""
    account_status: str = "active"
    setup_verified_at: str = ""
    assigned_staff: str = ""
    referrer_code: str = ""
    reseller_code: str = ""
    renewal_count: int = 0
    last_renewed_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class PaymentRecord:
    payment_id: str
    lead_id: str = ""
    customer_id: str = ""
    phone_e164: str = ""
    expected_amount_le: int = 0
    method: str = ""
    transaction_reference: str = ""
    proof_received_at: str = ""
    status: str = "pending"  # pending|verifying|confirmed|rejected
    verified_by: str = ""
    verified_at: str = ""
    note: str = ""
    created_at: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class InstallationRecord:
    installation_id: str
    lead_id: str = ""
    wa_id: str = ""
    device_platform: str = ""
    device_model: str = ""
    installation_method: str = ""
    area: str = ""
    address_if_booked: str = ""
    visit_fee_le: int = 0
    quote_approved_by: str = ""
    assigned_staff: str = ""
    scheduled_at: str = ""
    app_sent_at: str = ""
    app_installed_reported_at: str = ""
    setup_status: str = "pending"
    setup_verified_at: str = ""
    issue_note: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class TrialRecord:
    trial_id: str
    lead_id: str = ""
    requested_at: str = ""
    offered_at: str = ""
    approval_status: str = "pending"
    approved_by: str = ""
    duration_policy: str = ""
    start_at: str = ""
    end_at: str = ""
    trial_status: str = ""
    converted_to_paid: bool = False
    note: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class StaffHandoffRecord:
    handoff_id: str
    lead_id: str = ""
    wa_id: str = ""
    reason: str = ""
    requested_at: str = ""
    assigned_staff: str = ""
    status: str = "pending"  # pending|accepted|resolved
    accepted_at: str = ""
    resolved_at: str = ""
    resolution: str = ""
    next_stage: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class FollowUpRecord:
    followup_id: str
    lead_id: str = ""
    wa_id: str = ""
    reason: str = ""
    consent_basis: str = ""
    due_at: str = ""
    template_name_if_required: str = ""
    status: str = "pending"
    sent_at: str = ""
    suppressed_reason: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


@dataclass
class ReferralRecord:
    referral_id: str
    referrer_id: str = ""
    referred_lead_id: str = ""
    referral_code: str = ""
    reseller_code: str = ""
    qualified_payment_id: str = ""
    reward_policy_version: str = ""
    reward_status: str = ""
    verified_by: str = ""

    def to_row(self) -> list:
        return [getattr(self, f) for f in self.__dataclass_fields__]

    @classmethod
    def headers(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())


# --- Abstract CRM Provider ----------------------------------------------------

class CRMProvider(ABC):
    """Abstract base for CRM providers (Google Sheets, Mock, etc.)"""

    @abstractmethod
    def upsert_lead(self, lead: LeadRecord) -> bool:
        pass

    @abstractmethod
    def get_lead_by_wa_id(self, wa_id: str) -> Optional[LeadRecord]:
        pass

    @abstractmethod
    def upsert_customer(self, customer: CustomerRecord) -> bool:
        pass

    @abstractmethod
    def get_customer_by_wa_id(self, wa_id: str) -> Optional[CustomerRecord]:
        pass

    @abstractmethod
    def upsert_payment(self, payment: PaymentRecord) -> bool:
        pass

    @abstractmethod
    def upsert_installation(self, installation: InstallationRecord) -> bool:
        pass

    @abstractmethod
    def upsert_trial(self, trial: TrialRecord) -> bool:
        pass

    @abstractmethod
    def upsert_handoff(self, handoff: StaffHandoffRecord) -> bool:
        pass

    @abstractmethod
    def upsert_followup(self, followup: FollowUpRecord) -> bool:
        pass

    @abstractmethod
    def upsert_referral(self, referral: ReferralRecord) -> bool:
        pass

    def get_payment_by_ref(self, ref: str) -> Optional[PaymentRecord]:
        return None


# --- Mock Provider (for testing without credentials) --------------------------

class MockCRMProvider(CRMProvider):
    """In-memory CRM for testing and dry-run mode."""

    def __init__(self):
        self.leads: dict[str, LeadRecord] = {}  # keyed by wa_id
        self.customers: dict[str, CustomerRecord] = {}  # keyed by wa_id
        self.payments: list[PaymentRecord] = []
        self.installations: list[InstallationRecord] = []
        self.trials: list[TrialRecord] = []
        self.handoffs: list[StaffHandoffRecord] = []
        self.followups: list[FollowUpRecord] = []
        self.referrals: list[ReferralRecord] = []
        log.info("Mock CRM provider initialized")

    def _now(self) -> str:
        return _utc_now_iso()

    def upsert_lead(self, lead: LeadRecord) -> bool:
        existing = self.leads.get(lead.wa_id)
        if existing:
            # Preserve created_at and lead_id
            lead.lead_id = existing.lead_id
            lead.created_at = existing.created_at
            lead.updated_at = self._now()
        else:
            if not lead.lead_id:
                lead.lead_id = str(uuid4())
            if not lead.created_at:
                lead.created_at = self._now()
            if not lead.first_contact_at:
                lead.first_contact_at = self._now()
            lead.updated_at = self._now()
        self.leads[lead.wa_id] = lead
        log.debug("Mock CRM: upserted lead %s (%s)", lead.lead_id, lead.wa_id)
        return True

    def get_lead_by_wa_id(self, wa_id: str) -> Optional[LeadRecord]:
        return self.leads.get(wa_id)

    def upsert_customer(self, customer: CustomerRecord) -> bool:
        existing = self.customers.get(customer.wa_id)
        if existing:
            customer.customer_id = existing.customer_id
            customer.created_at = existing.created_at
            customer.updated_at = self._now()
        else:
            if not customer.customer_id:
                customer.customer_id = str(uuid4())
            if not customer.created_at:
                customer.created_at = self._now()
            customer.updated_at = self._now()
        self.customers[customer.wa_id] = customer
        log.debug("Mock CRM: upserted customer %s (%s)", customer.customer_id, customer.wa_id)
        return True

    def get_customer_by_wa_id(self, wa_id: str) -> Optional[CustomerRecord]:
        return self.customers.get(wa_id)

    def upsert_payment(self, payment: PaymentRecord) -> bool:
        if not payment.payment_id:
            payment.payment_id = str(uuid4())
        if not payment.created_at:
            payment.created_at = self._now()
        self.payments.append(payment)
        log.debug("Mock CRM: recorded payment %s", payment.payment_id)
        return True

    def get_payment_by_ref(self, ref: str) -> Optional[PaymentRecord]:
        clean = (ref or "").strip().lower()
        if not clean:
            return None
        for p in reversed(self.payments):
            if (p.transaction_reference and clean == p.transaction_reference.lower()) or \
               (p.payment_id and clean == p.payment_id.lower()) or \
               (p.phone_e164 and clean in p.phone_e164.lower()) or \
               (p.customer_id and clean == p.customer_id.lower()):
                return p
        return None

    def upsert_installation(self, installation: InstallationRecord) -> bool:
        if not installation.installation_id:
            installation.installation_id = str(uuid4())
        self.installations.append(installation)
        return True

    def upsert_trial(self, trial: TrialRecord) -> bool:
        if not trial.trial_id:
            trial.trial_id = str(uuid4())
        self.trials.append(trial)
        return True

    def upsert_handoff(self, handoff: StaffHandoffRecord) -> bool:
        if not handoff.handoff_id:
            handoff.handoff_id = str(uuid4())
        self.handoffs.append(handoff)
        return True

    def upsert_followup(self, followup: FollowUpRecord) -> bool:
        if not followup.followup_id:
            followup.followup_id = str(uuid4())
        self.followups.append(followup)
        return True

    def upsert_referral(self, referral: ReferralRecord) -> bool:
        if not referral.referral_id:
            referral.referral_id = str(uuid4())
        self.referrals.append(referral)
        return True


# --- Google Sheets Provider ---------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

WORKSHEET_NAMES = [
    "Leads", "Customers", "Payments", "Installations",
    "Trials", "StaffHandoffs", "FollowUps", "Referrals",
]

RECORD_CLASSES = {
    "Leads": LeadRecord,
    "Customers": CustomerRecord,
    "Payments": PaymentRecord,
    "Installations": InstallationRecord,
    "Trials": TrialRecord,
    "StaffHandoffs": StaffHandoffRecord,
    "FollowUps": FollowUpRecord,
    "Referrals": ReferralRecord,
}


class GoogleSheetsCRMProvider(CRMProvider):
    """Google Sheets CRM with retry logic and idempotent upserts."""

    def __init__(
        self,
        sheet_id: str,
        service_account_json: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ):
        self.sheet_id = sheet_id
        self.service_account_json = service_account_json
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._client: Optional[gspread.Client] = None
        self._spreadsheet = None
        self._worksheets: dict[str, gspread.Worksheet] = {}
        self._header_cache: dict[str, list[str]] = {}
        self._row_index_cache: dict[str, dict[str, int]] = {}  # worksheet -> {wa_id: row_num}
        self._lock = threading.RLock()

    def _get_client(self) -> gspread.Client:
        with self._lock:
            if self._client is None:
                creds_dict = json.loads(self.service_account_json)
                creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
                self._client = gspread.authorize(creds)
            return self._client

    def _get_spreadsheet(self):
        with self._lock:
            if self._spreadsheet is None:
                self._spreadsheet = self._get_client().open_by_key(self.sheet_id)
            return self._spreadsheet

    def _get_worksheet(self, name: str) -> gspread.Worksheet:
        with self._lock:
            if name not in self._worksheets:
                try:
                    ws = self._get_spreadsheet().worksheet(name)
                except gspread.WorksheetNotFound:
                    ws = self._get_spreadsheet().add_worksheet(title=name, rows=1000, cols=50)
                    ws.append_row(RECORD_CLASSES[name].headers())
                self._worksheets[name] = ws
                self._refresh_header_cache(name)
            return self._worksheets[name]

    def _refresh_header_cache(self, name: str) -> None:
        ws = self._worksheets[name]
        self._header_cache[name] = ws.row_values(1)

    def _get_row_index(self, name: str, wa_id: str) -> Optional[int]:
        """Find row by wa_id (column B in all sheets). Uses cache."""
        with self._lock:
            if name not in self._row_index_cache:
                ws = self._get_worksheet(name)
                # Column B is wa_id (index 1 in 0-based, 2 in 1-based)
                col_values = ws.col_values(2)[1:]  # Skip header
                self._row_index_cache[name] = {v: i + 2 for i, v in enumerate(col_values) if v}
            return self._row_index_cache[name].get(wa_id)

    def _invalidate_row_cache(self, name: str) -> None:
        with self._lock:
            if name in self._row_index_cache:
                del self._row_index_cache[name]

    def _retry(self, func, *args, **kwargs):
        """Execute with exponential backoff on 429/5xx errors."""
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except gspread.exceptions.APIError as e:
                last_exc = e
                if e.response.status_code in (429, 500, 502, 503, 504):
                    delay = self.base_delay * (2 ** attempt)
                    log.warning("Sheets API error %s, retrying in %.1fs (attempt %d/%d)",
                               e.response.status_code, delay, attempt + 1, self.max_retries)
                    time.sleep(delay)
                    continue
                raise
            except Exception as e:
                last_exc = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.base_delay)
                    continue
                raise
        raise last_exc

    def _upsert_record(self, worksheet_name: str, record, wa_id_field: str = "wa_id") -> bool:
        """Generic upsert by wa_id."""
        ws = self._get_worksheet(worksheet_name)
        wa_id = getattr(record, wa_id_field, None)
        if not wa_id:
            log.error("Cannot upsert %s without wa_id", worksheet_name)
            return False

        row_num = self._get_row_index(worksheet_name, wa_id)
        headers = self._header_cache.get(worksheet_name) or RECORD_CLASSES[worksheet_name].headers()

        # Ensure all fields are present
        row_data = []
        for h in headers:
            row_data.append(getattr(record, h, ""))

        if row_num:
            # Update existing row
            self._retry(ws.update, f"A{row_num}", [row_data])
            log.debug("Updated %s row %d for %s", worksheet_name, row_num, wa_id)
        else:
            # Append new row
            self._retry(ws.append_row, row_data, value_input_option="USER_ENTERED")
            self._invalidate_row_cache(worksheet_name)
            log.debug("Appended %s for %s", worksheet_name, wa_id)
        return True

    def upsert_lead(self, lead: LeadRecord) -> bool:
        return self._upsert_record("Leads", lead)

    def get_lead_by_wa_id(self, wa_id: str) -> Optional[LeadRecord]:
        ws = self._get_worksheet("Leads")
        row_num = self._get_row_index("Leads", wa_id)
        if not row_num:
            return None
        row = ws.row_values(row_num)
        headers = self._header_cache["Leads"]
        data = dict(zip(headers, row))
        return LeadRecord(**{k: v for k, v in data.items() if k in LeadRecord.__dataclass_fields__})

    def upsert_customer(self, customer: CustomerRecord) -> bool:
        return self._upsert_record("Customers", customer)

    def get_customer_by_wa_id(self, wa_id: str) -> Optional[CustomerRecord]:
        ws = self._get_worksheet("Customers")
        row_num = self._get_row_index("Customers", wa_id)
        if not row_num:
            return None
        row = ws.row_values(row_num)
        headers = self._header_cache["Customers"]
        data = dict(zip(headers, row))
        return CustomerRecord(**{k: v for k, v in data.items() if k in CustomerRecord.__dataclass_fields__})

    def upsert_payment(self, payment: PaymentRecord) -> bool:
        # Payments are append-only, keyed by payment_id
        ws = self._get_worksheet("Payments")
        if not payment.payment_id:
            payment.payment_id = str(uuid4())
        if not payment.created_at:
            payment.created_at = _utc_now_iso()
        row_data = [getattr(payment, h, "") for h in self._header_cache.get("Payments", PaymentRecord.headers())]
        self._retry(ws.append_row, row_data, value_input_option="USER_ENTERED")
        self._invalidate_row_cache("Payments")
        return True

    def upsert_installation(self, installation: InstallationRecord) -> bool:
        return self._upsert_record("Installations", installation)

    def upsert_trial(self, trial: TrialRecord) -> bool:
        return self._upsert_record("Trials", trial, wa_id_field="lead_id")  # Keyed by lead_id

    def upsert_handoff(self, handoff: StaffHandoffRecord) -> bool:
        return self._upsert_record("StaffHandoffs", handoff)

    def upsert_followup(self, followup: FollowUpRecord) -> bool:
        return self._upsert_record("FollowUps", followup)

    def upsert_referral(self, referral: ReferralRecord) -> bool:
        return self._upsert_record("Referrals", referral)


# --- Factory ------------------------------------------------------------------

def create_crm_provider(
    provider: str = "mock",
    sheet_id: str = "",
    service_account_json: str = "",
) -> CRMProvider:
    """Factory for CRM providers."""
    if provider == "google_sheets":
        if not sheet_id or not service_account_json or gspread is None:
            log.warning("Google Sheets credentials or gspread missing, falling back to mock")
            return MockCRMProvider()
        return GoogleSheetsCRMProvider(sheet_id, service_account_json)
    return MockCRMProvider()


# --- High-level CRM Service ---------------------------------------------------

class CRMService:
    """High-level CRM operations for the NexgloTV agent."""

    def __init__(self, provider: CRMProvider):
        self.provider = provider

    def ensure_lead(
        self,
        wa_id: str,
        phone_e164: str,
        profile_name: Optional[str] = None,
        source: str = "whatsapp",
    ) -> LeadRecord:
        """Get existing lead or create new one."""
        now = _utc_now_iso()
        try:
            lead = self.provider.get_lead_by_wa_id(wa_id)
            if lead:
                lead.last_message_at = now
                if profile_name and not lead.name:
                    lead.name = profile_name
                self.provider.upsert_lead(lead)
                return lead
        except Exception:
            log.exception("Failed to read/update existing lead for %s", wa_id)

        # Create new lead
        lead = LeadRecord(
            lead_id=str(uuid4()),
            wa_id=wa_id,
            phone_e164=phone_e164,
            name=profile_name or "",
            source=source,
            first_contact_at=now,
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        try:
            self.provider.upsert_lead(lead)
        except Exception:
            log.exception("Failed to upsert new lead for %s", wa_id)
        return lead

    def update_lead_stage(self, wa_id: str, stage: str, **extra_fields) -> Optional[LeadRecord]:
        """Update lead stage and optional extra fields."""
        try:
            lead = self.provider.get_lead_by_wa_id(wa_id)
            if not lead:
                lead = self.ensure_lead(wa_id, wa_id)
            now = _utc_now_iso()
            lead.lead_stage = stage
            lead.last_message_at = now
            lead.updated_at = now
            for key, value in extra_fields.items():
                if hasattr(lead, key):
                    setattr(lead, key, value)
            self.provider.upsert_lead(lead)
            return lead
        except Exception:
            log.exception("Failed to update lead stage for %s to %s", wa_id, stage)
            return None

    def record_quote(self, wa_id: str, quote: PriceQuote, device_count: int) -> Optional[LeadRecord]:
        return self.update_lead_stage(
            wa_id,
            "PACKAGE_SELECTED",
            months=quote.months,
            device_count=device_count,
            subscription_quote_le=quote.final_price,
            discount_pct=quote.discount_pct,
            quote_version=quote.quote_version,
        )

    def record_device_info(
        self,
        wa_id: str,
        device_type: str,
        device_model: str = "",
        device_os: str = "",
    ) -> Optional[LeadRecord]:
        return self.update_lead_stage(
            wa_id,
            "DEVICE_SELECTED",
            device_types=device_type,
            device_model=device_model,
            device_os=device_os,
        )

    def record_install_method(self, wa_id: str, method: str, area: str = "") -> Optional[LeadRecord]:
        return self.update_lead_stage(
            wa_id,
            "INSTALL_METHOD" if method == "self_install" else "AREA_CAPTURED",
            install_method=method,
            area=area,
        )

    def record_app_sent(
        self,
        wa_id: str,
        app_name: str,
        app_url: str,
    ) -> Optional[LeadRecord]:
        return self.update_lead_stage(
            wa_id,
            "APP_LINK_SENT",
            app_name=app_name,
            app_url_sent=app_url,
            app_sent_at=_utc_now_iso(),
        )

    def record_app_installed(self, wa_id: str) -> Optional[LeadRecord]:
        return self.update_lead_stage(
            wa_id,
            "APP_INSTALLED",
            app_installed_reported=True,
        )

    def record_handoff(self, wa_id: str, reason: str, handoff_id: str) -> Optional[LeadRecord]:
        lead = self.update_lead_stage(
            wa_id,
            "HANDOFF_REQUESTED",
            handoff_status="pending",
        )
        if lead:
            handoff_rec = StaffHandoffRecord(
                handoff_id=handoff_id,
                lead_id=lead.lead_id,
                wa_id=wa_id,
                reason=reason,
                requested_at=_utc_now_iso(),
                status="pending",
            )
            try:
                self.provider.upsert_handoff(handoff_rec)
            except Exception:
                log.exception("Failed to upsert handoff %s for %s", handoff_id, wa_id)
        return lead

    def record_setup_verified(self, wa_id: str, staff_name: str) -> Optional[LeadRecord]:
        lead = self.update_lead_stage(
            wa_id,
            "SETUP_VERIFIED",
            staff_setup_verified=True,
            assigned_staff=staff_name,
        )
        if lead:
            inst = InstallationRecord(
                installation_id=str(uuid4()),
                lead_id=lead.lead_id,
                wa_id=wa_id,
                setup_status="verified",
                setup_verified_at=_utc_now_iso(),
                assigned_staff=staff_name,
            )
            try:
                self.provider.upsert_installation(inst)
            except Exception:
                log.exception("Failed to upsert installation for %s", wa_id)
        return lead

    def record_payment_due(self, wa_id: str, quote: PriceQuote) -> Optional[LeadRecord]:
        return self.update_lead_stage(
            wa_id,
            "PAYMENT_DUE",
            subscription_quote_le=quote.final_price,
            payment_status="awaiting_payment",
        )

    def record_payment_proof(self, wa_id: str, method: str, reference: str, amount: int) -> Optional[LeadRecord]:
        try:
            lead = self.provider.get_lead_by_wa_id(wa_id)
            if not lead:
                lead = self.ensure_lead(wa_id, wa_id)
        except Exception:
            log.exception("Failed to fetch lead for payment proof (%s)", wa_id)
            return None

        payment = PaymentRecord(
            payment_id=str(uuid4()),
            lead_id=lead.lead_id,
            phone_e164=lead.phone_e164,
            expected_amount_le=amount,
            method=method,
            transaction_reference=reference,
            proof_received_at=_utc_now_iso(),
            status="verifying",
        )
        try:
            self.provider.upsert_payment(payment)
        except Exception:
            log.exception("Failed to upsert payment for %s", wa_id)

        return self.update_lead_stage(
            wa_id,
            "PAYMENT_VERIFICATION",
            payment_status="verifying",
        )

    def confirm_payment_and_convert(
        self,
        wa_id: str,
        payment_id: str,
        verified_by: str,
        customer_id: Optional[str] = None,
    ) -> Optional[CustomerRecord]:
        try:
            lead = self.provider.get_lead_by_wa_id(wa_id)
        except Exception:
            log.exception("Failed to fetch lead for conversion (%s)", wa_id)
            lead = None
        if not lead:
            return None

        now = _utc_now_iso()
        months = lead.months if lead.months and lead.months > 0 else 1
        expires_at = (datetime.now(timezone.utc) + timedelta(days=30 * months)).date().isoformat()
        try:
            existing_customer = self.provider.get_customer_by_wa_id(wa_id)
        except Exception:
            log.exception("Failed to fetch existing customer for %s", wa_id)
            existing_customer = None

        if existing_customer:
            customer = existing_customer
            customer.renewal_count += 1
            customer.last_renewed_at = now
            customer.subscription_months = months
            customer.subscription_expires_at = expires_at
            customer.amount_paid_le = lead.subscription_quote_le
            customer.payment_verified_at = now
            customer.account_status = "active"
        else:
            customer = CustomerRecord(
                customer_id=customer_id or str(uuid4()),
                source_lead_id=lead.lead_id,
                wa_id=wa_id,
                phone_e164=lead.phone_e164,
                name=lead.name,
                location_area=lead.area,
                device_types=lead.device_types,
                device_count=lead.device_count,
                subscription_months=months,
                package_code=f"{months}m_{lead.device_count or 1}d",
                amount_paid_le=lead.subscription_quote_le,
                payment_verified_at=now,
                activation_at=now,
                subscription_expires_at=expires_at,
                account_status="active",
                created_at=now,
            )
        try:
            self.provider.upsert_customer(customer)
        except Exception:
            log.exception("Failed to upsert customer for %s", wa_id)

        # Record confirmed payment linked to both lead and customer
        confirmed_payment = PaymentRecord(
            payment_id=payment_id or str(uuid4()),
            lead_id=lead.lead_id,
            customer_id=customer.customer_id,
            phone_e164=lead.phone_e164,
            expected_amount_le=lead.subscription_quote_le,
            status="confirmed",
            verified_by=verified_by,
            verified_at=now,
            created_at=now,
        )
        try:
            self.provider.upsert_payment(confirmed_payment)
        except Exception:
            log.exception("Failed to upsert confirmed payment for %s", wa_id)

        # Mark lead converted
        self.update_lead_stage(
            wa_id,
            "CONVERTED",
            payment_status="confirmed",
        )

        return customer

    def get_customer_for_renewal(self, wa_id: str) -> Optional[CustomerRecord]:
        try:
            return self.provider.get_customer_by_wa_id(wa_id)
        except Exception:
            log.exception("Failed to get customer for renewal (%s)", wa_id)
            return None

    def record_trial_request(self, wa_id: str) -> Optional[LeadRecord]:
        lead = self.update_lead_stage(
            wa_id,
            "TRIAL_REQUESTED",
            trial_requested=True,
        )
        if lead:
            trial = TrialRecord(
                trial_id=str(uuid4()),
                lead_id=lead.lead_id,
                requested_at=_utc_now_iso(),
                approval_status="pending",
            )
            try:
                self.provider.upsert_trial(trial)
            except Exception:
                log.exception("Failed to upsert trial for %s", wa_id)
        return lead

    def record_referral(self, wa_id: str, referrer_code: str) -> Optional[LeadRecord]:
        try:
            lead = self.provider.get_lead_by_wa_id(wa_id)
            if not lead:
                lead = self.ensure_lead(wa_id, wa_id)
            lead.referrer_code = referrer_code
            self.provider.upsert_lead(lead)

            referral = ReferralRecord(
                referral_id=str(uuid4()),
                referrer_id=referrer_code,
                referred_lead_id=lead.lead_id,
                referral_code=referrer_code,
            )
            self.provider.upsert_referral(referral)
            return lead
        except Exception:
            log.exception("Failed to record referral for %s", wa_id)
            return None

    def set_opt_out(self, wa_id: str, opted_out: bool) -> Optional[LeadRecord]:
        try:
            lead = self.provider.get_lead_by_wa_id(wa_id)
            if not lead:
                lead = self.ensure_lead(wa_id, wa_id)
            lead.opted_out = opted_out
            lead.updated_at = _utc_now_iso()
            self.provider.upsert_lead(lead)
            return lead
        except Exception:
            log.exception("Failed to set opt_out for %s", wa_id)
            return None

    def get_payment_by_ref(self, ref: str) -> Optional[PaymentRecord]:
        try:
            if hasattr(self.provider, "get_payment_by_ref"):
                return self.provider.get_payment_by_ref(ref)
        except Exception:
            log.exception("Failed to get payment by ref %s", ref)
        return None