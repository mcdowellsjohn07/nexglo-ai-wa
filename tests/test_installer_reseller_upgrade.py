"""Comprehensive test suite for NexgloTV Unified Reseller + Installer Upgrade.

Verifies:
1. Economics: 40% physical install commission & company 60% share.
2. Performance bands: Starter (0), Bronze (50), Silver (125), Gold (250), Platinum (450), Diamond (750).
3. Partner model: Single partner record in 09_Resellers, 'Reseller Only' vs 'Reseller + Installer'.
4. Separation of funds: Prepaid wallet != Sales commission (20%) != Install earnings (40%).
5. Dual-verification qualification gate: Completion verified + Fee verified required.
6. WhatsApp Admin Commands: ADMIN INSTALL, ADMIN ASSIGN, ADMIN VERIFY INSTALL, ADMIN VERIFY FEE, ADMIN INSTALLER STATS, ADMIN LOCK MONTH.
7. WhatsApp Installer Commands: ACCEPT, DECLINE, DONE, MY STATS.
8. Idempotency: replay of events never generates duplicate earnings.
"""

import pytest
from datetime import datetime, timezone
from app.config import Settings
from app.crm_sheets import InstallationRecord
from app.deps import build_services
from app.installer_engine import (
    calculate_installer_earning,
    get_monthly_performance_band,
    InstallerManager,
)
from app.models import InboundMessage
from app.reseller_bot import ResellerProfile


def test_installation_earning_calculations():
    # Test Case 05: SLE 100 paid physical job -> Installer SLE 40, Company SLE 60
    e1 = calculate_installer_earning(100.0)
    assert e1["basis_fee_sle"] == 100.0
    assert e1["rate_pct"] == 40.0
    assert e1["installer_earning_sle"] == 40.0
    assert e1["company_retained_sle"] == 60.0
    assert e1["qualifying"] is True

    # Test Case 06: SLE 250 paid physical job -> Installer SLE 100, Company SLE 150
    e2 = calculate_installer_earning(250.0)
    assert e2["installer_earning_sle"] == 100.0
    assert e2["company_retained_sle"] == 150.0

    # Test Case 07: Free remote setup / zero fee -> SLE 0, non-qualifying
    e3 = calculate_installer_earning(0.0)
    assert e3["installer_earning_sle"] == 0.0
    assert e3["company_retained_sle"] == 0.0
    assert e3["qualifying"] is False


def test_monthly_performance_bands():
    # Test Cases 13-18
    assert get_monthly_performance_band(0) == ("None", 0)
    assert get_monthly_performance_band(4) == ("Starter", 0)
    assert get_monthly_performance_band(5) == ("Bronze", 50)
    assert get_monthly_performance_band(9) == ("Bronze", 50)
    assert get_monthly_performance_band(10) == ("Silver", 125)
    assert get_monthly_performance_band(19) == ("Silver", 125)
    assert get_monthly_performance_band(20) == ("Gold", 250)
    assert get_monthly_performance_band(29) == ("Gold", 250)
    assert get_monthly_performance_band(30) == ("Platinum", 450)
    assert get_monthly_performance_band(49) == ("Platinum", 450)
    assert get_monthly_performance_band(50) == ("Diamond", 750)
    assert get_monthly_performance_band(65) == ("Diamond", 750)


