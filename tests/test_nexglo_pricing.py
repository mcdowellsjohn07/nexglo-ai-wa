"""Tests for NexgloTV deterministic pricing engine."""

import pytest
from app.nexglo_pricing import (
    calculate_price,
    parse_package_selection,
    format_price_card,
    PriceQuote,
    PricingError,
)


class TestPricingCalculations:
    """Test exact price calculations match specification."""

    def test_3_months_2_devices(self):
        q = calculate_price(3, 2)
        assert q.final_price == 720
        assert q.base_price == 900
        assert q.discount_pct == 20
        assert q.discount_amount == 180

    def test_4_devices_3_months_per_device(self):
        q = calculate_price(3, 4)
        assert q.final_price == 1088  # 272 * 4

    def test_5_devices_12_months(self):
        q = calculate_price(12, 5)
        assert q.final_price == 4800  # 960 * 5

    def test_all_standard_packages(self):
        expected = {
            (1, 1): 144, (1, 2): 256, (1, 3): 336, (1, 4): 384,
            (3, 1): 400, (3, 2): 720, (3, 3): 960, (3, 4): 1088,
            (6, 1): 760, (6, 2): 1360, (6, 3): 1800, (6, 4): 2048,
            (12, 1): 1440, (12, 2): 2560, (12, 3): 3360, (12, 4): 3840,
        }
        for (months, devices), expected_price in expected.items():
            q = calculate_price(months, devices)
            assert q.final_price == expected_price, f"{months}m x {devices}d"

    def test_no_double_discount(self):
        """Ensure 20% is applied once, not twice."""
        q = calculate_price(3, 2, discount_pct=20)
        # Base 900, 20% = 180 off, final 720
        assert q.final_price == 720
        # If applied twice: 900 * 0.8 * 0.8 = 576 (wrong)
        assert q.final_price != 576

    def test_integer_math_no_float(self):
        """All calculations use integer arithmetic."""
        q = calculate_price(3, 2)
        assert isinstance(q.final_price, int)
        assert isinstance(q.base_price, int)
        assert isinstance(q.discount_amount, int)


class TestPackageParsing:
    """Test parsing user package selections."""

    def test_parse_explicit(self):
        assert parse_package_selection("3 months 2 devices") == (3, 2)
        assert parse_package_selection("4 devices for 3 months") == (3, 4)
        assert parse_package_selection("5 devices 12 months") == (12, 5)

    def test_parse_variations(self):
        assert parse_package_selection("3m 2d") == (3, 2)
        assert parse_package_selection("1 month 1 device") == (1, 1)

    def test_invalid_returns_none(self):
        assert parse_package_selection("hello") is None
        assert parse_package_selection("2 months") is None  # missing devices
        assert parse_package_selection("5 devices") is None  # missing months


class TestPriceCardFormatting:
    """Test price card text output."""

    def test_format_contains_all_packages(self):
        quotes = [calculate_price(m, d) for m in (1, 3, 6, 12) for d in (1, 2, 3, 4)]
        card = format_price_card(quotes)
        assert "20% OFF" in card
        assert "Le144" in card
        assert "Le720" in card
        assert "PER DEVICE" in card
        assert "4+ devices priced PER DEVICE" in card


class TestPricingErrors:
    """Test error handling."""

    def test_invalid_months_raises(self):
        with pytest.raises(PricingError):
            calculate_price(2, 1)  # 2 months not supported

    def test_invalid_devices_raises(self):
        with pytest.raises(PricingError):
            calculate_price(3, 0)

    def test_invalid_discount_raises(self):
        with pytest.raises(PricingError):
            calculate_price(3, 2, discount_pct=150)