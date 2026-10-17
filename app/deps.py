"""Service wiring.

``build_services`` assembles the store, knowledge base, LLM client, WhatsApp
client and agent from a ``Settings`` object. Nothing is built at import time:
the FastAPI app creates its services on startup (or on the first request), and
tests or the chat simulator build their own with a temp database, a fake
WhatsApp client and a frozen clock. Importing ``app.webhook`` or ``app.main``
therefore never creates ``data/nexglotv.sqlite`` as a side effect.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from .automations import AutomationRunner
from .clock import Clock, system_clock
from .config import Settings, get_settings
from .crm_sheets import CRMService, create_crm_provider
from .kb import KnowledgeBase
from .llm import LLMClient
from .media_service import MediaService
from .nexglo_agent import Agent
from .nexglo_state import Store
from .wa_client import DryRunTransport, Transport, WhatsAppClient

log = logging.getLogger("nexglo.deps")


@dataclass
class Services:
    settings: Settings
    store: Store
    kb: KnowledgeBase
    llm: LLMClient
    wa: WhatsAppClient
    agent: Agent
    crm: CRMService
    media: MediaService
    clock: Clock
    automations: Optional[AutomationRunner] = None
    reseller_mgr: Optional[Any] = None
    admin_bot: Optional[Any] = None


def build_services(
    settings: Optional[Settings] = None,
    *,
    db_path: Optional[Path] = None,
    clock: Optional[Clock] = None,
    llm=None,
    wa=None,
    transport: Optional[Transport] = None,
    http_client: Optional[httpx.Client] = None,
) -> Services:
    """Wire up the app. Every collaborator can be swapped for a fake."""
    settings = settings or get_settings()
    clock = clock if clock is not None else system_clock
    default_mode = getattr(settings, "auto_reply_mode", "selective")
    turso_url = settings.turso_database_url if not db_path else None
    turso_token = settings.turso_auth_token if not db_path else None
    store = Store(
        db_path or settings.db_path,
        settings.schema_path,
        clock=clock,
        default_auto_reply_mode=default_mode,
        turso_url=turso_url,
        turso_token=turso_token,
    )
    kb = KnowledgeBase(settings.kb_dir)
    llm = llm if llm is not None else LLMClient(settings)

    # CRM provider
    crm_provider_name = getattr(settings, "crm_provider", "mock")
    crm_provider = None
    if crm_provider_name == "lark_base":
        try:
            from .crm_lark import create_lark_provider
            crm_provider = create_lark_provider(
                base_token=getattr(settings, "lark_base_token", ""),
                auto_create=True,
            )
            log.info("CRM provider: Lark Base (%s)", getattr(crm_provider, "base_token", "?"))
        except Exception as exc:
            log.warning("Lark Base CRM unavailable (%s); falling back to mock", exc)
            crm_provider = None
    if crm_provider is None:
        crm_provider = create_crm_provider(
            provider=crm_provider_name,
            sheet_id=getattr(settings, "google_sheet_id", ""),
            service_account_json=getattr(settings, "google_service_account_json", ""),
        )
    crm = CRMService(crm_provider)

    # Media service
    media = MediaService(
        wa=None,  # Will be set after wa is created
        price_card_media_url=getattr(settings, "price_card_media_url", ""),
        price_card_media_id=getattr(settings, "price_card_media_id", ""),
    )

    if wa is None:
        wa = WhatsAppClient(settings, transport=transport, http_client=http_client, store=store)

    # Update media with wa client
    media.wa = wa

    # Restore persistent settings from store (survives deploys & dyno restarts)
    if hasattr(store, "get_setting"):
        saved_model = store.get_setting("active_model", "")
        if saved_model and hasattr(llm, "set_model"):
            try:
                llm.set_model(saved_model)
                log.info("Restored persisted active model: %s", saved_model)
            except Exception as exc:
                log.warning("Could not restore active model %s: %s", saved_model, exc)

        saved_dry = store.get_setting("dry_run", "")
        if saved_dry in ("0", "1", "true", "false") and hasattr(wa, "set_dry_run"):
            try:
                wa.set_dry_run(saved_dry in ("1", "true"))
                log.info("Restored persisted dry_run setting: %s", wa.dry_run)
            except Exception as exc:
                log.warning("Could not restore dry_run setting: %s", exc)

    from .reseller_bot import ResellerBotManager
    reseller_mgr = ResellerBotManager(getattr(crm, "provider", None), store=store)

    from .admin_bot import AdminBotManager
    admin_bot = AdminBotManager(
        settings=settings,
        store=store,
        llm=llm,
        wa=wa,
        crm=crm,
        reseller_mgr=reseller_mgr,
    )

    agent = Agent(
        settings=settings,
        wa=wa,
        store=store,
        kb=kb,
        llm=llm,
        crm=crm,
        media=media,
        clock=clock,
        reseller_mgr=reseller_mgr,
        admin_bot=admin_bot,
    )
    svc = Services(
        settings=settings,
        store=store,
        kb=kb,
        llm=llm,
        wa=wa,
        agent=agent,
        crm=crm,
        media=media,
        clock=clock,
        reseller_mgr=reseller_mgr,
        admin_bot=admin_bot,
    )
    svc.automations = AutomationRunner(svc)
    return svc


# --------------------------------------------------------------- default app
_default: Optional[Services] = None
_lock = threading.Lock()


def default_services() -> Services:
    """Process-wide services built from the environment, created on first use."""
    global _default
    if _default is None:
        with _lock:
            if _default is None:
                _default = build_services(get_settings())
    return _default


def __getattr__(name: str):
    # Backwards compatibility with the old module-level singletons
    # (``from app.deps import agent, store``), now built lazily.
    if name in {"settings", "store", "kb", "llm", "wa", "agent", "crm", "media"}:
        return getattr(default_services(), name)
    raise AttributeError(name)