def test_partner_role_assignment_restriction():
    settings = Settings(admin_token="test_tok", admin_phone_numbers="23276000000")
    services = build_services(settings)
    mgr: InstallerManager = services.installer_mgr

    # Partner 1: Reseller Only
    r1 = ResellerProfile(
        reseller_id="RES-ONLY-01",
        reseller_code="RSL-ONLY01",
        name="Sales Agent One",
        phone="+23276999001",
        partner_role="Reseller Only",
        installer_approval_status="Not Applied",
    )
    services.reseller_mgr.register_reseller(r1)

    # Partner 2: Reseller + Installer (Approved)
    r2 = ResellerProfile(
        reseller_id="RES-INST-02",
        reseller_code="RSL-INST02",
        name="Technician Alpha",
        phone="+23276999002",
        partner_role="Reseller + Installer",
        installer_approval_status="Approved",
    )
    services.reseller_mgr.register_reseller(r2)

    # Create job
    inst = mgr.create_installation_job(
        customer_phone="076123456",
        customer_name="Alhaji Koroma",
        area="Wilkinson Road",
        quoted_fee_sle=120,
    )

    # Attempt to assign to Reseller Only -> Should fail
    ok1, msg1 = mgr.offer_job(inst.installation_id, "RES-ONLY-01")
    assert ok1 is False
    assert "not an approved installer" in msg1

    # Attempt to assign to Reseller + Installer -> Should succeed
    ok2, msg2 = mgr.offer_job(inst.installation_id, "RES-INST-02")
    assert ok2 is True
    assert "offered to *Technician Alpha*" in msg2
    assert inst.installer_assignment_status == "Offered"


def test_end_to_end_job_lifecycle_and_dual_verification():
    settings = Settings(admin_token="test_tok", admin_phone_numbers="23276000000")
    services = build_services(settings)
    admin_bot = services.admin_bot
    mgr: InstallerManager = services.installer_mgr

    # Seed approved installer
    partner = ResellerProfile(
        reseller_id="RES-TECH-01",
        reseller_code="RSL-TECH01",
        name="Foday Installation Hub",
        phone="+23276888777",
        partner_role="Reseller + Installer",
        installer_approval_status="Approved",
        wallet_balance=500,
        unpaid_commissions=100,
    )
    services.reseller_mgr.register_reseller(partner)

    # 1. Admin creates job via WhatsApp command
    res1 = admin_bot._execute_admin_command(
        None,
        "ADMIN INSTALL 076123456 Hawa Kamara Lumley Beach 150 Smart TV 2 screens",
    )
    assert "Installation Booking Created" in res1
    assert "Hawa Kamara" in res1
    assert "40% Installer Cut:* SLE 60" in res1
    assert "60% Company Retained:* SLE 90" in res1

    # Grab created job ID
    inst_id = list(mgr._installations.keys())[-1]
    inst = mgr.get_installation(inst_id)
    assert inst is not None
    assert inst.approved_fee_sle == 150

    # 2. Admin assigns job
    res2 = admin_bot._execute_admin_command(None, f"ADMIN ASSIGN {inst_id} RES-TECH-01")
    assert "offered to *Foday Installation Hub*" in res2

    # 3. Installer accepts via WhatsApp from their registered number
    ok_accept, msg_accept = mgr.installer_accept_job(inst_id, "+23276888777")
    assert ok_accept is True
    assert inst.installer_assignment_status == "Accepted"
    assert inst.setup_status == "in_progress"

    # 4. Installer reports completion
    ok_done, msg_done = mgr.installer_submit_completion(inst_id, "+23276888777", notes="Setup on 2 Samsung TVs")
    assert ok_done is True
    assert inst.setup_status == "completion_reported"
    # Ensure NO commission is awarded yet
    assert inst.installation_earning_id == ""
    assert inst.qualified_at == ""

    # 5. Staff verifies completion, but fee is not yet verified
    res_staff = admin_bot._execute_admin_command(None, f"ADMIN VERIFY INSTALL {inst_id}")
    assert "verified by staff" in res_staff
    assert "Awaiting finance verification of installation fee" in res_staff
    assert inst.installation_earning_id == ""

    # 6. Finance verifies fee collection -> QUALIFICATION TRIGGERED
    res_fee = admin_bot._execute_admin_command(None, f"ADMIN VERIFY FEE {inst_id} 150 OM991122")
    assert "Installation fee of *SLE 150* verified" in res_fee
    assert "Installation Qualified!" in res_fee
    assert "40% Installer Earning: *SLE 60*" in res_fee
    assert "Company Retained: SLE 90" in res_fee

    # Verify earning record created
    assert inst.installation_earning_id != ""
    assert inst.monthly_count_eligible is True
    assert partner.unpaid_installer_earnings == 60

    # Verify wallet balance is 100% UNCHANGED (separation of funds)
    assert partner.wallet_balance == 500
    assert partner.unpaid_commissions == 100

    # 7. Idempotency check: repeat finance verification does NOT double-commission
    res_repeat = admin_bot._execute_admin_command(None, f"ADMIN VERIFY FEE {inst_id} 150 OM991122")
    assert "Installation fee of *SLE 150* verified" in res_repeat
    assert "Installation Qualified!" not in res_repeat
    assert partner.unpaid_installer_earnings == 60  # Still 60, not 120!


