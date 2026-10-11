"""NexgloTV conversation orchestrator — replaces the barbershop agent."""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .config import Settings
from .crm_sheets import CRMService, create_crm_provider
from .kb import KnowledgeBase
from .llm import LLMClient
from .media_service import MediaService
from .models import InboundMessage
from .nexglo_catalog import (
    DEVICE_PLATFORMS,
    INSTALL_METHODS,
    INSTALL_BY_ID,
    STRINGS,
    device_label,
    get_device,
    pluralize,
    t,
)
from .nexglo_devices import device_app_directory
from .nexglo_pricing import PriceQuote, calculate_price, format_price_card, parse_package_selection
from .nexglo_state import (
    Conversation,
    IllegalTransition,
    State,
    Store,
    can_transition,
    payload_allowed,
)
from .payment_service import format_payment_message, payment_config
from .transcribe import transcribe_audio
from .wa_client import WhatsAppClient

log = logging.getLogger("nexglo_agent")

# How far ahead customers can see packages (not really needed for NexgloTV)
LIST_ROWS = 10  # WhatsApp's hard limit per list message

# --- Language / intent lexicons --------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9]+")


ES_HINTS = {
    "hola", "gracias", "paquete", "paquetes", "precio", "precios", "dispositivo", "dispositivos",
    "cuanto", "cuanta", "donde", "quiero", "ver", "buenas", "buenos", "para", "una", "que",
    "como", "cuando", "tienen", "abierto", "abren", "cierran", "mes", "meses", "instalar",
    "instalacion", "app", "aplicacion", "pagar", "pago", "orange", "afrimoney", "qmoney",
    "transferencia", "efectivo", "renovar", "renovacion", "soporte", "ayuda", "problema",
    "canal", "canales", "deportes", "futbol", "internet", "wifi", "prueba", "gratis",
    "referido", "referral", "hablar", "persona", "cancelar", "suscripcion", "baja", "alta",
    "mi", "mis", "el", "la", "los", "las", "hoy", "manana", "por", "favor", "necesito",
    "puedo", "cuesta", "cuestan", "ustedes", "estan", "hay", "dias", "tardes", "noches",
    "si", "claro", "vale", "nombre", "llamo", "instalado", "instalada", "listo",
}
EN_HINTS = {
    "hi", "hello", "thanks", "thank", "price", "prices", "package", "packages", "device",
    "devices", "month", "months", "install", "installation", "app", "application",
    "pay", "payment", "orange", "afrimoney", "qmoney", "transfer", "cash", "renew",
    "renewal", "support", "help", "problem", "channel", "channels", "sports", "football",
    "internet", "wifi", "trial", "free", "referral", "refer", "talk", "person",
    "cancel", "subscription", "stop", "start", "my", "today", "tomorrow", "please",
    "need", "cost", "how", "much", "what", "when", "where", "yes", "ready", "installed",
    "set up", "setup", "working", "works",
}
GREETING_KW = {
    "hola", "buenas", "buenos", "dias", "tardes", "noches", "hey", "hi", "hello",
    "menu", "inicio", "ola", "saludos", "good", "morning", "afternoon", "evening",
}
PRICE_KW = {
    "precio", "precios", "cuanto", "cuesta", "cuestan", "vale", "paquete", "paquetes",
    "plan", "planes", "package", "packages", "price", "prices", "cost", "how", "much",
}
DEVICE_KW = {
    "dispositivo", "dispositivos", "telefono", "movil", "celular", "smart tv", "televisor",
    "fire stick", "firestick", "tablet", "laptop", "computadora", "pc", "android tv box",
    "roku", "iphone", "ipad", "device", "devices", "phone", "mobile", "tv", "fire",
    "stick", "laptop", "computer",
}
INSTALL_KW = {
    "instalar", "instalacion", "install", "installation", "setup", "configurar",
    "visita", "visit", "tecnico", "technician", "tecnico", "visit",
}
TRIAL_KW = {
    "prueba", "gratis", "free trial", "trial", "test", "probar", "try",
}
HUMAN_KW = {
    "humano", "persona", "agente", "asesor", "reclamo", "queja", "urgente",
    "emergencia", "human", "agent", "person", "manager", "complaint",
    "representative", "hablar", "alguien", "someone",
}
RESET_KW = {
    "reset", "reiniciar", "inicio", "menu", "start", "cancelar", "cancel", "volver",
    "salir", "exit", "restart", "menú",
}
RENEWAL_KW = {
    "renovar", "renovacion", "renew", "renewal", "extender", "continuar",
}
SUPPORT_KW = {
    "soporte", "ayuda", "help", "support", "problema", "problem", "error", "falla",
    "no funciona", "not working", "buffering", "login", "acceso", "canal", "channel",
}
CHANNELS_KW = {
    "canales", "channels", "deportes", "sports", "futbol", "football", "premier league",
    "champions league", "laliga", "super sport", "dstv", "peliculas", "movies",
    "series", "ninos", "kids", "noticias", "news",
}
INTERNET_KW = {
    "internet", "wifi", "wifi", "mifi", "datos", "data", "velocidad", "speed", "mbps",
    "qcell", "africell", "sierratel",
}
REFERRAL_KW = {
    "referido", "referral", "recomendar", "recommend", "codigo", "code", "reseller", "revendedor",
}
OPT_OUT_ES = {
    "baja", "darme de baja", "dar de baja", "de baja", "cancelar suscripcion",
    "no mas mensajes", "no quiero mas mensajes", "no me escriban mas",
}
OPT_OUT_EN = {"unsubscribe", "opt out", "optout", "stop all", "stopall"}
OPT_OUT_ANY = {"stop"}
OPT_IN_ES = {"alta", "darme de alta", "dar de alta", "suscribirme", "reanudar"}
OPT_IN_EN = {"subscribe", "unstop", "opt in", "optin"}
OPT_IN_ANY = {"start"}


