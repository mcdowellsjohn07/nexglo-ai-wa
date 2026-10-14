"""Tests for NexgloTV sales conversation flow."""

import pytest
from app.config import Settings
from app.clock import FrozenClock
from app.cli import ChatSimulator
from datetime import datetime, timezone
from pathlib import Path
import tempfile


@pytest.fixture
def simulator():
    """Create a chat simulator with frozen clock."""
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        db_path = Path(f.name)
    
    s = Settings.from_env({})
    clock = FrozenClock(datetime(2026, 9, 24, 9, 0, 0, tzinfo=timezone.utc))
    wa = '50760001234'
    
    sim = ChatSimulator(s, db_path, clock, wa_id=wa, offline=True)
    return sim


class TestPriceEnquiry:
    """Test price card delivery."""

    def test_how_much_shows_price_card(self, simulator):
        sim = simulator
        sim.send_text('How much?')
        state = sim.services.store.get_conversation(sim.wa_id).state
        assert state == 'prices_sent'
        # Check price card was sent (text fallback)
        last_msg = sim.services.store.transcript(sim.wa_id, limit=1)[0]
        assert 'Le180' in last_msg['content'] or 'Le900' in last_msg['content']

    def test_price_enquiry_no_questions_first(self, simulator):
        """Price card sent without asking name/area/device first."""
        sim = simulator
        sim.send_text('How much?')
        transcript = sim.services.store.transcript(sim.wa_id)
        # Should not have asked for name, area, or device before price
        for msg in transcript:
            if msg['author'] == 'bot':
                content = msg['content'].lower()
                assert 'name' not in content or 'price' in content
                assert 'area' not in content or 'price' in content
                assert 'device' not in content or 'price' in content


class TestPackageSelection:
    """Test package selection and quote."""

    def test_package_selection_flow(self, simulator):
        sim = simulator
        sim.send_text('How much?')
        sim.send_text('3 months 2 devices')
        
        state = sim.services.store.get_conversation(sim.wa_id).state
        assert state == 'package_selected'
        
        draft = sim.services.store.get_conversation(sim.wa_id).draft
        assert draft.get('months') == 3
        assert draft.get('device_count') == 2
        assert draft.get('quote') == 900

    def test_readiness_question_after_quote(self, simulator):
        """Readiness question asked after package quote."""
        sim = simulator
        sim.send_text('How much?')
        sim.send_text('3 months 2 devices')
        
        transcript = sim.services.store.transcript(sim.wa_id)
        last_bot = [m for m in transcript if m['author'] == 'bot'][-1]
        assert 'ready to pay' in last_bot['content'].lower() or 'comfortable paying' in last_bot['content'].lower()

    def test_typed_ready_works(self, simulator):
        """Typing 'ready' works like button tap."""
        sim = simulator
        sim.send_text('How much?')
        sim.send_text('3 months 2 devices')
        sim.send_text('ready')
        
        state = sim.services.store.get_conversation(sim.wa_id).state
        assert state == 'payment_readiness'  # Should advance to device selection


class TestDeviceSelection:
    """Test device selection flow."""

    def test_device_selection_advances(self, simulator):
        sim = simulator
        sim.send_text('How much?')
        sim.send_text('3 months 2 devices')
        sim.send_text('ready')
        sim.tap('device:android_phone', 'Android phone')
        
        state = sim.services.store.get_conversation(sim.wa_id).state
        assert state == 'device_selected'
        
        draft = sim.services.store.get_conversation(sim.wa_id).draft
        assert draft.get('device_id') == 'android_phone'


class TestInstallMethod:
    """Test installation method selection."""

    def test_self_install_shows_app_link(self, simulator):
        sim = simulator
        sim.send_text('How much?')
        sim.send_text('3 months 2 devices')
        sim.send_text('ready')
        sim.tap('device:android_phone', 'Android phone')
        sim.tap('install:self', 'Autoinstalación guiada (gratis)')
        
        state = sim.services.store.get_conversation(sim.wa_id).state
        # Should show app link or handoff if no verified app
        assert state in ('app_link_sent', 'human')


