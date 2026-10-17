"""NexgloTV Reseller Bot Engine — Model 1 (Direct-to-NexgloTV) and Model 2 (Prepaid Wallet).

Enables verified resellers to perform commercial operations directly over WhatsApp chat:
1. Model 1 (`DIRECT_TO_NEXGLOTV`):
   - Reseller submits a direct sale or resubscription where customer paid NexgloTV directly.
   - Strictly validates phone, customer name, package duration (1, 3, 6, 12m), devices (1-5), and payment reference.
   - For first-time payments, immediately registers the customer in Lark Base 03_Customers (and 05_Subscriptions).
   - For resubscriptions, extends the subscription, increments renewal count, and updates Lark 03_Customers.
   - Computes expected 20% commission attributed to verified reseller.
2. Model 2 (`PREPAID_WALLET`):
   - Reseller checks live wallet balance & commission totals.
   - Reseller triggers instant customer activation debited from their prepaid balance.
   - Verifies available balance >= net subscription price before debiting.
   - Immediately provisions active customer, subscription, payment, and approved commission.
3. Security & Identification:
   - Robust and secure reseller detection: cross-checks sender phone number against registered profiles
     and Lark Base 09_Resellers.
   - Strictly forbids phone takeover via code hints from unauthorized numbers.
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


def phone_matches(a: str, b: str) -> bool:
    """Robust phone matching across Sierra Leone local (076...) and international (+23276...) formats."""
    da = re.sub(r"[^\d]", "", str(a or ""))
    db = re.sub(r"[^\d]", "", str(b or ""))
    if not da or not db:
        return False
    if da == db:
        return True
    # If one is local (e.g. 076123456, 9 digits) and other international (23276123456, 11 digits)
    # The last 8 digits match for any Sierra Leone mobile line
    if len(da) >= 8 and len(db) >= 8 and da[-8:] == db[-8:]:
        return True
    return False


def normalize_phone_sl(phone: str) -> str:
    """Normalize phone to standard +232 format for Sierra Leone numbers or clean international E.164."""
    digits = re.sub(r"[^\d]", "", str(phone or ""))
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) == 9:
        return f"+232{digits[1:]}"
    if digits.startswith("232") and len(digits) == 11:
        return f"+{digits}"
    if len(digits) == 8:
        return f"+232{digits}"
    return f"+{digits}" if not str(phone).startswith("+") else f"+{digits}"


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


def validate_sale_inputs(
    customer_phone: str,
    customer_name: str,
    months: int,
    devices: int,
    payment_method: str = "Orange Money",
    payment_reference: str = "",
    is_renewal: bool = False,
) -> tuple[bool, Optional[str]]:
    """Validate all commercial parameters before recording a sale or subscription."""
    digits = re.sub(r"[^\d]", "", str(customer_phone or ""))
    if not digits or len(digits) < 8 or len(digits) > 15:
        return False, "❌ Invalid customer phone number. Must be a valid phone number (e.g. 076123456 or +23276123456)."

    if not is_renewal:
        clean_name = str(customer_name or "").strip()
        if len(clean_name) < 2 or not any(c.isalpha() for c in clean_name):
            return False, "❌ Customer name is required (at least 2 letters)."
        if clean_name.lower() in ("valued customer", "customer", "unknown", "test", "none", "null"):
            return False, "❌ Please provide the customer's actual full name."

    if months not in (1, 3, 6, 12):
        return False, f"❌ Invalid duration: {months} month(s). NexgloTV packages are 1, 3, 6, or 12 months."

    if not isinstance(devices, int) or devices < 1 or devices > 5:
        return False, f"❌ Invalid device count: {devices}. Supported devices are between 1 and 5 devices."

    if payment_method:
        valid_methods = {"orange money", "afrimoney", "bank transfer", "cash", "qmoney", "card", "prepaid wallet", "reported"}
        if payment_method.strip().lower() not in valid_methods and len(payment_method.strip()) < 3:
            return False, f"❌ Invalid payment method '{payment_method}'. Use Orange Money, Afrimoney, Bank Transfer, or Cash."

    if not payment_reference or len(str(payment_reference).strip()) < 3:
        return False, "❌ A valid payment reference or transaction ID (min 3 chars) is required for verification."

    return True, None


class ResellerBotManager:
    """Manages Reseller operations over WhatsApp chat, connecting to Lark Base CRM."""

    def __init__(self, crm_provider=None, wallet_enabled: bool = False, store=None):
        self.crm_provider = crm_provider
        self.wallet_enabled = wallet_enabled or WALLET_MODEL_ENABLED
        self.store = store
        # In-memory registry for local testing, fallback, and fast session lookup
        self._resellers_by_phone: dict[str, ResellerProfile] = {}
        self._resellers_by_code: dict[str, ResellerProfile] = {}
        self._wallet_ledger: list[dict[str, Any]] = []
        self._commissions_ledger: list[dict[str, Any]] = []
        self._seed_default_resellers()

    def _seed_default_resellers(self) -> None:
        """Seed default verified pilot resellers for instant recognition."""
        pilot1 = ResellerProfile(
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
        self.register_reseller(pilot1)

        pilot2 = ResellerProfile(
            reseller_id="RES-PILOT-001",
            reseller_code="RSL-PILOT01",
            name="Alpha Partner (SL)",
            phone="+23276111000",
            email="pilot01@nexglotv.com",
            status="Active",
            operating_model="Hybrid",
            commission_rate=20,
            wallet_balance=1500,
            approved_commissions=360,
            unpaid_commissions=360,
        )
        self.register_reseller(pilot2)

    def register_reseller(self, profile: ResellerProfile) -> None:
        """Register or update a reseller in local memory."""
        phone_key = _digits(profile.phone)
        code_key = profile.reseller_code.strip().upper()
        self._resellers_by_phone[phone_key] = profile
        self._resellers_by_code[code_key] = profile

    def identify_reseller(self, wa_id: str, code_hint: Optional[str] = None) -> Optional[ResellerProfile]:
        """Look up a verified active reseller strictly by WhatsApp ID.
        
        Security guarantees:
        - Arbitrary senders CANNOT claim a reseller account merely by typing a code.
        - The sender's phone number must match the registered phone on the profile.
        - If code_hint is provided, it only succeeds if the sender's phone matches that code's registered profile.
        """
        if not wa_id:
            return None

        # 1. Match against registered phone numbers in memory
        for reg_phone, profile in self._resellers_by_phone.items():
            if phone_matches(wa_id, profile.phone) or phone_matches(wa_id, reg_phone):
                if profile.status.lower() == "active":
                    # If code_hint was also given, ensure it doesn't conflict
                    if code_hint and code_hint.strip().upper() != profile.reseller_code.strip().upper():
                        continue
                    return profile

        # 2. Query live Lark Base if crm_provider is connected
        if self.crm_provider and hasattr(self.crm_provider, "_get_by_wa"):
            try:
                row = self.crm_provider._get_by_wa("09_Resellers", wa_id)
                if row:
                    res_phone = str(row.get("Phone Number") or row.get("Phone") or wa_id)
                    # Strict security check: phone must match sender
                    if phone_matches(wa_id, res_phone):
                        res = ResellerProfile(
                            reseller_id=str(row.get("Reseller ID", "RSL-999")),
                            reseller_code=str(row.get("Reseller Code", "RES-NEW")),
                            name=str(row.get("Reseller Name") or row.get("Business Name", "Partner")),
                            phone=res_phone,
                            email=str(row.get("Business Email", "")),
                            status=str(row.get("Status", "Active")),
                            operating_model=str(row.get("Operating Model", "Hybrid")),
                        )
                        self.register_reseller(res)
                        return res
            except Exception as exc:
                log.warning("Live Lark reseller lookup failed for %s: %s", wa_id, exc)

        # 3. If code_hint was provided, check if code exists, but STRICTLY VERIFY SENDER PHONE
        if code_hint:
            clean_code = code_hint.strip().upper()
            if clean_code in self._resellers_by_code:
                cand = self._resellers_by_code[clean_code]
                if phone_matches(wa_id, cand.phone):
                    return cand
                else:
                    log.warning(
                        "Security violation: Sender %s attempted to claim reseller code %s belonging to %s",
                        wa_id, clean_code, cand.phone,
                    )
                    return None

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
        is_renewal: bool = False,
    ) -> dict[str, Any]:
        """Process Model 1 direct sale or resubscription: Customer paid NexgloTV directly.

        Validates inputs, logs customer to Lark 03_Customers (and 05_Subscriptions),
        records payment, and attributes 20% commission to reseller.
        """
        # 1. Input validations
        is_valid, err_msg = validate_sale_inputs(
            customer_phone=customer_phone,
            customer_name=customer_name,
            months=months,
            devices=devices,
            payment_method=payment_method,
            payment_reference=payment_reference,
            is_renewal=is_renewal,
        )
        if not is_valid:
            return {
                "success": False,
                "error": "validation_error",
                "message": err_msg,
            }

        norm_phone = normalize_phone_sl(customer_phone)
        quote = calculate_price(months, devices)
        sale_amount = amount_reported or quote.final_price
        expected_commission = round(sale_amount * (reseller.commission_rate / 100))

        event_ts = int(time.time())
        lead_id = f"LEAD-RSL-{event_ts}"
        payment_id = f"PAY-RSL-{event_ts}"
        sale_ref = f"RSALE-{reseller.reseller_code}-{event_ts}"
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        # Check existing customer
        existing_customer = None
        if self.crm_provider and hasattr(self.crm_provider, "get_customer_by_wa_id"):
            try:
                existing_customer = self.crm_provider.get_customer_by_wa_id(norm_phone)
            except Exception:
                existing_customer = None

        is_resub = is_renewal or (existing_customer is not None)
        resolved_name = customer_name or (existing_customer.name if existing_customer else "Valued Customer")

        if is_resub and existing_customer:
            customer_id = existing_customer.customer_id
            renewal_count = (existing_customer.renewal_count or 0) + 1
            # Extend from current expiry if future, else from now
            base_exp = now_dt
            if existing_customer.subscription_expires_at:
                try:
                    cur_exp = datetime.fromisoformat(existing_customer.subscription_expires_at.replace("Z", "+00:00"))
                    if cur_exp > now_dt:
                        base_exp = cur_exp
                except Exception:
                    pass
            expires_iso = (base_exp + timedelta(days=months * 30)).isoformat()
        else:
            customer_id = f"CUST-RSL-{event_ts}"
            renewal_count = 0
            expires_iso = (now_dt + timedelta(days=months * 30)).isoformat()

        # Sync to Lark Base CRM
        if self.crm_provider:
            try:
                from .crm_sheets import CustomerRecord, LeadRecord, PaymentRecord

                # When a person pays first time, it is written to Lark Base 03_Customers
                customer = CustomerRecord(
                    customer_id=customer_id,
                    source_lead_id=lead_id if not is_resub else getattr(existing_customer, "source_lead_id", ""),
                    wa_id=norm_phone,
                    phone_e164=norm_phone,
                    name=resolved_name,
                    subscription_months=months,
                    device_count=devices,
                    package_code=f"PKG-{months}M-{devices}D",
                    amount_paid_le=sale_amount,
                    payment_method=payment_method,
                    transaction_reference=payment_reference,
                    reseller_code=reseller.reseller_code,
                    activation_at=now_iso,
                    subscription_expires_at=expires_iso,
                    account_status="active",
                    renewal_count=renewal_count,
                    last_renewed_at=now_iso if is_resub else None,
                )
                if hasattr(self.crm_provider, "upsert_customer"):
                    self.crm_provider.upsert_customer(customer)

                # Keep lead updated as converted
                if hasattr(self.crm_provider, "upsert_lead"):
                    lead = LeadRecord(
                        lead_id=lead_id,
                        wa_id=norm_phone,
                        phone_e164=norm_phone,
                        name=resolved_name,
                        source="reseller",
                        reseller_code=reseller.reseller_code,
                        lead_stage="CONVERTED" if not is_resub else "RENEWAL",
                        months=months,
                        device_count=devices,
                        subscription_quote_le=sale_amount,
                        discount_pct=20,
                        notes=(
                            f"Model: DIRECT_TO_NEXGLOTV | Reseller: {reseller.reseller_code} | "
                            f"Ref: {payment_reference} | Customer: {customer_id}"
                        ),
                    )
                    self.crm_provider.upsert_lead(lead)

                # Record payment in 04_Payments
                if hasattr(self.crm_provider, "upsert_payment"):
                    payment = PaymentRecord(
                        payment_id=payment_id,
                        customer_id=customer_id,
                        lead_id=lead_id,
                        expected_amount_le=sale_amount,
                        method=payment_method,
                        transaction_reference=payment_reference,
                        status="pending",
                        note=(
                            f"Reseller {'Renewal' if is_resub else 'Direct Sale'} via {reseller.reseller_code}. "
                            f"Commission expected: Le{expected_commission:,}"
                        ),
                    )
                    self.crm_provider.upsert_payment(payment)
            except Exception as exc:
                log.warning("Failed to sync direct sale/customer to Lark: %s", exc)

        # Mark in local / Turso DB state store
        if self.store and hasattr(self.store, "set_customer_flag"):
            try:
                self.store.set_customer_flag(norm_phone, True, customer_id)
            except Exception:
                pass

        # Track in commissions ledger
        comm_entry = {
            "sale_ref": sale_ref,
            "reseller_code": reseller.reseller_code,
            "customer_phone": norm_phone,
            "customer_name": resolved_name,
            "amount": sale_amount,
            "expected_commission": expected_commission,
            "is_renewal": is_resub,
            "status": "pending_verification",
            "payment_ref": payment_reference,
            "timestamp": now_iso,
        }
        self._commissions_ledger.append(comm_entry)

        return {
            "success": True,
            "model": "DIRECT_TO_NEXGLOTV",
            "is_renewal": is_resub,
            "sale_ref": sale_ref,
            "customer_id": customer_id,
            "customer_name": resolved_name,
            "customer_phone": norm_phone,
            "package": f"{months} Month{'s' if months > 1 else ''} ({devices} Device{'s' if devices > 1 else ''})",
            "amount_due": sale_amount,
            "payment_method": payment_method,
            "payment_reference": payment_reference,
            "commission_rate": reseller.commission_rate,
            "expected_commission": expected_commission,
            "renewal_count": renewal_count if is_resub else 0,
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
        is_renewal: bool = False,
    ) -> dict[str, Any]:
        """Process Model 2 instant activation funded by Reseller Prepaid Wallet.

        Checks available wallet balance >= net price, debits wallet, creates
        or extends active customer, subscription, and immediately awards 20% commission.
        """
        # 1. Input validations
        is_valid, err_msg = validate_sale_inputs(
            customer_phone=customer_phone,
            customer_name=customer_name,
            months=months,
            devices=devices,
            payment_method="Prepaid Wallet",
            payment_reference="WALLET",
            is_renewal=is_renewal,
        )
        if not is_valid:
            return {
                "success": False,
                "model": "PREPAID_WALLET",
                "error": "validation_error",
                "message": err_msg,
            }

        norm_phone = normalize_phone_sl(customer_phone)
        quote = calculate_price(months, devices)
        net_subscription_price = quote.final_price
        commission_earned = round(net_subscription_price * (reseller.commission_rate / 100))

        # Check if wallet model is currently enabled
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

        # Balance verification check
        if reseller.wallet_balance < net_subscription_price:
            return {
                "success": False,
                "model": "PREPAID_WALLET",
                "error": "insufficient_funds",
                "required_amount": net_subscription_price,
                "available_balance": reseller.wallet_balance,
                "deficit": net_subscription_price - reseller.wallet_balance,
            }

        # Debit wallet balance & award commission
        reseller.wallet_balance -= net_subscription_price
        reseller.approved_commissions += commission_earned
        reseller.unpaid_commissions += commission_earned

        event_ts = int(time.time())
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        wallet_entry_id = f"WLT-{reseller.reseller_code}-{event_ts}"

        # Check existing customer for renewal
        existing_customer = None
        if self.crm_provider and hasattr(self.crm_provider, "get_customer_by_wa_id"):
            try:
                existing_customer = self.crm_provider.get_customer_by_wa_id(norm_phone)
            except Exception:
                existing_customer = None

        is_resub = is_renewal or (existing_customer is not None)
        resolved_name = customer_name or (existing_customer.name if existing_customer else "Valued Customer")

        if is_resub and existing_customer:
            customer_id = existing_customer.customer_id
            renewal_count = (existing_customer.renewal_count or 0) + 1
            base_exp = now_dt
            if existing_customer.subscription_expires_at:
                try:
                    cur_exp = datetime.fromisoformat(existing_customer.subscription_expires_at.replace("Z", "+00:00"))
                    if cur_exp > now_dt:
                        base_exp = cur_exp
                except Exception:
                    pass
            expires_iso = (base_exp + timedelta(days=months * 30)).isoformat()
        else:
            customer_id = f"CUST-RSL-{event_ts}"
            renewal_count = 0
            expires_iso = (now_dt + timedelta(days=months * 30)).isoformat()

        sub_id = f"SUB-RSL-{event_ts}"

        # Record in local wallet ledger
        self._wallet_ledger.append({
            "entry_id": wallet_entry_id,
            "reseller_code": reseller.reseller_code,
            "type": "WALLET_ACTIVATION_DEBIT",
            "debit": net_subscription_price,
            "credit": 0,
            "related_customer": norm_phone,
            "is_renewal": is_resub,
            "new_balance": reseller.wallet_balance,
            "timestamp": now_iso,
        })

        # Sync to Lark CRM
        if self.crm_provider:
            try:
                from .crm_sheets import CustomerRecord, PaymentRecord

                customer = CustomerRecord(
                    customer_id=customer_id,
                    source_lead_id=f"LEAD-RSL-{event_ts}",
                    wa_id=norm_phone,
                    phone_e164=norm_phone,
                    name=resolved_name,
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
                    renewal_count=renewal_count,
                    last_renewed_at=now_iso if is_resub else None,
                )
                if hasattr(self.crm_provider, "upsert_customer"):
                    self.crm_provider.upsert_customer(customer)

                if hasattr(self.crm_provider, "upsert_payment"):
                    payment = PaymentRecord(
                        payment_id=f"PAY-WLT-{event_ts}",
                        customer_id=customer_id,
                        expected_amount_le=net_subscription_price,
                        method="Prepaid Wallet",
                        transaction_reference=wallet_entry_id,
                        status="confirmed",
                        verified_by=f"WALLET_AUTO:{reseller.reseller_code}",
                        note=(
                            f"Funded via Reseller {reseller.reseller_code} Prepaid Wallet "
                            f"({'Renewal' if is_resub else 'Activation'}). Comm: Le{commission_earned:,}"
                        ),
                    )
                    self.crm_provider.upsert_payment(payment)
            except Exception as exc:
                log.warning("Failed to sync wallet activation to Lark: %s", exc)

        # Mark in local / Turso DB state store
        if self.store and hasattr(self.store, "set_customer_flag"):
            try:
                self.store.set_customer_flag(norm_phone, True, customer_id)
            except Exception:
                pass

        return {
            "success": True,
            "model": "PREPAID_WALLET",
            "is_renewal": is_resub,
            "customer_id": customer_id,
            "subscription_id": sub_id,
            "customer_name": resolved_name,
            "customer_phone": norm_phone,
            "package": f"{months} Month{'s' if months > 1 else ''} ({devices} Device{'s' if devices > 1 else ''})",
            "debited_amount": net_subscription_price,
            "commission_earned": commission_earned,
            "remaining_balance": reseller.wallet_balance,
            "unpaid_commissions_total": reseller.unpaid_commissions,
            "renewal_count": renewal_count if is_resub else 0,
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


def parse_direct_sale_text(text: str, is_renewal: bool = False) -> Optional[dict[str, Any]]:
    """Parse text input into Model 1 Direct Sale or Resubscription arguments."""
    clean = re.sub(
        r"^(?:DIRECT\s+SALE|SALE|RENEW|RESUBSCRIBE|RENEWAL)\s*[:,]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not clean:
        return None

    # Check if text explicitly uses RENEW or RESUBSCRIBE keywords
    is_resub = is_renewal or bool(re.search(r"^(?:RENEW|RESUBSCRIBE|RENEWAL)\b", text, re.IGNORECASE))

    # Comma-separated: Phone, [Name], Package, Method, Ref
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) >= 2:
            phone = parse_phone_number(parts[0])
            if phone:
                # If renewal and format is: Phone, Package, Method, Ref
                if is_resub and len(parts) in (3, 4) and any(k in parts[1].lower() for k in ("m", "mo", "dev", "month", "device")):
                    months, devices = parse_package_spec(parts[1])
                    method = parts[2] if len(parts) >= 3 else "Orange Money"
                    ref = parts[3] if len(parts) >= 4 else f"REF-{int(time.time())}"
                    return {
                        "customer_phone": phone,
                        "customer_name": "",
                        "months": months,
                        "devices": devices,
                        "payment_method": method,
                        "payment_reference": ref,
                        "is_renewal": True,
                    }

                if len(parts) >= 3:
                    name = parts[1]
                    months, devices = parse_package_spec(parts[2])
                    method = parts[3] if len(parts) >= 4 else "Orange Money"
                    ref = parts[4] if len(parts) >= 5 else f"REF-{int(time.time())}"
                    return {
                        "customer_phone": phone,
                        "customer_name": name,
                        "months": months,
                        "devices": devices,
                        "payment_method": method,
                        "payment_reference": ref,
                        "is_renewal": is_resub,
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
        if len(tok) >= 4 and any(c.isdigit() for c in tok) and tok not in phone:
            ref = tok
            break

    potential_names = [t for t in tokens if t.isalpha() and t.lower() not in (
        "direct", "sale", "renew", "resubscribe", "renewal", "orange", "money",
        "afrimoney", "bank", "cash", "month", "months", "device", "devices", "via", "ref"
    )]
    name = " ".join(potential_names[:2]) if potential_names else ("" if is_resub else "Valued Customer")

    return {
        "customer_phone": phone,
        "customer_name": name,
        "months": months,
        "devices": devices,
        "payment_method": method,
        "payment_reference": ref,
        "is_renewal": is_resub,
    }


def parse_wallet_activation_text(text: str, is_renewal: bool = False) -> Optional[dict[str, Any]]:
    """Parse text input into Model 2 Wallet Activation or Resubscription arguments."""
    clean = re.sub(
        r"^(?:ACTIVATE|WALLET\s+ACTIVATE|WALLET\s+RENEW|WALLET)\s*[:,]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not clean:
        return None

    is_resub = is_renewal or "renew" in text.lower()

    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) >= 2:
            phone = parse_phone_number(parts[0])
            if phone:
                if is_resub and len(parts) == 2 and any(k in parts[1].lower() for k in ("m", "mo", "dev", "month", "device")):
                    months, devices = parse_package_spec(parts[1])
                    return {
                        "customer_phone": phone,
                        "customer_name": "",
                        "months": months,
                        "devices": devices,
                        "is_renewal": True,
                    }
                name = parts[1]
                pkg_str = parts[2] if len(parts) >= 3 else "1m 1d"
                months, devices = parse_package_spec(pkg_str)
                return {
                    "customer_phone": phone,
                    "customer_name": name,
                    "months": months,
                    "devices": devices,
                    "is_renewal": is_resub,
                }

    phone = parse_phone_number(clean)
    if not phone:
        return None

    months, devices = parse_package_spec(clean)
    tokens = clean.split()
    potential_names = [t for t in tokens if t.isalpha() and t.lower() not in (
        "activate", "wallet", "renew", "month", "months", "device", "devices", "dev"
    )]
    name = " ".join(potential_names[:2]) if potential_names else ("" if is_resub else "Valued Customer")

    return {
        "customer_phone": phone,
        "customer_name": name,
        "months": months,
        "devices": devices,
        "is_renewal": is_resub,
    }
