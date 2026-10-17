"""Unit and integration tests for the Admin WhatsApp Command Engine:
- Strict sender verification & zero information leakage for unauthorized senders
- Admin commands: STATUS, MODEL, MODE, DRYRUN, HANDOFFS, RESOLVE, PAUSE, VERIFY,
  RESELLER, WALLET, NUMBERS, ADD, REMOVE, SYNC, BACKUP, HELP
"""

from __future__ import annotations

import pytest
from app.admin_bot import AdminBotManager, _mask_phone
from app.config import Settings
from app.deps import build_services
from app.models import InboundMessage


@pytest.fixture
def admin_services():
    settings = Settings(
        admin_token="secret-token-123",
        admin_phone_numbers="+23276999000,23278111222",
    )
    svc = build_services(settings)
    return svc


def test_mask_phone():
    assert _mask_phone("+23276999000") == "+232 *** 000"
    assert _mask_phone("123") == "123"


def test_admin_verification_security_leakage(admin_services):
    """An unauthorized user sending admin commands receives zero response and zero leakage."""
    agent = admin_services.agent
    attacker_phone = "23277000111"

    # Attacker attempts ADMIN STATUS
    inbound = InboundMessage(
        message_id="atk_1",
        wa_id=attacker_phone,
        type="text",
        text="ADMIN STATUS",
    )
    agent.handle_message(inbound)

    history = agent.store.history(attacker_phone, limit=2)
    assert len(history) > 0
    last_reply = history[-1]["content"]

    # Security check: bot did NOT execute admin status or mention admin commands!
    assert "System Status Statement" not in last_reply
    assert "Active LLM" not in last_reply
    assert "Access Denied" not in last_reply  # Zero leakage


def test_admin_phone_matching_formats(admin_services):
    """Registered admin number resolves across local (076...), standard (+23276...), and raw (23276...) formats."""
    admin_bot = admin_services.admin_bot

    # Registered: +23276999000
    assert admin_bot.is_admin("+23276999000") is True
    assert admin_bot.is_admin("23276999000") is True
    assert admin_bot.is_admin("076999000") is True

    # Unregistered
    assert admin_bot.is_admin("23276000999") is False
    assert admin_bot.is_admin("") is False