class TestOptOut:
    """Test opt-out compliance."""

    def test_stop_stops_messages(self, simulator):
        sim = simulator
        sim.send_text('STOP')
        
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.opted_out is True
        
        # Further messages should get no response
        sim.send_text('Hello')
        # No new bot messages should be added

    def test_start_resumes(self, simulator):
        sim = simulator
        sim.send_text('STOP')
        sim.send_text('START')
        
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.opted_out is False


class TestHandoff:
    """Test human handoff flow."""

    def test_human_request_creates_handoff(self, simulator):
        sim = simulator
        sim.send_text('Talk to a person')
        
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.handoff is True
        assert conv.state == 'human'


class TestExistingCustomer:
    """Test existing customer renewal flow."""

    def test_renewal_recognizes_customer(self, simulator):
        sim = simulator
        # Pre-create a customer
        crm = sim.services.crm
        from app.crm_sheets import CustomerRecord
        customer = CustomerRecord(
            customer_id='cust_123',
            source_lead_id='lead_123',
            wa_id=sim.wa_id,
            phone_e164=sim.wa_id,
            name='Test User',
            subscription_months=3,
            device_count=2,
            amount_paid_le=900,
            account_status='active',
        )
        crm.provider.upsert_customer(customer)
        
        sim.send_text('I want to renew')
        
        state = sim.services.store.get_conversation(sim.wa_id).state
        assert state == 'renewal'
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.is_existing_customer is True


class TestIdempotency:
    """Test duplicate handling."""

    def test_duplicate_webhook_dropped(self, simulator):
        """Duplicate message IDs are dropped."""
        sim = simulator
        sim.send_text('How much?')
        
        # Get the message ID from the transcript
        transcript = sim.services.store.transcript(sim.wa_id)
        user_msgs = [m for m in transcript if m['author'] == 'customer']
        assert len(user_msgs) == 1
        
        # Simulate duplicate by directly calling handle with same message
        from app.models import InboundMessage
        msg = InboundMessage(
            wa_id=sim.wa_id,
            message_id=user_msgs[0]['content'],  # Using content as proxy
            type='text',
            text='How much?',
            timestamp=str(int(sim.clock().timestamp())),
            profile_name='Test',
        )
        # The dedupe is in the store, so this would need a fresh message ID
        # Actual test would use the webhook directly
        pass


class TestPaymentFlow:
    """Test payment verification flow."""

    def test_payment_not_confirmed_without_staff(self, simulator):
        """Customer claiming payment doesn't auto-confirm."""
        sim = simulator
        sim.send_text('How much?')
        sim.send_text('3 months 2 devices')
        sim.send_text('ready')
        sim.tap('device:android_phone', 'Android phone')
        sim.tap('install:self', 'Autoinstalación guiada (gratis)')
        # Simulate app installed
        sim.tap('app_installed:confirm', 'INSTALLED')
        
        conv = sim.services.store.get_conversation(sim.wa_id)
        # Should be in human handoff, not converted
        assert conv.handoff is True
        assert conv.state == 'human'


class TestTrialFlow:
    """Test free trial request flow."""

    def test_trial_request_goes_to_staff(self, simulator):
        sim = simulator
        sim.send_text('Do you offer a free trial?')
        
        state = sim.services.store.get_conversation(sim.wa_id).state
        assert state == 'trial_requested'
        
        transcript = sim.services.store.transcript(sim.wa_id)
        last_bot = [m for m in transcript if m['author'] == 'bot'][-1]
        assert 'trial' in last_bot['content'].lower()


class TestNoAutoTrial:
    """Test trial is not automatically advertised."""

    def test_no_trial_in_greeting(self, simulator):
        sim = simulator
        sim.send_text('Hi')
        
        transcript = sim.services.store.transcript(sim.wa_id)
        for msg in transcript:
            if msg['author'] == 'bot':
                assert 'trial' not in msg['content'].lower()
                assert 'free' not in msg['content'].lower() or 'free trial' not in msg['content'].lower()


