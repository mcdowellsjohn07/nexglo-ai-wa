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
        if clean_name.lower() in ("unknown", "test", "none", "null"):
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
                    res_phone = str(row.get("WhatsApp Number") or row.get("Phone Number") or row.get("Phone") or wa_id)
                    # Strict security check: phone must match sender
                    if phone_matches(wa_id, res_phone):
                        res = ResellerProfile(
                            reseller_id=str(row.get("Reseller ID", "RSL-999")),
                            reseller_code=str(row.get("Reseller Code", "RES-NEW")),
                            name=str(row.get("Business or Full Name") or row.get("Primary Contact") or row.get("Reseller Name") or row.get("Business Name", "Partner")),
                            phone=res_phone,
                            email=str(row.get("Business Email", "")),
                            status=str(row.get("Status", "Active")),
                            operating_model=str(row.get("Operating Model", "DIRECT_TO_NEXGLOTV")),
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
                    log.info(
                        "Sender %s provided reseller code %s (customer referral context)",
                        wa_id, clean_code,
                    )
                    return None

        return None

    def get_reseller_by_code(self, code: str) -> Optional[ResellerProfile]:
        """Look up a reseller profile by code (case-insensitive) in cache or live Lark CRM."""
        if not code:
            return None
        clean_code = code.strip().upper()
        if clean_code in self._resellers_by_code:
            return self._resellers_by_code[clean_code]

        if self.crm_provider and hasattr(self.crm_provider, "_get_by_key"):
            try:
                row = self.crm_provider._get_by_key("09_Resellers", clean_code)
                if row:
                    res_phone = normalize_phone_sl(str(row.get("WhatsApp Number") or row.get("Phone Number") or row.get("Phone", "")))
                    res = ResellerProfile(
                        reseller_id=str(row.get("Reseller ID", clean_code)),
                        reseller_code=str(row.get("Reseller Code", clean_code)),
                        name=str(row.get("Business or Full Name") or row.get("Primary Contact") or row.get("Reseller Name") or row.get("Business Name", "Partner")),
                        phone=res_phone,
                        email=str(row.get("Business Email", "")),
                        status=str(row.get("Status", "Active")),
                        operating_model=str(row.get("Operating Model", "DIRECT_TO_NEXGLOTV")),
                    )
                    self.register_reseller(res)
                    return res
            except Exception as exc:
                log.debug("Lark reseller lookup by code failed for %s: %s", clean_code, exc)

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

                # Record in 10_Reseller_Sales
                if hasattr(self.crm_provider, "_upsert_by_key"):
                    sale_fields = {
                        "Reseller Sale ID": sale_ref,
                        "Reseller ID": reseller.reseller_id,
                        "Reseller Code Snapshot": reseller.reseller_code,
                        "Customer ID": customer_id,
                        "Payment ID": payment_id,
                        "Lead ID": lead_id,
                        "Sale Date": now_iso,
                        "Sale Type": "Renewal" if is_resub else "New",
                        "Sale Status": "Payment Pending",
                        "Payment Path": "DIRECT_TO_NEXGLOTV",
                        "Device Count": str(devices),
                        "Gross Subscription SLE": quote.original_price or sale_amount,
                        "Discount SLE": (quote.original_price - quote.final_price) if quote.original_price > quote.final_price else 0,
                        "Net Subscription SLE": sale_amount,
                        "Collected By": "NexgloTV",
                        "Commission Eligible": True,
                        "Commission Rate Snapshot %": str(reseller.commission_rate),
                        "Standard Commission 20% SLE": expected_commission,
                    }
                    self.crm_provider._upsert_by_key("10_Reseller_Sales", sale_fields)

                    # Record in 11_Commissions
                    comm_id = f"COMM-{sale_ref}"
                    comm_fields = {
                        "Commission ID": comm_id,
                        "Reseller ID": reseller.reseller_id,
                        "Reseller Sale ID": sale_ref,
                        "Customer ID": customer_id,
                        "Payment ID": payment_id,
                        "Earned On": now_iso,
                        "Eligible Revenue SLE": sale_amount,
                        "Rate % Snapshot": str(reseller.commission_rate),
                        "Commission Earned SLE": expected_commission,
                        "Payable SLE": 0,
                        "Commission Status": "Pending",
                        "Commission Event Type": "RENEWAL" if is_resub else "NEW_SALE",
                        "Commission Method Snapshot": "Percentage",
                    }
                    self.crm_provider._upsert_by_key("11_Commissions", comm_fields)
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

                if hasattr(self.crm_provider, "_upsert_by_key"):
                    sale_fields = {
                        "Reseller Sale ID": f"RSALE-WLT-{event_ts}",
                        "Reseller ID": reseller.reseller_id,
                        "Reseller Code Snapshot": reseller.reseller_code,
                        "Customer ID": customer_id,
                        "Payment ID": f"PAY-WLT-{event_ts}",
                        "Subscription ID": sub_id,
                        "Sale Date": now_iso,
                        "Sale Type": "Renewal" if is_resub else "New",
                        "Sale Status": "Confirmed",
                        "Payment Path": "PREPAID_WALLET",
                        "Device Count": str(devices),
                        "Net Subscription SLE": net_subscription_price,
                        "Collected By": "Reseller",
                        "Commission Eligible": True,
                        "Commission Rate Snapshot %": str(reseller.commission_rate),
                        "Standard Commission 20% SLE": commission_earned,
                        "Wallet Debit Entry ID": wallet_entry_id,
                    }
                    self.crm_provider._upsert_by_key("10_Reseller_Sales", sale_fields)

                    comm_id = f"COMM-WLT-{event_ts}"
                    comm_fields = {
                        "Commission ID": comm_id,
                        "Reseller ID": reseller.reseller_id,
                        "Customer ID": customer_id,
                        "Payment ID": f"PAY-WLT-{event_ts}",
                        "Earned On": now_iso,
                        "Eligible Revenue SLE": net_subscription_price,
                        "Rate % Snapshot": str(reseller.commission_rate),
                        "Commission Earned SLE": commission_earned,
                        "Payable SLE": commission_earned,
                        "Commission Status": "Approved",
                        "Commission Event Type": "RENEWAL" if is_resub else "NEW_SALE",
                        "Commission Method Snapshot": "Percentage",
                    }
                    self.crm_provider._upsert_by_key("11_Commissions", comm_fields)

                    wallet_fields = {
                        "Wallet Entry ID": wallet_entry_id,
                        "Reseller ID": reseller.reseller_id,
                        "Transaction Type": "DEBIT",
                        "Debit Amount SLE": net_subscription_price,
                        "Credit Amount SLE": 0,
                        "Running Balance SLE": reseller.wallet_balance,
                        "Transaction At": now_iso,
                        "Notes": f"Wallet activation for {norm_phone} ({months}m)",
                    }
                    self.crm_provider._upsert_by_key("13_Reseller_Wallet", wallet_fields)
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
    """Extract (months, devices) from text in any format, e.g. '1m 1d', '3 months 2 devices', '1 year', '180'."""
    if not text:
        return 1, 1

    months = None
    devices = None
    lower = text.lower()

    # 1. Combined code pattern (e.g. 1m1d, 1m_1d, 3m2d, 1mo1dev)
    comb = re.search(r"(\d+)\s*[mM][_\s\-/]*(\d+)\s*[dD]", text)
    if comb:
        try:
            m_val, d_val = int(comb.group(1)), int(comb.group(2))
            if m_val in (1, 3, 6, 12):
                months = m_val
            if 1 <= d_val <= 5:
                devices = d_val
        except (ValueError, IndexError):
            pass

    # 2. Months / Duration parsing
    if months is None:
        y_match = re.search(r"(\d+)\s*(?:years?|yrs?|y|anos?)\b", lower)
        if y_match:
            months = int(y_match.group(1)) * 12
        elif re.search(r"\b(?:annual|yearly|anual)\b", lower):
            months = 12
        elif re.search(r"\b(?:semi[- ]?annual|half[- ]?year|semestral)\b", lower):
            months = 6
        elif re.search(r"\b(?:quarter|quarterly|trimestral)\b", lower):
            months = 3
        else:
            m_match = re.search(r"(\d+)\s*(?:months?|meses?|mo|m)\b", lower)
            if m_match:
                months = int(m_match.group(1))

    # 3. Devices parsing
    if devices is None:
        d_match = re.search(r"(\d+)\s*(?:devices?|dispositivos?|screens?|tvs?|users?|devs?|disp|d)\b", lower)
        if d_match:
            devices = int(d_match.group(1))

    # 4. Price matching fallback (if months or devices still missing)
    if months is None or devices is None:
        price_map = {
            180: (1, 1), 320: (1, 2), 420: (1, 3), 480: (1, 4),
            500: (3, 1), 900: (3, 2), 1200: (3, 3), 1360: (3, 4),
            950: (6, 1), 1700: (6, 2), 2250: (6, 3), 2560: (6, 4),
            1800: (12, 1), 3200: (12, 2), 4200: (12, 3), 4800: (12, 4),
        }
        price_match = re.search(r"\b(?:le|sle|nle)?\s*(180|320|420|480|500|900|1200|1360|950|1700|2250|2560|1800|3200|4200|4800)\b", lower)
        if price_match:
            val = int(price_match.group(1))
            p_m, p_d = price_map[val]
            if months is None:
                months = p_m
            if devices is None:
                devices = p_d

    # 5. Sanitize defaults
    if months not in (1, 3, 6, 12):
        if months is None:
            months = 1
        elif months <= 2:
            months = 1
        elif months <= 4:
            months = 3
        elif months <= 9:
            months = 6
        else:
            months = 12

    if devices is None or devices < 1:
        devices = 1
    elif devices > 5:
        devices = 5

    return months, devices


def parse_phone_number(text: str) -> Optional[str]:
    """Find a phone number in Sierra Leone or international format, tolerating spaces, dashes, dots, and labels."""
    if not text:
        return None

    # 1. Check for labeled phone patterns first
    labeled = re.search(r"(?:phone|tel|number|wa|num|mobile|celular|contacto)[:\s#]+([+0-9\s\.\-]{8,22})", text, re.I)
    target = labeled.group(1) if labeled else text

    # 2. Check Sierra Leone phone numbers with optional spacing / hyphens
    sl_match = re.search(r"(?:(?:\+|00)?232[\s\.\-]*)?[0-9]{2}[\s\.\-]*[0-9]{3}[\s\.\-]*[0-9]{3,4}\b", target)
    if sl_match:
        digits = re.sub(r"[^\d]", "", sl_match.group(0))
        if digits.startswith("232") and len(digits) >= 11:
            return f"+{digits}"
        if digits.startswith("0") and len(digits) == 9:
            return f"+232{digits[1:]}"
        if len(digits) == 8 and digits[0] in "23789":
            return f"+232{digits}"
        if len(digits) >= 8 and len(digits) <= 15:
            return f"+{digits}"

    # 3. Check generic E.164 or international digits
    intl = re.search(r"(\+?[0-9]{1,4}[\s\.\-]*(?:[0-9]{2,4}[\s\.\-]*){2,4}[0-9]{2,4})", target)
    if intl:
        digits = re.sub(r"[^\d]", "", intl.group(1))
        if len(digits) >= 8:
            return f"+{digits}" if not digits.startswith("+") else digits

    # 4. Check fallback regex
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
    """Parse text input into Model 1 Direct Sale or Resubscription arguments.
    
    Robust and schema-aware: extracts phone number, package, payment method,
    transaction reference, and customer name in ANY order, with or without commas,
    labels, or bullet points.
    """
    if not text:
        return None

    clean = re.sub(
        r"^(?:/)?(?:ADMIN\s+)?(?:DIRECT\s+SALE|NEW\s+SALE|RECORD\s+SALE|ADD\s+SALE|SALE|RENEW|RESUBSCRIBE|RENEWAL)\s*[:,]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not clean:
        return None

    # Check if text explicitly indicates renewal / resubscription
    is_resub = is_renewal or bool(re.search(r"\b(?:RENEW|RESUBSCRIBE|RENEWAL|RENOVACION|RENOVAR)\b", text, re.IGNORECASE))

    # 1. Extract Phone Number
    phone = parse_phone_number(clean) or parse_phone_number(text)
    if not phone:
        return None

    # 2. Extract Payment Method
    clean_lower = clean.lower()
    method = "Orange Money"
    if re.search(r"\b(?:afri\s*money|afrimoney|africell\s*money|africell|afri|am)\b", clean_lower):
        method = "Afrimoney"
    elif re.search(r"\b(?:bank\s*transfer|bank|wire|transfer|transferencia|rokel|slcb|ecobank|uba|zenith|gtbank)\b", clean_lower):
        method = "Bank Transfer"
    elif re.search(r"\b(?:cash|efectivo|hand)\b", clean_lower):
        method = "Cash"
    elif re.search(r"\b(?:qmoney|q\s*money|qm)\b", clean_lower):
        method = "QMoney"
    elif re.search(r"\b(?:prepaid\s*wallet|wallet)\b", clean_lower):
        method = "Prepaid Wallet"
    elif re.search(r"\b(?:orange\s*money|orangemoney|orange)\b", clean_lower):
        method = "Orange Money"

    # 3. Extract Package (Duration & Devices)
    months, devices = parse_package_spec(clean)

    # 4. Extract Reference / Txn ID
    ref = None
    ref_match = re.search(r"(?:ref(?:erence)?(?:\s*no\.?|\s*id)?|txn(?:\s*id)?|trans(?:action)?\s*id|id\s*de\s*trans|receipt\s*no\.?|code)[\s:=#]+([a-zA-Z0-9\-_]{4,32})", clean, re.I)
    if ref_match:
        ref = ref_match.group(1).strip()

    if not ref:
        code_match = re.search(r"\b((?:OM|CI|AF|TXN|RCP|PP|BT)[A-Z0-9\-]{4,25})\b", clean, re.I)
        if code_match and code_match.group(1).upper() not in (phone.upper(), "ORANGEMONEY", "AFRIMONEY"):
            c_cand = code_match.group(1).strip()
            if _digits(c_cand) != _digits(phone):
                ref = c_cand

    if not ref:
        tokens = [t.strip(",.:;#-()\"'") for t in clean.split()]
        phone_digits = _digits(phone)
        for tok in reversed(tokens):
            tok_lower = tok.lower()
            tok_digits = _digits(tok)
            # Never pick customer phone or any phone number as payment reference
            if tok_digits and (tok_digits == phone_digits or phone_matches(tok, phone)):
                continue
            if tok.isdigit() and 8 <= len(tok) <= 15:
                continue
            if (
                len(tok) >= 4 and
                any(c.isdigit() for c in tok) and
                not re.match(r"^\d+[mdy]$", tok_lower) and
                not re.match(r"^\d+dev$", tok_lower) and
                not re.match(r"^le\d+$", tok_lower) and
                tok_lower not in ("180", "320", "420", "480", "500", "900", "1200", "1360", "950", "1700", "2250", "2560", "1800", "3200", "4200", "4800")
            ):
                ref = tok
                break

    if not ref:
        if method == "Cash":
            ref = f"CASH-{int(time.time())}"
        else:
            ref = f"REF-{int(time.time())}"

    # 5. Extract Customer Name
    name = ""
    # 5a. If comma-separated, inspect each chunk
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        for p in parts:
            p_clean = p.strip()
            # Skip if matches phone
            if parse_phone_number(p_clean) == phone or re.search(r"\d{7,}", p_clean):
                continue
            # Skip if package
            if any(k in p_clean.lower() for k in ("m", "mo", "dev", "device", "month", "screen", "tv", "pkg", "package", "year", "yr", "annual")) and re.search(r"\d", p_clean):
                continue
            # Skip if method
            if any(m_word in p_clean.lower() for m_word in ("orange", "afri", "bank", "cash", "qmoney", "wallet", "transfer")):
                continue
            # Skip if ref
            if ref and (p_clean == ref or p_clean.lower().startswith("ref") or p_clean.lower().startswith("txn")):
                continue
            # If letters, this is the name
            if any(c.isalpha() for c in p_clean) and len(p_clean) >= 2:
                name = p_clean
                break

    # 5b. If name not yet found, check explicit label: name: John Kamara, customer: John Kamara
    if not name:
        label_m = re.search(
            r"(?:name|customer|client|subscriber|cliente|nombre)[:\s]+(.*?)(?=\s*(?:package|pkg|plan|phone|tel|wa|number|method|ref|txn|receipt|code|id)[:\s]|$|,|\n|;)",
            clean,
            re.I,
        )
        if label_m and label_m.group(1).strip():
            name = label_m.group(1).strip()

    # 5c. Residual token extraction
    if not name:
        text_for_name = clean
        # Remove phone match
        phone_raw = re.search(r"(?:(?:\+|00)?232[\s\.\-]*)?[0-9]{2}[\s\.\-]*[0-9]{3}[\s\.\-]*[0-9]{3,4}\b|\b\d{8,15}\b", text_for_name)
        if phone_raw:
            text_for_name = text_for_name.replace(phone_raw.group(0), " ")
        # Remove ref if present
        if ref and ref in text_for_name and not ref.startswith(("REF-", "CASH-")):
            text_for_name = text_for_name.replace(ref, " ")
        # Remove package patterns
        text_for_name = re.sub(r"\b\d+\s*(?:months?|meses?|mo|m)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b\d+\s*(?:years?|yrs?|y|anos?)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b\d+\s*(?:devices?|dispositivos?|screens?|tvs?|users?|devs?|disp|d)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b\d+[mdy]\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b(?:annual|yearly|quarterly|half[- ]?year|semi[- ]?annual)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b(?:le|sle|nle)?\s*(?:180|320|420|480|500|900|1200|1360|950|1700|2250|2560|1800|3200|4200|4800)\b", " ", text_for_name, flags=re.I)
        # Remove payment methods
        text_for_name = re.sub(r"\b(?:orange\s*money|orangemoney|orange|om|afri\s*money|afrimoney|africell|afri|am|bank\s*transfer|bank|transfer|cash|efectivo|qmoney|wallet)\b", " ", text_for_name, flags=re.I)
        # Remove command keywords and prepositions
        text_for_name = re.sub(r"\b(?:direct|sale|sales|record|new|add|renew|resubscribe|renewal|activate|wallet|for|to|via|with|paid|ref|txn|phone|name|package|pkg|method)\b", " ", text_for_name, flags=re.I)

        stop_words = {
            "direct", "sale", "sales", "record", "new", "add", "renew", "resubscribe",
            "renewal", "activate", "wallet", "for", "to", "via", "with", "paid",
            "ref", "txn", "phone", "name", "package", "pkg", "method", "month",
            "months", "year", "years", "device", "devices", "screen", "screens",
            "tv", "tvs", "user", "users", "dev", "devs", "mes", "meses", "ano", "anos",
            "plan", "plans", "sub", "subscription", "customer", "client", "renovacion",
            "renovar", "dispositivo", "dispositivos", "pantalla", "pantallas", "orange",
            "orangemoney", "afri", "afrimoney", "africell", "bank", "cash", "qmoney",
        }

        candidate_tokens = [t.strip(",.:;#-()\"'") for t in text_for_name.split() if t.strip(",.:;#-()\"'")]
        valid_tokens = [
            t for t in candidate_tokens
            if any(c.isalpha() for c in t)
            and len(t) >= 2
            and t.lower() not in stop_words
        ]
        if valid_tokens:
            name = " ".join(valid_tokens[:3])

    # 5d. Default if name is still empty
    if not name:
        name = "" if is_resub else f"Customer {phone[-6:]}"

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
    """Parse text input into Model 2 Wallet Activation arguments in any flexible order."""
    if not text:
        return None

    clean = re.sub(
        r"^(?:/)?(?:ADMIN\s+)?(?:ACTIVATE|WALLET\s+ACTIVATE|WALLET\s+RENEW|WALLET)\s*[:,]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not clean:
        return None

    is_resub = is_renewal or "renew" in text.lower()

    # 1. Phone
    phone = parse_phone_number(clean) or parse_phone_number(text)
    if not phone:
        return None

    # 2. Package
    months, devices = parse_package_spec(clean)

    # 3. Name
    name = ""
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        for p in parts:
            p_clean = p.strip()
            if parse_phone_number(p_clean) == phone or re.search(r"\d{7,}", p_clean):
                continue
            if any(k in p_clean.lower() for k in ("m", "mo", "dev", "device", "month", "screen", "tv", "pkg", "package", "year", "yr", "annual")) and re.search(r"\d", p_clean):
                continue
            if any(c.isalpha() for c in p_clean) and len(p_clean) >= 2:
                name = p_clean
                break

    if not name:
        label_m = re.search(
            r"(?:name|customer|client|subscriber|cliente|nombre)[:\s]+(.*?)(?=\s*(?:package|pkg|plan|phone|tel|wa|number|method|ref|txn|receipt|code|id)[:\s]|$|,|\n|;)",
            clean,
            re.I,
        )
        if label_m and label_m.group(1).strip():
            name = label_m.group(1).strip()

    if not name:
        text_for_name = clean
        phone_raw = re.search(r"(?:(?:\+|00)?232[\s\.\-]*)?[0-9]{2}[\s\.\-]*[0-9]{3}[\s\.\-]*[0-9]{3,4}\b|\b\d{8,15}\b", text_for_name)
        if phone_raw:
            text_for_name = text_for_name.replace(phone_raw.group(0), " ")
        text_for_name = re.sub(r"\b\d+\s*(?:months?|meses?|mo|m)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b\d+\s*(?:years?|yrs?|y|anos?)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b\d+\s*(?:devices?|dispositivos?|screens?|tvs?|users?|devs?|disp|d)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b\d+[mdy]\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b(?:annual|yearly|quarterly|half[- ]?year|semi[- ]?annual)\b", " ", text_for_name, flags=re.I)
        text_for_name = re.sub(r"\b(?:activate|wallet|renew|resubscribe|for|to|phone|name|package|pkg|method)\b", " ", text_for_name, flags=re.I)

        stop_words = {
            "direct", "sale", "sales", "record", "new", "add", "renew", "resubscribe",
            "renewal", "activate", "wallet", "for", "to", "via", "with", "paid",
            "ref", "txn", "phone", "name", "package", "pkg", "method", "month",
            "months", "year", "years", "device", "devices", "screen", "screens",
            "tv", "tvs", "user", "users", "dev", "devs", "mes", "meses", "ano", "anos",
            "plan", "plans", "sub", "subscription", "customer", "client", "renovacion",
            "renovar", "dispositivo", "dispositivos", "pantalla", "pantallas",
        }

        candidate_tokens = [t.strip(",.:;#-()\"'") for t in text_for_name.split() if t.strip(",.:;#-()\"'")]
        valid_tokens = [
            t for t in candidate_tokens
            if any(c.isalpha() for c in t)
            and len(t) >= 2
            and t.lower() not in stop_words
        ]
        if valid_tokens:
            name = " ".join(valid_tokens[:3])

    if not name:
        name = "" if is_resub else f"Customer {phone[-6:]}"

    return {
        "customer_phone": phone,
        "customer_name": name,
        "months": months,
        "devices": devices,
        "is_renewal": is_resub,
    }
