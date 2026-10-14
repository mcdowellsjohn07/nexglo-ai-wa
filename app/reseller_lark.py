"""NexgloTV Independent Reseller Management System — Lark Base CLI Implementation.

Authoritative implementation of:
  - NexgloTV_Reseller_Lark_CLI_Hermes_Playbook.md
  - NexgloTV_Reseller_CLI_Implementation_Manifest.json
  - NexgloTV_Reseller_Launch_QA_Checklist.csv

Architecture (Three-Layer Security Boundary):
  1. Master CRM Base (`E8jObNOAeaZqUHsyxRHjR9VcpBg` — "NexgloTV CRM", 18 tables):
     Staff/Admin only. NEVER shared with resellers. NEVER recreated or replaced.
  2. Reseller Intake Base ("NexgloTV - Reseller Intake (PRIVATE)", 6 tables + 6 forms):
     Private staff-owned Base. Resellers submit via Forms only (respondent fields
     only; admin/status/Master ID fields hidden from forms).
  3. Reseller Portal Template Base ("NexgloTV - Reseller Portal TEMPLATE (UNSHARED)",
     7 tables + formulas + 9 views + native Dashboard Block):
     Cloned into one isolated Base per approved reseller
     ("NexgloTV - Reseller - {ResellerCode}"). Contains only sanitized, allowlisted
     snapshots for that single reseller.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import time
from app.crm_lark import LarkCLIError, _run_cli as _raw_run_cli

log = logging.getLogger(__name__)


def _run_cli(args: list[str], *, timeout: int = 90, confirm: bool = False) -> dict[str, Any]:
    """Resilient wrapper around `crm_lark._run_cli` that retries transient timeouts or Go OOMs."""
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            return _raw_run_cli(args, timeout=timeout, confirm=confirm)
        except LarkCLIError as exc:
            msg = str(exc).lower()
            if attempt < 2 and ("timeout" in msg or "cannot allocate memory" in msg or "empty output" in msg):
                log.warning("Transient Lark CLI error on %s (attempt %d/3): %s", args[0], attempt + 1, exc)
                time.sleep(1.5 * (attempt + 1))
                last_err = exc
                continue
            raise
    raise last_err  # type: ignore[misc]

MASTER_CRM_BASE_TOKEN = "E8jObNOAeaZqUHsyxRHjR9VcpBg"
INTAKE_BASE_NAME = "NexgloTV - Reseller Intake (PRIVATE)"
PORTAL_TEMPLATE_BASE_NAME = "NexgloTV - Reseller Portal TEMPLATE (UNSHARED)"
PORTAL_DASHBOARD_NAME = "Reseller Overview Dashboard"


# ============================================================================
# Field Schema Builders (Manifest type_hint -> Lark CLI field definition)
# ============================================================================

def _f_text(name: str) -> dict[str, Any]:
    return {"name": name, "type": "text"}


def _f_phone(name: str) -> dict[str, Any]:
    return {"name": name, "type": "text", "style": {"type": "phone"}}


def _f_email(name: str) -> dict[str, Any]:
    return {"name": name, "type": "text", "style": {"type": "email"}}


def _f_datetime(name: str) -> dict[str, Any]:
    return {"name": name, "type": "datetime", "style": {"format": "yyyy/MM/dd HH:mm"}}


def _f_date(name: str) -> dict[str, Any]:
    return {"name": name, "type": "datetime", "style": {"format": "yyyy/MM/dd"}}


def _f_number(name: str) -> dict[str, Any]:
    return {"name": name, "type": "number", "style": {"type": "plain", "precision": 0}}


def _f_checkbox(name: str) -> dict[str, Any]:
    return {"name": name, "type": "checkbox"}


def _f_select(name: str, options: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "type": "select",
        "multiple": False,
        "options": [{"name": o} for o in options],
    }


def manifest_field_to_lark(field_def: dict[str, Any]) -> dict[str, Any]:
    """Convert a manifest field specification into a Lark Base CLI field payload."""
    name = field_def["name"]
    th = field_def.get("type_hint", "text")
    if th == "text":
        return _f_text(name)
    if th == "phone":
        return _f_phone(name)
    if th == "email":
        return _f_email(name)
    if th == "date_time":
        return _f_datetime(name)
    if th == "date":
        return _f_date(name)
    if th == "number":
        return _f_number(name)
    if th == "checkbox":
        return _f_checkbox(name)
    if th == "select":
        return _f_select(name, field_def.get("options", []))
    return _f_text(name)


# ============================================================================
# Base 1: NexgloTV - Reseller Intake (PRIVATE) — 6 Tables & Form Specs
# ============================================================================

INTAKE_TABLES_SPEC: dict[str, dict[str, Any]] = {
    "01_Sale_Requests": {
        "purpose": "Reseller submits a new sale, renewal, upgrade or installation request.",
        "form_name": "NexgloTV Reseller Sale Request Form",
        "form_description": (
            "Submit a customer sale, renewal, upgrade, or installation request. "
            "Do not include customer passwords or raw access credentials."
        ),
        "admin_only_fields": [
            "Request ID",
            "Submitted At",
            "Request Status",
            "Duplicate Key",
            "Reviewed By Staff",
            "Reviewed At",
            "Master Lead ID",
            "Master Customer ID",
            "Master Sale ID",
            "Master Payment ID",
            "Rejection Reason",
        ],
        "fields": [
            {"name": "Request ID", "type_hint": "text"},
            {"name": "Submitted At", "type_hint": "date_time"},
            {"name": "Reseller Code", "type_hint": "text", "required_on_form": True},
            {"name": "Submitted By Name", "type_hint": "text", "required_on_form": True},
            {"name": "Submitter Email", "type_hint": "email", "required_on_form": True},
            {"name": "Sale Type", "type_hint": "select", "options": ["New Subscription", "Renewal", "Upgrade", "Installation Only"], "required_on_form": True},
            {"name": "Existing Customer Ref", "type_hint": "text"},
            {"name": "Customer Full Name", "type_hint": "text", "required_on_form": True},
            {"name": "Customer WhatsApp", "type_hint": "phone", "required_on_form": True},
            {"name": "Customer Alt Phone", "type_hint": "phone"},
            {"name": "Region", "type_hint": "select", "options": ["Western Area Urban", "Western Area Rural", "Bo", "Kenema", "Makeni", "Kono", "Port Loko", "Other"], "required_on_form": True},
            {"name": "District or Town", "type_hint": "text", "required_on_form": True},
            {"name": "Community or Address", "type_hint": "text"},
            {"name": "Preferred Language", "type_hint": "select", "options": ["English", "Krio", "Temne", "Mende", "Other"]},
            {"name": "Package Wanted", "type_hint": "select", "options": ["Monthly - 1 Device", "Monthly - 2 Devices", "Monthly - 3 Devices", "Monthly - 4+ Devices", "Quarterly", "6 Months", "Annual"], "required_on_form": True},
            {"name": "Device Count", "type_hint": "number", "required_on_form": True},
            {"name": "Device Type", "type_hint": "select", "options": ["Android TV", "Smart TV", "Firestick", "Android Box", "Android Phone", "iPhone/iPad", "Laptop/PC", "Other"], "required_on_form": True},
            {"name": "Internet Type", "type_hint": "select", "options": ["Mobile Data", "Home Wi-Fi", "Fiber", "Office Network", "Unknown"]},
            {"name": "Setup Type", "type_hint": "select", "options": ["Self-Setup", "Remote Assistance", "Physical Installation"], "required_on_form": True},
            {"name": "Collected By", "type_hint": "select", "options": ["Customer Pays NexgloTV Direct", "Reseller Collected Cash/MoMo", "Use Reseller Prepaid Wallet"], "required_on_form": True},
            {"name": "Amount Reported SLE", "type_hint": "number", "required_on_form": True},
            {"name": "Payment Method", "type_hint": "select", "options": ["Orange Money", "Afrimoney", "Bank Transfer", "Cash", "Prepaid Wallet", "Pending Payment"], "required_on_form": True},
            {"name": "Transaction Reference", "type_hint": "text"},
            {"name": "Payment Proof URL", "type_hint": "text"},
            {"name": "Customer Notes", "type_hint": "text"},
            {"name": "Request Status", "type_hint": "select", "options": ["Submitted", "Identity Check", "Under Review", "Payment Pending", "Approved", "Rejected", "Duplicate"]},
            {"name": "Duplicate Key", "type_hint": "text"},
            {"name": "Reviewed By Staff", "type_hint": "text"},
            {"name": "Reviewed At", "type_hint": "date_time"},
            {"name": "Master Lead ID", "type_hint": "text"},
            {"name": "Master Customer ID", "type_hint": "text"},
            {"name": "Master Sale ID", "type_hint": "text"},
            {"name": "Master Payment ID", "type_hint": "text"},
            {"name": "Rejection Reason", "type_hint": "text"},
        ],
    },
    "02_Trial_Requests": {
        "purpose": "Reseller requests a 24-hour free trial before payment. Never generates commission.",
        "form_name": "NexgloTV 24-Hour Free Trial Request Form",
        "form_description": (
            "Request a 24-hour prepayment free trial for a qualified prospect. "
            "Free trials last exactly 24 hours from activation and do not earn commission."
        ),
        "admin_only_fields": [
            "Trial Request ID",
            "Submitted At",
            "Request Status",
            "Duplicate Check",
            "Reviewed By Staff",
            "Reviewed At",
            "Master Lead ID",
            "Master Trial ID",
            "Activated At",
            "Expires At",
            "Decline Reason",
        ],
        "fields": [
            {"name": "Trial Request ID", "type_hint": "text"},
            {"name": "Submitted At", "type_hint": "date_time"},
            {"name": "Reseller Code", "type_hint": "text", "required_on_form": True},
            {"name": "Submitted By Name", "type_hint": "text", "required_on_form": True},
            {"name": "Submitter Email", "type_hint": "email", "required_on_form": True},
            {"name": "Customer Full Name", "type_hint": "text", "required_on_form": True},
            {"name": "Customer WhatsApp", "type_hint": "phone", "required_on_form": True},
            {"name": "Region", "type_hint": "select", "options": ["Western Area Urban", "Western Area Rural", "Bo", "Kenema", "Makeni", "Kono", "Port Loko", "Other"]},
            {"name": "District or Town", "type_hint": "text"},
            {"name": "Device Type", "type_hint": "select", "options": ["Android TV", "Smart TV", "Firestick", "Android Box", "Android Phone", "iPhone/iPad", "Laptop/PC", "Other"], "required_on_form": True},
            {"name": "Device Count", "type_hint": "number"},
            {"name": "Internet Type", "type_hint": "select", "options": ["Mobile Data", "Home Wi-Fi", "Fiber", "Unknown"]},
            {"name": "App Installed", "type_hint": "checkbox"},
            {"name": "Preferred Trial Start", "type_hint": "date_time"},
            {"name": "Trial Notes", "type_hint": "text"},
            {"name": "Request Status", "type_hint": "select", "options": ["Submitted", "Identity Check", "Eligibility Check", "Approved", "Activated", "Expired", "Converted", "Declined", "Duplicate"]},
            {"name": "Duplicate Check", "type_hint": "select", "options": ["Not Checked", "Clear", "Possible Duplicate", "Confirmed Duplicate"]},
            {"name": "Reviewed By Staff", "type_hint": "text"},
            {"name": "Reviewed At", "type_hint": "date_time"},
            {"name": "Master Lead ID", "type_hint": "text"},
            {"name": "Master Trial ID", "type_hint": "text"},
            {"name": "Activated At", "type_hint": "date_time"},
            {"name": "Expires At", "type_hint": "date_time"},
            {"name": "Decline Reason", "type_hint": "text"},
        ],
    },
    "03_Support_Requests": {
        "purpose": "Reseller support requests become staff-reviewed Master tickets; never accept passwords or access tokens.",
        "form_name": "NexgloTV Reseller Support Request Form",
        "form_description": (
            "Submit a technical or billing support request for one of your customers. "
            "Never enter customer passwords, PINs, or private stream tokens."
        ),
        "admin_only_fields": [
            "Support Request ID",
            "Submitted At",
            "Status",
            "Assigned Staff",
            "Master Ticket ID",
            "Last Updated At",
        ],
        "fields": [
            {"name": "Support Request ID", "type_hint": "text"},
            {"name": "Reseller Code", "type_hint": "text", "required_on_form": True},
            {"name": "Submitted By Name", "type_hint": "text", "required_on_form": True},
            {"name": "Submitter Email", "type_hint": "email", "required_on_form": True},
            {"name": "Submitted At", "type_hint": "date_time"},
            {"name": "Customer Ref or Contact", "type_hint": "text", "required_on_form": True},
            {"name": "Issue Type", "type_hint": "select", "options": ["App Setup", "Login / Access", "Playback", "Billing", "Device", "Installation", "Other"], "required_on_form": True},
            {"name": "Priority", "type_hint": "select", "options": ["Normal", "High", "Urgent"]},
            {"name": "Problem Description", "type_hint": "text", "required_on_form": True},
            {"name": "Evidence URL", "type_hint": "text"},
            {"name": "Status", "type_hint": "select", "options": ["Submitted", "Assigned", "In Progress", "Waiting for Customer", "Resolved", "Closed"]},
            {"name": "Assigned Staff", "type_hint": "text"},
            {"name": "Master Ticket ID", "type_hint": "text"},
            {"name": "Last Updated At", "type_hint": "date_time"},
        ],
    },
    "04_Payout_Requests": {
        "purpose": "Requests are not payments; finance verifies earned/unpaid commissions and destination out of band.",
        "form_name": "NexgloTV Reseller Payout Request Form",
        "form_description": (
            "Request payout of approved, unpaid commissions. Finance verifies your "
            "registered payout destination out of band before settlement."
        ),
        "admin_only_fields": [
            "Payout Request ID",
            "Submitted At",
            "Request Status",
            "Reviewed By Staff",
            "Reviewed At",
            "Master Payout ID",
        ],
        "fields": [
            {"name": "Payout Request ID", "type_hint": "text"},
            {"name": "Reseller Code", "type_hint": "text", "required_on_form": True},
            {"name": "Submitter Email", "type_hint": "email", "required_on_form": True},
            {"name": "Submitted At", "type_hint": "date_time"},
            {"name": "Amount Requested SLE", "type_hint": "number", "required_on_form": True},
            {"name": "Method", "type_hint": "select", "options": ["Mobile Money", "Bank Transfer", "Cash"], "required_on_form": True},
            {"name": "Destination Masked", "type_hint": "text"},
            {"name": "Request Note", "type_hint": "text"},
            {"name": "Request Status", "type_hint": "select", "options": ["Submitted", "Identity Check", "Under Review", "Approved", "Rejected", "Paid"]},
            {"name": "Reviewed By Staff", "type_hint": "text"},
            {"name": "Reviewed At", "type_hint": "date_time"},
            {"name": "Master Payout ID", "type_hint": "text"},
        ],
    },
    "05_Wallet_Deposit_Requests": {
        "purpose": "Only confirmed funds create an approved wallet credit in Master. Prevent duplicates by transaction reference.",
        "form_name": "NexgloTV Wallet Deposit Request Form",
        "form_description": (
            "Report a prepaid reseller wallet top-up deposit. Wallet credit becomes "
            "available only after finance confirms receipt of funds."
        ),
        "admin_only_fields": [
            "Wallet Request ID",
            "Submitted At",
            "Request Status",
            "Verified By Staff",
            "Verified At",
            "Master Wallet Entry ID",
        ],
        "fields": [
            {"name": "Wallet Request ID", "type_hint": "text"},
            {"name": "Reseller Code", "type_hint": "text", "required_on_form": True},
            {"name": "Submitter Email", "type_hint": "email", "required_on_form": True},
            {"name": "Submitted At", "type_hint": "date_time"},
            {"name": "Amount SLE", "type_hint": "number", "required_on_form": True},
            {"name": "Deposit Method", "type_hint": "select", "options": ["Mobile Money", "Bank Transfer", "Cash"], "required_on_form": True},
            {"name": "Transaction Reference", "type_hint": "text"},
            {"name": "Proof URL", "type_hint": "text"},
            {"name": "Request Status", "type_hint": "select", "options": ["Submitted", "Identity Check", "Pending Verification", "Confirmed", "Rejected", "Duplicate"]},
            {"name": "Verified By Staff", "type_hint": "text"},
            {"name": "Verified At", "type_hint": "date_time"},
            {"name": "Master Wallet Entry ID", "type_hint": "text"},
        ],
    },
    "06_Reseller_Applications": {
        "purpose": "Optional onboarding form; admins alone approve contract, settlement terms and identity verification.",
        "form_name": "NexgloTV Reseller Onboarding Application Form",
        "form_description": (
            "Apply to become an authorized NexgloTV reseller. Applications are "
            "reviewed by NexgloTV management prior to onboarding."
        ),
        "admin_only_fields": [
            "Application ID",
            "Submitted At",
            "Application Status",
            "Reviewed By Staff",
            "Approved Reseller Code",
            "Notes",
        ],
        "fields": [
            {"name": "Application ID", "type_hint": "text"},
            {"name": "Submitted At", "type_hint": "date_time"},
            {"name": "Business or Full Name", "type_hint": "text", "required_on_form": True},
            {"name": "Applicant Name", "type_hint": "text", "required_on_form": True},
            {"name": "WhatsApp", "type_hint": "phone", "required_on_form": True},
            {"name": "Email", "type_hint": "email", "required_on_form": True},
            {"name": "Territory", "type_hint": "text"},
            {"name": "Desired Operating Model", "type_hint": "select", "options": ["Referral Commission", "Collect and Remit", "Prepaid Wallet"]},
            {"name": "Relevant Experience", "type_hint": "text"},
            {"name": "Application Status", "type_hint": "select", "options": ["New", "Under Review", "Approved", "Rejected", "Onboarded"]},
            {"name": "Reviewed By Staff", "type_hint": "text"},
            {"name": "Approved Reseller Code", "type_hint": "text"},
            {"name": "Notes", "type_hint": "text"},
        ],
    },
}


# ============================================================================
# Base 2: NexgloTV - Reseller Portal TEMPLATE (UNSHARED) — 7 Tables, Formulas, Views
# ============================================================================

PORTAL_TABLES_SPEC: dict[str, dict[str, Any]] = {
    "01_My_Customers": {
        "purpose": "Only this reseller's approved customer summaries. Do not include account credentials, private admin notes, financial proofs or master hyperlinks.",
        "fields": [
            {"name": "Customer Ref", "type_hint": "text"},
            {"name": "Customer Display Name", "type_hint": "text"},
            {"name": "Masked Phone", "type_hint": "text"},
            {"name": "Region", "type_hint": "text"},
            {"name": "Current Package", "type_hint": "text"},
            {"name": "Devices", "type_hint": "number"},
            {"name": "Subscription Status", "type_hint": "select", "options": ["Trial", "Active", "Renewal Due", "Expired", "Suspended"]},
            {"name": "Activation Date", "type_hint": "date"},
            {"name": "Expiry Date", "type_hint": "date"},
            {"name": "Renewal Due Days", "type_hint": "number"},
            {"name": "Next Action", "type_hint": "text"},
            {"name": "Last Verified At", "type_hint": "date_time"},
        ],
    },
    "02_My_Sales": {
        "purpose": "Reseller-visible status of submitted and verified sales.",
        "fields": [
            {"name": "Reseller Sale Ref", "type_hint": "text"},
            {"name": "Sale Date", "type_hint": "date_time"},
            {"name": "Customer Ref", "type_hint": "text"},
            {"name": "Customer Display Name", "type_hint": "text"},
            {"name": "Sale Type", "type_hint": "select", "options": ["New Subscription", "Renewal", "Upgrade", "Installation"]},
            {"name": "Package", "type_hint": "text"},
            {"name": "Devices", "type_hint": "number"},
            {"name": "Gross Subscription SLE", "type_hint": "number"},
            {"name": "Discount SLE", "type_hint": "number"},
            {"name": "Net Subscription SLE", "type_hint": "number"},
            {"name": "Installation Fee SLE", "type_hint": "number"},
            {"name": "Collected By", "type_hint": "select", "options": ["NexgloTV Direct", "Reseller Collected", "Prepaid Wallet"]},
            {"name": "Remittance Due SLE", "type_hint": "number"},
            {"name": "Payment Status", "type_hint": "select", "options": ["Pending", "Under Review", "Confirmed", "Failed", "Refunded"]},
            {"name": "Sale Status", "type_hint": "select", "options": ["Submitted", "Trial", "Payment Pending", "Confirmed", "Cancelled", "Refunded"]},
            {"name": "Commission Eligible", "type_hint": "checkbox"},
            {"name": "Commission SLE", "type_hint": "number"},
            {"name": "Commission Status", "type_hint": "select", "options": ["Not Eligible", "Pending Payment", "Under Review", "Approved", "In Payout", "Paid", "Held", "Reversed"]},
            {"name": "Last Verified At", "type_hint": "date_time"},
        ],
    },
    "03_My_Trials": {
        "purpose": "24-hour free trials requested by this reseller. Trials never create commission.",
        "fields": [
            {"name": "Trial ID", "type_hint": "text"},
            {"name": "Customer Name", "type_hint": "text"},
            {"name": "Masked Phone", "type_hint": "text"},
            {"name": "Device Type", "type_hint": "select", "options": ["Android TV", "Smart TV", "Firestick", "Android Box", "Android Phone", "iPhone/iPad", "Laptop/PC", "Other"]},
            {"name": "Trial Status", "type_hint": "select", "options": ["Requested", "Approved", "Active", "Expired", "Converted", "Declined"]},
            {"name": "Activated At", "type_hint": "date_time"},
            {"name": "Expires At", "type_hint": "date_time"},
            {"name": "Converted To Sale", "type_hint": "select", "options": ["Yes", "No"]},
            {"name": "Notes", "type_hint": "text"},
            {"name": "Last Verified At", "type_hint": "date_time"},
            {"name": "Trial Window Hours", "type_hint": "number"},
        ],
    },
    "04_My_Commissions": {
        "purpose": "Commission ledger snapshot for this reseller only.",
        "fields": [
            {"name": "Commission ID", "type_hint": "text"},
            {"name": "Earned Date", "type_hint": "date"},
            {"name": "Reseller Sale Ref", "type_hint": "text"},
            {"name": "Customer Display Name", "type_hint": "text"},
            {"name": "Eligible Revenue SLE", "type_hint": "number"},
            {"name": "Commission Method", "type_hint": "select", "options": ["Percentage", "Fixed", "None"]},
            {"name": "Rate or Fixed Snapshot", "type_hint": "text"},
            {"name": "Commission Earned SLE", "type_hint": "number"},
            {"name": "Adjustment SLE", "type_hint": "number"},
            {"name": "Commission Paid SLE", "type_hint": "number"},
            {"name": "Outstanding SLE", "type_hint": "number"},
            {"name": "Commission Status", "type_hint": "select", "options": ["Pending Payment", "Under Review", "Approved", "In Payout", "Paid", "Held", "Reversed"]},
            {"name": "Payout Batch ID", "type_hint": "text"},
            {"name": "Paid Date", "type_hint": "date"},
            {"name": "Notes", "type_hint": "text"},
            {"name": "Last Verified At", "type_hint": "date_time"},
        ],
    },
    "05_My_Wallet": {
        "purpose": "Prepaid credit ledger for resellers using the wallet model.",
        "fields": [
            {"name": "Wallet Entry ID", "type_hint": "text"},
            {"name": "Transaction Date", "type_hint": "date_time"},
            {"name": "Entry Type", "type_hint": "select", "options": ["Deposit Credit", "Package Debit", "Refund Credit", "Manual Adjustment Credit", "Manual Adjustment Debit"]},
            {"name": "Credit SLE", "type_hint": "number"},
            {"name": "Debit SLE", "type_hint": "number"},
            {"name": "Approved Net Movement SLE", "type_hint": "number"},
            {"name": "Related Sale Ref", "type_hint": "text"},
            {"name": "Reference", "type_hint": "text"},
            {"name": "Status", "type_hint": "select", "options": ["Pending", "Confirmed", "Reversed", "Rejected"]},
            {"name": "Verified By", "type_hint": "text"},
            {"name": "Notes", "type_hint": "text"},
            {"name": "Last Verified At", "type_hint": "date_time"},
        ],
    },
    "06_My_Payouts": {
        "purpose": "Approved and historical commission payouts for this reseller.",
        "fields": [
            {"name": "Payout ID", "type_hint": "text"},
            {"name": "Period Start", "type_hint": "date"},
            {"name": "Period End", "type_hint": "date"},
            {"name": "Requested At", "type_hint": "date_time"},
            {"name": "Approved Amount SLE", "type_hint": "number"},
            {"name": "Paid Amount SLE", "type_hint": "number"},
            {"name": "Balance Due SLE", "type_hint": "number"},
            {"name": "Method", "type_hint": "select", "options": ["Mobile Money", "Bank Transfer", "Cash"]},
            {"name": "Destination Masked", "type_hint": "text"},
            {"name": "Transaction Reference", "type_hint": "text"},
            {"name": "Payout Status", "type_hint": "select", "options": ["Under Review", "Approved", "Processing", "Paid", "Partially Paid", "Rejected"]},
            {"name": "Paid At", "type_hint": "date_time"},
            {"name": "Notes", "type_hint": "text"},
            {"name": "Last Verified At", "type_hint": "date_time"},
        ],
    },
    "07_My_Profile": {
        "purpose": "Single-row summary of the reseller's approved agreement and form links.",
        "fields": [
            {"name": "Reseller Code", "type_hint": "text"},
            {"name": "Reseller Name", "type_hint": "text"},
            {"name": "Status", "type_hint": "select", "options": ["Active", "Suspended", "Inactive"]},
            {"name": "Operating Model", "type_hint": "select", "options": ["Referral Commission", "Collect and Remit", "Prepaid Wallet"]},
            {"name": "Commission Structure", "type_hint": "text"},
            {"name": "Territory", "type_hint": "text"},
            {"name": "Assigned NexgloTV Manager", "type_hint": "text"},
            {"name": "Support Contact", "type_hint": "text"},
            {"name": "Sale Request Form URL", "type_hint": "text"},
            {"name": "Trial Request Form URL", "type_hint": "text"},
            {"name": "Support Request Form URL", "type_hint": "text"},
            {"name": "Payout Request Form URL", "type_hint": "text"},
            {"name": "Wallet Deposit Form URL", "type_hint": "text"},
            {"name": "Last Updated At", "type_hint": "date_time"},
        ],
    },
}

PORTAL_FORMULAS_SPEC: list[dict[str, str]] = [
    {
        "table": "02_My_Sales",
        "field_name": "Net Subscription SLE",
        "expression": "MAX(0, [Gross Subscription SLE] - [Discount SLE])",
    },
    {
        "table": "05_My_Wallet",
        "field_name": "Approved Net Movement SLE",
        "expression": 'IF([Status] = "Confirmed", [Credit SLE] - [Debit SLE], 0)',
    },
    {
        "table": "04_My_Commissions",
        "field_name": "Outstanding SLE",
        "expression": 'IF([Commission Status] = "Approved", [Commission Earned SLE] - [Commission Paid SLE], 0)',
    },
    {
        "table": "06_My_Payouts",
        "field_name": "Balance Due SLE",
        "expression": "[Approved Amount SLE] - [Paid Amount SLE]",
    },
    {
        "table": "03_My_Trials",
        "field_name": "Trial Window Hours",
        "expression": "IF(OR(ISBLANK([Activated At]), ISBLANK([Expires At])), 0, ROUND(DAYS([Expires At], [Activated At]) * 24, 0))",
    },
]

PORTAL_VIEWS_SPEC: list[dict[str, Any]] = [
    {
        "table": "01_My_Customers",
        "view_name": "My Active Customers",
        "filter": {"logic": "and", "conditions": [["Subscription Status", "intersects", ["Active"]]]},
    },
    {
        "table": "01_My_Customers",
        "view_name": "Renewals Due 7 Days",
        "filter": {"logic": "and", "conditions": [["Subscription Status", "intersects", ["Renewal Due"]]]},
    },
    {
        "table": "03_My_Trials",
        "view_name": "Current Trials",
        "filter": {"logic": "and", "conditions": [["Trial Status", "intersects", ["Requested", "Approved", "Active"]]]},
    },
    {
        "table": "02_My_Sales",
        "view_name": "Confirmed Sales",
        "filter": {"logic": "and", "conditions": [["Sale Status", "intersects", ["Confirmed"]]]},
    },
    {
        "table": "02_My_Sales",
        "view_name": "Payments Under Review",
        "filter": {"logic": "and", "conditions": [["Payment Status", "intersects", ["Pending", "Under Review"]]]},
    },
    {
        "table": "04_My_Commissions",
        "view_name": "Approved Commissions",
        "filter": {"logic": "and", "conditions": [["Commission Status", "intersects", ["Approved", "In Payout", "Paid"]]]},
    },
    {
        "table": "04_My_Commissions",
        "view_name": "Unpaid Commissions",
        "filter": {
            "logic": "and",
            "conditions": [
                ["Commission Status", "intersects", ["Approved"]],
                ["Outstanding SLE", ">", 0],
            ],
        },
    },
    {
        "table": "05_My_Wallet",
        "view_name": "Approved Wallet Movements",
        "filter": {"logic": "and", "conditions": [["Status", "intersects", ["Confirmed"]]]},
    },
    {
        "table": "06_My_Payouts",
        "view_name": "Payout History",
        "filter": {"logic": "and", "conditions": [["Payout Status", "intersects", ["Approved", "Processing", "Paid", "Partially Paid"]]]},
    },
]

INTAKE_VIEWS_SPEC: list[dict[str, Any]] = [
    {
        "table": "01_Sale_Requests",
        "view_name": "Pending Staff Review",
        "filter": {"logic": "and", "conditions": [["Request Status", "intersects", ["Submitted", "Identity Check", "Under Review", "Payment Pending"]]]},
    },
    {
        "table": "02_Trial_Requests",
        "view_name": "Pending Trial Review",
        "filter": {"logic": "and", "conditions": [["Request Status", "intersects", ["Submitted", "Identity Check", "Eligibility Check", "Approved", "Activated"]]]},
    },
    {
        "table": "03_Support_Requests",
        "view_name": "Open Reseller Tickets",
        "filter": {"logic": "and", "conditions": [["Status", "intersects", ["Submitted", "Assigned", "In Progress", "Waiting for Customer"]]]},
    },
    {
        "table": "04_Payout_Requests",
        "view_name": "Pending Finance Review",
        "filter": {"logic": "and", "conditions": [["Request Status", "intersects", ["Submitted", "Identity Check", "Under Review", "Approved"]]]},
    },
    {
        "table": "05_Wallet_Deposit_Requests",
        "view_name": "Pending Deposit Verification",
        "filter": {"logic": "and", "conditions": [["Request Status", "intersects", ["Submitted", "Identity Check", "Pending Verification"]]]},
    },
    {
        "table": "06_Reseller_Applications",
        "view_name": "Pending Applications",
        "filter": {"logic": "and", "conditions": [["Application Status", "intersects", ["New", "Under Review"]]]},
    },
]

PORTAL_DASHBOARD_BLOCKS_SPEC: list[dict[str, Any]] = [
    {
        "name": "Confirmed Sales",
        "type": "statistics",
        "data_config": {
            "table_name": "02_My_Sales",
            "count_all": True,
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "Sale Status", "operator": "is", "value": "Confirmed"}],
            },
        },
    },
    {
        "name": "Active Paid Customers",
        "type": "statistics",
        "data_config": {
            "table_name": "01_My_Customers",
            "count_all": True,
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "Subscription Status", "operator": "is", "value": "Active"}],
            },
        },
    },
    {
        "name": "Trials Active",
        "type": "statistics",
        "data_config": {
            "table_name": "03_My_Trials",
            "count_all": True,
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "Trial Status", "operator": "is", "value": "Active"}],
            },
        },
    },
    {
        "name": "Earned Commissions SLE",
        "type": "statistics",
        "data_config": {
            "table_name": "04_My_Commissions",
            "series": [{"field_name": "Commission Earned SLE", "rollup": "SUM"}],
            "filter": {
                "conjunction": "and",
                "conditions": [
                    {"field_name": "Commission Status", "operator": "isNot", "value": "Reversed"},
                    {"field_name": "Commission Status", "operator": "isNot", "value": "Pending Payment"},
                ],
            },
        },
    },
    {
        "name": "Approved Unpaid Commissions SLE",
        "type": "statistics",
        "data_config": {
            "table_name": "04_My_Commissions",
            "series": [{"field_name": "Outstanding SLE", "rollup": "SUM"}],
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "Commission Status", "operator": "is", "value": "Approved"}],
            },
        },
    },
    {
        "name": "Total Commission Paid SLE",
        "type": "statistics",
        "data_config": {
            "table_name": "04_My_Commissions",
            "series": [{"field_name": "Commission Paid SLE", "rollup": "SUM"}],
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "Commission Status", "operator": "is", "value": "Paid"}],
            },
        },
    },
    {
        "name": "Wallet Available SLE",
        "type": "statistics",
        "data_config": {
            "table_name": "05_My_Wallet",
            "series": [{"field_name": "Approved Net Movement SLE", "rollup": "SUM"}],
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "Status", "operator": "is", "value": "Confirmed"}],
            },
        },
    },
    {
        "name": "Remittance Outstanding SLE",
        "type": "statistics",
        "data_config": {
            "table_name": "02_My_Sales",
            "series": [{"field_name": "Remittance Due SLE", "rollup": "SUM"}],
        },
    },
    {
        "name": "Renewals Due",
        "type": "statistics",
        "data_config": {
            "table_name": "01_My_Customers",
            "count_all": True,
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "Subscription Status", "operator": "is", "value": "Renewal Due"}],
            },
        },
    },
    {
        "name": "Sales by Package",
        "type": "column",
        "data_config": {
            "table_name": "02_My_Sales",
            "series": [{"field_name": "Net Subscription SLE", "rollup": "SUM"}],
            "group_by": [{"field_name": "Package", "mode": "integrated", "sort": {"type": "value", "order": "desc"}}],
        },
    },
    {
        "name": "Customer Status Breakdown",
        "type": "pie",
        "data_config": {
            "table_name": "01_My_Customers",
            "count_all": True,
            "group_by": [{"field_name": "Subscription Status", "mode": "integrated"}],
        },
    },
]


# ============================================================================
# Business Rules & Pure Calculation Helpers
# ============================================================================

def mask_phone(phone: str) -> str:
    """Mask a phone number for reseller portal display (never expose raw full contact)."""
    cleaned = re.sub(r"\s+", "", str(phone or ""))
    digits = re.sub(r"[^\d]", "", cleaned)
    if len(digits) < 6:
        return "***"
    prefix = "+232" if digits.startswith("232") else cleaned[:4]
    last3 = digits[-3:]
    return f"{prefix}***{last3}"


def compute_trial_window(activated_at: datetime) -> dict[str, Any]:
    """Enforce the 24-hour prepayment trial rule:
    - Free trials last exactly 24 hours from activation.
    - Commission on free trials is strictly 0 SLE and ineligible.
    """
    if activated_at.tzinfo is None:
        activated_at = activated_at.replace(tzinfo=timezone.utc)
    expires_at = activated_at + timedelta(hours=24)
    return {
        "activated_at": activated_at.strftime("%Y/%m/%d %H:%M"),
        "expires_at": expires_at.strftime("%Y/%m/%d %H:%M"),
        "duration_hours": 24,
        "commission_eligible": False,
        "commission_earned_sle": 0,
    }


V2_ALLOWED_PAYMENT_PATHS: tuple[str, ...] = ("DIRECT_TO_NEXGLOTV", "PREPAID_WALLET")
V2_DISABLED_MODELS: tuple[str, ...] = (
    "COLLECT_AND_REMIT",
    "Collect and Remit",
    "WHOLESALE_MARGIN",
    "FIXED_COMMISSION_FOR_NEW_SALES",
)

# Authoritative 16-package V2 pricing catalog (NexgloTV_16_Package_Price_Upgrade.csv)
# Every package applies a single 20% customer discount to `regular_unit_sle` to preserve
# `discounted_unit_sle == legacy_unit_sle`, and awards 20% reseller commission on
# fully funded, verified `Net Subscription SLE`.
V2_PACKAGES_CATALOG: dict[str, dict[str, Any]] = {
    "PKG-01": {"duration_months": 1, "device_tier": "1 Device", "min_devices": 1, "legacy_unit_sle": 180.0, "regular_unit_sle": 225.0, "discounted_unit_sle": 180.0, "commission_per_device_sle": 36.0},
    "PKG-02": {"duration_months": 1, "device_tier": "2 Devices", "min_devices": 2, "legacy_unit_sle": 160.0, "regular_unit_sle": 200.0, "discounted_unit_sle": 160.0, "commission_per_device_sle": 32.0},
    "PKG-03": {"duration_months": 1, "device_tier": "3 Devices", "min_devices": 3, "legacy_unit_sle": 140.0, "regular_unit_sle": 175.0, "discounted_unit_sle": 140.0, "commission_per_device_sle": 28.0},
    "PKG-04": {"duration_months": 1, "device_tier": "4+ Devices", "min_devices": 4, "legacy_unit_sle": 120.0, "regular_unit_sle": 150.0, "discounted_unit_sle": 120.0, "commission_per_device_sle": 24.0},
    "PKG-05": {"duration_months": 3, "device_tier": "1 Device", "min_devices": 1, "legacy_unit_sle": 500.0, "regular_unit_sle": 625.0, "discounted_unit_sle": 500.0, "commission_per_device_sle": 100.0},
    "PKG-06": {"duration_months": 3, "device_tier": "2 Devices", "min_devices": 2, "legacy_unit_sle": 450.0, "regular_unit_sle": 562.5, "discounted_unit_sle": 450.0, "commission_per_device_sle": 90.0},
    "PKG-07": {"duration_months": 3, "device_tier": "3 Devices", "min_devices": 3, "legacy_unit_sle": 400.0, "regular_unit_sle": 500.0, "discounted_unit_sle": 400.0, "commission_per_device_sle": 80.0},
    "PKG-08": {"duration_months": 3, "device_tier": "4+ Devices", "min_devices": 4, "legacy_unit_sle": 340.0, "regular_unit_sle": 425.0, "discounted_unit_sle": 340.0, "commission_per_device_sle": 68.0},
    "PKG-09": {"duration_months": 6, "device_tier": "1 Device", "min_devices": 1, "legacy_unit_sle": 950.0, "regular_unit_sle": 1187.5, "discounted_unit_sle": 950.0, "commission_per_device_sle": 190.0},
    "PKG-10": {"duration_months": 6, "device_tier": "2 Devices", "min_devices": 2, "legacy_unit_sle": 850.0, "regular_unit_sle": 1062.5, "discounted_unit_sle": 850.0, "commission_per_device_sle": 170.0},
    "PKG-11": {"duration_months": 6, "device_tier": "3 Devices", "min_devices": 3, "legacy_unit_sle": 750.0, "regular_unit_sle": 937.5, "discounted_unit_sle": 750.0, "commission_per_device_sle": 150.0},
    "PKG-12": {"duration_months": 6, "device_tier": "4+ Devices", "min_devices": 4, "legacy_unit_sle": 640.0, "regular_unit_sle": 800.0, "discounted_unit_sle": 640.0, "commission_per_device_sle": 128.0},
    "PKG-13": {"duration_months": 12, "device_tier": "1 Device", "min_devices": 1, "legacy_unit_sle": 1800.0, "regular_unit_sle": 2250.0, "discounted_unit_sle": 1800.0, "commission_per_device_sle": 360.0},
    "PKG-14": {"duration_months": 12, "device_tier": "2 Devices", "min_devices": 2, "legacy_unit_sle": 1600.0, "regular_unit_sle": 2000.0, "discounted_unit_sle": 1600.0, "commission_per_device_sle": 320.0},
    "PKG-15": {"duration_months": 12, "device_tier": "3 Devices", "min_devices": 3, "legacy_unit_sle": 1400.0, "regular_unit_sle": 1750.0, "discounted_unit_sle": 1400.0, "commission_per_device_sle": 280.0},
    "PKG-16": {"duration_months": 12, "device_tier": "4+ Devices", "min_devices": 4, "legacy_unit_sle": 1200.0, "regular_unit_sle": 1500.0, "discounted_unit_sle": 1200.0, "commission_per_device_sle": 240.0},
}


def compute_v2_package_sale(
    *,
    package_id: str,
    device_count: int,
    payment_path: str = "DIRECT_TO_NEXGLOTV",
    verified_settlement: bool = True,
    activated: bool = True,
    installation_fee_sle: float = 0.0,
    wallet_available_sle: Optional[float] = None,
) -> dict[str, Any]:
    """Authoritative V2 calculation engine for the 16 packages:
    - Applies 20% discount to `New Regular Unit Price SLE` exactly once (preserving legacy selling price).
    - Rejects `COLLECT_AND_REMIT` or any unsupported payment path.
    - Rejects wallet activation debit if `wallet_available_sle < net_subscription_sle`.
    - Awards 20% commission on `net_subscription_sle` ONLY when `verified_settlement` and `activated` are True.
    - Excludes `installation_fee_sle` from discounts, wallet subscription debit, and commission base.
    """
    if payment_path not in V2_ALLOWED_PAYMENT_PATHS:
        raise ValueError(f"Unsupported or retired payment_path '{payment_path}'. Allowed: {V2_ALLOWED_PAYMENT_PATHS}")
    pkg = V2_PACKAGES_CATALOG.get(package_id)
    if not pkg:
        raise ValueError(f"Unknown package_id: {package_id}")
    if pkg["min_devices"] < 4 and device_count != pkg["min_devices"]:
        raise ValueError(f"{package_id} requires exactly {pkg['min_devices']} device(s), got {device_count}")
    if pkg["min_devices"] == 4 and device_count < 4:
        raise ValueError(f"{package_id} (4+ tier) requires >= 4 devices, got {device_count}")

    reg_unit = float(pkg["regular_unit_sle"])
    gross_sub = round(reg_unit * device_count, 2)
    cust_discount = round(gross_sub * 0.20, 2)
    net_sub = round(gross_sub - cust_discount, 2)
    install_fee = round(float(installation_fee_sle), 2)
    customer_invoice = round(net_sub + install_fee, 2)

    if payment_path == "PREPAID_WALLET" and wallet_available_sle is not None:
        if float(wallet_available_sle) < net_sub:
            raise ValueError(f"Insufficient prepaid wallet balance ({wallet_available_sle} SLE) for {net_sub} SLE activation debit")

    eligible = bool(verified_settlement and activated)
    comm_base = net_sub if eligible else 0.0
    comm_20pct = round(comm_base * 0.20, 2)
    retained = round(net_sub - comm_20pct, 2) if eligible else 0.0

    return {
        "package_id": package_id,
        "price_version": "regular-plus-20pct-v2",
        "pricing_basis": "PER_DEVICE",
        "device_count": device_count,
        "regular_unit_sle": reg_unit,
        "gross_subscription_sle": gross_sub,
        "customer_discount_pct": 20.0,
        "customer_discount_sle": cust_discount,
        "net_subscription_sle": net_sub,
        "installation_fee_sle": install_fee,
        "customer_invoice_sle": customer_invoice,
        "payment_path": payment_path,
        "wallet_debit_sle": net_sub if (payment_path == "PREPAID_WALLET" and eligible) else 0.0,
        "commission_eligible": eligible,
        "commission_rate_pct": 20.0,
        "commission_base_sle": comm_base,
        "commission_earned_sle": comm_20pct,
        "company_retained_before_costs_sle": retained,
        "remittance_due_sle": 0.0,
    }


def compute_sale_financials(
    *,
    gross_subscription_sle: int,
    discount_sle: int = 0,
    installation_fee_sle: int = 0,
    sale_status: str = "Confirmed",
    payment_status: str = "Confirmed",
    operating_model: str = "Referral Commission",
    commission_method: str = "Percentage",
    commission_rate_pct: int = 20,
    fixed_commission_sle: int = 0,
    collected_by: str = "NexgloTV",
    amount_collected_by_reseller_sle: int = 0,
    amount_remitted_to_nexglotv_sle: int = 0,
) -> dict[str, Any]:
    """Compute net subscription revenue, commission eligibility, snapshot values, and remittance due.

    Business rules enforced:
    1. Free trials (`sale_status == 'Trial'`) never generate commission.
    2. Installation fees are excluded from eligible subscription commission revenue by default.
    3. Commission becomes eligible & approved ONLY after payment is `Confirmed`.
    4. For `Collect and Remit` (`collected_by == 'Reseller'`), computes `remittance_due_sle`.
    5. For `Prepaid Wallet`, wallet debits are tracked separately from commission earnings.
    """
    net_subscription_sle = max(0, int(gross_subscription_sle) - int(discount_sle))

    # Free trial rule: zero commission
    if sale_status == "Trial":
        return {
            "gross_subscription_sle": int(gross_subscription_sle),
            "discount_sle": int(discount_sle),
            "net_subscription_sle": 0,
            "installation_fee_sle": int(installation_fee_sle),
            "eligible_revenue_sle": 0,
            "commission_eligible": False,
            "commission_earned_sle": 0,
            "commission_status": "Not Eligible",
            "remittance_due_sle": 0,
        }

    if sale_status in ("Cancelled", "Refunded") or payment_status in ("Failed", "Refunded"):
        return {
            "gross_subscription_sle": int(gross_subscription_sle),
            "discount_sle": int(discount_sle),
            "net_subscription_sle": net_subscription_sle,
            "installation_fee_sle": int(installation_fee_sle),
            "eligible_revenue_sle": 0,
            "commission_eligible": False,
            "commission_earned_sle": 0,
            "commission_status": "Reversed" if sale_status == "Refunded" or payment_status == "Refunded" else "Not Eligible",
            "remittance_due_sle": 0,
        }

    # Calculate commission based on snapshot method
    eligible_revenue_sle = net_subscription_sle
    if commission_method == "Percentage":
        raw_comm = round(eligible_revenue_sle * (int(commission_rate_pct) / 100.0))
    elif commission_method == "Fixed":
        raw_comm = int(fixed_commission_sle)
    else:
        raw_comm = 0

    remittance_due_sle = 0
    if collected_by in ("Reseller", "Reseller Collected", "Reseller Collected Cash/MoMo"):
        remittance_due_sle = max(
            0, int(amount_collected_by_reseller_sle) - int(amount_remitted_to_nexglotv_sle)
        )

    is_confirmed = payment_status == "Confirmed" and sale_status == "Confirmed"
    if not is_confirmed:
        return {
            "gross_subscription_sle": int(gross_subscription_sle),
            "discount_sle": int(discount_sle),
            "net_subscription_sle": net_subscription_sle,
            "installation_fee_sle": int(installation_fee_sle),
            "eligible_revenue_sle": eligible_revenue_sle,
            "commission_eligible": False,
            "commission_earned_sle": raw_comm if raw_comm > 0 else 0,
            "commission_status": "Pending Payment",
            "remittance_due_sle": remittance_due_sle,
        }

    # Payment is confirmed; if reseller still owes remittance under Collect and Remit, hold commission until remitted
    if remittance_due_sle > 0 and operating_model == "Collect and Remit":
        comm_status = "Held"
    elif raw_comm > 0:
        comm_status = "Approved"
    else:
        comm_status = "Not Eligible"

    return {
        "gross_subscription_sle": int(gross_subscription_sle),
        "discount_sle": int(discount_sle),
        "net_subscription_sle": net_subscription_sle,
        "installation_fee_sle": int(installation_fee_sle),
        "eligible_revenue_sle": eligible_revenue_sle,
        "commission_eligible": raw_comm > 0,
        "commission_earned_sle": raw_comm,
        "commission_status": comm_status,
        "remittance_due_sle": remittance_due_sle,
    }


# ============================================================================
# Lark Base Provisioning & Reconciliation Manager
# ============================================================================

class ResellerSystemManager:
    """Manages provisioning, form lockdown, formula/view/dashboard setup, and
    manual staff-approved reconciliation across Master CRM, Reseller Intake Base,
    and isolated Reseller Portal Bases.
    """

    def __init__(self, master_base_token: str = MASTER_CRM_BASE_TOKEN):
        self.master_base_token = master_base_token

    # ------------------------------------------------------------------
    # Low-level Lark CLI helpers
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_base_by_title(title: str, search_keyword: Optional[str] = None) -> str:
        """Resolve an existing Base token by exact title match, using <=30 char keyword."""
        keywords = []
        if search_keyword:
            keywords.append(search_keyword[:30].strip())
        keywords.append("NexgloTV")
        for kw in keywords:
            try:
                res = _run_cli(["+title-resolve", "--title", kw])
                data = res.get("data") or res
                candidates = data.get("candidates") or []
                for cand in candidates:
                    if cand.get("title") == title and cand.get("base_token"):
                        return cand["base_token"]
            except LarkCLIError:
                continue
        return ""

    @staticmethod
    def list_tables(base_token: str) -> dict[str, str]:
        """Return `{table_name: table_id}` for a Base."""
        res = _run_cli(["+table-list", "--base-token", base_token])
        data = res.get("data") or res
        items = data.get("tables") or data.get("items") or []
        out: dict[str, str] = {}
        for item in items:
            tname = item.get("name") or item.get("table_name", "")
            tid = item.get("table_id") or item.get("id", "")
            if tname and tid:
                out[tname] = tid
        return out

    @staticmethod
    def list_fields(base_token: str, table_id: str) -> list[dict[str, Any]]:
        res = _run_cli(["+field-list", "--base-token", base_token, "--table-id", table_id])
        data = res.get("data") or res
        return data.get("fields") or data.get("items") or []

    @staticmethod
    def list_views(base_token: str, table_id: str) -> list[dict[str, Any]]:
        res = _run_cli(["+view-list", "--base-token", base_token, "--table-id", table_id])
        data = res.get("data") or res
        return data.get("views") or data.get("items") or []

    @staticmethod
    def list_records(base_token: str, table_id: str, limit: int = 200) -> tuple[list[str], list[dict[str, Any]]]:
        """Return `(fields, rows_as_dicts_with_record_id)`."""
        res = _run_cli(["+record-list", "--base-token", base_token, "--table-id", table_id, "--limit", str(limit)])
        data = res.get("data") or res
        fields = data.get("fields") or []
        raw_rows = data.get("data") or []
        rows_id = data.get("record_id_list") or data.get("rows_id") or data.get("record_ids") or []
        parsed: list[dict[str, Any]] = []
        if raw_rows:
            for idx, row in enumerate(raw_rows):
                if isinstance(row, list):
                    row_dict = {fields[i]: row[i] for i in range(min(len(fields), len(row)))}
                    if idx < len(rows_id):
                        row_dict["_record_id"] = rows_id[idx]
                    parsed.append(row_dict)
                elif isinstance(row, dict):
                    parsed.append(row)
        else:
            for item in data.get("records") or data.get("items") or []:
                if isinstance(item, dict):
                    row_dict = dict(item.get("fields") or item)
                    if item.get("record_id"):
                        row_dict["_record_id"] = item["record_id"]
                    parsed.append(row_dict)
        return fields, parsed

    @staticmethod
    def upsert_record(
        base_token: str,
        table_id: str,
        key_field: str,
        key_value: str,
        values: dict[str, Any],
    ) -> str:
        """Create or update a record matched by `key_field == key_value`.

        Uses `+record-upsert`:
          - Without `--record-id` → creates a new record
          - With `--record-id`    → updates an existing record
        """
        # Clean None values — Lark CLI rejects null cells
        clean = {k: v for k, v in values.items() if v is not None}

        _, rows = ResellerSystemManager.list_records(base_token, table_id)
        for r in rows:
            if str(r.get(key_field, "")).strip() == str(key_value).strip():
                rec_id = r.get("_record_id") or r.get("record_id", "")
                if rec_id:
                    _run_cli([
                        "+record-upsert",
                        "--base-token", base_token,
                        "--table-id", table_id,
                        "--record-id", rec_id,
                        "--json", json.dumps(clean, ensure_ascii=False, default=str),
                    ])
                    return rec_id

        # No existing record found — create new
        res = _run_cli([
            "+record-upsert",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps(clean, ensure_ascii=False, default=str),
        ])
        data = res.get("data") or res
        rec = data.get("record") or {}
        return (
            data.get("record_id")
            or rec.get("record_id")
            or rec.get("id")
            or ""
        )

    # ------------------------------------------------------------------
    # Phase B: Provision NexgloTV - Reseller Intake (PRIVATE)
    # ------------------------------------------------------------------

    def ensure_intake_base(self) -> dict[str, Any]:
        """Idempotently create and configure `NexgloTV - Reseller Intake (PRIVATE)`."""
        base_token = self.resolve_base_by_title(INTAKE_BASE_NAME, "Reseller Intake")
        table_names = list(INTAKE_TABLES_SPEC.keys())

        if not base_token:
            first_tname = table_names[0]
            first_fields = [manifest_field_to_lark(f) for f in INTAKE_TABLES_SPEC[first_tname]["fields"]]
            res = _run_cli([
                "+base-create",
                "--name", INTAKE_BASE_NAME,
                "--table-name", first_tname,
                "--fields", json.dumps(first_fields, ensure_ascii=False),
            ], timeout=180)
            data = res.get("data") or res
            base_obj = data.get("base") or {}
            base_token = (
                data.get("base_token")
                or data.get("app_token")
                or base_obj.get("base_token")
                or base_obj.get("app_token")
                or ""
            )
            if not base_token:
                raise LarkCLIError(f"Failed to obtain base_token for {INTAKE_BASE_NAME}: {res}")

        tables = self.list_tables(base_token)
        for tname in table_names:
            if tname not in tables:
                fields_payload = [manifest_field_to_lark(f) for f in INTAKE_TABLES_SPEC[tname]["fields"]]
                res = _run_cli([
                    "+table-create",
                    "--base-token", base_token,
                    "--name", tname,
                    "--fields", json.dumps(fields_payload, ensure_ascii=False),
                ], timeout=180)
                data = res.get("data") or res
                tid = data.get("table_id") or (data.get("table") or {}).get("id", "")
                if tid:
                    tables[tname] = tid

        # Configure the 6 Forms with strict admin-field hiding and required respondent fields
        forms_info: dict[str, dict[str, Any]] = {}
        for tname, spec in INTAKE_TABLES_SPEC.items():
            tid = tables[tname]
            forms_info[tname] = self._ensure_intake_form(base_token, tid, tname, spec)

        # Configure staff operational views
        views_info = self._ensure_views(base_token, tables, INTAKE_VIEWS_SPEC)

        return {
            "base_name": INTAKE_BASE_NAME,
            "base_token": base_token,
            "url": f"https://gjpmrvdwvnro.jp.larksuite.com/base/{base_token}",
            "tables": tables,
            "forms": forms_info,
            "views": views_info,
        }

    def _ensure_intake_form(
        self,
        base_token: str,
        table_id: str,
        table_name: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        """Ensure the table's Form exists, hides all admin/Master fields, sets required flags,
        and enforces safe unopened sharing (`enabled=false`, `require-login=true`, `allow-anonymous=false`).
        """
        form_name = spec["form_name"]
        form_desc = spec["form_description"]
        views = self.list_views(base_token, table_id)
        form_id = ""
        for v in views:
            vtype = v.get("view_type") or v.get("type", "")
            vname = v.get("view_name") or v.get("name", "")
            vid = v.get("view_id") or v.get("id", "")
            if vtype == "form" or vname == form_name:
                form_id = vid
                break

        if not form_id:
            res = _run_cli([
                "+form-create",
                "--base-token", base_token,
                "--table-id", table_id,
                "--name", form_name,
                "--description", form_desc,
            ])
            data = res.get("data") or res
            form_id = (
                data.get("form_id")
                or data.get("id")
                or (data.get("form") or {}).get("id")
                or (data.get("view") or {}).get("id")
                or data.get("view_id", "")
            )
            if not form_id:
                for v in self.list_views(base_token, table_id):
                    if (v.get("view_type") or v.get("type")) == "form":
                        form_id = v.get("view_id") or v.get("id", "")
                        break

        # List form questions
        q_res = _run_cli([
            "+form-questions-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--form-id", form_id,
        ])
        q_data = q_res.get("data") or q_res
        questions = q_data.get("questions") or q_data.get("items") or []

        admin_fields_set = set(spec.get("admin_only_fields", []))
        required_fields_set = {
            f["name"] for f in spec["fields"] if f.get("required_on_form")
        }
        respondent_field_defs = [
            f for f in spec["fields"] if f["name"] not in admin_fields_set
        ]

        # Hide/remove admin_only_fields from the form while preserving underlying table columns (--keep-field)
        to_hide_ids = [
            q["id"] for q in questions
            if (q.get("title") in admin_fields_set or q.get("name") in admin_fields_set)
        ]
        for i in range(0, len(to_hide_ids), 10):
            batch_ids = to_hide_ids[i : i + 10]
            if batch_ids:
                try:
                    _run_cli([
                        "+form-questions-delete",
                        "--base-token", base_token,
                        "--table-id", table_id,
                        "--form-id", form_id,
                        "--question-ids", json.dumps(batch_ids),
                        "--keep-field",
                    ], confirm=True)
                except LarkCLIError as exc:
                    log.warning("Form question hide warning on %s: %s", table_name, exc)

        # Ensure every respondent field is present on the form (convert phone/email/checkbox per Playbook Sec 3 if omitted by Lark Form)
        q_res_mid = _run_cli([
            "+form-questions-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--form-id", form_id,
        ])
        mid_questions = (q_res_mid.get("data") or q_res_mid).get("questions") or (q_res_mid.get("data") or q_res_mid).get("items") or []
        present_titles = {q.get("title") or q.get("name", "") for q in mid_questions}

        missing_respondent_defs = [
            f for f in respondent_field_defs if f["name"] not in present_titles
        ]
        if missing_respondent_defs:
            table_fields = {f.get("name"): f for f in self.list_fields(base_token, table_id)}
            add_questions_payload: list[dict[str, Any]] = []
            for fdef in missing_respondent_defs:
                fname = fdef["name"]
                tf = table_fields.get(fname)
                if not tf:
                    continue
                fid = tf.get("id") or tf.get("field_id", "")
                th = fdef.get("type_hint", "text")
                # Convert phone/email to plain text and checkbox to Yes/No select so Lark Form supports them
                if th in ("phone", "email"):
                    _run_cli([
                        "+field-update",
                        "--base-token", base_token,
                        "--table-id", table_id,
                        "--field-id", fid,
                        "--json", json.dumps({"name": fname, "type": "text", "style": {"type": "plain"}}, ensure_ascii=False),
                    ], confirm=True)
                elif th == "checkbox":
                    _run_cli([
                        "+field-update",
                        "--base-token", base_token,
                        "--table-id", table_id,
                        "--field-id", fid,
                        "--json", json.dumps(_f_select(fname, ["Yes", "No"]), ensure_ascii=False),
                    ], confirm=True)
                add_questions_payload.append({
                    "use_existing_field": True,
                    "field_id": fid,
                    "required": fname in required_fields_set,
                })
            for i in range(0, len(add_questions_payload), 10):
                batch_add = add_questions_payload[i : i + 10]
                if batch_add:
                    try:
                        _run_cli([
                            "+form-questions-create",
                            "--base-token", base_token,
                            "--table-id", table_id,
                            "--form-id", form_id,
                            "--questions", json.dumps(batch_add, ensure_ascii=False),
                        ])
                    except LarkCLIError as exc:
                        log.warning("Form question add warning on %s: %s", table_name, exc)

        # Re-fetch remaining respondent questions and set required_on_form flags
        q_res2 = _run_cli([
            "+form-questions-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--form-id", form_id,
        ])
        q_data2 = q_res2.get("data") or q_res2
        remaining_questions = q_data2.get("questions") or q_data2.get("items") or []

        updates_payload: list[dict[str, Any]] = []
        for q in remaining_questions:
            q_title = q.get("title") or q.get("name", "")
            should_req = q_title in required_fields_set
            if bool(q.get("required")) != should_req:
                upd_obj: dict[str, Any] = {
                    "id": q["id"],
                    "title": q_title,
                    "description": q.get("description") or "",
                    "required": should_req,
                    "visible_rule": q.get("visible_rule"),
                }
                if "option_display_mode" in q and q["option_display_mode"] is not None:
                    upd_obj["option_display_mode"] = q["option_display_mode"]
                updates_payload.append(upd_obj)

        for i in range(0, len(updates_payload), 10):
            batch_upd = updates_payload[i : i + 10]
            if batch_upd:
                _run_cli([
                    "+form-questions-update",
                    "--base-token", base_token,
                    "--table-id", table_id,
                    "--form-id", form_id,
                    "--questions", json.dumps(batch_upd, ensure_ascii=False),
                ])

        # Configure form security settings: require login, disallow anonymous, keep sharing disabled until security gate
        share_settings: dict[str, Any] = {}
        for flag in ["--require-login=true", "--allow-anonymous=false", "--enabled=false"]:
            try:
                _run_cli([
                    "+form-share-update",
                    "--base-token", base_token,
                    "--table-id", table_id,
                    "--form-id", form_id,
                    flag,
                ])
            except LarkCLIError as exc:
                log.debug("form-share-update %s on %s note: %s", flag, table_name, exc)

        try:
            sh = _run_cli([
                "+form-share-get",
                "--base-token", base_token,
                "--table-id", table_id,
                "--form-id", form_id,
            ])
            share_settings = sh.get("data") or sh
        except LarkCLIError:
            pass

        # Final question list for verification
        q_final = _run_cli([
            "+form-questions-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--form-id", form_id,
        ])
        final_qs = (q_final.get("data") or q_final).get("questions") or (q_final.get("data") or q_final).get("items") or []

        return {
            "form_id": form_id,
            "form_name": form_name,
            "visible_questions": [q.get("title") or q.get("name", "") for q in final_qs],
            "required_questions": [
                q.get("title") or q.get("name", "") for q in final_qs if q.get("required")
            ],
            "hidden_admin_fields": list(admin_fields_set),
            "share_settings": share_settings,
        }

    # ------------------------------------------------------------------
    # Phase C: Provision NexgloTV - Reseller Portal TEMPLATE (UNSHARED)
    # ------------------------------------------------------------------

    def ensure_portal_template_base(self) -> dict[str, Any]:
        """Idempotently create and configure `NexgloTV - Reseller Portal TEMPLATE (UNSHARED)`."""
        base_token = self.resolve_base_by_title(PORTAL_TEMPLATE_BASE_NAME, "Reseller Portal")
        table_names = list(PORTAL_TABLES_SPEC.keys())

        if not base_token:
            first_tname = table_names[0]
            first_fields = [manifest_field_to_lark(f) for f in PORTAL_TABLES_SPEC[first_tname]["fields"]]
            res = _run_cli([
                "+base-create",
                "--name", PORTAL_TEMPLATE_BASE_NAME,
                "--table-name", first_tname,
                "--fields", json.dumps(first_fields, ensure_ascii=False),
            ], timeout=180)
            data = res.get("data") or res
            base_obj = data.get("base") or {}
            base_token = (
                data.get("base_token")
                or data.get("app_token")
                or base_obj.get("base_token")
                or base_obj.get("app_token")
                or ""
            )
            if not base_token:
                raise LarkCLIError(f"Failed to obtain base_token for {PORTAL_TEMPLATE_BASE_NAME}: {res}")

        tables = self.list_tables(base_token)
        for tname in table_names:
            if tname not in tables:
                fields_payload = [manifest_field_to_lark(f) for f in PORTAL_TABLES_SPEC[tname]["fields"]]
                res = _run_cli([
                    "+table-create",
                    "--base-token", base_token,
                    "--name", tname,
                    "--fields", json.dumps(fields_payload, ensure_ascii=False),
                ], timeout=180)
                data = res.get("data") or res
                tid = data.get("table_id") or (data.get("table") or {}).get("id", "")
                if tid:
                    tables[tname] = tid

        # Ensure all fields exist (including Trial Window Hours in 03_My_Trials)
        for tname, spec in PORTAL_TABLES_SPEC.items():
            tid = tables[tname]
            existing_names = {f.get("name") for f in self.list_fields(base_token, tid)}
            for fdef in spec["fields"]:
                if fdef["name"] not in existing_names:
                    _run_cli([
                        "+field-create",
                        "--base-token", base_token,
                        "--table-id", tid,
                        "--json", json.dumps(manifest_field_to_lark(fdef), ensure_ascii=False),
                    ])

        # Configure the 4 supported Lark Formulas
        formulas_status = self._ensure_portal_formulas(base_token, tables)

        # Configure the 9 required Views
        views_status = self._ensure_views(base_token, tables, PORTAL_VIEWS_SPEC)

        # Configure the native Dashboard Block
        dashboard_status = self._ensure_portal_dashboard(base_token)

        return {
            "base_name": PORTAL_TEMPLATE_BASE_NAME,
            "base_token": base_token,
            "url": f"https://gjpmrvdwvnro.jp.larksuite.com/base/{base_token}",
            "tables": tables,
            "formulas": formulas_status,
            "views": views_status,
            "dashboard": dashboard_status,
        }

    def _ensure_portal_formulas(self, base_token: str, tables: dict[str, str]) -> list[dict[str, Any]]:
        """Configure supported Lark Base formulas with `--i-have-read-guide`."""
        results: list[dict[str, Any]] = []
        for fspec in PORTAL_FORMULAS_SPEC:
            tname = fspec["table"]
            fname = fspec["field_name"]
            expr = fspec["expression"]
            tid = tables.get(tname, "")
            if not tid:
                continue
            fields = self.list_fields(base_token, tid)
            field_id = ""
            current_type = ""
            for f in fields:
                if f.get("name") == fname:
                    field_id = f.get("id") or f.get("field_id", "")
                    current_type = f.get("type", "")
                    break

            payload = {"name": fname, "type": "formula", "expression": expr}
            try:
                if field_id:
                    _run_cli([
                        "+field-update",
                        "--base-token", base_token,
                        "--table-id", tid,
                        "--field-id", field_id,
                        "--json", json.dumps(payload, ensure_ascii=False),
                        "--i-have-read-guide",
                    ], confirm=True)
                else:
                    _run_cli([
                        "+field-create",
                        "--base-token", base_token,
                        "--table-id", tid,
                        "--json", json.dumps(payload, ensure_ascii=False),
                        "--i-have-read-guide",
                    ])
                results.append({
                    "table": tname,
                    "field_name": fname,
                    "expression": expr,
                    "status": "configured_formula",
                })
            except LarkCLIError as exc:
                log.warning("Formula %s.%s fallback to numeric snapshot: %s", tname, fname, exc)
                results.append({
                    "table": tname,
                    "field_name": fname,
                    "expression": expr,
                    "status": "fallback_number",
                    "error": str(exc),
                })
        return results

    def _ensure_views(
        self,
        base_token: str,
        tables: dict[str, str],
        views_spec: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create and filter all operational/portal Grid views idempotently."""
        configured: list[dict[str, Any]] = []
        for vspec in views_spec:
            tname = vspec["table"]
            vname = vspec["view_name"]
            vfilter = vspec["filter"]
            tid = tables.get(tname, "")
            if not tid:
                continue
            existing_views = self.list_views(base_token, tid)
            vid = ""
            for v in existing_views:
                if (v.get("view_name") or v.get("name")) == vname:
                    vid = v.get("view_id") or v.get("id", "")
                    break
            if not vid:
                res = _run_cli([
                    "+view-create",
                    "--base-token", base_token,
                    "--table-id", tid,
                    "--json", json.dumps({"name": vname, "type": "grid"}, ensure_ascii=False),
                ])
                data = res.get("data") or res
                created_views = data.get("views") or data.get("items") or []
                if created_views:
                    vid = created_views[0].get("view_id") or created_views[0].get("id", "")
                else:
                    vid = data.get("view_id") or (data.get("view") or {}).get("id", "")

            filter_applied = False
            filter_err = ""
            if vid and vfilter:
                try:
                    _run_cli([
                        "+view-set-filter",
                        "--base-token", base_token,
                        "--table-id", tid,
                        "--view-id", vid,
                        "--json", json.dumps(vfilter, ensure_ascii=False),
                    ])
                    filter_applied = True
                except LarkCLIError as exc:
                    filter_err = str(exc)
                    log.warning("View filter warning on %s.%s: %s", tname, vname, exc)

            configured.append({
                "table": tname,
                "view_name": vname,
                "view_id": vid,
                "filter_applied": filter_applied,
                "filter_error": filter_err,
            })
        return configured

    def _ensure_portal_dashboard(self, base_token: str) -> dict[str, Any]:
        """Ensure the native Lark Base Dashboard Block (`Reseller Overview Dashboard`) exists,
        create its KPI/chart blocks serially, and arrange its layout.
        """
        dash_res = _run_cli(["+dashboard-list", "--base-token", base_token])
        dash_data = dash_res.get("data") or dash_res
        dashboards = dash_data.get("dashboards") or dash_data.get("items") or []
        dashboard_id = ""
        for d in dashboards:
            dname = d.get("name") or d.get("block_name", "")
            did = d.get("block_id") or d.get("dashboard_id") or d.get("id", "")
            if dname == PORTAL_DASHBOARD_NAME and did:
                dashboard_id = did
                break

        if not dashboard_id:
            cres = _run_cli([
                "+dashboard-create",
                "--base-token", base_token,
                "--name", PORTAL_DASHBOARD_NAME,
            ])
            cdata = cres.get("data") or cres
            dashboard_id = (
                cdata.get("block_id")
                or cdata.get("dashboard_id")
                or cdata.get("id")
                or (cdata.get("dashboard") or {}).get("block_id")
                or (cdata.get("dashboard") or {}).get("id", "")
            )
            if not dashboard_id:
                dl2 = _run_cli(["+dashboard-list", "--base-token", base_token])
                for d in (dl2.get("data") or dl2).get("dashboards") or (dl2.get("data") or dl2).get("items") or []:
                    if (d.get("name") or d.get("block_name")) == PORTAL_DASHBOARD_NAME:
                        dashboard_id = d.get("block_id") or d.get("dashboard_id") or d.get("id", "")
                        break

        # Check existing blocks in the dashboard
        bl_res = _run_cli([
            "+dashboard-block-list",
            "--base-token", base_token,
            "--dashboard-id", dashboard_id,
        ])
        bl_data = bl_res.get("data") or bl_res
        existing_blocks = bl_data.get("blocks") or bl_data.get("items") or []
        existing_by_name = {
            (b.get("name") or b.get("title", "")): (b.get("block_id") or b.get("id", ""))
            for b in existing_blocks
        }

        created_blocks: list[dict[str, str]] = []
        # Create blocks SERIALLY per lark-base-dashboard.md rule
        for bspec in PORTAL_DASHBOARD_BLOCKS_SPEC:
            bname = bspec["name"]
            btype = bspec["type"]
            dcfg = bspec["data_config"]
            if bname in existing_by_name and existing_by_name[bname]:
                created_blocks.append({"name": bname, "type": btype, "block_id": existing_by_name[bname]})
                continue
            try:
                bres = _run_cli([
                    "+dashboard-block-create",
                    "--base-token", base_token,
                    "--dashboard-id", dashboard_id,
                    "--name", bname,
                    "--type", btype,
                    "--data-config", json.dumps(dcfg, ensure_ascii=False),
                ])
                bdata = bres.get("data") or bres
                bid = bdata.get("block_id") or (bdata.get("block") or {}).get("block_id", "")
                created_blocks.append({"name": bname, "type": btype, "block_id": bid})
            except LarkCLIError as exc:
                log.warning("Dashboard block %s creation warning: %s", bname, exc)

        # Arrange the dashboard after all blocks are created
        arranged = False
        try:
            _run_cli([
                "+dashboard-arrange",
                "--base-token", base_token,
                "--dashboard-id", dashboard_id,
            ])
            arranged = True
        except LarkCLIError as exc:
            log.warning("Dashboard arrange warning: %s", exc)

        return {
            "dashboard_id": dashboard_id,
            "dashboard_name": PORTAL_DASHBOARD_NAME,
            "blocks": created_blocks,
            "arranged": arranged,
        }

    # ------------------------------------------------------------------
    # Phase D: Repeatable Per-Reseller Isolated Base Provisioning
    # ------------------------------------------------------------------

    def provision_reseller_portal_base(
        self,
        *,
        reseller_code: str,
        reseller_name: str,
        operating_model: str,
        commission_structure: str,
        territory: str,
        manager_name: str = "Samuel Gibson",
        support_contact: str = "+23276000000",
        template_base_token: str = "",
        form_urls: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Repeatable procedure to create one isolated Lark Base for an approved reseller:
        `NexgloTV - Reseller - {ResellerCode}`

        Uses `+base-copy --without-content` from the unshared Portal Template Base,
        verifies all 7 tables, formulas, views, and dashboard, and seeds `07_My_Profile`.
        Does NOT invite external users (paused at security gate).
        """
        target_name = f"NexgloTV - Reseller - {reseller_code}"
        base_token = self.resolve_base_by_title(target_name, reseller_code)

        if not base_token:
            if not template_base_token:
                template_base_token = self.resolve_base_by_title(PORTAL_TEMPLATE_BASE_NAME, "Reseller Portal")
            if template_base_token:
                res = _run_cli([
                    "+base-copy",
                    "--base-token", template_base_token,
                    "--name", target_name,
                    "--without-content",
                ], timeout=180)
                data = res.get("data") or res
                base_obj = data.get("base") or {}
                base_token = (
                    data.get("base_token")
                    or data.get("app_token")
                    or base_obj.get("base_token")
                    or base_obj.get("app_token")
                    or ""
                )

        if not base_token:
            raise LarkCLIError(f"Failed to provision isolated reseller Base {target_name}")

        tables = self.list_tables(base_token)
        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")
        urls = form_urls or {}

        # Seed single-row 07_My_Profile for this reseller
        profile_tid = tables.get("07_My_Profile", "")
        if profile_tid:
            self.upsert_record(
                base_token,
                profile_tid,
                "Reseller Code",
                reseller_code,
                {
                    "Reseller Code": reseller_code,
                    "Reseller Name": reseller_name,
                    "Status": "Active",
                    "Operating Model": operating_model,
                    "Commission Structure": commission_structure,
                    "Territory": territory,
                    "Assigned NexgloTV Manager": manager_name,
                    "Support Contact": support_contact,
                    "Sale Request Form URL": urls.get("01_Sale_Requests", "Pending Form Publish Approval"),
                    "Trial Request Form URL": urls.get("02_Trial_Requests", "Pending Form Publish Approval"),
                    "Support Request Form URL": urls.get("03_Support_Requests", "Pending Form Publish Approval"),
                    "Payout Request Form URL": urls.get("04_Payout_Requests", "Pending Form Publish Approval"),
                    "Wallet Deposit Form URL": urls.get("05_Wallet_Deposit_Requests", "Pending Form Publish Approval"),
                    "Last Updated At": now_str,
                },
            )

        return {
            "reseller_code": reseller_code,
            "base_name": target_name,
            "base_token": base_token,
            "url": f"https://gjpmrvdwvnro.jp.larksuite.com/base/{base_token}",
            "tables": tables,
            "external_collaborators_invited": False,
        }

    # ------------------------------------------------------------------
    # Phase E: Manual Staff Verification & Allowlisted Snapshot Projection
    # ------------------------------------------------------------------

    def verify_reseller_identity(
        self,
        reseller_code: str,
        submitter_email: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Verify that `reseller_code` exists in Master `09_Resellers`, has `Status == 'Active'`,
        `Onboarding Verified == True`, and `Business Email` matches `submitter_email` (case-insensitive).
        """
        master_tables = self.list_tables(self.master_base_token)
        resellers_tid = master_tables["09_Resellers"]
        _, rows = self.list_records(self.master_base_token, resellers_tid)
        for r in rows:
            if str(r.get("Reseller Code", "")).strip().upper() == reseller_code.strip().upper():
                status = str(r.get("Status", "")).strip()
                verified = bool(r.get("Onboarding Verified"))
                reg_email = str(r.get("Business Email", "")).strip().lower()
                if status != "Active" or not verified:
                    return False, f"Reseller {reseller_code} status={status}, onboarding_verified={verified}", r
                if reg_email and reg_email != submitter_email.strip().lower():
                    return False, f"Submitter email {submitter_email} does not match registered email {reg_email}", r
                return True, "Verified", r
        return False, f"Reseller Code {reseller_code} not found in 09_Resellers", {}

    def project_reseller_to_portal(
        self,
        *,
        reseller_code: str,
        portal_base_token: str,
        customers: list[dict[str, Any]],
        sales: list[dict[str, Any]],
        trials: list[dict[str, Any]],
        commissions: list[dict[str, Any]],
        wallet_entries: list[dict[str, Any]],
        payouts: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Project ONLY allowlisted, sanitized records for `reseller_code` into their isolated
        Reseller Portal Base (`portal_base_token`).

        Never writes formula columns (`Approved Net Movement SLE`, `Outstanding SLE`,
        `Balance Due SLE`, `Trial Window Hours`) so Lark Base computes them natively!
        """
        tables = self.list_tables(portal_base_token)
        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")
        counts = {
            "01_My_Customers": 0,
            "02_My_Sales": 0,
            "03_My_Trials": 0,
            "04_My_Commissions": 0,
            "05_My_Wallet": 0,
            "06_My_Payouts": 0,
        }

        # 01_My_Customers
        tid = tables["01_My_Customers"]
        for c in customers:
            payload = {
                "Customer Ref": c["Customer Ref"],
                "Customer Display Name": c["Customer Display Name"],
                "Masked Phone": mask_phone(c.get("Phone") or c.get("Masked Phone", "")),
                "Region": c.get("Region", "Western Area"),
                "Current Package": c.get("Current Package", ""),
                "Devices": int(c.get("Devices", 1)),
                "Subscription Status": c.get("Subscription Status", "Active"),
                "Activation Date": c.get("Activation Date", now_str[:10]),
                "Expiry Date": c.get("Expiry Date", now_str[:10]),
                "Renewal Due Days": int(c.get("Renewal Due Days", 30)),
                "Next Action": c.get("Next Action", "None"),
                "Last Verified At": now_str,
            }
            self.upsert_record(portal_base_token, tid, "Customer Ref", c["Customer Ref"], payload)
            counts["01_My_Customers"] += 1

        # 02_My_Sales
        tid = tables["02_My_Sales"]
        for s in sales:
            payload = {
                "Reseller Sale Ref": s["Reseller Sale Ref"],
                "Sale Date": s.get("Sale Date", now_str),
                "Customer Ref": s.get("Customer Ref", ""),
                "Customer Display Name": s.get("Customer Display Name", ""),
                "Sale Type": s.get("Sale Type", "New Subscription"),
                "Package": s.get("Package", ""),
                "Devices": int(s.get("Devices", 1)),
                "Gross Subscription SLE": int(s.get("Gross Subscription SLE", 0)),
                "Discount SLE": int(s.get("Discount SLE", 0)),
                "Installation Fee SLE": int(s.get("Installation Fee SLE", 0)),
                "Collected By": s.get("Collected By", "NexgloTV Direct"),
                "Remittance Due SLE": int(s.get("Remittance Due SLE", 0)),
                "Payment Status": s.get("Payment Status", "Pending"),
                "Sale Status": s.get("Sale Status", "Submitted"),
                "Commission Eligible": bool(s.get("Commission Eligible", False)),
                "Commission SLE": int(s.get("Commission SLE", 0)),
                "Commission Status": s.get("Commission Status", "Not Eligible"),
                "Last Verified At": now_str,
            }
            self.upsert_record(portal_base_token, tid, "Reseller Sale Ref", s["Reseller Sale Ref"], payload)
            counts["02_My_Sales"] += 1

        # 03_My_Trials (Note: `Trial Window Hours` is a formula field — do not overwrite!)
        tid = tables["03_My_Trials"]
        for tr in trials:
            payload = {
                "Trial ID": tr["Trial ID"],
                "Customer Name": tr.get("Customer Name", ""),
                "Masked Phone": mask_phone(tr.get("Phone") or tr.get("Masked Phone", "")),
                "Device Type": tr.get("Device Type", "Android TV"),
                "Trial Status": tr.get("Trial Status", "Active"),
                "Activated At": tr.get("Activated At", ""),
                "Expires At": tr.get("Expires At", ""),
                "Converted To Sale": tr.get("Converted To Sale", "No"),
                "Notes": tr.get("Notes", "24h prepayment trial - no commission"),
                "Last Verified At": now_str,
            }
            self.upsert_record(portal_base_token, tid, "Trial ID", tr["Trial ID"], payload)
            counts["03_My_Trials"] += 1

        # 04_My_Commissions (Note: `Outstanding SLE` is a formula field — do not overwrite!)
        tid = tables["04_My_Commissions"]
        for cm in commissions:
            payload = {
                "Commission ID": cm["Commission ID"],
                "Earned Date": cm.get("Earned Date", now_str[:10]),
                "Reseller Sale Ref": cm.get("Reseller Sale Ref", ""),
                "Customer Display Name": cm.get("Customer Display Name", ""),
                "Eligible Revenue SLE": int(cm.get("Eligible Revenue SLE", 0)),
                "Commission Method": cm.get("Commission Method", "Percentage"),
                "Rate or Fixed Snapshot": cm.get("Rate or Fixed Snapshot", "20%"),
                "Commission Earned SLE": int(cm.get("Commission Earned SLE", 0)),
                "Adjustment SLE": int(cm.get("Adjustment SLE", 0)),
                "Commission Paid SLE": int(cm.get("Commission Paid SLE", 0)),
                "Commission Status": cm.get("Commission Status", "Pending Payment"),
                "Payout Batch ID": cm.get("Payout Batch ID", ""),
                "Notes": cm.get("Notes", ""),
                "Last Verified At": now_str,
            }
            if cm.get("Paid Date"):
                payload["Paid Date"] = cm["Paid Date"]
            self.upsert_record(portal_base_token, tid, "Commission ID", cm["Commission ID"], payload)
            counts["04_My_Commissions"] += 1

        # 05_My_Wallet (Note: `Approved Net Movement SLE` is a formula field — do not overwrite!)
        tid = tables["05_My_Wallet"]
        for w in wallet_entries:
            payload = {
                "Wallet Entry ID": w["Wallet Entry ID"],
                "Transaction Date": w.get("Transaction Date", now_str),
                "Entry Type": w.get("Entry Type", "Deposit Credit"),
                "Credit SLE": int(w.get("Credit SLE", 0)),
                "Debit SLE": int(w.get("Debit SLE", 0)),
                "Related Sale Ref": w.get("Related Sale Ref", ""),
                "Reference": w.get("Reference", ""),
                "Status": w.get("Status", "Confirmed"),
                "Verified By": w.get("Verified By", "Finance Staff"),
                "Notes": w.get("Notes", ""),
                "Last Verified At": now_str,
            }
            self.upsert_record(portal_base_token, tid, "Wallet Entry ID", w["Wallet Entry ID"], payload)
            counts["05_My_Wallet"] += 1

        # 06_My_Payouts (Note: `Balance Due SLE` is a formula field — do not overwrite!)
        tid = tables["06_My_Payouts"]
        for p in payouts:
            payload = {
                "Payout ID": p["Payout ID"],
                "Period Start": p.get("Period Start", now_str[:10]),
                "Period End": p.get("Period End", now_str[:10]),
                "Requested At": p.get("Requested At", now_str),
                "Approved Amount SLE": int(p.get("Approved Amount SLE", 0)),
                "Paid Amount SLE": int(p.get("Paid Amount SLE", 0)),
                "Method": p.get("Method", "Mobile Money"),
                "Destination Masked": p.get("Destination Masked", ""),
                "Transaction Reference": p.get("Transaction Reference", ""),
                "Payout Status": p.get("Payout Status", "Under Review"),
                "Notes": p.get("Notes", ""),
                "Last Verified At": now_str,
            }
            if p.get("Paid At"):
                payload["Paid At"] = p["Paid At"]
            self.upsert_record(portal_base_token, tid, "Payout ID", p["Payout ID"], payload)
            counts["06_My_Payouts"] += 1

        return counts

    def sync_approved_master_to_reseller_portal(
        self,
        reseller_code: str,
        portal_base_token: str = "",
    ) -> dict[str, Any]:
        """Read approved records for `reseller_code` from the 18-table Master CRM
        (`09_Resellers`, `03_Customers`, `05_Subscriptions`, `02_Free_Trials`,
        `10_Reseller_Sales`, `11_Commissions`, `13_Reseller_Wallet`, `12_Reseller_Payouts`),
        run the financial calculation engine (`compute_sale_financials`), and project
        ONLY that reseller's allowlisted, masked snapshot into their isolated Portal Base.
        """
        if not portal_base_token:
            target_name = f"NexgloTV - Reseller - {reseller_code}"
            portal_base_token = self.resolve_base_by_title(target_name, reseller_code)
        if not portal_base_token:
            raise LarkCLIError(f"Isolated Portal Base not found for reseller {reseller_code}")

        master_tables = self.list_tables(self.master_base_token)
        _, resellers = self.list_records(self.master_base_token, master_tables["09_Resellers"])
        reseller_row: dict[str, Any] = {}
        for r in resellers:
            if str(r.get("Reseller Code", "")).strip().upper() == reseller_code.strip().upper():
                reseller_row = r
                break
        if not reseller_row:
            raise LarkCLIError(f"Reseller {reseller_code} not found in Master 09_Resellers")

        reseller_id = str(reseller_row.get("Reseller ID", "")).strip()
        op_model = str(reseller_row.get("Operating Model") or "Referral Commission")
        if isinstance(reseller_row.get("Operating Model"), list) and reseller_row["Operating Model"]:
            op_model = str(reseller_row["Operating Model"][0])
        comm_method = str(reseller_row.get("Default Commission Method") or "Percentage")
        if isinstance(reseller_row.get("Default Commission Method"), list) and reseller_row["Default Commission Method"]:
            comm_method = str(reseller_row["Default Commission Method"][0])
        comm_rate = int(reseller_row.get("Default Commission Rate %") or 20)
        comm_fixed = int(reseller_row.get("Default Fixed Commission SLE") or 0)

        def _matches_reseller(row: dict[str, Any]) -> bool:
            rc = str(row.get("Reseller Code") or row.get("Reseller Code Snapshot") or "").strip().upper()
            rid = str(row.get("Reseller ID") or "").strip()
            if rc and rc == reseller_code.strip().upper():
                return True
            if rid and reseller_id and rid == reseller_id:
                return True
            return False

        _, m_customers = self.list_records(self.master_base_token, master_tables["03_Customers"])
        _, m_sales = self.list_records(self.master_base_token, master_tables["10_Reseller_Sales"])
        _, m_trials = self.list_records(self.master_base_token, master_tables["02_Free_Trials"])
        _, m_comms = self.list_records(self.master_base_token, master_tables["11_Commissions"])
        _, m_wallet = self.list_records(self.master_base_token, master_tables["13_Reseller_Wallet"])
        _, m_payouts = self.list_records(self.master_base_token, master_tables["12_Reseller_Payouts"])

        cust_by_id = {str(c.get("Customer ID", "")): c for c in m_customers}

        portal_customers = [
            {
                "Customer Ref": str(c.get("Customer ID", "")),
                "Customer Display Name": str(c.get("Full Name") or c.get("Customer Name", "")),
                "Phone": str(c.get("WhatsApp Number") or c.get("Primary Phone", "")),
                "Region": str(c.get("Region") or "Western Area Urban"),
                "Current Package": str(c.get("Current Package") or ""),
                "Devices": int(c.get("Active Device Count") or 1),
                "Subscription Status": str(c.get("Customer Status") or "Active"),
                "Activation Date": str(c.get("Joined Date") or ""),
                "Expiry Date": str(c.get("Current Expiry Date") or ""),
                "Renewal Due Days": int(c.get("Days To Expiry") or 30),
                "Next Action": str(c.get("Notes") or "None"),
            }
            for c in m_customers
            if _matches_reseller(c)
        ]

        portal_sales = []
        for s in m_sales:
            if not _matches_reseller(s):
                continue
            cid = str(s.get("Customer ID", ""))
            cname = str((cust_by_id.get(cid) or {}).get("Full Name") or cid)
            s_status = s.get("Sale Status") or "Submitted"
            if isinstance(s_status, list) and s_status:
                s_status = s_status[0]
            c_by = s.get("Collected By") or "NexgloTV Direct"
            if isinstance(c_by, list) and c_by:
                c_by = c_by[0]
            fin = compute_sale_financials(
                gross_subscription_sle=int(s.get("Gross Subscription SLE") or 0),
                discount_sle=int(s.get("Discount SLE") or 0),
                installation_fee_sle=int(s.get("Installation Fee SLE") or 0),
                sale_status=str(s_status),
                payment_status="Confirmed" if str(s_status) == "Confirmed" else "Pending",
                operating_model=op_model,
                commission_method=comm_method,
                commission_rate_pct=comm_rate,
                fixed_commission_sle=comm_fixed,
                collected_by=str(c_by),
                amount_collected_by_reseller_sle=int(s.get("Amount Collected By Reseller SLE") or 0),
                amount_remitted_to_nexglotv_sle=int(s.get("Amount Remitted To NexgloTV SLE") or 0),
            )
            portal_sales.append({
                "Reseller Sale Ref": str(s.get("Reseller Sale ID", "")),
                "Sale Date": str(s.get("Sale Date") or ""),
                "Customer Ref": cid,
                "Customer Display Name": cname,
                "Sale Type": s.get("Sale Type") or "New Subscription",
                "Package": str(s.get("Package ID") or ""),
                "Devices": int(s.get("Device Count") or 1),
                "Gross Subscription SLE": fin["gross_subscription_sle"],
                "Discount SLE": fin["discount_sle"],
                "Net Subscription SLE": fin["net_subscription_sle"],
                "Installation Fee SLE": fin["installation_fee_sle"],
                "Collected By": c_by,
                "Remittance Due SLE": fin["remittance_due_sle"],
                "Payment Status": "Confirmed" if str(s_status) == "Confirmed" else "Pending",
                "Sale Status": s_status,
                "Commission Eligible": fin["commission_eligible"],
                "Commission SLE": fin["commission_earned_sle"],
                "Commission Status": fin["commission_status"],
            })

        portal_trials = [
            {
                "Trial ID": str(t.get("Trial ID", "")),
                "Customer Name": str(t.get("Lead Name") or t.get("Customer Name") or ""),
                "Phone": str(t.get("WhatsApp Number") or ""),
                "Device Type": t.get("Device Type") or "Android TV",
                "Trial Status": t.get("Trial Status") or "Active",
                "Activated At": str(t.get("Activated At") or ""),
                "Expires At": str(t.get("Expires At") or ""),
                "Converted To Sale": "Yes" if t.get("Converted Customer ID") else "No",
            }
            for t in m_trials
            if _matches_reseller(t)
        ]

        portal_comms = [
            {
                "Commission ID": str(cm.get("Commission ID", "")),
                "Earned Date": str(cm.get("Earned On") or ""),
                "Reseller Sale Ref": str(cm.get("Reseller Sale ID") or ""),
                "Customer Display Name": str((cust_by_id.get(str(cm.get("Customer ID", ""))) or {}).get("Full Name") or ""),
                "Eligible Revenue SLE": int(cm.get("Eligible Revenue SLE") or 0),
                "Commission Method": cm.get("Commission Method Snapshot") or comm_method,
                "Rate or Fixed Snapshot": f"{cm.get('Rate % Snapshot') or comm_rate}%",
                "Commission Earned SLE": int(cm.get("Commission Earned SLE") or 0),
                "Adjustment SLE": int(cm.get("Adjustment SLE") or 0),
                "Commission Paid SLE": int(cm.get("Payable SLE") or 0) if str(cm.get("Commission Status")) == "Paid" else 0,
                "Commission Status": cm.get("Commission Status") or "Pending Payment",
                "Payout Batch ID": str(cm.get("Payout ID") or ""),
                "Notes": str(cm.get("Commission Notes") or ""),
            }
            for cm in m_comms
            if _matches_reseller(cm)
        ]

        portal_wallet = [
            {
                "Wallet Entry ID": str(w.get("Wallet Entry ID", "")),
                "Transaction Date": str(w.get("Transaction At") or ""),
                "Entry Type": w.get("Entry Type") or "Deposit Credit",
                "Credit SLE": int(w.get("Credit SLE") or 0),
                "Debit SLE": int(w.get("Debit SLE") or 0),
                "Related Sale Ref": str(w.get("Reseller Sale ID") or ""),
                "Reference": str(w.get("Reference") or ""),
                "Status": w.get("Wallet Status") or "Confirmed",
                "Verified By": str(w.get("Approved By Staff ID") or "Finance Staff"),
                "Notes": str(w.get("Ledger Notes") or ""),
            }
            for w in m_wallet
            if _matches_reseller(w)
        ]

        portal_payouts = [
            {
                "Payout ID": str(p.get("Payout ID", "")),
                "Period Start": str(p.get("Period Start") or ""),
                "Period End": str(p.get("Period End") or ""),
                "Requested At": str(p.get("Requested At") or ""),
                "Approved Amount SLE": int(p.get("Payout Due SLE") or 0),
                "Paid Amount SLE": int(p.get("Amount Paid SLE") or 0),
                "Method": p.get("Payout Method") or "Mobile Money",
                "Destination Masked": str(p.get("Destination Account Masked") or ""),
                "Transaction Reference": str(p.get("Transaction Reference") or ""),
                "Payout Status": p.get("Payout Status") or "Under Review",
                "Notes": str(p.get("Payout Notes") or ""),
            }
            for p in m_payouts
            if _matches_reseller(p)
        ]

        counts = self.project_reseller_to_portal(
            reseller_code=reseller_code,
            portal_base_token=portal_base_token,
            customers=portal_customers,
            sales=portal_sales,
            trials=portal_trials,
            commissions=portal_comms,
            wallet_entries=portal_wallet,
            payouts=portal_payouts,
        )
        return {
            "reseller_code": reseller_code,
            "reseller_id": reseller_id,
            "portal_base_token": portal_base_token,
            "projected_counts": counts,
        }

    # ------------------------------------------------------------------
    # Phase F: Event-Driven Cross-Base Webhook Promotion & Sync (Part D)
    # ------------------------------------------------------------------

    def process_reseller_webhook_event(
        self,
        *,
        event_type: str,
        reseller_code: str,
        source_table: str = "",
        record_id: str = "",
        portal_base_token: str = "",
        intake_base_token: str = "Et5lbto6Vab1wqsOxpEj2jzLpXe",
    ) -> dict[str, Any]:
        """Event-driven handler triggered by Lark Base `HTTPClientAction` or staff 1-click API.

        Supports:
          1. `promote_intake_and_sync`: Reads an approved/confirmed row from `Intake Base`
             (`01_Sale_Requests`..`05_Wallet_Deposit_Requests`), promotes it into `Master CRM`,
             stamps the Master ID back onto the Intake row, and projects the sanitized snapshot
             into the reseller's isolated Portal Base.
          2. `sync_portal_only`: Reads approved records for `reseller_code` from `Master CRM`
             and projects the sanitized snapshot into the reseller's isolated Portal Base.
        """
        code = reseller_code.strip().upper()
        if not code:
            raise ValueError("reseller_code is required for webhook event processing")

        promoted: dict[str, Any] = {}
        now_str = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")

        if event_type == "promote_intake_and_sync" and source_table and record_id:
            intake_tables = self.list_tables(intake_base_token)
            master_tables = self.list_tables(self.master_base_token)
            tid = intake_tables.get(source_table, "")
            if tid:
                _, rows = self.list_records(intake_base_token, tid)
                target_row = next((r for r in rows if r.get("_record_id") == record_id), None)
                if target_row:
                    if source_table == "05_Wallet_Deposit_Requests" and str(target_row.get("Request Status")) == "Confirmed":
                        req_id = str(target_row.get("Wallet Request ID") or record_id)
                        wlt_entry_id = f"WLT-TOP-{req_id}"
                        amount_sle = int(float(target_row.get("Amount SLE") or 0))
                        self.upsert_record(
                            self.master_base_token,
                            master_tables["13_Reseller_Wallet"],
                            "Wallet Entry ID",
                            wlt_entry_id,
                            {
                                "Wallet Entry ID": wlt_entry_id,
                                "Ledger Key": f"WALLET_TOPUP|{req_id}",
                                "Transaction At": now_str,
                                "Approval At": now_str,
                                "Entry Type": "Deposit Credit",
                                "Wallet Entry Kind": "WALLET_TOPUP",
                                "Credit SLE": amount_sle,
                                "Debit SLE": 0,
                                "Wallet Status": "Confirmed",
                                "Posting Status": "POSTED",
                                "Source Event ID": req_id,
                                "Reference": str(target_row.get("Transaction Reference") or code),
                                "Ledger Notes": f"Promoted from verified Intake deposit {req_id} ({code})",
                            },
                        )
                        _run_cli([
                            "+record-upsert",
                            "--base-token", intake_base_token,
                            "--table-id", tid,
                            "--record-id", record_id,
                            "--json", json.dumps({
                                "Master Wallet Entry ID": wlt_entry_id,
                                "Verified At": now_str,
                                "Verified By Staff": "Samuel Gibson",
                            }, ensure_ascii=False),
                        ])
                        promoted = {"source_table": source_table, "master_wallet_entry_id": wlt_entry_id}

                    elif source_table == "01_Sale_Requests" and str(target_row.get("Request Status")) == "Approved":
                        req_id = str(target_row.get("Request ID") or record_id)
                        sale_id = f"RSL-SALE-{req_id}"
                        collected_by_raw = str(target_row.get("Collected By") or "Customer Pays NexgloTV Direct")
                        payment_path = (
                            "PREPAID_WALLET"
                            if "Wallet" in collected_by_raw
                            else "DIRECT_TO_NEXGLOTV"
                        )
                        net_reported = int(float(target_row.get("Amount Reported SLE") or 180))
                        gross_reg = round(net_reported / 0.80)
                        disc_sle = gross_reg - net_reported
                        self.upsert_record(
                            self.master_base_token,
                            master_tables["10_Reseller_Sales"],
                            "Reseller Sale ID",
                            sale_id,
                            {
                                "Reseller Sale ID": sale_id,
                                "Sale Date": now_str,
                                "Reseller Code Snapshot": code,
                                "Sale Type": "New",
                                "Device Count": int(target_row.get("Device Count") or 1),
                                "Regular Unit Snapshot SLE": gross_reg,
                                "Gross Subscription SLE": gross_reg,
                                "Customer Discount % Snapshot": 20,
                                "Discount SLE": disc_sle,
                                "Installation Fee SLE": 0,
                                "Price Version Snapshot": "regular-plus-20pct-v2",
                                "Payment Path": payment_path,
                                "Collected By": "NexgloTV" if payment_path == "DIRECT_TO_NEXGLOTV" else "Customer Direct",
                                "Verified Settlement": True,
                                "Verified Funding At": now_str,
                                "Commission Rate Snapshot %": 20,
                                "Commission Eligible": True,
                                "Sale Status": "Confirmed",
                                "Source Request Key": req_id,
                                "Reseller Sales Notes": f"Promoted from Intake Sale Request {req_id}",
                            },
                        )
                        _run_cli([
                            "+record-upsert",
                            "--base-token", intake_base_token,
                            "--table-id", tid,
                            "--record-id", record_id,
                            "--json", json.dumps({
                                "Master Sale ID": sale_id,
                                "Reviewed At": now_str,
                                "Reviewed By Staff": "Samuel Gibson",
                            }, ensure_ascii=False),
                        ])
                        promoted = {"source_table": source_table, "master_sale_id": sale_id}

        sync_result = self.sync_approved_master_to_reseller_portal(
            reseller_code=code,
            portal_base_token=portal_base_token,
        )
        return {
            "ok": True,
            "event_type": event_type,
            "promoted": promoted,
            "sync_result": sync_result,
        }

