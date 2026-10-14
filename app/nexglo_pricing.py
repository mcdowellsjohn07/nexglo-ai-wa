"""NexgloTV deterministic pricing engine and promotion calculations.

This module contains the single source of truth for all subscription pricing.
No LLM or external input can override these prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# Base regular list prices in Leones (before 20% promotional discount)
# Structure: {months: {device_count: regular_list_price}}
BASE_PRICES = {
    1:  {1: 225, 2: 400, 3: 525, "4+": 150},
    3:  {1: 625, 2: 1125, 3: 1500, "4+": 425},
    6:  {1: 1188, 2: 2125, 3: 2813, "4+": 800},
    12: {1: 2250, 2: 4000, 3: 5250, "4+": 1500},
}

DEFAULT_DISCOUNT_PCT = 20
SUPPORTED_MONTHS = (1, 3, 6, 12)


@dataclass(frozen=True)
class PriceQuote:
    """Complete price quote with full breakdown."""
    months: int
    device_count: int
    base_price: int
    discount_pct: int
    discount_amount: int
    final_price: int
    currency: str = "Le"
    quote_version: str = "v1"
    promo_active: bool = True

    def formatted_total(self) -> str:
        """Return formatted price like 'Le180'."""
        return f"{self.currency}{self.final_price:,}"

    def formatted_breakdown(self) -> str:
        """Return multi-line breakdown for customer display."""
        lines = [
            f"Base price: {self.currency}{self.base_price:,}",
            f"Discount ({self.discount_pct}%): -{self.currency}{self.discount_amount:,}",
            f"**Total: {self.formatted_total()}**",
        ]
        return "\n".join(lines)


class PricingError(ValueError):
    """Raised when pricing calculation fails due to invalid input."""
    pass


def _get_base_price(months: int, device_count: int) -> int:
    """Get the base (undiscounted) price for a package."""
    if months not in BASE_PRICES:
        raise PricingError(f"Unsupported duration: {months} months. Supported: {SUPPORTED_MONTHS}")

    row = BASE_PRICES[months]
    if not isinstance(device_count, int) or device_count < 1:
        raise PricingError("Device count must be a positive integer")

    if device_count <= 3:
        return row[device_count]
    else:
        # 4+ devices: price PER DEVICE
        return row["4+"] * device_count


def calculate_price(
    months: int,
    device_count: int,
    discount_pct: int = DEFAULT_DISCOUNT_PCT,
    currency: str = "Le",
    quote_version: str = "v1",
) -> PriceQuote:
    """Calculate the exact total after discount. All math in integers (leones)."""
    if discount_pct < 0 or discount_pct > 100:
        raise PricingError("Discount percent must be 0-100")

    base = _get_base_price(months, device_count)
    discount_amount = round(base * discount_pct / 100)
    final = base - discount_amount

    return PriceQuote(
        months=months,
        device_count=device_count,
        base_price=base,
        discount_pct=discount_pct,
        discount_amount=discount_amount,
        final_price=final,
        currency=currency,
        quote_version=quote_version,
        promo_active=discount_pct > 0,
    )


def get_all_packages(discount_pct: int = DEFAULT_DISCOUNT_PCT) -> list[PriceQuote]:
    """Generate quotes for all standard package combinations (for price card)."""
    quotes = []
    for months in SUPPORTED_MONTHS:
        for devices in (1, 2, 3, 4):
            quotes.append(calculate_price(months, devices, discount_pct))
    return quotes


def format_price_card(quotes: list[PriceQuote], currency: str = "Le") -> str:
    """Format a text-based price card for WhatsApp fallback."""
    lines = [f"📺 **NexgloTV — {quotes[0].discount_pct}% OFF Subscription Packages**", ""]

    # Group by months
    for months in SUPPORTED_MONTHS:
        month_quotes = [q for q in quotes if q.months == months]
        duration_label = f"{months} month{'s' if months > 1 else ''}"
        lines.append(f"**{duration_label}**")
        for q in month_quotes:
            if q.device_count <= 3:
                lines.append(f"  {q.device_count} device{'s' if q.device_count > 1 else ''}: {q.formatted_total()}")
            else:
                per_device = q.final_price // q.device_count
                lines.append(f"  {q.device_count}+ devices: {currency}{per_device:,} each (total {q.formatted_total()})")
        lines.append("")

    lines.append("Prices in Sierra Leonean Leones (Le). No VAT added.")
    lines.append("4+ devices priced PER DEVICE.")
    lines.append("Reply with your choice (e.g. '3 months 2 devices') or ask questions.")
    return "\n".join(lines)


def parse_package_selection(text: str) -> Optional[tuple[int, int]]:
    """Extract (months, device_count) from user text like '3 months 2 devices' or '3 meses 2 dispositivos'."""
    import re

    text = text.lower().strip()

    # Pattern: "3 months 2 devices", "3 meses 2 dispositivos", "3m 2d", "3mo 2dev"
    month_match = re.search(r'(\d+)\s*(?:months?|mo|meses|mes|m)\b', text)
    device_match = re.search(r'(\d+)\s*(?:devices?|dev|dispositivos?|disp|equipos?|pantallas?|d)\b', text)

    # Alternative: "for 2 devices" / "para 2 dispositivos"
    if not device_match:
        device_match = re.search(r'(?:for|para)\s+(\d+)\s*(?:devices?|dispositivos?|equipos?|pantallas?)?', text)
    if not month_match:
        month_match = re.search(r'(\d+)\s*(?:months?|meses|mes)\s*(?:for|para|$)', text)

    if month_match and device_match:
        months = int(month_match.group(1))
        devices = int(device_match.group(1))
        if months in SUPPORTED_MONTHS and devices >= 1:
            return months, devices

    return None