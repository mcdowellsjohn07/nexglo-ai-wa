"""NexgloTV Receipt Engine — Master CRM Receipt Generation, PDF Rendering & Issuance.

Authoritative implementation of:
  - NexgloTV_Lark_Receipt_Implementation_Guide.md
  - NexgloTV_Receipt_Configuration_Manifest.json
  - NexgloTV_Mobile_Receipt_Antigravity_Notes (1).md
  - NexgloTV_Mobile_Receipt_Template.html
  - NexgloTV_Receipt_Acceptance_Checklist.csv (20 acceptance tests)

Features:
  1. Immutable Master CRM `19_Receipts` ledger management.
  2. Sequential, permanent receipt numbering (`NGT-RCT-YYYY-XXXXXX`).
  3. Strict idempotency by unique `Source Key` (e.g. `PAYMENT:PAY-00001`).
  4. Only verified transactions with funds received (> 0) generate payment receipts.
  5. Deterministic frozen financial snapshots (regular sub, 20% discount, net sub,
     undiscounted installation fee, actual amount received, balance due).
  6. Support for Customer Subscription, Renewal, Installation, Wallet Funding,
     Commission Payout Advice, Refund Credit Notes, and 24h Trial Notices.
  7. HTML rendering using `NexgloTV_Mobile_Receipt_Template.html` with safe escaping.
  8. Headless Chrome/Edge PDF rendering for single-column 390px mobile layout.
  9. Direct PDF attachment upload via official Lark CLI `+record-upload-attachment`.
  10. Delivery & issuance status tracking; Master Base remains strictly private.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.reseller_lark import ResellerSystemManager, _run_cli

log = logging.getLogger(__name__)

MASTER_BASE_TOKEN = "E8jObNOAeaZqUHsyxRHjR9VcpBg"
RECEIPTS_TABLE_NAME = "19_Receipts"
TEMPLATE_PATH = Path(r"C:\Users\PROF\Downloads\NexgloTV_Mobile_Receipt_Template.html")
WORKSPACE_DIR = Path(__file__).resolve().parents[1]
RECEIPTS_STORAGE_DIR = WORKSPACE_DIR / "receipts"
RECEIPTS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

SUPPORT_CONTACT = "+232 76 000 000 / support@nexglotv.com"


# ============================================================================
# Helpers: Formatting, Escaping & Browser Discovery
# ============================================================================

def _validate_phone(phone: Optional[str]) -> tuple[bool, str]:
    """Validate customer phone number against standard E.164 and Sierra Leone patterns."""
    if not phone:
        return False, "Missing phone number"
    p = re.sub(r"[\s\-\(\)]", "", str(phone).strip())
    # Sierra Leone local formats: 07x..., 08x..., 03x..., 09x... (8-9 digits)
    # International formats: +232 7x..., +232 8x..., +232 3x..., or general E.164
    if re.match(r"^(\+?232[3789]\d{7}|0[3789]\d{7}|\+[1-9]\d{7,14})$", p):
        return True, p
    return False, f"Invalid / mismatched phone format: '{phone}'"


def _normalize_val(val: Any) -> str:
    """Normalize select/text fields that may be returned as single-element lists by Lark."""
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return str(val or "")


def _fmt_sle(val: Any) -> str:
    """Format numeric SLE value with 2 decimals (e.g. 180.00)."""
    try:
        f = float(val or 0)
        return f"{f:,.2f}"
    except (ValueError, TypeError):
        return "0.00"


def _fmt_date(dt: Optional[datetime] = None) -> str:
    """Format date/time in Africa/Freetown (UTC+0)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%d %b %Y, %H:%M GMT")


def _find_browser() -> Optional[str]:
    """Find installed Chrome or Edge executable on Windows."""
    candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


# ============================================================================
# Core Receipt Engine
# ============================================================================

