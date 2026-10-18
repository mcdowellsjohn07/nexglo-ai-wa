"""Tests for flexible, data-type-aware sales and renewal command parsing.

Verifies:
1. Flexible argument order (name before phone, package before name, etc.)
2. Varied separator types (commas, spaces, hyphens, key-value labels, newlines)
3. Diverse data formats for phones (spaces, hyphens, +232, 0...)
4. Diverse duration types (1m, 1 month, 1 year, annual, quarterly, 180 Le price mapping)
5. Payment methods and automatic reference generation (Cash, Orange Money, Afrimoney, Bank)
6. Admin commands: ADMIN SALE, ADMIN DIRECT SALE, DIRECT SALE, RECORD SALE, RENEW
"""

import pytest
from app.config import Settings
from app.deps import build_services
from app.models import InboundMessage
from app.reseller_bot import (
    parse_direct_sale_text,
    parse_wallet_activation_text,
    parse_package_spec,
    parse_phone_number,
    validate_sale_inputs,
)


def test_package_spec_data_types():
    # Standard codes
    assert parse_package_spec("1m 1d") == (1, 1)
    assert parse_package_spec("3m 2d") == (3, 2)
    assert parse_package_spec("6m 1d") == (6, 1)
    assert parse_package_spec("12m 3d") == (12, 3)

    # Word durations
    assert parse_package_spec("1 month 1 device") == (1, 1)
    assert parse_package_spec("3 months 2 screens") == (3, 2)
    assert parse_package_spec("6 months 3 tvs") == (6, 3)
    assert parse_package_spec("1 year 2 devices") == (12, 2)
    assert parse_package_spec("1 yr 1 dev") == (12, 1)
    assert parse_package_spec("annual 2 screens") == (12, 2)
    assert parse_package_spec("quarterly 1 tv") == (3, 1)

    # Price mapping
    assert parse_package_spec("180") == (1, 1)
    assert parse_package_spec("Le500") == (3, 1)
    assert parse_package_spec("900 Leones") == (3, 2)
    assert parse_package_spec("Le1800") == (12, 1)


def test_phone_number_formats():
    assert parse_phone_number("076123456") == "+23276123456"
    assert parse_phone_number("+23276123456") == "+23276123456"
    assert parse_phone_number("23276123456") == "+23276123456"
    assert parse_phone_number("076 123 456") == "+23276123456"
    assert parse_phone_number("+232-76-123456") == "+23276123456"
    assert parse_phone_number("078-999-888") == "+23278999888"
    assert parse_phone_number("phone: 076123456") == "+23276123456"


def test_direct_sale_flexible_ordering():
    # 1. Comma separated with standard order
    s1 = parse_direct_sale_text("076123456, John Kamara, 1m 1dev, Orange Money, OM123456")
    assert s1 is not None
    assert s1["customer_phone"] == "+23276123456"
    assert s1["customer_name"] == "John Kamara"
    assert s1["months"] == 1
    assert s1["devices"] == 1
    assert s1["payment_method"] == "Orange Money"
    assert s1["payment_reference"] == "OM123456"

    # 2. Comma separated with name first
    s2 = parse_direct_sale_text("John Kamara, 076123456, 1m 1dev, Orange Money, OM123456")
    assert s2 is not None
    assert s2["customer_phone"] == "+23276123456"
    assert s2["customer_name"] == "John Kamara"
    assert s2["months"] == 1
    assert s2["payment_method"] == "Orange Money"

    # 3. Space separated with name first
    s3 = parse_direct_sale_text("ADMIN SALE John Kamara 076123456 3 months 2 devices Afrimoney AF554433")
    assert s3 is not None
    assert s3["customer_phone"] == "+23276123456"
    assert s3["customer_name"] == "John Kamara"
    assert s3["months"] == 3
    assert s3["devices"] == 2
    assert s3["payment_method"] == "Afrimoney"
    assert s3["payment_reference"] == "AF554433"

    # 4. Space separated with phone first
    s4 = parse_direct_sale_text("DIRECT SALE 076554433 Mariama 1m 1d OrangeMoney OM889900")
    assert s4 is not None
    assert s4["customer_phone"] == "+23276554433"
    assert s4["customer_name"] == "Mariama"
    assert s4["months"] == 1
    assert s4["devices"] == 1
    assert s4["payment_method"] == "Orange Money"
    assert s4["payment_reference"] == "OM889900"

    # 5. Labeled key-value format
    s5 = parse_direct_sale_text("phone: 078112233 name: Samuel Bangura package: 1 year 2 screens method: Bank ref: BT9988")
    assert s5 is not None
    assert s5["customer_phone"] == "+23278112233"
    assert s5["customer_name"] == "Samuel Bangura"
    assert s5["months"] == 12
    assert s5["devices"] == 2
    assert s5["payment_method"] == "Bank Transfer"
    assert s5["payment_reference"] == "BT9988"

    # 6. Price mapping (180 -> 1m 1d) with auto-generated reference for Cash
    s6 = parse_direct_sale_text("ADMIN SALE 076123456 Foday Koroma 180 cash")
    assert s6 is not None
    assert s6["customer_phone"] == "+23276123456"
    assert s6["customer_name"] == "Foday Koroma"
    assert s6["months"] == 1
    assert s6["devices"] == 1
    assert s6["payment_method"] == "Cash"
    assert s6["payment_reference"].startswith("CASH-")


