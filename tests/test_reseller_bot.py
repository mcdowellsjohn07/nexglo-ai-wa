"""Unit and integration tests for NexgloTV Reseller Bot Engine:
- Model 1: DIRECT_TO_NEXGLOTV (Direct customer payment to NexgloTV)
- Model 2: PREPAID_WALLET (Instant activation funded via reseller wallet)
"""

from __future__ import annotations

import pytest
from app.reseller_bot import (
    ResellerBotManager,
    ResellerProfile,
    parse_direct_sale_text,
    parse_package_spec,
    parse_phone_number,
    parse_wallet_activation_text,
)


@pytest.fixture
def manager():
    mgr = ResellerBotManager()
    pilot = ResellerProfile(
        reseller_id="RSL-001",
        reseller_code="RSL-PILOT01",
        name="Alpha Partner",
        phone="23276000001",
        wallet_balance=1000,
        approved_commissions=200,
        unpaid_commissions=200,
    )
    mgr.register_reseller(pilot)
    return mgr


# =============================================================================
# Unit Tests: Parsers
# =============================================================================

def test_parse_package_spec():
    assert parse_package_spec("1m 1d") == (1, 1)
    assert parse_package_spec("1 month 2 devices") == (1, 2)
    assert parse_package_spec("3m 2dev") == (3, 2)
    assert parse_package_spec("6 months 3 devices") == (6, 3)
    assert parse_package_spec("12m 4d") == (12, 4)
    # Defaults
    assert parse_package_spec("unknown") == (1, 1)


def test_parse_phone_number():
    assert parse_phone_number("076123456") == "+23276123456"
    assert parse_phone_number("+23276123456") == "+23276123456"
    assert parse_phone_number("23276123456") == "+23276123456"


def test_parse_direct_sale_text():
    # Comma-separated format
    raw = "076123456, Foday Koroma, 1m 1dev, Orange Money, OM1234567"
    parsed = parse_direct_sale_text(raw)
    assert parsed is not None
    assert parsed["customer_phone"] == "+23276123456"
    assert parsed["customer_name"] == "Foday Koroma"
    assert parsed["months"] == 1
    assert parsed["devices"] == 1
    assert parsed["payment_method"] == "Orange Money"
    assert parsed["payment_reference"] == "OM1234567"

    # Command format
    raw_cmd = "DIRECT SALE 076123456 Foday Koroma 3m 2d Afrimoney AF999888"
    parsed_cmd = parse_direct_sale_text(raw_cmd)
    assert parsed_cmd is not None
    assert parsed_cmd["customer_phone"] == "+23276123456"
    assert parsed_cmd["months"] == 3
    assert parsed_cmd["devices"] == 2
    assert parsed_cmd["payment_method"] == "Afrimoney"


def test_parse_wallet_activation_text():
    # Comma format
    raw = "076123456, Mariama Sesay, 1m 2dev"
    parsed = parse_wallet_activation_text(raw)
    assert parsed is not None
    assert parsed["customer_phone"] == "+23276123456"
    assert parsed["customer_name"] == "Mariama Sesay"
    assert parsed["months"] == 1
    assert parsed["devices"] == 2

    # Command format
    raw_cmd = "ACTIVATE 076999888 Alpha Diallo 1m 1d"
    parsed_cmd = parse_wallet_activation_text(raw_cmd)
    assert parsed_cmd is not None
    assert parsed_cmd["customer_phone"] == "+23276999888"
    assert parsed_cmd["months"] == 1
    assert parsed_cmd["devices"] == 1


# =============================================================================
# Unit Tests: Model 1 (DIRECT_TO_NEXGLOTV)
# =============================================================================

def test_model_1_direct_sale(manager):
    reseller = manager.identify_reseller("23276000001")
    assert reseller is not None

    # Submit 1 Month / 1 Device sale (Le180 net)
    res = manager.process_direct_sale(
        reseller=reseller,
        customer_phone="+23276112233",
        customer_name="John Kamara",
        months=1,
        devices=1,
        payment_method="Orange Money",
        payment_reference="OM-554433",
    )

    assert res["success"] is True
    assert res["model"] == "DIRECT_TO_NEXGLOTV"
    assert res["amount_due"] == 180  # Approved 1m 1d price
    assert res["expected_commission"] == 36  # Exactly 20% of Le180
    assert res["status"] == "Pending Admin Verification"

    # Submit 3 Months / 2 Devices sale (Le900 net)
    res3 = manager.process_direct_sale(
        reseller=reseller,
        customer_phone="+23276998877",
        customer_name="Sorie Conteh",
        months=3,
        devices=2,
        payment_method="Afrimoney",
        payment_reference="AF-778899",
    )
    assert res3["amount_due"] == 900
    assert res3["expected_commission"] == 180  # Exactly 20% of Le900


# =============================================================================
# Unit Tests: Model 2 (PREPAID_WALLET)
# =============================================================================

