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
    """Test exact price calculations match approved commercial specification."""

    def test_1_month_1_device(self):
        q = calculate_price(1, 1)
        assert q.base_price == 225
        assert q.discount_pct == 20
        assert q.discount_amount == 45
        assert q.final_price == 180

    def test_3_months_2_devices(self):
        q = calculate_price(3, 2)
        assert q.final_price == 900
        assert q.base_price == 1125
        assert q.discount_pct == 20
        assert q.discount_amount == 225

    def test_4_devices_3_months_per_device(self):
        q = calculate_price(3, 4)
        assert q.final_price == 1360  # 340 * 4
        assert q.base_price == 1700   # 425 * 4

    def test_5_devices_12_months(self):
        q = calculate_price(12, 5)
        assert q.final_price == 6000  # 1200 * 5
        assert q.base_price == 7500   # 1500 * 5

    def test_all_standard_packages(self):
        expected = {
            (1, 1): 180, (1, 2): 320, (1, 3): 420, (1, 4): 480,
            (3, 1): 500, (3, 2): 900, (3, 3): 1200, (3, 4): 1360,
            (6, 1): 950, (6, 2): 1700, (6, 3): 2250, (6, 4): 2560,
            (12, 1): 1800, (12, 2): 3200, (12, 3): 4200, (12, 4): 4800,
        }
        for (months, devices), expected_price in expected.items():
            q = calculate_price(months, devices)
            assert q.final_price == expected_price, f"{months}m x {devices}d"

    def test_no_double_discount(self):
        """Ensure 20% is applied once, not twice (e.g. 225 -> 180, not 144)."""
        q = calculate_price(1, 1, discount_pct=20)
        assert q.base_price == 225
        assert q.final_price == 180
        # If applied twice: 225 * 0.8 * 0.8 = 144 (wrong)
        assert q.final_price != 144

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
        assert "Le180" in card
        assert "Le900" in card
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
            calculate_price(1, 1, discount_pct=-5)
        with pytest.raises(PricingError):
            calculate_price(1, 1, discount_pct=105)