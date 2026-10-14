"""Tests for NexgloTV Lark Base CRM enhancements and AutomationRunner."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.crm_lark import LarkBaseCRMProvider
from app.crm_sheets import CustomerRecord, TrialRecord
from app.deps import build_services
from app.main import create_app
from app.nexglo_lark_schema import map_record, map_value, package_id_for
from app.nexglo_state import State


class MutableClock:
    def __init__(self, initial: datetime):
        self.now = initial

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


def _make_services(tmp_path: Path, clock: MutableClock):
    settings = Settings(
        admin_token="test-secret-token",
        dry_run_flag=True,
        crm_provider="mock",
    )
    return build_services(settings, db_path=tmp_path / "test.sqlite", clock=clock)


# ------------------------------------------------------------------ Schema & Lark CRM tests
def test_package_id_for_all_tiers():
    assert package_id_for(1, 1) == "PKG-01"
    assert package_id_for(1, 2) == "PKG-02"
    assert package_id_for(1, 3) == "PKG-03"
    assert package_id_for(1, 4) == "PKG-04"
    assert package_id_for(1, 6) == "PKG-04"
    assert package_id_for(3, 1) == "PKG-05"
    assert package_id_for(6, 2) == "PKG-10"
    assert package_id_for(12, 3) == "PKG-15"
    assert package_id_for(12, 5) == "PKG-16"
    assert package_id_for(0, 1) == ""
    assert package_id_for(2, 1) == ""


def test_map_value_select_guards_and_mappings():
    # Free trials
    assert map_value("02_Free_Trials", "Trial Status", "pending") == "Requested"
    assert map_value("02_Free_Trials", "Trial Status", "offered") == "Approved"
    assert map_value("02_Free_Trials", "Trial Status", "revoked") == "Revoked"
    # Activities outcomes
    assert map_value("17_Activities", "Outcome", "setup_credentials") == "Need Follow-up"
    assert map_value("17_Activities", "Outcome", "done") == "Resolved"
    # Unmapped select value falls back to Other when Other is an option, or None
    assert map_value("01_Leads", "Device Type", "roku") == "Other"
    assert map_value("01_Leads", "Device Type", "totally_unknown_device") == "Other"
    assert map_value("02_Free_Trials", "Trial Status", "invalid_status") is None

    rec = map_record(
        "02_Free_Trials",
        {"Trial ID": "TRIAL-1", "Trial Status": "pending", "Duplicate Check": "invalid"},
    )
    assert rec == {"Trial ID": "TRIAL-1", "Trial Status": "Requested"}


def test_lark_resolve_links_converts_keys_and_strips_invalid():
    provider = LarkBaseCRMProvider(base_token="basetok", auto_create=False)
    provider._table_ids = {
        "01_Leads": "tblLeads",
        "02_Free_Trials": "tblTrials",
        "03_Customers": "tblCusts",
        "04_Packages": "tblPkgs",
        "15_Staff": "tblStaff",
    }
    provider._cache_loaded = {"01_Leads", "03_Customers", "04_Packages", "15_Staff"}
    provider._id_cache = {
        "01_Leads": {"LEAD-001": "recLead001"},
        "03_Customers": {},
        "04_Packages": {"PKG-01": "recPkg01"},
        "15_Staff": {"STAFF-01": "recStaff01"},
    }

    raw = {
        "Trial ID": "TRIAL-001",
        "Lead ID": "LEAD-001",
        "Package ID": "PKG-01",
        "Approved By Staff ID": "staff",
        "Converted Customer ID": "NON-EXISTENT-CUST",
    }
    with patch("app.crm_lark._run_cli", return_value={"data": {"records": []}}):
        resolved = provider._resolve_links("02_Free_Trials", raw)

    assert resolved["Lead ID"] == [{"id": "recLead001"}]
    assert resolved["Package ID"] == [{"id": "recPkg01"}]
    assert resolved["Approved By Staff ID"] == [{"id": "recStaff01"}]
    assert "Converted Customer ID" not in resolved


def test_lark_ensure_base_parses_title_resolve_candidates():
    from app.nexglo_lark_schema import FIELD_SCHEMAS

    fake_resolve = {
        "ok": True,
        "data": {
            "candidates": [
                {"title": "NexgloTV CRM", "base_token": "E8jObNOAeaZqUHsyxRHjR9VcpBg"}
            ],
            "total": 1,
        },
    }
    fake_tables = {
        "ok": True,
        "data": {
            "tables": [{"id": f"tbl_{i}", "name": name} for i, name in enumerate(FIELD_SCHEMAS.keys())]
        },
    }
    with patch("app.crm_lark._run_cli", side_effect=[fake_resolve, fake_tables]):
        provider = LarkBaseCRMProvider(base_token="", auto_create=True)
        assert provider.base_token == "E8jObNOAeaZqUHsyxRHjR9VcpBg"
        assert provider._table_ids["01_Leads"] == "tbl_0"


# ------------------------------------------------------------------ AutomationRunner tests
def test_automation_stalled_quote_in_and_out_of_window(tmp_path: Path):
    t0 = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)
    clock = MutableClock(t0)
    svc = _make_services(tmp_path, clock)

    # Contact 1: in window (3 hours old)
    svc.store.ensure_conversation("23276000001", "Alice")
    svc.store.set_state("23276000001", State.PACKAGE_SELECTED)
    svc.store.touch_user("23276000001", (t0 - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"))

    # Contact 2: outside 24h window (30 hours old)
    svc.store.ensure_conversation("23276000002", "Bob")
    svc.store.set_state("23276000002", State.PRICES_SENT)
    svc.store.touch_user("23276000002", (t0 - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S"))

    # Contact 3: opted out
    svc.store.ensure_conversation("23276000003", "Charlie")
    svc.store.set_state("23276000003", State.PRICES_SENT)
    svc.store.touch_user("23276000003", (t0 - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"))
    svc.store.set_opted_out("23276000003", True)

    res = svc.automations.run_stalled_quote_followups(now=t0, stalled_after_hours=2.0)
    assert res["sent"] == ["23276000001"]
    assert res["queued_for_staff"] == ["23276000002"]

    # Running a second time is idempotent
    res2 = svc.automations.run_stalled_quote_followups(now=t0, stalled_after_hours=2.0)
    assert res2["sent"] == []
    assert res2["queued_for_staff"] == []


def test_automation_trial_expiry_transitions_and_notifies(tmp_path: Path):
    t0 = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
    clock = MutableClock(t0)
    svc = _make_services(tmp_path, clock)

    wa_id = "23276000010"
    svc.store.ensure_conversation(wa_id, "Trial User")
    svc.store.set_state(wa_id, State.TRIAL_ACTIVE)
    svc.store.touch_user(wa_id, (t0 - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
    svc.store.update_draft(wa_id, {"trial_ends_at": (t0 - timedelta(minutes=15)).isoformat(timespec="seconds")})

    lead = svc.crm.ensure_lead(wa_id, wa_id, profile_name="Trial User")
    lead.months = 1
    lead.device_count = 1
    lead.trial_status = "active"
    svc.crm.provider.upsert_lead(lead)

    res = svc.automations.run_trial_expiry_checks(now=t0)
    assert res["expired_notified"] == [wa_id]
    conv = svc.store.get_conversation(wa_id)
    assert conv.state == State.PAYMENT_READINESS
    updated_lead = svc.crm.provider.get_lead_by_wa_id(wa_id)
    assert updated_lead.trial_status == "expired"
    assert updated_lead.lead_stage == "trial_expired"


def test_automation_payment_and_renewal_reminders_and_admin_api(tmp_path: Path):
    t0 = datetime(2026, 10, 12, 15, 0, 0, tzinfo=timezone.utc)
    clock = MutableClock(t0)
    svc = _make_services(tmp_path, clock)

    # 1. Payment due contact (updated 2 hours ago, in 24h window)
    wa_pay = "23276000020"
    svc.store.ensure_conversation(wa_pay, "Payer")
    svc.store.set_state(wa_pay, State.PAYMENT_DUE)
    svc.store.touch_user(wa_pay, (t0 - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
    # Force updated_at to 2 hours ago
    with svc.store._connect() as con:
        con.execute(
            "UPDATE conversations SET updated_at = ? WHERE wa_id = ?",
            ((t0 - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), wa_pay),
        )

    # 2. Existing customer expiring in 2 days
    wa_cust = "23276000030"
    svc.store.ensure_conversation(wa_cust, "VIP Customer")
    svc.store.set_customer_flag(wa_cust, True, "CUST-0001")
    svc.store.touch_user(wa_cust, (t0 - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
    svc.crm.provider.upsert_customer(
        CustomerRecord(
            customer_id="CUST-0001",
            source_lead_id="LEAD-0001",
            wa_id=wa_cust,
            phone_e164=wa_cust,
            name="VIP Customer",
            subscription_months=3,
            device_count=2,
            amount_paid_le=450,
            account_status="active",
            subscription_expires_at=(t0 + timedelta(days=2)).strftime("%Y-%m-%d"),
        )
    )

    app = create_app(services=svc)
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-secret-token"}

    status_before = client.get("/admin/automations/status", headers=headers)
    assert status_before.status_code == 200
    assert status_before.json()["pending_payments"] == 1
    assert status_before.json()["existing_customers"] == 1

    run_resp = client.post("/admin/automations/run", json={}, headers=headers)
    assert run_resp.status_code == 200
    body = run_resp.json()
    assert body["payment_reminders"]["sent"] == [wa_pay]
    assert body["renewal_reminders"]["sent"] == [wa_cust]
    assert body["total_messages_sent"] == 2

    cust_after = svc.crm.provider.get_customer_by_wa_id(wa_cust)
    assert cust_after.account_status == "renewal_due"


def test_lark_ensure_workflows_idempotent():
    provider = LarkBaseCRMProvider(base_token="basetok", auto_create=False)
    provider._table_ids = {
        "01_Leads": "tbl1",
        "02_Free_Trials": "tbl2",
        "05_Subscriptions": "tbl5",
        "06_Payments": "tbl6",
        "16_Support_Tickets": "tbl16",
    }

    def fake_cli(args, **kwargs):
        cmd = args[0]
        if cmd == "+workflow-list":
            return {"ok": True, "data": {"workflows": []}}
        if cmd == "+field-list":
            return {
                "ok": True,
                "data": {
                    "fields": [
                        {"name": "Lead ID", "id": "fldLeadId"},
                        {"name": "WhatsApp Number", "id": "fldWa"},
                        {"name": "Trial ID", "id": "fldTrialId"},
                        {"name": "Subscription ID", "id": "fldSubId"},
                        {"name": "Payment ID", "id": "fldPayId"},
                        {"name": "Ticket ID", "id": "fldTktId"},
                        {"name": "Subject", "id": "fldSubj"},
                    ]
                },
            }
        if cmd == "+workflow-create":
            return {"ok": True, "data": {"workflow_id": "wf_new"}}
        if cmd == "+workflow-enable":
            return {"ok": True, "data": {"workflow_id": "wf_new", "status": "enabled"}}
        return {"ok": True, "data": {}}

    with patch("app.crm_lark._run_cli", side_effect=fake_cli):
        res = provider.ensure_workflows()
    assert len(res) == 5
    assert all(r["action"] == "created_and_enabled" for r in res)

