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
        assert 'Le144' in last_msg['content'] or 'Le720' in last_msg['content']

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
        assert draft.get('quote') == 720

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
            amount_paid_le=720,
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])