def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(_strip_accents(text).lower()))


def _norm(text: str) -> str:
    return " ".join(_TOKEN_RE.findall(_strip_accents(text).lower()))


def detect_lang(text: str) -> Optional[str]:
    toks = _tokens(text)
    es = len(toks & ES_HINTS) + (1 if ("¿" in text or "¡" in text) else 0)
    en = len(toks & EN_HINTS)
    if en > es:
        return "en"
    if es > en:
        return "es"
    return None


def is_opt_out(text: str) -> bool:
    return _norm(text) in OPT_OUT_ES | OPT_OUT_EN | OPT_OUT_ANY


def is_opt_in(text: str) -> bool:
    return _norm(text) in OPT_IN_ES | OPT_IN_EN | OPT_IN_ANY


def is_reset(text: str) -> bool:
    toks = _tokens(text)
    return bool(toks) and len(toks) <= 3 and bool(toks & RESET_KW)


def _keyword_lang(text: str) -> Optional[str]:
    norm = _norm(text)
    if norm in OPT_OUT_ES | OPT_IN_ES:
        return "es"
    if norm in OPT_OUT_EN | OPT_IN_EN:
        return "en"
    return None


class Agent:
    def __init__(
        self,
        settings: Settings,
        wa: WhatsAppClient,
        store: Store,
        kb: KnowledgeBase,
        llm: LLMClient,
        crm: CRMService,
        media: MediaService,
        clock=None,
    ):
        self.settings = settings
        self.wa = wa
        self.store = store
        self.kb = kb
        self.llm = llm
        self.crm = crm
        self.media = media
        self.clock = clock
        try:
            self.tz = ZoneInfo(settings.timezone)
        except Exception:
            log.warning("Unknown BUSINESS_TIMEZONE %r; using UTC", settings.timezone)
            self.tz = ZoneInfo("UTC")
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ================================================================= entry
    def handle_message(self, msg: InboundMessage) -> None:
        with self._lock_for(msg.wa_id):
            try:
                self._handle(msg)
            except Exception:
                log.exception("Failed to handle message %s from %s", msg.message_id, msg.wa_id)

    def _lock_for(self, wa_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(wa_id, threading.Lock())

    def _handle(self, msg: InboundMessage) -> None:
        wa_id = msg.wa_id
        self.store.ensure_conversation(wa_id, msg.profile_name)
        conv = self.store.get_conversation(wa_id)

        # Resolve message to text and/or interactive payload
        text: Optional[str] = None
        payload_id: Optional[str] = None
        if msg.type == "text":
            text = (msg.text or "").strip()
        elif msg.type == "interactive":
            payload_id = msg.interactive_id
            text = msg.interactive_title
        elif msg.type == "audio":
            text = self._transcribe(msg)
        elif msg.type == "image":
            text = msg.caption

        self.store.add_message(wa_id, "user", self._describe_inbound(msg, text))
        self.store.touch_user(wa_id)

        # Compliance: opted out
        typed = text if (text and not payload_id) else None
        if conv.opted_out:
            if typed and is_opt_in(typed):
                self._opt_in(conv, msg, typed)
            return
        if typed and is_opt_out(typed):
            self._opt_out(conv, msg, typed)
            return

        self.wa.mark_read(msg.message_id)

        # Language detection (only free text)
        if text and not payload_id:
            detected = detect_lang(text)
            if detected and detected != conv.lang:
                self.store.set_lang(wa_id, detected)
                conv.lang = detected
        lang = conv.lang

        # Human handoff active
        if conv.handoff:
            if text and not payload_id and is_reset(text):
                self.store.set_handoff(wa_id, False)
                self.store.resolve_handoffs(wa_id, by="customer")
                conv.handoff = False
                self._reset(conv)
                self._send_text(wa_id, t("reset_ack", lang))
                self._send_menu(wa_id, lang)
            return

        if msg.type == "audio" and text:
            self._send_text(wa_id, t("audio_heard", lang, text=text))

        # Interactive payloads
        if payload_id:
            self._handle_payload(conv, payload_id)
            return

        if msg.type == "audio" and not text:
            self._send_text(wa_id, t("audio_unsupported", lang))
            self._send_menu(wa_id, lang)
            return

        if msg.type == "image" and not text:
            self._send_text(wa_id, t("image_received", lang))
            self._escalate(conv, reason="image")
            return

        if not text:
            self._send_menu(wa_id, lang)
            return

        self._handle_text(conv, text)

    # ============================================================ free text
    def _handle_text(self, conv: Conversation, text: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        toks = _tokens(text)

        # 1. Existing customer check (look up CRM)
        if conv.state == State.IDLE and not conv.is_existing_customer:
            customer = self.crm.get_customer_for_renewal(wa_id)
            if customer:
                conv.is_existing_customer = True
                conv.customer_id = customer.customer_id
                self.store.set_customer_flag(wa_id, True, customer.customer_id)

        # 2. Greetings -> menu
        if toks and toks <= GREETING_KW:
            self._reset(conv)
            self._send_menu(wa_id, lang)
            return

        # 3. Thanks/ack only (but not "listo" which means "ready" in Spanish)
        if not toks or toks <= {"gracias", "thanks", "thank", "you", "ty", "ok", "okay", "vale", "perfecto", "genial", "great", "cool", "bye", "adios", "chao", "chau", "excelente", "buenisimo", "super", "dale", "de", "nada"}:
            if conv.state in {
                State.PRICES_SENT, State.PACKAGE_SELECTED, State.PAYMENT_READINESS,
                State.DEVICE_SELECTED, State.DEVICE_MODEL, State.INSTALL_METHOD,
                State.AREA_CAPTURED, State.APP_LINK_SENT, State.APP_INSTALLED,
                State.HANDOFF_REQUESTED, State.SETUP_VERIFIED, State.PAYMENT_DUE,
                State.PAYMENT_VERIFICATION, State.FAQ_ONLY, State.SUPPORT,
                State.COMPATIBILITY_CHECK, State.TRIAL_REQUESTED, State.TRIAL_APPROVAL,
                State.TRIAL_ACTIVE, State.FOLLOW_UP, State.REFERRAL, State.RENEWAL,
            }:
                self._resend_step(conv)
            else:
                self._send_text(wa_id, t("thanks_reply", lang))
            return

        # 4. Explicit reset
        if is_reset(text):
            was_in_flow = conv.state != State.IDLE
            self._reset(conv)
            if was_in_flow:
                self._send_text(wa_id, t("booking_cancelled", lang))
            else:
                self._send_menu(wa_id, lang)
            return

        # 5. Route intent
        intent = self._route_intent(text, conv)

        if intent == "price":
            self._send_price_card(conv)
        elif intent == "package":
            self._handle_package_selection(conv, text)
        elif intent == "ready":
            # Handle typed "ready" as if they clicked the button
            self._on_ready(conv, "yes")
        elif intent == "device":
            self._handle_device_selection(conv, text)
        elif intent == "install":
            self._handle_install_method(conv, text)
        elif intent == "trial":
            self._handle_trial_request(conv)
        elif intent == "human":
            self._escalate(conv, reason="requested")
        elif intent == "renewal":
            self._handle_renewal(conv)
        elif intent == "referral":
            self._handle_referral(conv, text)
        elif intent == "support":
            self._handle_support(conv, text)
        elif intent == "channels":
            self._send_text(wa_id, t("channels_disclaimer", lang))
        elif intent == "internet":
            self._send_text(wa_id, t("internet_note", lang))
        elif intent == "dstv":
            self._send_text(wa_id, t("dstv_comparison", lang))
        elif intent == "payment":
            self._handle_payment_enquiry(conv)
        elif intent == "app_installed":
            self._handle_app_installed(conv)
        else:
            answered = self._answer_info(conv, text)
            if answered and conv.state not in (State.IDLE, State.FAQ_ONLY, State.HUMAN, State.OPTED_OUT):
                self._resend_step(conv)

    def _route_intent(self, text: str, conv: Conversation) -> str:
        toks = _tokens(text)
        norm = _norm(text)

        # Check for explicit package selection (e.g., "3 months 2 devices")
        if conv.state in (State.PRICES_SENT, State.PACKAGE_SELECTED):
            pkg = parse_package_selection(text)
            if pkg:
                return "package"

        # Check for "INSTALLED" confirmation
        if conv.state in (State.APP_LINK_SENT, State.APP_INSTALLED):
            if norm in ("instalado", "installed", "instalada"):
                return "app_installed"

        # Check for trial request
        if toks & TRIAL_KW:
            return "trial"

        # Check for human request
        if toks & HUMAN_KW:
            return "human"

        # Check for renewal
        if toks & RENEWAL_KW or (conv.is_existing_customer and toks & PRICE_KW):
            return "renewal"

        # Check for referral
        if toks & REFERRAL_KW:
            return "referral"

        # Check for support
        if toks & SUPPORT_KW:
            return "support"

        # Check for channels/sports
        if toks & CHANNELS_KW:
            return "channels"

        # Check for internet
        if toks & INTERNET_KW:
            return "internet"

        # Check for DStv comparison
        if toks & {"dstv", "super sport", "supersport", "satelite", "satellite", "antena", "dish"}:
            return "dstv"

        # Check for "ready" confirmation (typed as text in simulator)
        if "ready" in toks or "listo" in toks:
            if conv.state == State.PACKAGE_SELECTED:
                return "ready"

        # Check for payment
        if toks & {"pagar", "pago", "pay", "payment", "orange", "afrimoney", "qmoney", "transferencia", "transfer", "efectivo", "cash", "referencia", "reference", "comprobante", "proof"}:
            return "payment"

        # Check for package/pricing
        if toks & PRICE_KW:
            return "price"

        # Check for device
        if toks & DEVICE_KW:
            return "device"

        # Check for install
        if toks & INSTALL_KW:
            return "install"

        # LLM fallback for ambiguous cases
        if self.llm.available:
            return self._llm_classify_intent(text)

        return "info"

    def _llm_classify_intent(self, text: str) -> str:
        system = (
            "You are an intent classifier for NexgloTV WhatsApp assistant. "
            "Classify into exactly one: 'price' (wants pricing/packages), "
            "'package' (choosing duration/devices), 'device' (device questions), "
            "'install' (installation questions), 'trial' (wants free trial), "
            "'human' (wants person), 'renewal' (existing customer renewal), "
            "'referral' (referral/reseller), 'support' (technical issue), "
            "'channels' (channel/sports queries), 'internet' (internet/hardware), "
            "'dstv' (DStv comparison), 'payment' (payment questions), "
            "'app_installed' (customer says app is installed), 'info' (general). "
            "Reply with only the single word."
        )
        out = self.llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": text}],
            temperature=0.0,
            max_tokens=4,
        )
        if out:
            low = out.strip().lower()
            for label in ("price", "package", "device", "install", "trial", "human",
                          "renewal", "referral", "support", "channels", "internet",
                          "dstv", "payment", "app_installed", "info"):
                if label in low:
                    return label
        return "info"

    # =============================================================== actions
    def _send_menu(self, wa_id: str, lang: str) -> None:
        body = t("menu_body", lang, business=self.settings.business_name)
        rows = [
            {"id": "menu:packages", "title": t("menu_packages", lang)},
            {"id": "menu:devices", "title": t("menu_devices", lang)},
            {"id": "menu:renewal", "title": t("menu_renewal", lang)},
            {"id": "menu:support", "title": t("menu_support", lang)},
            {"id": "menu:human", "title": t("menu_human", lang)},
        ]
        self._send_list(None, body, t("menu_button", lang), t("menu_section", lang), rows, wa_id=wa_id)

    def _send_price_card(self, conv: Conversation) -> None:
        """Send price card image immediately, then text fallback if needed."""
        wa_id, lang = conv.wa_id, conv.lang

        # Update CRM lead
        lead = self.crm.ensure_lead(wa_id, wa_id, conv.profile_name)
        self.crm.update_lead_stage(wa_id, "PRICES_SENT")

        # Try to send image
        import asyncio

        async def send_media():
            return await self.media.send_price_card(wa_id)

        try:
            # Run async send in sync context
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(send_media())
            loop.close()

            if result.success:
                self._send_text(wa_id, t("price_prompt", lang))
            else:
                # Fallback to text
                quotes = [calculate_price(m, d) for m in (1, 3, 6, 12) for d in (1, 2, 3, 4)]
                self._send_text(wa_id, t("price_only", lang, price_card=format_price_card(quotes)))
        except Exception as e:
            log.warning("Price card send failed: %s", e)
            quotes = [calculate_price(m, d) for m in (1, 3, 6, 12) for d in (1, 2, 3, 4)]
            self._send_text(wa_id, t("price_only", lang, price_card=format_price_card(quotes)))

        self._goto(conv, State.PRICES_SENT)

    def _handle_package_selection(self, conv: Conversation, text: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        pkg = parse_package_selection(text)

        if not pkg:
            # Show package options via list
            self._send_package_options(conv)
            return

        months, devices = pkg
        try:
            quote = calculate_price(months, devices)
        except Exception as e:
            self._send_text(wa_id, f"Invalid selection: {e}")
            return

        # Store quote in draft
        self.store.update_draft(wa_id, {
            "months": months,
            "device_count": devices,
            "quote": quote.final_price,
        })

        # Record in CRM
        self.crm.record_quote(wa_id, quote, devices)

        # Send quote with readiness question
        months_plural = pluralize(months, lang)
        devices_plural = pluralize(devices, lang)
        self._send_text(wa_id, t(
            "quote_body", lang,
            months=months,
            months_plural=months_plural,
            devices=devices,
            devices_plural=devices_plural,
            total=quote.formatted_total(),
        ))
        self._send_buttons(wa_id, "", [
            {"id": "ready:yes", "title": t("quote_ready_yes", lang)},
            {"id": "ready:no", "title": t("quote_ready_no", lang)},
            {"id": "ready:change", "title": t("quote_change", lang)},
        ], conv=conv)

        self._goto(conv, State.PACKAGE_SELECTED)

    def _send_package_options(self, conv: Conversation) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        rows = []
        for months in (1, 3, 6, 12):
            for devices in (1, 2, 3, 4):
                quote = calculate_price(months, devices)
                rows.append({
                    "id": f"pkg:{months}m_{devices}d",
                    "title": f"{months}mo × {devices}dev",
                    "description": quote.formatted_total(),
                })
                if len(rows) >= 10:
                    break
            if len(rows) >= 10:
                break

        self._send_list(conv, t("choose_package", lang), t("package_button", lang), t("package_section", lang), rows)

    def _handle_device_selection(self, conv: Conversation, text: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        toks = _tokens(text)
        norm = _norm(text)

        # Check if they picked a device by number
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(DEVICE_PLATFORMS):
                device = DEVICE_PLATFORMS[idx]
                self._select_device(conv, device["id"])
                return

        # Check for device name match
        for device in DEVICE_PLATFORMS:
            if device["id"].replace("_", " ") in norm or any(alias in norm for alias in [device["label"].lower()]):
                self._select_device(conv, device["id"])
                return

        # Show device options
        self._send_text(wa_id, t("choose_device", lang))

    def _select_device(self, conv: Conversation, device_id: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        device = get_device(device_id)
        if not device:
            self._send_text(wa_id, "Invalid device selection.")
            return

        self.store.update_draft(wa_id, {"device_id": device_id})
        self.crm.record_device_info(wa_id, device_id)

        # If Smart TV, Tablet, or Laptop - need model for platform detection
        if device_id in ("smart_tv", "tablet", "laptop"):
            self._send_text(wa_id, t("device_model_prompt", lang))
            self._goto(conv, State.DEVICE_MODEL)
        else:
            # Go to DEVICE_SELECTED state (install method will be chosen next)
            self._send_text(wa_id, t("choose_install", lang))
            self._send_buttons(wa_id, "", [
                {"id": "install:self", "title": t("install_self", lang)},
                {"id": "install:visit", "title": t("install_visit", lang)},
            ], conv=conv)
            self._goto(conv, State.DEVICE_SELECTED)

    def _handle_install_method(self, conv: Conversation, text: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        norm = _norm(text)

        # Check for button payload
        if "self" in norm or "autoinstal" in norm or "guided" in norm or "self install" in norm:
            self._handle_self_install(conv)
        elif "visit" in norm or "visita" in norm or "staff" in norm or "equipo" in norm:
            self._handle_staff_visit(conv)
        else:
            self._send_text(wa_id, t("choose_install", lang))

    def _handle_self_install(self, conv: Conversation) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        device_id = conv.draft.get("device_id")
        model = conv.draft.get("device_model", "")

        app = device_app_directory.find_app_for_device(device_id, model)
        if app:
            # Send app link
            self._send_app_link(conv, app)
        else:
            # No verified app - handoff
            self._send_text(wa_id, t("app_link_missing", lang))
            self._escalate(conv, reason="compatibility_check")

        self.crm.record_install_method(wa_id, "self_install")

    def _handle_staff_visit(self, conv: Conversation) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        self._send_text(wa_id, t("area_prompt", lang))
        self.crm.record_install_method(wa_id, "staff_visit")
        self._goto(conv, State.AREA_CAPTURED)

    def _send_app_link(self, conv: Conversation, app) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        device_id = conv.draft.get("device_id")
        device = get_device(device_id) if device_id else None

        self._send_text(wa_id, t("app_link_sent", lang,
            device=device["label"] if device else "your device",
            app_name=app.app_name,
            app_url=app.official_download_url,
        ))

        # Send app icon if available
        if app.app_icon_url:
            import asyncio
            async def send_icon():
                return await self.media.send_app_icon(wa_id, app.app_icon_url, app.app_name)
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(send_icon())
                loop.close()
            except Exception:
                pass

        self._send_text(wa_id, t("app_installed_prompt", lang))
        self.crm.record_app_sent(wa_id, app.app_name, app.official_download_url)
        self._goto(conv, State.APP_LINK_SENT)

    def _handle_app_installed(self, conv: Conversation) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        self.crm.record_app_installed(wa_id)
        self._send_text(wa_id, t("handoff", lang, business=self.settings.business_name))
        self._escalate(conv, reason="setup_credentials")
        self._goto(conv, State.HANDOFF_REQUESTED)

    def _handle_trial_request(self, conv: Conversation) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        self.crm.record_trial_request(wa_id)
        self._send_text(wa_id, t("trial_available", lang))
        self._goto(conv, State.TRIAL_REQUESTED)

    def _handle_renewal(self, conv: Conversation) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        customer = self.crm.get_customer_for_renewal(wa_id)
        if customer:
            self._send_text(wa_id, t("renewal_prompt", lang))
            self._goto(conv, State.RENEWAL)
        else:
            self._send_price_card(conv)

    def _handle_referral(self, conv: Conversation, text: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        # Extract referral code (simple heuristic)
        words = text.split()
        code = None
        for i, w in enumerate(words):
            if w.lower() in ("code", "codigo", "referred", "referido", "by", "por") and i + 1 < len(words):
                code = words[i + 1]
                break
        if code:
            self.crm.record_referral(wa_id, code)
        self._send_text(wa_id, t("referral_prompt", lang))
        self._goto(conv, State.REFERRAL)

    def _handle_support(self, conv: Conversation, text: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        self._send_text(wa_id, t("info_prompt", lang))
        self._goto(conv, State.SUPPORT)

    def _handle_payment_enquiry(self, conv: Conversation) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        quote_total = conv.draft.get("quote")
        if quote_total:
            msg, verified = format_payment_message(
                package=f"{conv.draft.get('months')}mo × {conv.draft.get('device_count')}dev",
                amount=quote_total,
            )
            self._send_text(wa_id, msg)
            if verified:
                self._goto(conv, State.PAYMENT_DUE)
        else:
            self._send_text(wa_id, t("payment_details_missing", lang))

    def _answer_info(self, conv: Conversation, text: str) -> bool:
        wa_id, lang = conv.wa_id, conv.lang

        if self.llm.available:
            answer = self._llm_answer(wa_id, lang, text, self.kb.context(text, k=4))
            if answer:
                self._send_text(wa_id, answer)
                return True

        top = self.kb.search(text, k=1)
        if top:
            body = f"{t('fallback_prefix', lang)}\n\n{whatsapp_snippet(top[0].text)}"
            self._send_text(wa_id, body)
            return True

        self._send_buttons(wa_id, t("no_answer", lang, business=self.settings.business_name), [
            {"id": "menu:human", "title": t("menu_human", lang)},
            {"id": "menu:main", "title": t("menu_main", lang)},
        ])
        return False

    def _llm_answer(self, wa_id: str, lang: str, text: str, context: str) -> Optional[str]:
        lang_name = "English" if lang == "en" else "Spanish"
        system = (
            f"You are the WhatsApp assistant for {self.settings.business_name}, "
            f"{self.settings.business_description}. Answer ONLY using the CONTEXT "
            "below. Be warm and concise (2-4 short sentences) with WhatsApp-friendly "
            f"formatting. Always reply in {lang_name}. The BUSINESS FACTS in the "
            "context are authoritative for prices, packages, and policies. If "
            "the answer is not in the context, say you are not sure and offer to "
            "connect the customer with a person; never invent details."
        )
        history = self.store.history(wa_id, limit=6)
        messages = [{"role": "system", "content": system}]
        for turn in history[:-1]:
            if turn["role"] in ("user", "assistant"):
                messages.append(turn)
        messages.append({"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {text}"})
        return self.llm.chat(messages, temperature=0.3, max_tokens=400)

    # ========================================================= payloads
    def _handle_payload(self, conv: Conversation, payload_id: str) -> None:
        kind, _, value = payload_id.partition(":")
        if not payload_allowed(kind, conv.state):
            log.info("Rejected %r in state %s for %s", payload_id, conv.state, conv.wa_id)
            self._expired(conv)
            return

        handler = getattr(self, f"_on_{kind}", None)
        if handler:
            handler(conv, value)
        else:
            self._expired(conv)

    def _on_menu(self, conv: Conversation, value: str) -> None:
        wa_id, lang = conv.wa_id, conv.lang
        if value == "packages":
            self._send_price_card(conv)
        elif value == "devices":
            self._send_text(wa_id, t("choose_device", lang))
            self._goto(conv, State.DEVICE_SELECTED)
        elif value == "renewal":
            self._handle_renewal(conv)
        elif value == "support":
            self._handle_support(conv, "")
        elif value == "human":
            self._escalate(conv, reason="requested")
        elif value == "main":
            self._reset(conv)
            self._send_menu(wa_id, lang)
        else:
            self._expired(conv)

    def _on_pkg(self, conv: Conversation, value: str) -> None:
        # Format: "3m_2d"
        try:
            months_part, devices_part = value.split("_")
            months = int(months_part.replace("m", ""))
            devices = int(devices_part.replace("d", ""))
            quote = calculate_price(months, devices)
            self.store.update_draft(conv.wa_id, {
                "months": months,
                "device_count": devices,
                "quote": quote.final_price,
            })
            self.crm.record_quote(conv.wa_id, quote, devices)

            months_plural = pluralize(months, conv.lang)
            devices_plural = pluralize(devices, conv.lang)
            self._send_text(conv.wa_id, t(
                "quote_body", conv.lang,
                months=months,
                months_plural=months_plural,
                devices=devices,
                devices_plural=devices_plural,
                total=quote.formatted_total(),
            ))
            self._send_buttons(conv.wa_id, "", [
                {"id": "ready:yes", "title": t("quote_ready_yes", conv.lang)},
                {"id": "ready:no", "title": t("quote_ready_no", conv.lang)},
                {"id": "ready:change", "title": t("quote_change", conv.lang)},
            ], conv=conv)
            self._goto(conv, State.PACKAGE_SELECTED)
        except Exception:
            self._expired(conv)

    def _on_ready(self, conv: Conversation, value: str) -> None:
        lang = conv.lang
        if value == "yes":
            self._send_text(conv.wa_id, t("choose_device", lang))
            self._goto(conv, State.PAYMENT_READINESS)
        elif value == "no":
            self._send_text(conv.wa_id, t("trial_offer_hesitant", lang))
            self._goto(conv, State.FAQ_ONLY)
        elif value == "change":
            self._send_price_card(conv)

    def _on_device(self, conv: Conversation, value: str) -> None:
        # value is device_id
        self._select_device(conv, value)

    def _on_install(self, conv: Conversation, value: str) -> None:
        if value == "self":
            self._handle_self_install(conv)
        elif value == "visit":
            self._handle_staff_visit(conv)

    def _on_app_installed(self, conv: Conversation, value: str) -> None:
        self._handle_app_installed(conv)

    def _on_trial(self, conv: Conversation, value: str) -> None:
        self._handle_trial_request(conv)

    def _on_renewal(self, conv: Conversation, value: str) -> None:
        self._handle_renewal(conv)

    def _on_reset(self, conv: Conversation, value: str) -> None:
        self._reset(conv)
        self._send_menu(conv.wa_id, conv.lang)

    # ======================================================== compliance
    def _opt_out(self, conv: Conversation, msg: InboundMessage, text: str) -> None:
        wa_id = conv.wa_id
        lang = _keyword_lang(text) or conv.lang
        if lang != conv.lang:
            self.store.set_lang(wa_id, lang)
            conv.lang = lang
        if conv.handoff:
            self.store.set_handoff(wa_id, False)
            self.store.resolve_handoffs(wa_id, by="opt_out")
            conv.handoff = False
        self._reset(conv)
        self.store.set_opted_out(wa_id, True)
        conv.opted_out = True
        self.wa.mark_read(msg.message_id)
        self.crm.set_opt_out(wa_id, True)
        self._send_text(wa_id, t("optout_ack", lang))

    def _opt_in(self, conv: Conversation, msg: InboundMessage, text: str) -> None:
        wa_id = conv.wa_id
        lang = _keyword_lang(text) or conv.lang
        if lang != conv.lang:
            self.store.set_lang(wa_id, lang)
            conv.lang = lang
        self.store.set_opted_out(wa_id, False)
        conv.opted_out = False
        self.wa.mark_read(msg.message_id)
        self.crm.set_opt_out(wa_id, False)
        self._send_text(wa_id, t("optin_ack", lang))
        self._send_menu(wa_id, lang)

    # ========================================================= handoff
    def _escalate(self, conv: Conversation, reason: str, announce: bool = True) -> None:
        wa_id = conv.wa_id
        self.store.clear_draft(wa_id)
        conv.draft = {}
        self._goto(conv, State.HUMAN)
        self.store.set_handoff(wa_id, True)
        conv.handoff = True
        self.store.create_handoff(wa_id, reason)
        self.crm.record_handoff(wa_id, reason, f"handoff_{wa_id}_{int(datetime.utcnow().timestamp())}")
        if announce:
            self._send_text(wa_id, t("handoff", conv.lang, business=self.settings.business_name))

    # ========================================================= flow helpers
    def _goto(self, conv: Conversation, target: str) -> None:
        if not can_transition(conv.state, target):
            raise IllegalTransition(f"{conv.state} -> {target}")
        if conv.state != target:
            self.store.set_state(conv.wa_id, target)
            conv.state = target

    def _reset(self, conv: Conversation) -> None:
        self._goto(conv, State.IDLE)
        self.store.clear_draft(conv.wa_id)
        conv.draft = {}

    def _expired(self, conv: Conversation) -> None:
        self._send_text(conv.wa_id, t("option_expired", conv.lang))
        self._resend_step(conv)

    def _resend_step(self, conv: Conversation) -> None:
        state = conv.state
        if state == State.PRICES_SENT:
            self._send_price_card(conv)
        elif state == State.PACKAGE_SELECTED:
            self._send_package_options(conv)
        elif state == State.PAYMENT_READINESS:
            # Resend quote
            quote_total = conv.draft.get("quote")
            if quote_total:
                months = conv.draft.get("months", 0)
                devices = conv.draft.get("device_count", 0)
                months_plural = pluralize(months, conv.lang)
                devices_plural = pluralize(devices, conv.lang)
                self._send_text(conv.wa_id, t(
                    "quote_body", conv.lang,
                    months=months, months_plural=months_plural,
                    devices=devices, devices_plural=devices_plural,
                    total=f"Le{quote_total:,}",
                ))
        elif state == State.DEVICE_SELECTED:
            self._send_text(conv.wa_id, t("choose_device", conv.lang))
        elif state == State.DEVICE_MODEL:
            self._send_text(conv.wa_id, t("device_model_prompt", conv.lang))
        elif state == State.INSTALL_METHOD:
            self._send_text(conv.wa_id, t("choose_install", conv.lang))
        elif state == State.AREA_CAPTURED:
            self._send_text(conv.wa_id, t("visit_fee_note", conv.lang))
        elif state == State.APP_LINK_SENT:
            self._send_text(conv.wa_id, t("app_installed_prompt", conv.lang))
        elif state == State.HANDOFF_REQUESTED:
            self._send_text(conv.wa_id, t("handoff", conv.lang, business=self.settings.business_name))
        else:
            self._send_menu(conv.wa_id, conv.lang)

    # ========================================================= outbound
    def _send_text(self, wa_id: str, body: str) -> None:
        self.wa.send_text(wa_id, body)
        self.store.add_message(wa_id, "assistant", body, author="bot")

    def _send_buttons(
        self, wa_id: str, body: str, buttons: list[dict], conv: Optional[Conversation] = None
    ) -> None:
        self.wa.send_buttons(wa_id, body=body, buttons=buttons)
        titles = " | ".join(b["title"] for b in buttons)
        self.store.add_message(wa_id, "assistant", f"{body}\n[{titles}]", author="bot")
        if conv is not None:
            self.store.update_draft(conv.wa_id, {"_offered": [[b["id"], b["title"], ""] for b in buttons]})

    def _send_list(
        self,
        conv: Optional[Conversation],
        body: str,
        button_text: str,
        section_title: str,
        rows: list[dict],
        wa_id: Optional[str] = None,
    ) -> None:
        wa_id = wa_id or (conv.wa_id if conv else None)
        if not wa_id:
            return
        self.wa.send_list(wa_id, body=body, button_text=button_text, sections=[{"title": section_title, "rows": rows}])
        titles = " | ".join(r["title"] for r in rows)
        self.store.add_message(wa_id, "assistant", f"{body}\n[{titles}]", author="bot")
        if conv is not None:
            self.store.update_draft(conv.wa_id, {"_offered": [[r["id"], r["title"], r.get("description", "")] for r in rows]})

    # --------------------------------------------------------------- util
    def _transcribe(self, msg: InboundMessage) -> Optional[str]:
        if not msg.media_id:
            return None
        data = self.wa.download_media(msg.media_id)
        if not data:
            return None
        return transcribe_audio(data, model_size=self.settings.whisper_model)

    @staticmethod
    def _describe_inbound(msg: InboundMessage, text: Optional[str]) -> str:
        if msg.type == "interactive":
            return f"[button] {msg.interactive_title or msg.interactive_id}"
        if msg.type == "image":
            return f"[image] {text or ''}".strip()
        if msg.type == "audio":
            return f"[voice] {text or '(untranscribed)'}"
        return text or f"[{msg.type}]"


def whatsapp_snippet(markdown: str, limit: int = 900) -> str:
    lines = markdown.strip().splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            out.append(f"*{stripped.lstrip('#').strip()}*")
        elif stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt.startswith("|") and all(set(c.strip()) <= set("-: ") for c in nxt.strip("|").split("|")):
                continue
            out.append(f"{cells[0]}: {' · '.join(cells[1:])}" if len(cells) > 1 else cells[0])
        else:
            out.append(re.sub(r"\*\*(.+?)\*\*", r"*\1*", line))
    text = "\n".join(out).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"