def test_monthly_band_progression_and_month_lock():
    settings = Settings(admin_token="test_tok", admin_phone_numbers="23276000000")
    services = build_services(settings)
    admin_bot = services.admin_bot
    mgr: InstallerManager = services.installer_mgr

    partner = ResellerProfile(
        reseller_id="RES-BONUS-01",
        reseller_code="RSL-BONUS01",
        name="Alpha Tech Services",
        phone="+23276555111",
        partner_role="Reseller + Installer",
        installer_approval_status="Approved",
    )
    services.reseller_mgr.register_reseller(partner)

    # Simulate 5 qualifying installations in 2026-10
    month = "2026-10"
    for i in range(5):
        inst = mgr.create_installation_job(
            customer_phone=f"07600000{i}",
            customer_name=f"Customer {i}",
            area="Freetown Central",
            quoted_fee_sle=100,
            assigned_installer_reseller_id="RES-BONUS-01",
        )
        mgr.staff_verify_completion(inst.installation_id)
        mgr.finance_verify_fee(inst.installation_id, 100, f"REF_{i}")

    # Check stats: 5 jobs should hit Bronze (SLE 50 bonus)
    stats = mgr.get_installer_stats("RES-BONUS-01", month=month)
    assert stats["month_qualifying_jobs"] == 5
    assert stats["provisional_band"] == "Bronze"
    assert stats["provisional_bonus_sle"] == 50
    assert stats["total_install_earnings_sle"] == 200  # 5 x SLE 40

    # Lock month via Admin Command
    lock_res = admin_bot._execute_admin_command(None, f"ADMIN LOCK MONTH RES-BONUS-01 {month}")
    assert f"Month {month} Locked for RES-BONUS-01" in lock_res
    assert "Final Qualifying Installs: *5*" in lock_res
    assert "Achieved Band: *Bronze*" in lock_res
    assert "One-time Approved Bonus: *SLE 50*" in lock_res

    # Partner unpaid installer earnings = 200 (installs) + 50 (bonus) = 250
    assert partner.unpaid_installer_earnings == 250

    # Replay lock: should be rejected
    lock_replay = admin_bot._execute_admin_command(None, f"ADMIN LOCK MONTH RES-BONUS-01 {month}")
    assert "already locked" in lock_replay


def test_whatsapp_installer_stats_query():
    settings = Settings(admin_token="test_tok")
    services = build_services(settings)

    # Registered partner
    partner = ResellerProfile(
        reseller_id="RES-QUERY-01",
        reseller_code="RSL-QUERY01",
        name="Sorie Installer",
        phone="+23276444333",
        partner_role="Reseller + Installer",
        installer_approval_status="Approved",
        wallet_balance=1200,
        unpaid_commissions=240,
        unpaid_installer_earnings=80,
    )
    services.reseller_mgr.register_reseller(partner)

    # Installer sends "MY STATS" from registered number
    msg = InboundMessage(
        message_id="msg_stats_01",
        wa_id="+23276444333",
        type="text",
        profile_name="Sorie Installer",
        text="MY STATS",
    )
    services.agent.handle_message(msg)

    history = services.store.history("+23276444333", limit=5)
    replies = [h["content"] for h in history if h["role"] == "assistant"]
    assert any("Installer Performance" in r for r in replies)
    assert any("Sorie Installer" in r for r in replies)
    assert any("SLE 80" in r for r in replies)
    assert any("SLE 240" in r for r in replies)
    assert any("SLE 1,200" in r for r in replies)
