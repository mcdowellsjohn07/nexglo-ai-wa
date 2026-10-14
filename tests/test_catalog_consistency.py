"""The NexgloTV catalog/pricing (app/nexglo_pricing.py & app/nexglo_catalog.py)
and the knowledge base (kb/01_packages_and_discount.md) must not drift apart.
"""

from __future__ import annotations

from app.nexglo_catalog import DEVICE_PLATFORMS, PACKAGE_MONTHS, t
from app.nexglo_pricing import calculate_price

from .conftest import REPO_ROOT

KB = REPO_ROOT / "kb"


def test_prices_table_matches_nexglo_pricing():
    text = (KB / "01_packages_and_discount.md").read_text(encoding="utf-8")
    for months in PACKAGE_MONTHS:
        for devices in (1, 2, 3):
            quote = calculate_price(months, devices)
            assert quote.formatted_total() in text, (months, devices, quote.formatted_total())
        per_dev = calculate_price(months, 4).final_price // 4
        assert f"Le{per_dev:,} each" in text, (months, per_dev)


def test_device_platforms_have_required_fields():
    assert len(DEVICE_PLATFORMS) >= 8
    for dev in DEVICE_PLATFORMS:
        assert dev.get("id") and dev.get("label") and dev.get("os")


def test_list_row_titles_fit_whatsapp_limits():
    list_keys = [
        "menu_packages",
        "menu_devices",
        "menu_renewal",
        "menu_support",
        "menu_human",
        "menu_main",
    ]
    for key in list_keys:
        for lang in ("es", "en"):
            assert len(t(key, lang)) <= 24, (key, lang, t(key, lang))


def test_button_labels_fit_whatsapp_limits():
    button_keys = [
        "menu_button",
        "package_button",
        "quote_ready_yes",
        "quote_ready_no",
        "quote_change",
        "install_self",
        "install_visit",
        "menu_human",
        "menu_main",
    ]
    for key in button_keys:
        for lang in ("es", "en"):
            assert len(t(key, lang)) <= 20, (key, lang, t(key, lang))
