"""BM25 retriever over the NexgloTV knowledge base."""

from __future__ import annotations


def test_kb_loaded(kb):
    assert len(kb.chunks) >= 8
    sources = {c.source for c in kb.chunks}
    assert "01_packages_and_discount.md" in sources
    assert "04_devices_and_app_setup.md" in sources


def test_price_question_retrieves_prices(kb):
    hits = kb.search("cuánto cuesta un paquete de suscripción", k=3)
    assert hits
    joined = " ".join(h.source for h in hits)
    assert "01_packages_and_discount.md" in joined


def test_devices_question_retrieves_devices(kb):
    hits = kb.search("en qué dispositivos puedo instalar la app", k=3)
    assert hits
    assert any(h.source == "04_devices_and_app_setup.md" for h in hits)


def test_accent_insensitive_match(kb):
    # "instalacion" (no accent) should still find installation articles.
    hits = kb.search("como funciona la instalacion", k=3)
    assert any(h.source in ("04_devices_and_app_setup.md", "05_installation_fees_and_locations.md") for h in hits)


def test_context_is_nonempty_string(kb):
    ctx = kb.context("promociones y descuentos", k=2)
    assert isinstance(ctx, str) and len(ctx) > 0