def test_model_2_wallet_disabled_by_default(manager):
    reseller = manager.identify_reseller("23276000001")
    assert manager.wallet_enabled is False

    res = manager.process_wallet_activation(
        reseller=reseller,
        customer_phone="+23276334455",
        customer_name="Mariama Sesay",
        months=1,
        devices=1,
    )
    assert res["success"] is False
    assert res["error"] == "wallet_model_disabled"
    assert "temporarily disabled" in res["message"]


def test_model_2_wallet_activation_success(manager):
    # Enable wallet model to verify underlying activation calculation
    manager.wallet_enabled = True
    reseller = manager.identify_reseller("23276000001")
    initial_balance = reseller.wallet_balance  # 1000

    # Activate 1 Month / 1 Device (Le180)
    res = manager.process_wallet_activation(
        reseller=reseller,
        customer_phone="+23276334455",
        customer_name="Mariama Sesay",
        months=1,
        devices=1,
    )

    assert res["success"] is True
    assert res["model"] == "PREPAID_WALLET"
    assert res["debited_amount"] == 180
    assert res["commission_earned"] == 36  # 20% of 180
    assert res["remaining_balance"] == initial_balance - 180  # 820
    assert reseller.wallet_balance == 820
    assert reseller.unpaid_commissions == 200 + 36  # 236


def test_model_2_wallet_insufficient_funds(manager):
    manager.wallet_enabled = True
    reseller = manager.identify_reseller("23276000001")
    reseller.wallet_balance = 100  # Only Le100 in wallet

    # Try to activate 1 Month / 1 Device (requires Le180)
    res = manager.process_wallet_activation(
        reseller=reseller,
        customer_phone="+23276334455",
        customer_name="Mariama Sesay",
        months=1,
        devices=1,
    )

    assert res["success"] is False
    assert res["error"] == "insufficient_funds"
    assert res["required_amount"] == 180
    assert res["available_balance"] == 100
    assert res["deficit"] == 80
    # Balance must NOT be debited
    assert reseller.wallet_balance == 100


# =============================================================================
# Integration Test: WhatsApp Agent Reseller Interaction
# =============================================================================

def test_agent_reseller_chat_flow():
    from app.config import Settings
    from app.deps import build_services
    from app.models import InboundMessage

    services = build_services(Settings())
    agent = services.agent

    # Register pilot reseller on a test phone
    test_reseller_phone = "23276000099"
    profile = ResellerProfile(
        reseller_id="RSL-009",
        reseller_code="RSL-PILOT09",
        name="Test Reseller",
        phone=test_reseller_phone,
        wallet_balance=500,
        approved_commissions=100,
        unpaid_commissions=100,
    )
    agent.reseller_mgr.register_reseller(profile)

    # 1. Partner checks balance via text
    inbound_bal = InboundMessage(
        message_id="msg_1",
        wa_id=test_reseller_phone,
        type="text",
        text="BALANCE",
    )
    agent.handle_message(inbound_bal)
    history = agent.store.history(test_reseller_phone, limit=2)
    last_reply = history[-1]["content"]
    assert "Prepaid Wallet Balance" in last_reply and "Le500" in last_reply
    assert "RSL-PILOT09" in last_reply

    # 2a. Partner tries fast command ACTIVATE while disabled by default -> intercepted with notice
    inbound_act_paused = InboundMessage(
        message_id="msg_2a",
        wa_id=test_reseller_phone,
        type="text",
        text="ACTIVATE 076112233 Foday 1m 1d",
    )
    agent.handle_message(inbound_act_paused)
    history = agent.store.history(test_reseller_phone, limit=2)
    last_reply = history[-1]["content"]
    assert "Prepaid Wallet Model Temporarily Paused" in last_reply

    # 2b. Partner activates customer via fast command when wallet model is enabled
    agent.reseller_mgr.wallet_enabled = True
    inbound_act = InboundMessage(
        message_id="msg_2b",
        wa_id=test_reseller_phone,
        type="text",
        text="ACTIVATE 076112233 Foday 1m 1d",
    )
    agent.handle_message(inbound_act)
    history = agent.store.history(test_reseller_phone, limit=2)
    last_reply = history[-1]["content"]
    assert "Instant Activation Confirmed" in last_reply
    assert "Wallet Debited: Le180" in last_reply
    assert "Remaining Balance" in last_reply and "Le320" in last_reply

    # 3. Partner submits Model 1 Direct Sale
    inbound_sale = InboundMessage(
        message_id="msg_3",
        wa_id=test_reseller_phone,
        type="text",
        text="DIRECT SALE 076223344 Aminata 1m 1d OrangeMoney OM776655",
    )
    agent.handle_message(inbound_sale)
    history = agent.store.history(test_reseller_phone, limit=2)
    last_reply = history[-1]["content"]
    assert "Direct Sale Recorded" in last_reply
    assert "Expected Commission" in last_reply and "Le36" in last_reply
    assert "Pending Finance Verification" in last_reply