def test_admin_status_command(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"

    inbound = InboundMessage(
        message_id="adm_1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN STATUS",
    )
    agent.handle_message(inbound)

    history = agent.store.history(admin_phone, limit=2)
    last_reply = history[-1]["content"]
    assert "NexgloTV System Status Statement" in last_reply
    assert "AI Model:" in last_reply
    assert "Auto-Reply Policy:" in last_reply


def test_admin_model_switching(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"

    # View models
    inbound_view = InboundMessage(
        message_id="adm_m1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN MODEL",
    )
    agent.handle_message(inbound_view)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Available Free NVIDIA NIM Models" in last_reply
    assert "meta/llama-3.3-70b-instruct" in last_reply

    # Switch model
    inbound_switch = InboundMessage(
        message_id="adm_m2",
        wa_id=admin_phone,
        type="text",
        text="ADMIN MODEL deepseek-ai/deepseek-r1",
    )
    agent.handle_message(inbound_switch)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Model Switched Successfully" in last_reply
    assert "deepseek-ai/deepseek-r1" in last_reply

    # Verify model is persisted in store
    saved = agent.store.get_setting("active_model")
    assert saved == "deepseek-ai/deepseek-r1"


def test_admin_mode_switching(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"

    inbound = InboundMessage(
        message_id="adm_mode1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN MODE SELECTIVE",
    )
    agent.handle_message(inbound)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Auto-Reply Mode Updated" in last_reply
    assert "SELECTIVE" in last_reply

    assert agent.store.get_setting("auto_reply_mode") == "selective"


def test_admin_dryrun_toggle(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"

    inbound_on = InboundMessage(
        message_id="adm_dry1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN DRYRUN ON",
    )
    agent.handle_message(inbound_on)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Dry-Run Mode Set To" in last_reply
    assert "ON" in last_reply

    assert agent.store.get_setting("dry_run") == "1"


def test_admin_handoff_and_resolve(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"
    cust_phone = "23276112233"

    # Put customer in handoff
    agent.store.ensure_conversation(cust_phone)
    agent.store.set_handoff(cust_phone, True)
    agent.store.create_handoff(cust_phone, reason="customer_request")

    # List handoffs
    inbound_list = InboundMessage(
        message_id="adm_h1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN HANDOFFS",
    )
    agent.handle_message(inbound_list)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Pending Staff Handoff Queue" in last_reply
    assert cust_phone in last_reply

    # Resolve handoff
    inbound_res = InboundMessage(
        message_id="adm_h2",
        wa_id=admin_phone,
        type="text",
        text=f"ADMIN RESOLVE {cust_phone}",
    )
    agent.handle_message(inbound_res)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Handoff Resolved" in last_reply

    # Confirm handoff is false in store
    conv = agent.store.get_conversation(cust_phone)
    assert conv.handoff is False


def test_admin_add_and_remove_number(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"
    new_admin = "076333444"

    # Add admin
    inbound_add = InboundMessage(
        message_id="adm_a1",
        wa_id=admin_phone,
        type="text",
        text=f"ADMIN ADD {new_admin}",
    )
    agent.handle_message(inbound_add)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Admin Number Authorized" in last_reply

    # Verify new admin is recognized
    assert agent.admin_bot.is_admin("+23276333444") is True

    # List admins
    inbound_list = InboundMessage(
        message_id="adm_a2",
        wa_id=admin_phone,
        type="text",
        text="ADMIN NUMBERS",
    )
    agent.handle_message(inbound_list)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Authorized Admin Phone Numbers" in last_reply
    assert "***" in last_reply  # Masked display

    # Remove admin
    inbound_rem = InboundMessage(
        message_id="adm_a3",
        wa_id=admin_phone,
        type="text",
        text=f"ADMIN REMOVE {new_admin}",
    )
    agent.handle_message(inbound_rem)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Admin Privileges Revoked" in last_reply
    assert agent.admin_bot.is_admin("+23276333444") is False


def test_admin_reseller_and_wallet_controls(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"

    # Add reseller
    inbound_add_rsl = InboundMessage(
        message_id="adm_r1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN RESELLER ADD 076888777 RES-BO Bo Central",
    )
    agent.handle_message(inbound_add_rsl)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Reseller Added Successfully" in last_reply
    assert "RES-BO" in last_reply

    # Reseller list
    inbound_list_rsl = InboundMessage(
        message_id="adm_r2",
        wa_id=admin_phone,
        type="text",
        text="ADMIN RESELLER LIST",
    )
    agent.handle_message(inbound_list_rsl)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Registered Reseller Partners" in last_reply
    assert "RES-BO" in last_reply

    # Toggle wallet
    inbound_w_on = InboundMessage(
        message_id="adm_w1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN WALLET ON",
    )
    agent.handle_message(inbound_w_on)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Reseller Prepaid Wallet Model ENABLED" in last_reply
    assert agent.reseller_mgr.wallet_enabled is True

    inbound_w_off = InboundMessage(
        message_id="adm_w2",
        wa_id=admin_phone,
        type="text",
        text="ADMIN WALLET OFF",
    )
    agent.handle_message(inbound_w_off)
    last_reply = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Reseller Prepaid Wallet Model DISABLED" in last_reply
    assert agent.reseller_mgr.wallet_enabled is False


def test_admin_direct_sale_and_renewal(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"
    customer_phone = "076123456"
    norm_phone = "+23276123456"

    # 1. Admin records a direct sale
    inbound_sale = InboundMessage(
        message_id="adm_sale_1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN SALE 076123456, John Kamara, 1mo 1dev, Orange Money, OM123456",
    )
    agent.handle_message(inbound_sale)
    reply = agent.store.history(admin_phone, limit=2)[-1]["content"]

    assert "Direct Sale Recorded & Customer Activated" in reply
    assert "John Kamara" in reply
    assert norm_phone in reply
    assert "Le180" in reply
    assert "OM123456" in reply
    assert "DIRECT" in reply

    # Verify CRM customer record
    cust = agent.crm.provider.get_customer_by_wa_id(norm_phone)
    assert cust is not None
    assert cust.name == "John Kamara"
    assert cust.account_status == "active"
    assert cust.reseller_code == "DIRECT"
    assert cust.amount_paid_le == 180

    # Verify payment record
    payment = agent.crm.provider.get_payment_by_ref("OM123456")
    assert payment is not None
    assert payment.status == "confirmed"
    assert payment.verified_by == "admin_whatsapp"

    # Verify lead record marked converted
    lead = agent.crm.provider.get_lead_by_wa_id(norm_phone)
    assert lead is not None
    assert lead.lead_stage == "CONVERTED"

    # 2. Admin records a direct renewal for the customer
    inbound_renew = InboundMessage(
        message_id="adm_renew_1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN RENEW 076123456, 3mo 2dev, Afrimoney, AF998877",
    )
    agent.handle_message(inbound_renew)
    reply_renew = agent.store.history(admin_phone, limit=2)[-1]["content"]

    assert "Direct Renewal Recorded & Subscription Extended" in reply_renew
    assert "Renewal Count: *1*" in reply_renew
    assert "AF998877" in reply_renew

    cust_renewed = agent.crm.provider.get_customer_by_wa_id(norm_phone)
    assert cust_renewed.renewal_count == 1


def test_admin_crm_actions(admin_services):
    agent = admin_services.agent
    admin_phone = "+23276999000"
    target_phone = "076888999"
    norm_target = "+23276888999"

    # Seed a sale first so records exist in CRM
    agent.handle_message(InboundMessage(
        message_id="seed_1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN SALE 076888999, Aminata Koroma, 1mo 1dev, Cash, CASH-001",
    ))

    # 1. ADMIN CRM CUSTOMER
    agent.handle_message(InboundMessage(
        message_id="crm_c1",
        wa_id=admin_phone,
        type="text",
        text=f"ADMIN CRM CUSTOMER {target_phone}",
    ))
    reply_cust = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Lark CRM Customer Profile" in reply_cust
    assert "Aminata Koroma" in reply_cust
    assert "ACTIVE" in reply_cust

    # 2. ADMIN CRM LEAD
    agent.handle_message(InboundMessage(
        message_id="crm_l1",
        wa_id=admin_phone,
        type="text",
        text=f"ADMIN CRM LEAD {target_phone}",
    ))
    reply_lead = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Lark CRM Lead Profile" in reply_lead
    assert "CONVERTED" in reply_lead

    # 3. ADMIN CRM STAGE
    agent.handle_message(InboundMessage(
        message_id="crm_s1",
        wa_id=admin_phone,
        type="text",
        text=f"ADMIN CRM STAGE {target_phone} QUOTED",
    ))
    reply_stage = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Lead Stage Updated" in reply_stage
    assert "QUOTED" in reply_stage

    # 4. ADMIN CRM PAYMENT
    agent.handle_message(InboundMessage(
        message_id="crm_p1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN CRM PAYMENT CASH-001",
    ))
    reply_pay = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Lark CRM Payment Record" in reply_pay
    assert "CONFIRMED" in reply_pay
    assert "CASH-001" in reply_pay

    # 5. ADMIN CRM STATS
    agent.handle_message(InboundMessage(
        message_id="crm_st1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN CRM STATS",
    ))
    reply_stats = agent.store.history(admin_phone, limit=2)[-1]["content"]
    assert "Lark CRM & Operations Summary" in reply_stats
    assert "Total Leads:" in reply_stats
    assert "Active Customers:" in reply_stats


def test_customer_mentioning_reseller_code_promo_reward(admin_services):
    """When a customer mentions a reseller code, it is not flagged as a security issue.
    
    Instead, it applies a 20% discount, records referral in CRM, and presents packages.
    """
    agent = admin_services.agent
    customer_phone = "23277123456"  # Regular customer, NOT the pilot reseller (23276000001)

    # Ensure clean starting state for customer test
    agent.store.set_handoff(customer_phone, False)
    agent.store.set_state(customer_phone, "idle")

    # Customer texts reseller promo code
    inbound = InboundMessage(
        message_id="cust_rsl_1",
        wa_id=customer_phone,
        type="text",
        text="RSL-PILOT01",
    )
    agent.handle_message(inbound)

    history = agent.store.history(customer_phone, limit=5)
    assistant_messages = [m["content"] for m in history if m.get("role") == "assistant"]
    all_assistant_text = "\n".join(assistant_messages)

    # Must NOT contain security warnings or errors
    assert "Security violation" not in all_assistant_text
    assert "inactive" not in all_assistant_text.lower() or "not recognized" not in all_assistant_text.lower()

    # Must contain friendly partner promo applied message and discount details
    assert "Partner Promo Code Applied!" in all_assistant_text
    assert "RSL-PILOT01" in all_assistant_text
    assert "20% Partner Discount" in all_assistant_text

    # Referral must be recorded in CRM
    lead = agent.crm.provider.get_lead_by_wa_id(customer_phone)
    assert lead is not None
    assert lead.referrer_code == "RSL-PILOT01"