def test_renewal_parsing_flexible():
    # 1. Standard renewal
    r1 = parse_direct_sale_text("RENEW 076123456 1m 1dev Orange Money OM9988", is_renewal=True)
    assert r1 is not None
    assert r1["customer_phone"] == "+23276123456"
    assert r1["is_renewal"] is True
    assert r1["months"] == 1
    assert r1["payment_reference"] == "OM9988"

    # 2. Renewal without reference (auto-generated)
    r2 = parse_direct_sale_text("ADMIN RENEWAL 076123456 3 months")
    assert r2 is not None
    assert r2["customer_phone"] == "+23276123456"
    assert r2["is_renewal"] is True
    assert r2["months"] == 3
    assert r2["payment_reference"].startswith("REF-")


def test_wallet_activation_flexible():
    w1 = parse_wallet_activation_text("ACTIVATE 076123456 Mariama Sesay 1m 1d")
    assert w1 is not None
    assert w1["customer_phone"] == "+23276123456"
    assert w1["customer_name"] == "Mariama Sesay"
    assert w1["months"] == 1
    assert w1["devices"] == 1

    w2 = parse_wallet_activation_text("WALLET ACTIVATE Mariama Sesay 076123456 3 months 2 devices")
    assert w2 is not None
    assert w2["customer_phone"] == "+23276123456"
    assert w2["customer_name"] == "Mariama Sesay"
    assert w2["months"] == 3
    assert w2["devices"] == 2


def test_admin_executes_flexible_sale_formats():
    settings = Settings(
        admin_token="secret-123",
        admin_phone_numbers="+23276999000",
    )
    services = build_services(settings)
    agent = services.agent
    admin_phone = "+23276999000"

    # 1. Admin sends DIRECT SALE with name first, no commas
    msg1 = InboundMessage(
        message_id="adm_flex_1",
        wa_id=admin_phone,
        type="text",
        text="ADMIN SALE John Kamara 076123456 1m 1d Orange Money OM112233",
    )
    agent.handle_message(msg1)
    history = agent.store.history(admin_phone, limit=2)
    last_reply = history[-1]["content"]
    assert "Direct Sale Recorded & Customer Activated" in last_reply
    assert "John Kamara" in last_reply
    assert "+23276123456" in last_reply
    assert "OM112233" in last_reply

    # 2. Admin sends ADMIN DIRECT SALE with Cash and no ref
    msg2 = InboundMessage(
        message_id="adm_flex_2",
        wa_id=admin_phone,
        type="text",
        text="ADMIN DIRECT SALE 076778899 Fatmata 3 months Cash",
    )
    agent.handle_message(msg2)
    history = agent.store.history(admin_phone, limit=2)
    last_reply = history[-1]["content"]
    assert "Direct Sale Recorded & Customer Activated" in last_reply
    assert "Fatmata" in last_reply
    assert "+23276778899" in last_reply
    assert "Cash" in last_reply
