"""Tests for customer account credentials and subscription WhatsApp number integration.

Verifies:
1. Lark Schema: 03_Customers has Account Username, Account Password, Server URL
2. Lark Schema: 05_Subscriptions has Customer WhatsApp Number
3. CustomerRecord dataclass: new fields default to empty strings
4. CRM Lark: _CUSTOMER_MAP maps account_username, account_password, server_url
5. CRM Lark: _sync_customer_subscription_and_device populates Customer WhatsApp Number
6. Reseller parsing: parse_direct_sale_text extracts credentials in flexible formats
7. Admin bot: ADMIN CREDENTIALS sets credentials and syncs to Lark Base
8. Admin bot: ADMIN SEND CREDENTIALS sends login details to customer WhatsApp
9. Admin bot: ADMIN EDIT SALE updates customer sale information
10. Customer flow: Customer credentials inquiry delivers login details if active
"""

from typing import Any
import pytest
from app.config import Settings
from app.crm_sheets import CustomerRecord
from app.nexglo_lark_schema import FIELD_SCHEMAS, TABLE_WA_FIELD, TABLE_KEY_FIELD
from app.crm_lark import LarkBaseCRMProvider
from app.reseller_bot import parse_direct_sale_text, parse_wallet_activation_text
from app.deps import build_services
from app.models import InboundMessage


def test_schema_definitions():
    cust_fields = [f["name"] for f in FIELD_SCHEMAS["03_Customers"]]
    assert "Account Username" in cust_fields
    assert "Account Password" in cust_fields
    assert "Server URL" in cust_fields

    sub_fields = [f["name"] for f in FIELD_SCHEMAS["05_Subscriptions"]]
    assert "Customer WhatsApp Number" in sub_fields

    assert TABLE_WA_FIELD["05_Subscriptions"] == "Customer WhatsApp Number"


def test_customer_record_dataclass():
    c = CustomerRecord(
        customer_id="CUST-TEST-01",
        source_lead_id="LEAD-01",
        wa_id="+23276123456",
        phone_e164="+23276123456",
        name="Mohamed Bangura",
    )
    assert c.account_username == ""
    assert c.account_password == ""
    assert c.server_url == ""

    c.account_username = "mbangura"
    c.account_password = "SecretPassword123"
    c.server_url = "http://stream.nexglotv.com:8080"
    assert c.account_username == "mbangura"
    assert c.account_password == "SecretPassword123"
    assert c.server_url == "http://stream.nexglotv.com:8080"


def test_crm_lark_mapping_and_subscription_whatsapp_sync():
    provider = LarkBaseCRMProvider(base_token="mock_token", auto_create=False)
    assert provider._CUSTOMER_MAP["account_username"] == "Account Username"
    assert provider._CUSTOMER_MAP["account_password"] == "Account Password"
    assert provider._CUSTOMER_MAP["server_url"] == "Server URL"

    mock_tables: dict[str, dict[str, Any]] = {}
    def fake_upsert(table, fields):
        key_field = TABLE_KEY_FIELD.get(table, "ID")
        val = fields.get(key_field)
        mock_tables.setdefault(table, {}).setdefault(val, {}).update(fields)
        return True, val

    provider._upsert_by_key = fake_upsert
    provider._mock_tables = mock_tables

    c = CustomerRecord(
        customer_id="CUST-0099",
        source_lead_id="LEAD-0099",
        wa_id="+23276112233",
        phone_e164="+23276112233",
        name="Fatmata Koroma",
        subscription_months=3,
        device_count=2,
        amount_paid_le=900,
        account_username="fatmata_k",
        account_password="pwd_fatmata_99",
        server_url="http://stream.nexglotv.com:8080",
    )

    # Upsert customer (mock memory provider)
    provider.upsert_customer(c)

    # Verify subscription was synced with Customer WhatsApp Number
    sub_key = "SUB-0099-R0"
    sub_row = provider._mock_tables.get("05_Subscriptions", {}).get(sub_key)
    assert sub_row is not None
    assert sub_row.get("Customer WhatsApp Number") == "+23276112233"
    assert sub_row.get("Customer ID") == "CUST-0099"
    assert sub_row.get("Duration Months") == 3

    # Verify customer table has credentials
    cust_row = provider._mock_tables.get("03_Customers", {}).get("CUST-0099")
    assert cust_row is not None
    assert cust_row.get("Account Username") == "fatmata_k"
    assert cust_row.get("Account Password") == "pwd_fatmata_99"
    assert cust_row.get("Server URL") == "http://stream.nexglotv.com:8080"


