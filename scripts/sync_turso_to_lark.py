"""Sync all customer conversations from Turso Cloud database to Lark Base CRM.

Reads 100+ active WhatsApp conversations from Turso SQLite/Cloud DB and
synchronizes them into the NexgloTV CRM Base (table 01_Leads, 02_Free_Trials,
03_Customers).

Usage:
    python scripts/sync_turso_to_lark.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.crm_lark import LarkBaseCRMProvider
from app.crm_sheets import CustomerRecord, LeadRecord, TrialRecord
from app.deps import build_services

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_turso_to_lark")


STATE_TO_LEAD_STAGE = {
    "idle": "NEW_LEAD",
    "faq_only": "CONTACTED",
    "prices_sent": "PRICES_SENT",
    "package_selected": "PACKAGE_SELECTED",
    "payment_readiness": "PAYMENT_READINESS",
    "device_selected": "DEVICE_SELECTED",
    "device_model": "DEVICE_SELECTED",
    "install_method": "INSTALL_METHOD",
    "area_captured": "AREA_CAPTURED",
    "app_link_sent": "APP_LINK_SENT",
    "app_installed": "APP_INSTALLED",
    "handoff_requested": "ESCALATED",
    "human": "ESCALATED",
    "human_owned": "ESCALATED",
    "setup_verified": "SETUP_VERIFIED",
    "payment_due": "PAYMENT_DUE",
    "payment_verification": "PAYMENT_VERIFICATION",
    "converted": "CONVERTED",
    "trial_requested": "TRIAL_REQUESTED",
    "trial_approval": "TRIAL_REQUESTED",
    "trial_active": "TRIAL_ACTIVE",
    "opted_out": "OPTED_OUT",
    "lost": "LOST",
    "renewal": "RENEWAL",
}


def sync_all():
    settings = get_settings()
    log.info("Connecting to Turso Cloud DB (%s)...", settings.turso_database_url)
    services = build_services(settings)
    store = services.store

    base_token = getattr(settings, "lark_base_token", "") or "E8jObNOAeaZqUHsyxRHjR9VcpBg"
    log.info("Connecting to Lark Base CRM (%s)...", base_token)
    crm_provider = LarkBaseCRMProvider(base_token=base_token, auto_create=False)
    crm_provider._load_tables()
    crm_provider._load_cache("01_Leads")
    log.info("Lark Base loaded. Current 01_Leads count: %d", len(crm_provider._id_cache.get("01_Leads", {})))

    # Fetch all conversations with latest message in single query
    sql = """
    SELECT 
        c.wa_id, c.state, c.lang, c.draft, c.handoff, c.profile_name, c.opted_out,
        c.last_user_at, c.is_existing_customer, c.customer_id, c.lead_id,
        c.created_at, c.updated_at,
        m.content AS last_message,
        m.created_at AS last_message_at
    FROM conversations c
    LEFT JOIN (
        SELECT wa_id, content, created_at
        FROM messages
        WHERE id IN (SELECT MAX(id) FROM messages GROUP BY wa_id)
    ) m ON m.wa_id = c.wa_id
    ORDER BY c.updated_at DESC
    """
    with store._connect() as con:
        rows = [dict(r) for r in con.execute(sql).fetchall()]

    total = len(rows)
    log.info("Found %d conversations in Turso to synchronize.", total)

    synced_leads = 0
    synced_custs = 0
    errors = 0

    for idx, row in enumerate(rows, 1):
        wa_id = str(row.get("wa_id") or "").strip()
        if not wa_id:
            continue

        profile_name = (row.get("profile_name") or "").strip()
        state = (row.get("state") or "idle").strip()
        handoff = bool(row.get("handoff"))
        opted_out = bool(row.get("opted_out"))
        last_message = (row.get("last_message") or "").strip()
        created_at = row.get("created_at") or datetime.now(timezone.utc).isoformat()
        last_contact = row.get("last_user_at") or row.get("last_message_at") or row.get("updated_at") or created_at

        try:
            draft = json.loads(row.get("draft") or "{}")
        except Exception:
            draft = {}

        # Determine lead stage
        if opted_out:
            stage = "OPTED_OUT"
        elif handoff:
            stage = "ESCALATED"
        else:
            stage = STATE_TO_LEAD_STAGE.get(state, "CONTACTED")

        # Clean phone
        phone_e164 = f"+{wa_id}" if not wa_id.startswith("+") else wa_id

        lead = LeadRecord(
            lead_id=row.get("lead_id") or "",
            wa_id=wa_id,
            phone_e164=phone_e164,
            name=profile_name or f"WhatsApp Contact {wa_id[-4:]}",
            source="whatsapp",
            lead_stage=stage,
            first_contact_at=str(created_at),
            last_message_at=str(last_contact),
            months=int(draft.get("months") or 0),
            device_count=int(draft.get("devices") or draft.get("device_count") or 0),
            subscription_quote_le=int(draft.get("quote") or draft.get("subscription_quote_le") or 0),
            device_types=str(draft.get("device_type") or draft.get("platform") or ""),
            device_model=str(draft.get("device_model") or ""),
            area=str(draft.get("area") or ""),
            install_method=str(draft.get("install_method") or ""),
            app_name=str(draft.get("app_name") or ""),
            app_url_sent=str(draft.get("app_link") or draft.get("app_url") or ""),
            app_installed_reported=bool(draft.get("app_installed")),
            ready_to_pay_after_setup=bool(draft.get("ready_to_pay")),
            trial_requested=bool(draft.get("trial_requested") or state in ("trial_requested", "trial_approval", "trial_active")),
            referrer_code=str(draft.get("referrer_code") or draft.get("ref_code") or ""),
            reseller_code=str(draft.get("reseller_code") or ""),
        )

        try:
            ok = crm_provider.upsert_lead(lead)
            if ok:
                synced_leads += 1
                if lead.lead_id and lead.lead_id != row.get("lead_id"):
                    # Save generated lead_id back to Turso
                    store.set_lead_id(wa_id, lead.lead_id)
            else:
                log.warning("[%d/%d] Could not upsert lead for %s", idx, total, wa_id)
        except Exception as exc:
            errors += 1
            log.error("[%d/%d] Error syncing lead %s: %s", idx, total, wa_id, exc)

        # Sync existing customer if flagged
        if row.get("is_existing_customer") or row.get("customer_id") or state == "converted":
            try:
                cust = CustomerRecord(
                    customer_id=row.get("customer_id") or "",
                    wa_id=wa_id,
                    phone_e164=phone_e164,
                    name=profile_name or f"Customer {wa_id[-4:]}",
                    account_status="ACTIVE",
                    activation_at=str(created_at),
                )
                if crm_provider.upsert_customer(cust):
                    synced_custs += 1
                    if cust.customer_id and cust.customer_id != row.get("customer_id"):
                        store.set_customer_id(wa_id, cust.customer_id)
            except Exception as exc:
                log.warning("Could not upsert customer for %s: %s", wa_id, exc)

        if idx % 10 == 0 or idx == total:
            log.info("Progress: %d/%d leads processed (%d synced, %d errors)", idx, total, synced_leads, errors)

    log.info("==================================================")
    log.info("SYNC FINISHED!")
    log.info("Total WhatsApp conversations checked: %d", total)
    log.info("Total Leads synced to Lark Base:      %d", synced_leads)
    log.info("Total Customers synced to Lark Base:  %d", synced_custs)
    log.info("Total errors encountered:            %d", errors)
    log.info("==================================================")


if __name__ == "__main__":
    sync_all()
