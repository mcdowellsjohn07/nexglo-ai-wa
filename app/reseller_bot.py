"""NexgloTV Reseller Bot Engine — Model 1 (Direct-to-NexgloTV) and Model 2 (Prepaid Wallet).

Enables verified resellers to perform commercial operations directly over WhatsApp chat:
1. Model 1 (`DIRECT_TO_NEXGLOTV`):
   - Reseller submits a direct sale where customer paid NexgloTV directly.
   - Logs customer lead, pending payment with transaction reference, and tags Reseller ID.
   - Computes expected 20% commission upon admin verification.
2. Model 2 (`PREPAID_WALLET`):
   - Reseller checks live wallet balance & commission totals.
   - Reseller triggers instant customer activation debited from their prepaid balance.
   - Verifies available balance >= net subscription price before debiting.
   - Immediately provisions active customer, subscription, payment, and approved commission.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.nexglo_pricing import calculate_price, PriceQuote

log = logging.getLogger("nexglo.reseller_bot")


def _digits(phone: str) -> str:
    """Extract standard trailing 9 digits for phone comparison."""
    return re.sub(r"[^\d]", "", str(phone or ""))[-9:]


# Operational toggle: Wallet model is disabled by default until official admin rollout
WALLET_MODEL_ENABLED: bool = False


@dataclass
class ResellerProfile:
    reseller_id: str
    reseller_code: str
    name: str
    phone: str
    email: str = ""
    status: str = "Active"
    operating_model: str = "Hybrid"  # Direct, Prepaid Wallet, or Hybrid
    commission_rate: int = 20
    wallet_balance: int = 0
    approved_commissions: int = 0
    unpaid_commissions: int = 0


class ResellerBotManager:
    """Manages Reseller operations over WhatsApp chat, connecting to Lark Base CRM."""

    def __init__(self, crm_provider=None, wallet_enabled: bool = False):
        self.crm_provider = crm_provider
        self.wallet_enabled = wallet_enabled or WALLET_MODEL_ENABLED
        # In-memory registry for local testing, fallback, and fast session lookup
        self._resellers_by_phone: dict[str, ResellerProfile] = {}
        self._resellers_by_code: dict[str, ResellerProfile] = {}
        self._wallet_ledger: list[dict[str, Any]] = []
        self._commissions_ledger: list[dict[str, Any]] = []
        self._seed_default_resellers()

    def _seed_default_resellers(self) -> None:
        """Seed default verified pilot resellers for instant recognition."""
        pilot = ResellerProfile(
            reseller_id="RSL-001",
            reseller_code="RSL-PILOT01",
            name="Alpha Partner",
            phone="23276000001",
            email="pilot01@nexglotv.com",
            status="Active",
            operating_model="Hybrid",
            commission_rate=20,
            wallet_balance=1500,  # Seeded Le1,500 initial prepaid balance
            approved_commissions=360,
            unpaid_commissions=360,
        )
        self.register_reseller(pilot)

    def register_reseller(self, profile: ResellerProfile) -> None:
        """Register or update a reseller in local memory."""
        phone_key = _digits(profile.phone)
        code_key = profile.reseller_code.strip().upper()
        self._resellers_by_phone[phone_key] = profile
        self._resellers_by_code[code_key] = profile

    def identify_reseller(self, wa_id: str, code_hint: Optional[str] = None) -> Optional[ResellerProfile]:
        """Look up a verified active reseller by WhatsApp ID or Reseller Code."""
        phone_key = _digits(wa_id)
        if phone_key and phone_key in self._resellers_by_phone:
            res = self._resellers_by_phone[phone_key]
            if res.status.lower() == "active":
                return res

        if code_hint:
            clean_code = code_hint.strip().upper()
            if clean_code in self._resellers_by_code:
                res = self._resellers_by_code[clean_code]
                if res.status.lower() == "active":
                    # Associate phone with code for current session
                    if phone_key:
                        self._resellers_by_phone[phone_key] = res
                    return res

        # Fallback: Query live Lark Base if crm_provider is connected
        if self.crm_provider and hasattr(self.crm_provider, "_get_by_wa"):
            try:
                row = self.crm_provider._get_by_wa("09_Resellers", wa_id)
                if row:
                    res = ResellerProfile(
                        reseller_id=str(row.get("Reseller ID", "RSL-999")),
                        reseller_code=str(row.get("Reseller Code", "RES-NEW")),
                        name=str(row.get("Reseller Name") or row.get("Business Name", "Partner")),
                        phone=wa_id,
                        email=str(row.get("Business Email", "")),
                        status=str(row.get("Status", "Active")),
                        operating_model=str(row.get("Operating Model", "Hybrid")),
                    )
                    self.register_reseller(res)
                    return res
            except Exception as exc:
                log.warning("Live Lark reseller lookup failed for %s: %s", wa_id, exc)

        return None

    def get_wallet_summary(self, reseller: ResellerProfile) -> dict[str, int]:
        """Return wallet balance, total earned commissions, and unpaid commissions."""
        return {
            "wallet_balance": reseller.wallet_balance,
            "approved_commissions": reseller.approved_commissions,
            "unpaid_commissions": reseller.unpaid_commissions,
        }

    # =========================================================================
    # Model 1: DIRECT_TO_NEXGLOTV (Customer Paid NexgloTV Directly)
    # =========================================================================
    def process_direct_sale(
        self,
        reseller: ResellerProfile,
        customer_phone: str,
        customer_name: str,
        months: int,
        devices: int,
        payment_method: str,
        payment_reference: str,
        amount_reported: Optional[int] = None,
    ) -> dict[str, Any]:
        """Process Model 1 direct sale: Customer paid NexgloTV directly.

        Logs lead, pending payment, and attributes 20% commission to reseller.
        """
        quote = calculate_price(months, devices)
        sale_amount = amount_reported or quote.final_price
        expected_commission = round(sale_amount * (reseller.commission_rate / 100))

        lead_id = f"LEAD-RSL-{int(time.time())}"
        payment_id = f"PAY-RSL-{int(time.time())}"
        sale_ref = f"RSALE-{reseller.reseller_code}-{int(time.time())}"

        # Sync to Lark if available
        if self.crm_provider and hasattr(self.crm_provider, "upsert_lead"):
            try:
                from .crm_sheets import LeadRecord, PaymentRecord
                lead = LeadRecord(
                    lead_id=lead_id,
                    wa_id=customer_phone,
                    phone_e164=customer_phone,
                    name=customer_name,
                    source="reseller",
                    reseller_code=reseller.reseller_code,
                    lead_stage="PAYMENT_VERIFICATION",
                    months=months,
                    device_count=devices,
                    subscription_quote_le=sale_amount,
                    discount_pct=20,
                    notes=f"Model: DIRECT_TO_NEXGLOTV | Reseller: {reseller.reseller_code} | Ref: {payment_reference}",
                )
                self.crm_provider.upsert_lead(lead)

                payment = PaymentRecord(
                    payment_id=payment_id,
                    lead_id=lead_id,
                    expected_amount_le=sale_amount,
                    method=payment_method,
                    transaction_reference=payment_reference,
                    status="pending",
                    note=f"Reseller Direct Sale via {reseller.reseller_code}. Commission expected: Le{expected_commission:,}",
                )
                self.crm_provider.upsert_payment(payment)
            except Exception as exc:
                log.warning("Failed to sync direct sale to Lark: %s", exc)

        # Track in commissions ledger
        comm_entry = {
            "sale_ref": sale_ref,
            "reseller_code": reseller.reseller_code,
            "customer_phone": customer_phone,
            "customer_name": customer_name,
            "amount": sale_amount,
            "expected_commission": expected_commission,
            "status": "pending_verification",
            "payment_ref": payment_reference,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._commissions_ledger.append(comm_entry)

        return {
            "success": True,
            "model": "DIRECT_TO_NEXGLOTV",
            "sale_ref": sale_ref,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "package": f"{months} Month{'s' if months > 1 else ''} ({devices} Device{'s' if devices > 1 else ''})",
            "amount_due": sale_amount,
            "payment_method": payment_method,
            "payment_reference": payment_reference,
            "commission_rate": reseller.commission_rate,
            "expected_commission": expected_commission,
            "status": "Pending Admin Verification",
        }

    # =========================================================================
    # Model 2: PREPAID_WALLET (Instant Activation via Reseller Wallet)
    # =========================================================================
    def process_wallet_activation(
        self,
        reseller: ResellerProfile,
        customer_phone: str,
        customer_name: str,
        months: int,
        devices: int,
    ) -> dict[str, Any]:
        """Process Model 2 instant activation funded by Reseller Prepaid Wallet.

        Checks available wallet balance >= net price, debits wallet, creates
        active customer, subscription, and immediately awards 20% commission.
        """
        quote = calculate_price(months, devices)
        net_subscription_price = quote.final_price
        commission_earned = round(net_subscription_price * (reseller.commission_rate / 100))

        # 0. Check if wallet model is currently enabled
        if not self.wallet_enabled and not WALLET_MODEL_ENABLED:
            return {
                "success": False,
                "model": "PREPAID_WALLET",
                "error": "wallet_model_disabled",
                "message": (
                    "Prepaid Wallet activation is temporarily disabled by NexgloTV Administration. "
                    "Please process sales via Model 1 (Direct to NexgloTV) or contact Admin."
                ),
            }

        # 1. Balance verification check
        if reseller.wallet_balance < net_subscription_price:
            return {
                "success": False,
                "model": "PREPAID_WALLET",
                "error": "insufficient_funds",
                "required_amount": net_subscription_price,
                "available_balance": reseller.wallet_balance,
                "deficit": net_subscription_price - reseller.wallet_balance,
            }

        # 2. Debit wallet balance
        reseller.wallet_balance -= net_subscription_price
        reseller.approved_commissions += commission_earned
        reseller.unpaid_commissions += commission_earned

        event_ts = int(time.time())
        customer_id = f"CUST-RSL-{event_ts}"
        sub_id = f"SUB-RSL-{event_ts}"
        wallet_entry_id = f"WLT-{reseller.reseller_code}-{event_ts}"

        # 3. Record in local wallet ledger
        self._wallet_ledger.append({
            "entry_id": wallet_entry_id,
            "reseller_code": reseller.reseller_code,
            "type": "WALLET_ACTIVATION_DEBIT",
            "debit": net_subscription_price,
            "credit": 0,
            "related_customer": customer_phone,
            "new_balance": reseller.wallet_balance,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 4. Sync to Lark CRM if connected
        if self.crm_provider and hasattr(self.crm_provider, "upsert_customer"):
            try:
                from .crm_sheets import CustomerRecord, PaymentRecord
                now_iso = datetime.now(timezone.utc).isoformat()
                expires_iso = (datetime.now(timezone.utc) + timedelta(days=months * 30)).isoformat()

                customer = CustomerRecord(
                    customer_id=customer_id,
                    source_lead_id=f"LEAD-RSL-{event_ts}",
                    wa_id=customer_phone,
                    phone_e164=customer_phone,
                    name=customer_name,
                    subscription_months=months,
                    device_count=devices,
                    package_code=f"PKG-{months}M-{devices}D",
                    amount_paid_le=net_subscription_price,
                    payment_method="Prepaid Wallet",
                    transaction_reference=wallet_entry_id,
                    reseller_code=reseller.reseller_code,
                    activation_at=now_iso,
                    subscription_expires_at=expires_iso,
                    account_status="active",
                )
                self.crm_provider.upsert_customer(customer)

                payment = PaymentRecord(
                    payment_id=f"PAY-WLT-{event_ts}",
                    customer_id=customer_id,
                    expected_amount_le=net_subscription_price,
                    method="Prepaid Wallet",
                    transaction_reference=wallet_entry_id,
                    status="confirmed",
                    verified_by=f"WALLET_AUTO:{reseller.reseller_code}",
                    note=f"Funded via Reseller {reseller.reseller_code} Prepaid Wallet. Comm: Le{commission_earned:,}",
                )
                self.crm_provider.upsert_payment(payment)
            except Exception as exc:
                log.warning("Failed to sync wallet activation to Lark: %s", exc)

        return {
            "success": True,
            "model": "PREPAID_WALLET",
            "customer_id": customer_id,
            "subscription_id": sub_id,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "package": f"{months} Month{'s' if months > 1 else ''} ({devices} Device{'s' if devices > 1 else ''})",
            "debited_amount": net_subscription_price,
            "commission_earned": commission_earned,
            "remaining_balance": reseller.wallet_balance,
            "unpaid_commissions_total": reseller.unpaid_commissions,
            "status": "Active & Provisioned Immediately",
        }


# =============================================================================
# Input Parsers for WhatsApp Chat
# =============================================================================

def parse_package_spec(text: str) -> tuple[int, int]:
    """Extract (months, devices) from text snippet like '1m 1d', '3 months 2 devices'."""
    months = 1
    devices = 1
    m_match = re.search(r"(\d+)\s*(?:m|mo|mes|month|meses)", text, re.IGNORECASE)
    if m_match:
        months = int(m_match.group(1))
    d_match = re.search(r"(\d+)\s*(?:d|dev|disp|device|dispositivo)", text, re.IGNORECASE)
    if d_match:
        devices = int(d_match.group(1))
    if months not in (1, 3, 6, 12):
        months = 1
    if devices < 1:
        devices = 1
    return months, devices


def parse_phone_number(text: str) -> Optional[str]:
    """Find a phone number in Sierra Leone or international format."""
    m = re.search(r"(\+?232\d{8}|0\d{8}|\d{8,12})", text)
    if m:
        raw = m.group(1)
        if raw.startswith("0") and len(raw) == 9:
            return f"+232{raw[1:]}"
        if not raw.startswith("+"):
            return f"+{raw}"
        return raw
    return None


def parse_direct_sale_text(text: str) -> Optional[dict[str, Any]]:
    """Parse text input into Model 1 Direct Sale arguments."""
    clean = re.sub(r"^(?:DIRECT\s+SALE|SALE)\s*[:,]?\s*", "", text, flags=re.IGNORECASE).strip()
    if not clean:
        return None

    # Comma-separated: Phone, Name, Package, Method, Ref
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) >= 3:
            phone = parse_phone_number(parts[0])
            name = parts[1]
            months, devices = parse_package_spec(parts[2])
            method = parts[3] if len(parts) >= 4 else "Orange Money"
            ref = parts[4] if len(parts) >= 5 else f"REF-{int(time.time())}"
            if phone:
                return {
                    "customer_phone": phone,
                    "customer_name": name,
                    "months": months,
                    "devices": devices,
                    "payment_method": method,
                    "payment_reference": ref,
                }

    phone = parse_phone_number(clean)
    if not phone:
        return None

    months, devices = parse_package_spec(clean)
    clean_lower = clean.lower()
    method = "Orange Money"
    if "afri" in clean_lower:
        method = "Afrimoney"
    elif "bank" in clean_lower:
        method = "Bank Transfer"
    elif "cash" in clean_lower:
        method = "Cash"

    ref = f"REF-{int(time.time())}"
    tokens = clean.split()
    for tok in reversed(tokens):
        if len(tok) >= 5 and any(c.isdigit() for c in tok) and tok not in phone:
            ref = tok
            break

    potential_names = [t for t in tokens if t.isalpha() and t.lower() not in (
        "direct", "sale", "orange", "money", "afrimoney", "bank", "cash",
        "month", "months", "device", "devices", "via", "ref"
    )]
    name = " ".join(potential_names[:2]) if potential_names else "Valued Customer"

    return {
        "customer_phone": phone,
        "customer_name": name,
        "months": months,
        "devices": devices,
        "payment_method": method,
        "payment_reference": ref,
    }


def parse_wallet_activation_text(text: str) -> Optional[dict[str, Any]]:
    """Parse text input into Model 2 Wallet Activation arguments."""
    clean = re.sub(r"^(?:ACTIVATE|WALLET\s+ACTIVATE|WALLET)\s*[:,]?\s*", "", text, flags=re.IGNORECASE).strip()
    if not clean:
        return None

    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) >= 2:
            phone = parse_phone_number(parts[0])
            name = parts[1]
            pkg_str = parts[2] if len(parts) >= 3 else "1m 1d"
            months, devices = parse_package_spec(pkg_str)
            if phone:
                return {
                    "customer_phone": phone,
                    "customer_name": name,
                    "months": months,
                    "devices": devices,
                }

    phone = parse_phone_number(clean)
    if not phone:
        return None

    months, devices = parse_package_spec(clean)
    tokens = clean.split()
    potential_names = [t for t in tokens if t.isalpha() and t.lower() not in (
        "activate", "wallet", "month", "months", "device", "devices", "dev"
    )]
    name = " ".join(potential_names[:2]) if potential_names else "Valued Customer"

    return {
        "customer_phone": phone,
        "customer_name": name,
        "months": months,
        "devices": devices,
    }

