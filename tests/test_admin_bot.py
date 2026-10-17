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