class ReceiptEngine:
    def __init__(self, master_base_token: str = MASTER_BASE_TOKEN):
        self.master_base_token = master_base_token
        self._tables: dict[str, str] = {}
        self.receipts_tid: str = ""
        self._load_table_ids()

    def _load_table_ids(self) -> None:
        self._tables = ResellerSystemManager.list_tables(self.master_base_token)
        self.receipts_tid = self._tables.get(RECEIPTS_TABLE_NAME, "")
        if not self.receipts_tid:
            log.warning("Table %s not found in Master CRM", RECEIPTS_TABLE_NAME)

    def generate_receipt_number(self, year: Optional[int] = None) -> str:
        """Generate a sequential, permanent receipt number: NGT-RCT-YYYY-XXXXXX."""
        if year is None:
            year = datetime.now(timezone.utc).year
        prefix = f"NGT-RCT-{year}-"
        max_seq = 0

        if self.receipts_tid:
            _, rows = ResellerSystemManager.list_records(self.master_base_token, self.receipts_tid, limit=200)
            for r in rows:
                num = str(r.get("Receipt Number") or "")
                if num.startswith(prefix):
                    suffix = num[len(prefix):]
                    if suffix.isdigit():
                        max_seq = max(max_seq, int(suffix))

        return f"{prefix}{max_seq + 1:06d}"

    def find_receipt_by_source_key(self, source_key: str) -> Optional[dict[str, Any]]:
        """Find existing receipt by unique idempotent Source Key."""
        if not self.receipts_tid or not source_key:
            return None
        _, rows = ResellerSystemManager.list_records(self.master_base_token, self.receipts_tid, limit=200)
        for r in rows:
            if _normalize_val(r.get("Source Key")).strip() == str(source_key).strip():
                return r
        return None

    def find_receipt_by_number(self, receipt_number: str) -> Optional[dict[str, Any]]:
        """Find existing receipt by permanent Receipt Number."""
        if not self.receipts_tid or not receipt_number:
            return None
        _, rows = ResellerSystemManager.list_records(self.master_base_token, self.receipts_tid, limit=200)
        for r in rows:
            if _normalize_val(r.get("Receipt Number")).strip() == str(receipt_number).strip():
                return r
        return None

    def delete_record(self, record_id: str) -> bool:
        """Delete a record from 19_Receipts (strictly for testing cleanup)."""
        if not self.receipts_tid or not record_id:
            return False
        res = _run_cli([
            "+record-delete",
            "--base-token", self.master_base_token,
            "--table-id", self.receipts_tid,
            "--record-id", record_id,
        ], confirm=True)
        return bool(res.get("ok") or res.get("data", {}).get("record_id_list"))

    # ------------------------------------------------------------------------
    # 1. Prepare Frozen Snapshot from Verified Payment
    # ------------------------------------------------------------------------
    def prepare_payment_receipt_snapshot(
        self,
        *,
        payment_id: str,
        customer_id: str = "",
        payer_name: str = "",
        payer_contact: str = "",
        package_desc: str = "NexgloTV Standard Package",
        regular_sub_sle: float = 225.0,
        discount_pct: float = 20.0,
        discount_amount_sle: Optional[float] = None,
        installation_fee_sle: float = 0.0,
        amount_received_sle: float = 180.0,
        payment_method: str = "Orange Money",
        payment_reference: str = "",
        payment_status: str = "Confirmed",
        service_period: str = "1 Month Access",
        payment_for: str = "New Subscription",
        subscription_id: str = "",
        reseller_code: str = "",
        received_at: Optional[datetime] = None,
        verified_by_staff: str = "Finance Staff",
    ) -> dict[str, Any]:
        """Validate payment verification rules and compute frozen financial snapshot."""
        # Rule R-02: Unverified payments must never issue a payment receipt
        status_norm = str(payment_status).strip()
        if status_norm not in ("Confirmed", "Paid", "Verified"):
            raise ValueError(f"Cannot generate receipt for unverified payment status '{payment_status}'")

        # Must have positive funds received
        if float(amount_received_sle) <= 0:
            raise ValueError(f"Cannot generate payment receipt for non-positive amount received ({amount_received_sle} SLE)")

        reg_sub = round(float(regular_sub_sle), 2)
        disc_pct = round(float(discount_pct), 0)
        if discount_amount_sle is None:
            disc_amt = round(reg_sub * (disc_pct / 100.0), 2)
        else:
            disc_amt = round(float(discount_amount_sle), 2)

        net_sub = round(max(0.0, reg_sub - disc_amt), 2)
        install_fee = round(float(installation_fee_sle), 2)

        # Rule R-05: 20% discount applies to subscription ONLY, excludes installation
        amount_due = round(net_sub + install_fee, 2)
        received = round(float(amount_received_sle), 2)
        balance_due = round(max(0.0, amount_due - received), 2)

        # Kind & Titles
        if payment_for == "Installation Only":
            r_kind = "Installation Payment"
            r_title = "INSTALLATION PAYMENT RECEIPT"
        elif payment_for == "Renewal":
            r_kind = "Subscription Renewal"
            r_title = "SUBSCRIPTION RENEWAL RECEIPT"
        else:
            r_kind = "Customer Subscription"
            r_title = "PAYMENT RECEIPT"

        # Rule R-03: Partial payments must never say PAID IN FULL
        if balance_due > 0:
            r_title = f"{r_title} — PARTIAL PAYMENT"
            p_status = "PARTIALLY PAID"
        else:
            p_status = "PAID IN FULL"

        now_utc = datetime.now(timezone.utc)
        rec_date = received_at or now_utc

        return {
            "Receipt Kind": r_kind,
            "Source Type": "Payment",
            "Source Record ID": payment_id,
            "Source Key": f"PAYMENT:{payment_id}",
            "Linked Payment ID": payment_id,
            "Linked Customer ID": customer_id,
            "Linked Subscription ID": subscription_id,
            "Reseller Code Snapshot": reseller_code,
            "Payer Display Name": payer_name or "NexgloTV Customer",
            "Payer Contact": payer_contact,
            "Customer ID Snapshot": customer_id,
            "Package Description": package_desc,
            "Service Period": service_period,
            "Regular Subscription SLE": reg_sub,
            "Discount % Snapshot": disc_pct,
            "Discount Amount SLE": disc_amt,
            "Net Subscription SLE": net_sub,
            "Installation Fee SLE": install_fee,
            "Other Authorized Charges SLE": 0.0,
            "Tax Amount SLE": 0.0,
            "Amount Due SLE": amount_due,
            "Amount Received SLE": received,
            "Outstanding Balance SLE": balance_due,
            "Currency Snapshot": "SLE",
            "Payment Method Snapshot": payment_method,
            "External Payment Reference": payment_reference,
            "Payment Received At": rec_date.strftime("%Y/%m/%d %H:%M"),
            "Payment Verification Staff": verified_by_staff,
            "Verification Timestamp": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Issued At": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Receipt Title": r_title,
            "Receipt Payment Status": p_status,
        }

    # ------------------------------------------------------------------------
    # 2. Prepare Wallet Funding Confirmation Snapshot
    # ------------------------------------------------------------------------
    def prepare_wallet_funding_snapshot(
        self,
        *,
        wallet_entry_id: str,
        reseller_code: str,
        reseller_name: str,
        deposit_amount_sle: float,
        payment_method: str = "Orange Money",
        payment_reference: str = "",
        verified_by_staff: str = "Finance Staff",
    ) -> dict[str, Any]:
        """Prepare frozen snapshot for verified wallet top-up deposit."""
        amt = round(float(deposit_amount_sle), 2)
        if amt <= 0:
            raise ValueError(f"Wallet funding amount must be positive ({amt} SLE)")

        now_utc = datetime.now(timezone.utc)
        return {
            "Receipt Kind": "Wallet Funding",
            "Source Type": "Wallet Entry",
            "Source Record ID": wallet_entry_id,
            "Source Key": f"WALLET:{wallet_entry_id}",
            "Linked Wallet Entry ID": wallet_entry_id,
            "Linked Reseller ID": reseller_code,
            "Reseller Code Snapshot": reseller_code,
            "Payer Display Name": reseller_name or f"Reseller {reseller_code}",
            "Customer ID Snapshot": reseller_code,
            "Package Description": "Prepaid Reseller Wallet Top-Up Deposit (Advance Funds)",
            "Service Period": "N/A (Wallet Balance Credit)",
            "Regular Subscription SLE": 0.0,
            "Discount % Snapshot": 0,
            "Discount Amount SLE": 0.0,
            "Net Subscription SLE": 0.0,
            "Installation Fee SLE": 0.0,
            "Other Authorized Charges SLE": 0.0,
            "Tax Amount SLE": 0.0,
            "Amount Due SLE": amt,
            "Amount Received SLE": amt,
            "Outstanding Balance SLE": 0.0,
            "Currency Snapshot": "SLE",
            "Payment Method Snapshot": payment_method,
            "External Payment Reference": payment_reference,
            "Payment Verification Staff": verified_by_staff,
            "Verification Timestamp": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Issued At": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Receipt Title": "WALLET FUNDING CONFIRMATION",
            "Receipt Payment Status": "FUNDS DEPOSITED",
        }

    # ------------------------------------------------------------------------
    # 3. Prepare Commission Payout Advice Snapshot
    # ------------------------------------------------------------------------
    def prepare_payout_advice_snapshot(
        self,
        *,
        payout_id: str,
        reseller_code: str,
        reseller_name: str,
        amount_paid_sle: float,
        payout_method: str = "Orange Money",
        transaction_reference: str = "",
        verified_by_staff: str = "Finance Staff",
    ) -> dict[str, Any]:
        """Prepare frozen snapshot for disbursed commission payout advice."""
        amt = round(float(amount_paid_sle), 2)
        if amt <= 0:
            raise ValueError(f"Payout amount must be positive ({amt} SLE)")

        now_utc = datetime.now(timezone.utc)
        return {
            "Receipt Kind": "Commission Payout Advice",
            "Source Type": "Payout",
            "Source Record ID": payout_id,
            "Source Key": f"PAYOUT:{payout_id}",
            "Linked Payout ID": payout_id,
            "Linked Reseller ID": reseller_code,
            "Reseller Code Snapshot": reseller_code,
            "Payer Display Name": reseller_name or f"Reseller {reseller_code}",
            "Customer ID Snapshot": reseller_code,
            "Package Description": f"Earned Reseller Commission Payout ({reseller_code})",
            "Service Period": "Commission Settlement",
            "Regular Subscription SLE": 0.0,
            "Discount % Snapshot": 0,
            "Discount Amount SLE": 0.0,
            "Net Subscription SLE": 0.0,
            "Installation Fee SLE": 0.0,
            "Other Authorized Charges SLE": 0.0,
            "Tax Amount SLE": 0.0,
            "Amount Due SLE": amt,
            "Amount Received SLE": amt,
            "Outstanding Balance SLE": 0.0,
            "Currency Snapshot": "SLE",
            "Payment Method Snapshot": payout_method,
            "External Payment Reference": transaction_reference,
            "Payment Verification Staff": verified_by_staff,
            "Verification Timestamp": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Issued At": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Receipt Title": "COMMISSION PAYOUT ADVICE",
            "Receipt Payment Status": "DISBURSED",
        }

    # ------------------------------------------------------------------------
    # 4. Prepare 24-Hour Free Trial Notice (Expressly Zero Payment)
    # ------------------------------------------------------------------------
    def prepare_trial_notice_snapshot(
        self,
        *,
        trial_id: str,
        customer_name: str,
        customer_phone: str,
        device_type: str = "Firestick",
        activated_at: str = "",
        expires_at: str = "",
    ) -> dict[str, Any]:
        """Prepare 24-hour trial activation notice (Rule R-06: strictly zero payment)."""
        now_utc = datetime.now(timezone.utc)
        return {
            "Receipt Kind": "Trial Notice",
            "Source Type": "Trial",
            "Source Record ID": trial_id,
            "Source Key": f"TRIAL:{trial_id}",
            "Payer Display Name": customer_name or "Trial User",
            "Payer Contact": customer_phone,
            "Customer ID Snapshot": trial_id,
            "Package Description": f"24-Hour Free Trial ({device_type}) — ZERO PAYMENT REQUIRED",
            "Service Period": f"{activated_at} to {expires_at}" if activated_at else "24 Hours Access",
            "Regular Subscription SLE": 0.0,
            "Discount % Snapshot": 0,
            "Discount Amount SLE": 0.0,
            "Net Subscription SLE": 0.0,
            "Installation Fee SLE": 0.0,
            "Other Authorized Charges SLE": 0.0,
            "Tax Amount SLE": 0.0,
            "Amount Due SLE": 0.0,
            "Amount Received SLE": 0.0,
            "Outstanding Balance SLE": 0.0,
            "Currency Snapshot": "SLE",
            "Payment Method Snapshot": "Free Trial (No Payment)",
            "External Payment Reference": "TRIAL-ZERO-PAYMENT",
            "Payment Verification Staff": "Tech Ops Staff",
            "Verification Timestamp": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Issued At": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Receipt Title": "24-HOUR FREE TRIAL ACTIVATION NOTICE",
            "Receipt Payment Status": "TRIAL ACTIVE (ZERO PAYMENT)",
        }

    # ------------------------------------------------------------------------
    # 5. Render HTML from Template
    # ------------------------------------------------------------------------
    def render_receipt_html(
        self,
        snapshot: dict[str, Any],
        receipt_number: str,
        template_path: Optional[Path] = None,
    ) -> str:
        """Substitute all placeholders in the phone-first mobile HTML template with safe escaping."""
        t_path = template_path or TEMPLATE_PATH
        if not t_path.is_file():
            raise FileNotFoundError(f"Receipt HTML template not found at {t_path}")

        raw_tmpl = t_path.read_text(encoding="utf-8")

        # Escaped string variables
        replacements = {
            "{{RECEIPT_TITLE}}": html.escape(str(snapshot.get("Receipt Title") or "PAYMENT RECEIPT")),
            "{{PAYMENT_STATUS}}": html.escape(str(snapshot.get("Receipt Payment Status") or "PAID IN FULL")),
            "{{RECEIPT_NUMBER}}": html.escape(str(receipt_number)),
            "{{ISSUED_AT}}": html.escape(str(snapshot.get("Issued At") or _fmt_date())),
            "{{PAYER_NAME}}": html.escape(str(snapshot.get("Payer Display Name") or "Customer")),
            "{{CUSTOMER_ID}}": html.escape(str(snapshot.get("Customer ID Snapshot") or "N/A")),
            "{{PAYMENT_METHOD}}": html.escape(str(snapshot.get("Payment Method Snapshot") or "Mobile Money")),
            "{{PAYMENT_REFERENCE}}": html.escape(str(snapshot.get("External Payment Reference") or "N/A")),
            "{{PACKAGE_DESCRIPTION}}": html.escape(str(snapshot.get("Package Description") or "NexgloTV Access")),
            "{{SERVICE_PERIOD}}": html.escape(str(snapshot.get("Service Period") or "Active")),
            "{{REGULAR_SUBSCRIPTION_SLE}}": _fmt_sle(snapshot.get("Regular Subscription SLE")),
            "{{DISCOUNT_PERCENT}}": str(int(float(snapshot.get("Discount % Snapshot") or 0))),
            "{{DISCOUNT_AMOUNT_SLE}}": _fmt_sle(snapshot.get("Discount Amount SLE")),
            "{{NET_SUBSCRIPTION_SLE}}": _fmt_sle(snapshot.get("Net Subscription SLE")),
            "{{INSTALLATION_FEE_SLE}}": _fmt_sle(snapshot.get("Installation Fee SLE")),
            "{{AMOUNT_DUE_SLE}}": _fmt_sle(snapshot.get("Amount Due SLE")),
            "{{AMOUNT_RECEIVED_SLE}}": _fmt_sle(snapshot.get("Amount Received SLE")),
            "{{BALANCE_DUE_SLE}}": _fmt_sle(snapshot.get("Outstanding Balance SLE")),
            "{{SUPPORT_CONTACT}}": html.escape(SUPPORT_CONTACT),
        }

        rendered = raw_tmpl
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)

        return rendered

    # ------------------------------------------------------------------------
    # 6. Render HTML to PDF using Headless Chrome
    # ------------------------------------------------------------------------
    def render_pdf_from_html(
        self,
        html_content: str,
        output_filename: str,
    ) -> Path:
        """Render HTML string to PDF using headless Chrome/Edge."""
        browser_exe = _find_browser()
        if not browser_exe:
            raise RuntimeError("No headless browser found for PDF export (Chrome/Edge required)")

        out_pdf = RECEIPTS_STORAGE_DIR / output_filename
        temp_html = RECEIPTS_STORAGE_DIR / f"{output_filename}.html"
        temp_html.write_text(html_content, encoding="utf-8")

        cmd = [
            browser_exe,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={out_pdf}",
            str(temp_html),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if temp_html.exists():
            temp_html.unlink()

        if res.returncode != 0 or not out_pdf.exists() or out_pdf.stat().st_size == 0:
            raise RuntimeError(f"Headless browser PDF rendering failed (code {res.returncode}): {res.stderr}")

        return out_pdf

    # ------------------------------------------------------------------------
    # 7. End-to-End Idempotent Receipt Issuance into 19_Receipts
    # ------------------------------------------------------------------------
    def issue_receipt(
        self,
        snapshot: dict[str, Any],
        issued_by_staff: str = "Samuel Gibson",
    ) -> dict[str, Any]:
        """Idempotently issue receipt in 19_Receipts, render PDF, and attach document."""
        source_key = snapshot.get("Source Key")
        if not source_key:
            raise ValueError("snapshot missing required 'Source Key'")

        # Rule R-14: Validate payer contact if provided
        payer_contact = snapshot.get("Payer Contact")
        phone_valid, phone_msg = _validate_phone(payer_contact) if payer_contact else (True, "No contact")
        target_delivery_status = "Ready for Manual Delivery" if phone_valid else "Delivery Failed"

        # Rule R-10 & R-15: Check idempotency and handle retry on previous failure
        existing = self.find_receipt_by_source_key(source_key)
        rec_id = ""
        attempt_count = 1

        if existing:
            st = _normalize_val(existing.get("Receipt Status"))
            if st in ("Issued", "Ready for Manual Delivery"):
                log.info("Receipt already issued for %s: %s", source_key, existing.get("Receipt Number"))
                return {
                    "status": "already_exists",
                    "receipt_number": existing.get("Receipt Number"),
                    "record_id": existing.get("_record_id") or existing.get("record_id"),
                    "record": existing,
                }
            elif st in ("Failed", "Ready to Generate", "Generating"):
                # Rule R-15: Safe retry without burning new receipt number or creating duplicate rows
                receipt_number = _normalize_val(existing.get("Receipt Number"))
                rec_id = existing.get("_record_id") or existing.get("record_id")
                attempt_count = int(existing.get("Generation Attempt Count") or 1) + 1
                log.info("Retrying receipt generation for %s (attempt %d, existing %s)", source_key, attempt_count, receipt_number)
            else:
                receipt_number = self.generate_receipt_number()
        else:
            receipt_number = self.generate_receipt_number()

        pdf_filename = f"{receipt_number}.pdf"

        # Render HTML & PDF
        html_str = self.render_receipt_html(snapshot, receipt_number)
        pdf_path = self.render_pdf_from_html(html_str, pdf_filename)

        # Build clean payload for 19_Receipts
        row_payload = {
            "Receipt Number": receipt_number,
            "Receipt Kind": snapshot.get("Receipt Kind"),
            "Source Type": snapshot.get("Source Type"),
            "Source Record ID": snapshot.get("Source Record ID"),
            "Source Key": source_key,
            "Linked Payment ID": snapshot.get("Linked Payment ID"),
            "Linked Customer ID": snapshot.get("Linked Customer ID"),
            "Linked Subscription ID": snapshot.get("Linked Subscription ID"),
            "Linked Reseller ID": snapshot.get("Linked Reseller ID"),
            "Linked Wallet Entry ID": snapshot.get("Linked Wallet Entry ID"),
            "Linked Payout ID": snapshot.get("Linked Payout ID"),
            "Original Receipt No": snapshot.get("Original Receipt No"),
            "Issued At": snapshot.get("Issued At"),
            "Payer Display Name": snapshot.get("Payer Display Name"),
            "Payer Contact": snapshot.get("Payer Contact"),
            "Customer ID Snapshot": snapshot.get("Customer ID Snapshot"),
            "Reseller Code Snapshot": snapshot.get("Reseller Code Snapshot"),
            "Package Description": snapshot.get("Package Description"),
            "Regular Subscription SLE": snapshot.get("Regular Subscription SLE"),
            "Discount % Snapshot": snapshot.get("Discount % Snapshot"),
            "Discount Amount SLE": snapshot.get("Discount Amount SLE"),
            "Net Subscription SLE": snapshot.get("Net Subscription SLE"),
            "Installation Fee SLE": snapshot.get("Installation Fee SLE"),
            "Other Authorized Charges SLE": snapshot.get("Other Authorized Charges SLE"),
            "Tax Amount SLE": snapshot.get("Tax Amount SLE"),
            "Amount Due SLE": snapshot.get("Amount Due SLE"),
            "Amount Received SLE": snapshot.get("Amount Received SLE"),
            "Outstanding Balance SLE": snapshot.get("Outstanding Balance SLE"),
            "Currency Snapshot": snapshot.get("Currency Snapshot") or "SLE",
            "Payment Method Snapshot": snapshot.get("Payment Method Snapshot"),
            "External Payment Reference": snapshot.get("External Payment Reference"),
            "Payment Received At": snapshot.get("Payment Received At"),
            "Payment Verification Staff": snapshot.get("Payment Verification Staff"),
            "Verification Timestamp": snapshot.get("Verification Timestamp"),
            "Receipt Status": "Generating",
            "Generation Attempt Count": attempt_count,
            "Issued By Staff": issued_by_staff,
            "Delivery Status": "Not Sent",
            "Audit Notes": f"Generated via NexgloTV Receipt Engine for {source_key}" + (f" | Recipient warning: {phone_msg}" if not phone_valid else ""),
        }

        # Clean null values
        clean_row = {k: v for k, v in row_payload.items() if v is not None}

        # Upsert record in 19_Receipts
        upsert_args = [
            "+record-upsert",
            "--base-token", self.master_base_token,
            "--table-id", self.receipts_tid,
        ]
        if rec_id:
            upsert_args.extend(["--record-id", rec_id])
        upsert_args.extend(["--json", json.dumps(clean_row, ensure_ascii=False, default=str)])

        res = _run_cli(upsert_args)
        data = res.get("data") or res
        rec_id = (
            data.get("record_id")
            or (data.get("record") or {}).get("record_id")
            or ((data.get("record") or {}).get("record_id_list") or [None])[0]
            or rec_id
        )
        if not rec_id:
            _, rows = ResellerSystemManager.list_records(self.master_base_token, self.receipts_tid)
            for r in rows:
                if str(r.get("Receipt Number")) == receipt_number:
                    rec_id = r.get("_record_id") or r.get("record_id")
                    break

        if not rec_id:
            raise RuntimeError(f"Failed to retrieve record_id for created receipt {receipt_number}")

        # Upload attachment using workspace-relative path
        rel_pdf = f"receipts/{pdf_filename}"
        up_res = _run_cli([
            "+record-upload-attachment",
            "--base-token", self.master_base_token,
            "--table-id", self.receipts_tid,
            "--record-id", rec_id,
            "--field-id", "Receipt PDF",
            "--file", rel_pdf,
        ])

        # Mark Issued & Update Delivery Status
        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")
        update_payload = {
            "Receipt Status": "Issued",
            "Delivery Status": target_delivery_status,
            "Last Updated At": now_str,
            "Receipt File ID or URL": rel_pdf,
        }
        _run_cli([
            "+record-upsert",
            "--base-token", self.master_base_token,
            "--table-id", self.receipts_tid,
            "--record-id", rec_id,
            "--json", json.dumps(update_payload, ensure_ascii=False),
        ])

        return {
            "status": "issued",
            "receipt_number": receipt_number,
            "record_id": rec_id,
            "pdf_path": str(pdf_path),
            "upload_res": up_res,
        }

    # ------------------------------------------------------------------------
    # 8. Void / Correction Control (Rule R-12)
    # ------------------------------------------------------------------------
    def void_receipt(
        self,
        receipt_number: str,
        reason: str,
        approved_by_staff: str,
    ) -> dict[str, Any]:
        """Void an issued receipt with required reason and staff approval."""
        if not reason or not approved_by_staff:
            raise ValueError("Voiding a receipt requires both a reason and approved_by_staff")

        existing = self.find_receipt_by_number(receipt_number)
        if not existing:
            raise ValueError(f"Receipt {receipt_number} not found")

        rec_id = existing.get("_record_id") or existing.get("record_id")
        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")
        payload = {
            "Receipt Status": "Voided",
            "Void or Correction Reason": reason,
            "Approved Adjustment By": approved_by_staff,
            "Last Updated At": now_str,
            "Audit Notes": f"Voided on {now_str} by {approved_by_staff}: {reason}",
        }
        _run_cli([
            "+record-upsert",
            "--base-token", self.master_base_token,
            "--table-id", self.receipts_tid,
            "--record-id", rec_id,
            "--json", json.dumps(payload, ensure_ascii=False),
        ])
        return {"status": "voided", "receipt_number": receipt_number, "record_id": rec_id}

    def issue_refund_credit_note(
        self,
        *,
        original_receipt_number: str,
        refund_amount_sle: float,
        reason: str,
        approved_by_staff: str,
    ) -> dict[str, Any]:
        """Issue distinct linked Refund Acknowledgement / Credit Note and void/supersede original (Rule R-12)."""
        orig = self.find_receipt_by_number(original_receipt_number)
        if not orig:
            raise ValueError(f"Original receipt {original_receipt_number} not found")

        # First void the original with reason
        self.void_receipt(
            original_receipt_number,
            reason=f"Superseded by refund: {reason}",
            approved_by_staff=approved_by_staff,
        )

        now_utc = datetime.now(timezone.utc)
        refund_snap = {
            "Receipt Kind": "Refund Acknowledgement",
            "Source Type": "Refund",
            "Source Record ID": orig.get("Source Record ID") or original_receipt_number,
            "Source Key": f"REFUND:{original_receipt_number}",
            "Original Receipt No": original_receipt_number,
            "Linked Payment ID": orig.get("Linked Payment ID"),
            "Linked Customer ID": orig.get("Linked Customer ID"),
            "Payer Display Name": orig.get("Payer Display Name"),
            "Customer ID Snapshot": orig.get("Customer ID Snapshot"),
            "Package Description": f"Refund Adjustment for {original_receipt_number}: {reason}",
            "Service Period": "Refund / Reversal",
            "Regular Subscription SLE": float(orig.get("Regular Subscription SLE") or 0),
            "Discount % Snapshot": float(orig.get("Discount % Snapshot") or 0),
            "Discount Amount SLE": float(orig.get("Discount Amount SLE") or 0),
            "Net Subscription SLE": float(orig.get("Net Subscription SLE") or 0),
            "Installation Fee SLE": float(orig.get("Installation Fee SLE") or 0),
            "Other Authorized Charges SLE": 0.0,
            "Tax Amount SLE": 0.0,
            "Amount Due SLE": 0.0,
            "Amount Received SLE": -round(float(refund_amount_sle), 2),
            "Outstanding Balance SLE": 0.0,
            "Currency Snapshot": "SLE",
            "Payment Method Snapshot": orig.get("Payment Method Snapshot") or "Mobile Money",
            "External Payment Reference": f"REFUND-{original_receipt_number}",
            "Payment Verification Staff": approved_by_staff,
            "Verification Timestamp": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Issued At": now_utc.strftime("%Y/%m/%d %H:%M"),
            "Receipt Title": "REFUND ACKNOWLEDGEMENT / CREDIT NOTE",
            "Receipt Payment Status": "REFUNDED",
        }

        return self.issue_receipt(refund_snap, issued_by_staff=approved_by_staff)
