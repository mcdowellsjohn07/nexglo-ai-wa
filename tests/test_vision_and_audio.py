"""Unit and integration tests for:
1. Image Recognition of payment receipts / transaction details (Orange Money, Afrimoney, etc.)
2. Voice note recognition and transcription
3. Interactive Confirmation Blocks for all CRM writes and updates from WhatsApp
4. Confirmation / Cancellation flow committing to Lark CRM
"""

import time
import pytest
from app.config import Settings
from app.deps import build_services
from app.models import InboundMessage
from app.receipt_ocr import extract_receipt_from_text, ReceiptDetails
from app.reseller_bot import ResellerProfile


@pytest.fixture
def test_services():
    settings = Settings(
        admin_token="secret-123",
        admin_phone_numbers="+23280529239",
    )
    return build_services(settings)


def test_extract_receipt_from_text_orange_money():
    text = "Payment of SLE 150.00 to NexgloTV via Orange Money. Ref: OM98765432 on 2026-10-18 from +23276123456"
    receipt = extract_receipt_from_text(text)
    assert receipt is not None
    assert receipt.is_receipt is True
    assert receipt.provider == "Orange Money"
    assert receipt.reference == "OM98765432"
    assert receipt.amount == 150.0
    assert receipt.currency == "SLE"
    assert receipt.sender_phone == "+23276123456"


def test_extract_receipt_from_text_afrimoney():
    text = "Afrimoney cash-in successful. Txn ID: AF55443322. Amount: SLE 300. Paid to NexgloTV."
    receipt = extract_receipt_from_text(text)
    assert receipt is not None
    assert receipt.is_receipt is True
    assert receipt.provider == "Afrimoney"
    assert receipt.reference == "AF55443322"
    assert receipt.amount == 300.0


def test_image_receipt_triggers_confirmation_block(test_services):
    agent = test_services.agent
    cust_phone = "23278999111"

    # Simulated receipt image (caption contains payment proof)
    msg = InboundMessage(
        message_id="img_001",
        wa_id=cust_phone,
        type="image",
        media_id="media_img_test",
        caption="Orange Money transfer of SLE 150.00 Ref: OM11223344",
    )

    agent.handle_message(msg)
    history = agent.store.history(cust_phone, limit=2)
    last_reply = history[-1]["content"]

    # Verify confirmation block was rendered
    assert "Payment Receipt Detected" in last_reply
    assert "OM11223344" in last_reply
    assert "Orange Money" in last_reply
    assert "Reply *CONFIRM*" in last_reply
    assert "Reply *CANCEL*" in last_reply

    # Verify pending action is stored
    conv = agent.store.get_conversation(cust_phone)
    assert conv.draft.get("pending_crm_action") is not None
    assert conv.draft["pending_crm_action"]["action_type"] == "RECEIPT_PAYMENT"
    assert conv.draft["pending_crm_action"]["reference"] == "OM11223344"


def test_confirm_receipt_payment_writes_to_crm(test_services):
    agent = test_services.agent
    cust_phone = "23278999222"

    # Step 1: Send receipt image
    msg = InboundMessage(
        message_id="img_002",
        wa_id=cust_phone,
        type="image",
        media_id="media_img_test2",
        caption="Orange Money transfer of SLE 150.00 Ref: OM88997766",
    )
    agent.handle_message(msg)

    # Step 2: Customer confirms write
    msg_confirm = InboundMessage(
        message_id="txt_conf_001",
        wa_id=cust_phone,
        type="text",
        text="CONFIRM",
    )
    agent.handle_message(msg_confirm)

    history = agent.store.history(cust_phone, limit=2)
    last_reply = history[-1]["content"]

    assert "Payment Confirmed & Recorded in Lark CRM" in last_reply
    assert "OM88997766" in last_reply
    assert "NGT-RCT-" in last_reply
    assert "Subscription Status: *Active & Provisioned*" in last_reply

    # Verify pending action was cleared
    conv = agent.store.get_conversation(cust_phone)
    assert conv.draft.get("pending_crm_action") is None


def test_cancel_receipt_payment_aborts_cleanly(test_services):
    agent = test_services.agent
    cust_phone = "23278999333"

    # Step 1: Send receipt image
    msg = InboundMessage(
        message_id="img_003",
        wa_id=cust_phone,
        type="image",
        media_id="media_img_test3",
        caption="Orange Money transfer of SLE 150.00 Ref: OM44332211",
    )
    agent.handle_message(msg)

    # Step 2: Customer cancels
    msg_cancel = InboundMessage(
        message_id="txt_cancel_001",
        wa_id=cust_phone,
        type="text",
        text="CANCEL",
    )
    agent.handle_message(msg_cancel)

    history = agent.store.history(cust_phone, limit=2)
    last_reply = history[-1]["content"]

    assert "Transaction Cancelled" in last_reply
    assert "No changes or transactions were written to Lark CRM" in last_reply

    # Verify pending action was cleared
    conv = agent.store.get_conversation(cust_phone)
    assert conv.draft.get("pending_crm_action") is None


def test_voice_note_transcription_and_flow(test_services):
    agent = test_services.agent
    cust_phone = "23278999444"

    # Mock audio bytes with TEST_VOICE marker
    audio_data = b"TEST_VOICE:PRICE"

    # Mock download_media on wa client
    agent.wa.download_media = lambda mid: audio_data

    msg = InboundMessage(
        message_id="aud_001",
        wa_id=cust_phone,
        type="audio",
        media_id="media_aud_1",
    )
    agent.handle_message(msg)

    history = agent.store.history(cust_phone, limit=4)
    all_content = "\n---\n".join(h["content"] for h in history)

    # Voice was transcribed and answered price card
    assert "Heard: PRICE" in all_content or "PRICE" in all_content


def test_voice_note_can_confirm_pending_crm_action(test_services):
    agent = test_services.agent
    cust_phone = "23278999555"

    # Step 1: Send receipt
    msg = InboundMessage(
        message_id="img_004",
        wa_id=cust_phone,
        type="image",
        media_id="media_img_test4",
        caption="Orange Money SLE 150 Ref: OM33221100",
    )
    agent.handle_message(msg)

    # Step 2: Customer confirms via VOICE NOTE
    audio_confirm = b"TEST_VOICE:YES CONFIRM"
    agent.wa.download_media = lambda mid: audio_confirm

    msg_voice_conf = InboundMessage(
        message_id="aud_conf_001",
        wa_id=cust_phone,
        type="audio",
        media_id="media_aud_conf",
    )
    agent.handle_message(msg_voice_conf)

    history = agent.store.history(cust_phone, limit=4)
    all_content = "\n---\n".join(h["content"] for h in history)

    assert "Payment Confirmed & Recorded in Lark CRM" in all_content
    assert "OM33221100" in all_content