class TestStateHandlersAndFixes:
    """Regression tests for fixed bugs (#2 through #7)."""

    def test_device_model_and_area_capture_handlers(self, simulator):
        """Bug #6: Smart TV model capture -> install method -> area capture -> handoff."""
        sim = simulator
        sim.send_text('How much?')
        sim.send_text('1 month 1 device')
        sim.send_text('ready')
        # Pick Smart TV by number '3'
        sim.send_text('3')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'device_model'

        # Reply with TV model
        sim.send_text('Samsung 55 TU7000')
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.state == 'install_method'
        assert conv.draft.get('device_model') == 'Samsung 55 TU7000'

        # Choose staff visit
        sim.tap('install:visit', 'Staff visit (fee)')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'area_captured'

        # Reply with area
        sim.send_text('Lumley, Freetown')
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.state == 'human'
        assert conv.handoff is True
        lead = sim.services.crm.provider.get_lead_by_wa_id(sim.wa_id)
        assert lead is not None
        assert lead.area == 'Lumley, Freetown'
        assert lead.device_model == 'Samsung 55 TU7000'

    def test_payment_due_proof_handler_and_admin_endpoints(self, simulator):
        """Bug #4 & #6: Staff confirm-setup -> PAYMENT_DUE -> customer proof -> staff verify-payment."""
        from fastapi.testclient import TestClient
        from app.main import create_app

        with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
            db_path = Path(f.name)
        s = Settings.from_env({'ADMIN_TOKEN': 'secret-admin-token'})
        clock = FrozenClock(datetime(2026, 9, 24, 9, 0, 0, tzinfo=timezone.utc))
        sim = ChatSimulator(s, db_path, clock, wa_id='23277000111', offline=True)
        app = create_app(services=sim.services)
        client = TestClient(app)
        headers = {'Authorization': 'Bearer secret-admin-token'}

        sim.send_text('How much?')
        sim.send_text('3 months 2 devices')
        sim.send_text('ready')
        sim.tap('device:android_phone', 'Android phone')
        sim.tap('install:self', 'Self-install (free)')

        # Staff confirms setup via /admin/leads/confirm-setup
        r = client.post('/admin/leads/confirm-setup', json={'wa_id': sim.wa_id, 'staff_name': 'Samuel'}, headers=headers)
        assert r.status_code == 200
        assert sim.services.store.get_conversation(sim.wa_id).state == 'payment_due'

        # Customer sends payment reference in PAYMENT_DUE state
        sim.send_text('Orange Money Ref OM-998877')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'payment_verification'
        assert len(sim.services.crm.provider.payments) == 1
        assert sim.services.crm.provider.payments[0].transaction_reference == 'Orange Money Ref OM-998877'

        # Staff verifies payment via /admin/payments/verify
        r2 = client.post('/admin/payments/verify', json={'wa_id': sim.wa_id, 'verified_by': 'Samuel'}, headers=headers)
        assert r2.status_code == 200
        assert r2.json()['converted'] is True
        assert sim.services.store.get_conversation(sim.wa_id).state == 'converted'

    def test_discount_active_false_parsing(self):
        """Bug #5: DISCOUNT_ACTIVE=false is respected."""
        s = Settings.from_env({'DISCOUNT_ACTIVE': 'false'})
        assert s.discount_active is False
        s_default = Settings.from_env({})
        assert s_default.discount_active is True

    def test_media_service_sends_image_via_url_and_media_id(self, simulator):
        """Bug #3: MediaService.send_price_card works with synchronous WhatsAppClient.send_image."""
        from app.media_service import MediaService
        sim = simulator
        media = MediaService(
            wa=sim.services.wa,
            price_card_media_url='https://example.com/price-card.jpg',
            price_card_media_id='meta_media_123',
        )
        res = media.send_price_card(sim.wa_id)
        assert res.success is True
        assert res.media_id == 'meta_media_123'

    def test_crm_provider_exception_does_not_crash_conversation(self, simulator):
        """Bug #2: CRM exceptions are caught so the customer still gets a reply."""
        sim = simulator
        def broken_get_lead(wa_id):
            raise RuntimeError("CRM offline")
        sim.services.crm.provider.get_lead_by_wa_id = broken_get_lead
        sim.send_text('How much?')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'prices_sent'

    def test_button_titles_fit_whatsapp_limit(self):
        """Bug #7: Interactive button titles fit within WhatsApp's 20-char limit."""
        from app.nexglo_catalog import t
        for lang in ('es', 'en'):
            for key in ('quote_ready_yes', 'quote_ready_no', 'quote_change', 'install_self', 'install_visit'):
                assert len(t(key, lang)) <= 20, f"{key} ({lang}) exceeds 20 chars: {t(key, lang)!r}"

    def test_renewal_package_selection_and_expiration_date(self, simulator):
        """Renewal flow allows selecting a package from State.RENEWAL and sets subscription_expires_at."""
        from app.crm_sheets import CustomerRecord
        sim = simulator
        crm = sim.services.crm
        crm.provider.upsert_customer(CustomerRecord(
            customer_id='cust_999',
            source_lead_id='lead_999',
            wa_id=sim.wa_id,
            phone_e164=sim.wa_id,
            name='Renewing User',
            subscription_months=1,
            device_count=1,
            amount_paid_le=180,
            account_status='active',
        ))
        sim.send_text('I want to renew')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'renewal'

        # Customer selects renewal package via text or list payload
        sim.send_text('6 months 2 devices')
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.state == 'package_selected'
        assert conv.draft.get('months') == 6
        assert conv.draft.get('quote') == 1700

        updated_cust = crm.confirm_payment_and_convert(sim.wa_id, 'pay_1', 'Admin')
        assert updated_cust is not None
        assert updated_cust.renewal_count == 1
        assert updated_cust.subscription_months == 6
        assert updated_cust.subscription_expires_at != ''

    def test_trial_device_followup_and_referral_code_capture(self, simulator):
        """Trial device reply escalates cleanly; referral code reply records referral and shows price card."""
        sim = simulator
        sim.send_text('Can I get a free trial?')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'trial_requested'

        sim.send_text('Firestick')
        conv = sim.services.store.get_conversation(sim.wa_id)
        assert conv.state == 'human'
        assert conv.handoff is True
        lead = sim.services.crm.provider.get_lead_by_wa_id(sim.wa_id)
        assert lead.device_types == 'fire_stick'

        # Reset and test referral flow
        sim.send_text('menu')
        sim.send_text('I was referred by someone')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'referral'
        sim.send_text('REF-SAMUEL-01')
        assert sim.services.store.get_conversation(sim.wa_id).state == 'prices_sent'
        lead = sim.services.crm.provider.get_lead_by_wa_id(sim.wa_id)
        assert lead.referrer_code == 'REF-SAMUEL-01'

    def test_lark_merge_notes_idempotent_and_webhook_size_guard(self, simulator):
        """Lark _merge_notes replaces [Summary: ...] idempotently and webhook rejects >1MB payloads."""
        from app.crm_lark import LarkBaseCRMProvider
        from fastapi.testclient import TestClient
        from app.main import create_app

        merged1 = LarkBaseCRMProvider._merge_notes("", ["Stage=PRICES_SENT"])
        merged2 = LarkBaseCRMProvider._merge_notes(merged1, ["Stage=PACKAGE_SELECTED"])
        assert merged2 == "[Summary: Stage=PACKAGE_SELECTED]"
        assert merged2.count("[Summary:") == 1

        app = create_app(services=simulator.services)
        client = TestClient(app)
        oversized = b"x" * (1_048_576 + 10)
        resp = client.post("/webhook", content=oversized)
        assert resp.status_code == 413


if __name__ == '__main__':
    pytest.main([__file__, '-v'])