def test_parse_direct_sale_with_credentials():
    # 1. Direct sale with labeled credentials
    text1 = "ADMIN SALE 076123456 John Kamara 1m 1d Orange Money OM123456 user: jkamara pass: pass1234 server: http://stream.nexglo.tv:8080"
    p1 = parse_direct_sale_text(text1)
    assert p1 is not None
    assert p1["customer_phone"] == "+23276123456"
    assert p1["customer_name"] == "John Kamara"
    assert p1["account_username"] == "jkamara"
    assert p1["account_password"] == "pass1234"
    assert p1["server_url"] == "http://stream.nexglo.tv:8080"

    # 2. Wallet activation with credentials
    text2 = "ACTIVATE 078999888 Mariama Sesay 3 months user: msesay pass: secret88"
    p2 = parse_wallet_activation_text(text2)
    assert p2 is not None
    assert p2["customer_phone"] == "+23278999888"
    assert p2["customer_name"] == "Mariama Sesay"
    assert p2["account_username"] == "msesay"
    assert p2["account_password"] == "secret88"


def test_admin_bot_credentials_and_edit_sale():
    settings = Settings(
        admin_token="test_admin_token",
        admin_phone_numbers="23276000000",
    )
    services = build_services(settings)
    admin_bot = services.admin_bot
    crm = services.crm.provider

    # First register a customer via ADMIN SALE
    res_sale = admin_bot._execute_admin_command(
        None,
        "ADMIN SALE 076123456 Lansana Sesay 1m 1d Orange Money OM998877",
    )
    assert "Direct Sale Recorded" in res_sale

    # 1. Set credentials via ADMIN CREDENTIALS
    res_cred = admin_bot._execute_admin_command(
        None,
        "ADMIN CREDENTIALS 076123456 lsesay Pass7788 http://stream.nexglotv.com:8080",
    )
    assert "Account Credentials Saved" in res_cred
    assert "lsesay" in res_cred

    # Inspect customer profile via ADMIN CRM CUSTOMER
    cust_view = admin_bot._execute_admin_command(None, "ADMIN CRM CUSTOMER 076123456")
    assert "IPTV Username: `lsesay`" in cust_view
    assert "IPTV Password: `Pass7788`" in cust_view

    # 2. Send credentials via ADMIN SEND CREDENTIALS
    send_res = admin_bot._execute_admin_command(None, "ADMIN SEND CREDENTIALS 076123456")
    assert "Credentials Successfully Delivered" in send_res

    # 3. Edit sale via ADMIN EDIT SALE
    edit_res = admin_bot._execute_admin_command(
        None,
        "ADMIN EDIT SALE 076123456 name: Lansana K. Sesay user: lsesay_new package: 3 months 2 devices",
    )
    assert "Customer Sale Info Updated" in edit_res
    assert "Lansana K. Sesay" in edit_res
    assert "lsesay_new" in edit_res

    # Verify updated customer in Lark Base
    cust = admin_bot._get_customer("+23276123456")
    assert cust is not None
    assert cust.name == "Lansana K. Sesay"
    assert cust.account_username == "lsesay_new"
    assert cust.subscription_months == 3
    assert cust.device_count == 2


def test_customer_credentials_inquiry_flow():
    settings = Settings(
        admin_token="test_admin_token",
    )
    services = build_services(settings)
    crm = services.crm.provider

    # Seed an active customer with credentials
    c = CustomerRecord(
        customer_id="CUST-CRED-TEST",
        source_lead_id="LEAD-01",
        wa_id="+23276554433",
        phone_e164="+23276554433",
        name="Aminata Turay",
        subscription_months=1,
        device_count=1,
        amount_paid_le=180,
        account_username="aminata_iptv",
        account_password="tvpassword123",
        server_url="http://stream.nexglotv.com:8080",
    )
    crm.upsert_customer(c)

    # Customer sends message asking for credentials
    msg = InboundMessage(
        message_id="msg_cred_01",
        wa_id="23276554433",
        type="text",
        profile_name="Aminata Turay",
        text="Can you send my login credentials and password?",
    )
    services.agent.handle_message(msg)

    # Check conversation messages
    history = services.store.history("23276554433", limit=5)
    bot_replies = [h["content"] for h in history if h["role"] == "assistant"]
    assert any("aminata_iptv" in r for r in bot_replies)
    assert any("tvpassword123" in r for r in bot_replies)
    assert any("http://stream.nexglotv.com:8080" in r for r in bot_replies)
