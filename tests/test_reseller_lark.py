"""Unit tests for the NexgloTV Independent Reseller Management System (`app/reseller_lark.py`)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.reseller_lark import (
    INTAKE_BASE_NAME,
    INTAKE_TABLES_SPEC,
    INTAKE_VIEWS_SPEC,
    MASTER_CRM_BASE_TOKEN,
    PORTAL_DASHBOARD_BLOCKS_SPEC,
    PORTAL_FORMULAS_SPEC,
    PORTAL_TABLES_SPEC,
    PORTAL_TEMPLATE_BASE_NAME,
    PORTAL_VIEWS_SPEC,
    V2_ALLOWED_PAYMENT_PATHS,
    V2_DISABLED_MODELS,
    V2_PACKAGES_CATALOG,
    compute_sale_financials,
    compute_trial_window,
    compute_v2_package_sale,
    manifest_field_to_lark,
    mask_phone,
)


def test_master_crm_token_and_base_names():
    assert MASTER_CRM_BASE_TOKEN == "E8jObNOAeaZqUHsyxRHjR9VcpBg"
    assert INTAKE_BASE_NAME == "NexgloTV - Reseller Intake (PRIVATE)"
    assert PORTAL_TEMPLATE_BASE_NAME == "NexgloTV - Reseller Portal TEMPLATE (UNSHARED)"


def test_intake_tables_and_form_security_boundaries():
    expected_tables = [
        "01_Sale_Requests",
        "02_Trial_Requests",
        "03_Support_Requests",
        "04_Payout_Requests",
        "05_Wallet_Deposit_Requests",
        "06_Reseller_Applications",
    ]
    assert list(INTAKE_TABLES_SPEC.keys()) == expected_tables

    for tname, spec in INTAKE_TABLES_SPEC.items():
        all_field_names = {f["name"] for f in spec["fields"]}
        admin_only = set(spec["admin_only_fields"])
        # Every admin_only field must exist in the table schema
        assert admin_only.issubset(all_field_names), f"Missing admin fields in {tname}"
        # No admin_only field may be marked required_on_form
        req_on_form = {f["name"] for f in spec["fields"] if f.get("required_on_form")}
        assert admin_only.isdisjoint(req_on_form), f"Admin field marked required_on_form in {tname}"
        # Master IDs and Status fields must be hidden from forms
        for fn in all_field_names:
            if fn.startswith("Master ") or fn in ("Request Status", "Reviewed By Staff", "Verified By Staff"):
                assert fn in admin_only, f"{tname}.{fn} must be hidden from respondent form"


def test_portal_template_tables_views_formulas_and_dashboard():
    expected_portal_tables = [
        "01_My_Customers",
        "02_My_Sales",
        "03_My_Trials",
        "04_My_Commissions",
        "05_My_Wallet",
        "06_My_Payouts",
        "07_My_Profile",
    ]
    assert list(PORTAL_TABLES_SPEC.keys()) == expected_portal_tables
    assert len(PORTAL_FORMULAS_SPEC) == 5
    assert len(PORTAL_VIEWS_SPEC) == 9
    assert len(INTAKE_VIEWS_SPEC) == 6
    assert len(PORTAL_DASHBOARD_BLOCKS_SPEC) >= 10

    # Ensure no portal table contains Master link fields or raw unmasked phone fields
    for tname, spec in PORTAL_TABLES_SPEC.items():
        for f in spec["fields"]:
            lark_f = manifest_field_to_lark(f)
            assert lark_f["type"] != "link", f"Portal table {tname} must not contain cross-Base links"
            assert "Password" not in f["name"]


def test_mask_phone_privacy():
    assert mask_phone("+23276123456") == "+232***456"
    assert mask_phone("23278987654") == "+232***654"
    assert mask_phone("123") == "***"


def test_compute_trial_window_24h_and_zero_commission():
    act = datetime(2026, 10, 12, 10, 30, tzinfo=timezone.utc)
    res = compute_trial_window(act)
    assert res["activated_at"] == "2026/10/12 10:30"
    assert res["expires_at"] == "2026/10/13 10:30"
    assert res["duration_hours"] == 24
    assert res["commission_eligible"] is False
    assert res["commission_earned_sle"] == 0


def test_compute_sale_financials_three_models_and_rules():
    # 1. Free Trial -> strictly 0 commission
    trial_fin = compute_sale_financials(
        gross_subscription_sle=250,
        sale_status="Trial",
        payment_status="Pending",
    )
    assert trial_fin["commission_eligible"] is False
    assert trial_fin["commission_earned_sle"] == 0
    assert trial_fin["commission_status"] == "Not Eligible"

    # 2. Referral Commission model with Pending Payment -> Pending Payment (not yet Approved)
    pending_fin = compute_sale_financials(
        gross_subscription_sle=300,
        discount_sle=50,
        installation_fee_sle=100,
        sale_status="Payment Pending",
        payment_status="Pending",
        operating_model="Referral Commission",
        commission_method="Percentage",
        commission_rate_pct=10,
    )
    assert pending_fin["net_subscription_sle"] == 250
    assert pending_fin["eligible_revenue_sle"] == 250  # excludes 100 installation fee
    assert pending_fin["commission_eligible"] is False
    assert pending_fin["commission_earned_sle"] == 25
    assert pending_fin["commission_status"] == "Pending Payment"

    # 3. Referral Commission model with Confirmed Payment -> Approved
    confirmed_fin = compute_sale_financials(
        gross_subscription_sle=300,
        discount_sle=50,
        installation_fee_sle=100,
        sale_status="Confirmed",
        payment_status="Confirmed",
        operating_model="Referral Commission",
        commission_method="Percentage",
        commission_rate_pct=10,
    )
    assert confirmed_fin["net_subscription_sle"] == 250
    assert confirmed_fin["commission_eligible"] is True
    assert confirmed_fin["commission_earned_sle"] == 25
    assert confirmed_fin["commission_status"] == "Approved"

    # 4. Collect and Remit model with unremitted cash -> Held until remitted
    collect_held = compute_sale_financials(
        gross_subscription_sle=250,
        discount_sle=0,
        sale_status="Confirmed",
        payment_status="Confirmed",
        operating_model="Collect and Remit",
        commission_method="Fixed",
        fixed_commission_sle=30,
        collected_by="Reseller",
        amount_collected_by_reseller_sle=250,
        amount_remitted_to_nexglotv_sle=100,
    )
    assert collect_held["remittance_due_sle"] == 150
    assert collect_held["commission_earned_sle"] == 30
    assert collect_held["commission_status"] == "Held"

    # Once remitted in full -> Approved
    collect_remitted = compute_sale_financials(
        gross_subscription_sle=250,
        discount_sle=0,
        sale_status="Confirmed",
        payment_status="Confirmed",
        operating_model="Collect and Remit",
        commission_method="Fixed",
        fixed_commission_sle=30,
        collected_by="Reseller",
        amount_collected_by_reseller_sle=250,
        amount_remitted_to_nexglotv_sle=250,
    )
    assert collect_remitted["remittance_due_sle"] == 0
    assert collect_remitted["commission_status"] == "Approved"

    # 5. Refunded sale -> Reversed
    refund_fin = compute_sale_financials(
        gross_subscription_sle=250,
        sale_status="Refunded",
        payment_status="Refunded",
    )
    assert refund_fin["commission_eligible"] is False
    assert refund_fin["commission_earned_sle"] == 0
    assert refund_fin["commission_status"] == "Reversed"


def test_v2_packages_catalog_and_pricing_invariants():
    import pytest

    assert len(V2_PACKAGES_CATALOG) == 16
    assert V2_ALLOWED_PAYMENT_PATHS == ("DIRECT_TO_NEXGLOTV", "PREPAID_WALLET")
    assert "COLLECT_AND_REMIT" in V2_DISABLED_MODELS

    # T01: 1 device Monthly (PKG-01) -> Regular 225, Discount 45, Net 180, Comm 36, Retained 144
    t01 = compute_v2_package_sale(package_id="PKG-01", device_count=1, verified_settlement=True, activated=True)
    assert t01["gross_subscription_sle"] == 225.0
    assert t01["customer_discount_sle"] == 45.0
    assert t01["net_subscription_sle"] == 180.0
    assert t01["commission_earned_sle"] == 36.0
    assert t01["company_retained_before_costs_sle"] == 144.0
    assert t01["remittance_due_sle"] == 0.0

    # T02: 2 devices Monthly (PKG-02) -> Regular 400, Discount 80, Net 320, Comm 64, Retained 256
    t02 = compute_v2_package_sale(package_id="PKG-02", device_count=2, verified_settlement=True, activated=True)
    assert t02["gross_subscription_sle"] == 400.0
    assert t02["customer_discount_sle"] == 80.0
    assert t02["net_subscription_sle"] == 320.0
    assert t02["commission_earned_sle"] == 64.0
    assert t02["company_retained_before_costs_sle"] == 256.0

    # T03: 5 devices Monthly (PKG-04) -> Regular 750, Discount 150, Net 600, Comm 120, Retained 480
    t03 = compute_v2_package_sale(package_id="PKG-04", device_count=5, verified_settlement=True, activated=True)
    assert t03["gross_subscription_sle"] == 750.0
    assert t03["customer_discount_sle"] == 150.0
    assert t03["net_subscription_sle"] == 600.0
    assert t03["commission_earned_sle"] == 120.0
    assert t03["company_retained_before_costs_sle"] == 480.0

    # T06: Unverified direct payment -> Net 180, Commission 0
    t06 = compute_v2_package_sale(package_id="PKG-01", device_count=1, verified_settlement=False, activated=False)
    assert t06["net_subscription_sle"] == 180.0
    assert t06["commission_base_sle"] == 0.0
    assert t06["commission_earned_sle"] == 0.0

    # T09: Wallet paid activation with 50 SLE installation fee -> Commission still 36 (excludes install fee)
    t09 = compute_v2_package_sale(
        package_id="PKG-01",
        device_count=1,
        payment_path="PREPAID_WALLET",
        verified_settlement=True,
        activated=True,
        installation_fee_sle=50.0,
        wallet_available_sle=500.0,
    )
    assert t09["net_subscription_sle"] == 180.0
    assert t09["wallet_debit_sle"] == 180.0
    assert t09["commission_base_sle"] == 180.0
    assert t09["commission_earned_sle"] == 36.0
    assert t09["customer_invoice_sle"] == 230.0

    # T11: Collect-and-Remit rejected for new V2 transactions
    with pytest.raises(ValueError, match="Unsupported or retired payment_path"):
        compute_v2_package_sale(package_id="PKG-01", device_count=1, payment_path="COLLECT_AND_REMIT")

    # T12: Insufficient wallet balance rejected
    with pytest.raises(ValueError, match="Insufficient prepaid wallet balance"):
        compute_v2_package_sale(
            package_id="PKG-01",
            device_count=1,
            payment_path="PREPAID_WALLET",
            wallet_available_sle=100.0,
        )


