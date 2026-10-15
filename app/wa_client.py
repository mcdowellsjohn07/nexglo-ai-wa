"""WhatsApp Cloud API client.

``WhatsAppClient`` exposes the message types this agent uses (text, images,
interactive reply buttons and lists, read receipts) and inbound media
download. Payloads are built by :mod:`app.wa_payloads`; *delivering* them is
the job of a transport:

- :class:`GraphTransport` POSTs to ``graph.facebook.com/{version}/{phone_id}/messages``.
- :class:`DryRunTransport` stores the exact payload in the local ``outbox``
  table instead. It is selected automatically when WhatsApp credentials are
  missing or are the ``.env.example`` placeholders (see ``Settings.dry_run``),
  so a fresh checkout never calls Meta with a fake token.
- :class:`CallbackTransport` hands each payload to a Python function (used by
  the terminal chat simulator and tests).

All calls are synchronous. The webhook runs the agent in a FastAPI background
task, off the request path, so blocking here is fine.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any, Callable, Optional, Protocol

import httpx

from . import wa_payloads as P
from .config import Settings

log = logging.getLogger("whatsapp_agent.wa_client")


class Transport(Protocol):
    def deliver(self, payload: dict) -> Optional[dict]:
        """Send one payload; return the Graph-style response or None on failure."""


class GraphTransport:
    """Live delivery through the Meta Graph API."""

    def __init__(self, settings: Settings, http_client: Optional[httpx.Client] = None):
        self.settings = settings
        self.http = http_client or httpx.Client(timeout=30.0)

    def deliver(self, payload: dict) -> Optional[dict]:
        try:
            resp = self.http.post(
                self.settings.messages_url,
                headers={
                    "Authorization": f"Bearer {self.settings.whatsapp_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                log.error("Graph API %s: %s", resp.status_code, resp.text[:500])
                return None
            return resp.json()
        except httpx.HTTPError as exc:
            log.error("Graph API request failed: %s", exc)
            return None


class DryRunTransport:
    """Writes outbound messages to the ``outbox`` table instead of sending them.

    Read receipts are not messages, so they are acknowledged but not stored.
    """

    def __init__(self, outbox):
        self.outbox = outbox  # anything with add_outbox(wa_id, payload) -> int

    def deliver(self, payload: dict) -> Optional[dict]:
        if payload.get("status") == "read":
            return {"success": True, "dry_run": True}
        outbox_id = self.outbox.add_outbox(payload.get("to", ""), payload)
        log.info("[dry-run] outbox #%s -> %s: %s", outbox_id, payload.get("to"), P.render(payload).as_text()[:120])
        return {
            "messaging_product": "whatsapp",
            "messages": [{"id": f"wamid.DRYRUN.{outbox_id}"}],
            "dry_run": True,
        }


class CallbackTransport:
    """Passes every payload to ``callback`` (simulator / tests)."""

    def __init__(self, callback: Callable[[dict], None]):
        self.callback = callback
        self._ids = itertools.count(1)

    def deliver(self, payload: dict) -> Optional[dict]:
        self.callback(payload)
        return {"messaging_product": "whatsapp", "messages": [{"id": f"wamid.LOCAL.{next(self._ids)}"}]}


class WhatsAppClient:
    def __init__(
        self,
        settings: Settings,
        transport: Optional[Transport] = None,
        http_client: Optional[httpx.Client] = None,
        store: Optional[Any] = None,
    ):
        self.settings = settings
        self.store = store
        self._dry_run_override: Optional[bool] = None
        self._graph_transport: Optional[Transport] = None
        self._dry_transport: Optional[Transport] = None

        if transport is not None:
            self.transport = transport
            if isinstance(transport, GraphTransport):
                self._graph_transport = transport
            else:
                self._dry_transport = transport
        else:
            if settings.whatsapp_configured:
                self._graph_transport = GraphTransport(settings, http_client)
            if store is not None:
                self._dry_transport = DryRunTransport(store)
            else:
                self._dry_transport = CallbackTransport(
                    lambda payload: log.warning(
                        "WhatsApp not configured (dry-run); would send: %s", payload
                    )
                )
            self.transport = (
                self._dry_transport if settings.dry_run else (self._graph_transport or self._dry_transport)
            )

    @property
    def dry_run(self) -> bool:
        if self._dry_run_override is not None:
            return self._dry_run_override
        if self.store and hasattr(self.store, "get_setting"):
            db_val = self.store.get_setting("dry_run", "")
            if db_val in ("1", "true"):
                return True
            if db_val in ("0", "false"):
                return not self.settings.whatsapp_configured
        return not isinstance(self.transport, GraphTransport)

    def set_dry_run(self, enabled: bool) -> bool:
        """Switch between Dry Run (local outbox) and LIVE (graph.facebook.com) dynamically."""
        if not enabled and not self.settings.whatsapp_configured:
            # Cannot enable LIVE if credentials are not configured
            raise ValueError("Cannot disable dry-run: WhatsApp credentials (token/phone_id) are not configured.")
        self._dry_run_override = enabled
        if self.store and hasattr(self.store, "set_setting"):
            self.store.set_setting("dry_run", "true" if enabled else "false")
        if enabled:
            if self._dry_transport:
                self.transport = self._dry_transport
        else:
            if self._graph_transport:
                self.transport = self._graph_transport
        log.info("Switched WhatsApp delivery mode: dry_run=%s", self.dry_run)
        return self.dry_run

    # --------------------------------------------------------------- senders
    def send_payload(self, payload: dict) -> Optional[dict]:
        active_transport = self._dry_transport if self.dry_run and self._dry_transport else self.transport
        return active_transport.deliver(payload)

    def send_text(self, to: str, body: str, preview_url: bool = False) -> Optional[dict]:
        return self.send_payload(P.text_payload(to, body, preview_url))

    def send_image(
        self,
        to: str,
        link: str = "",
        caption: str = "",
        *,
        media_id: str = "",
        image_url: str = "",
    ) -> Optional[dict]:
        return self.send_payload(
            P.image_payload(to, link=link, caption=caption, media_id=media_id, image_url=image_url)
        )

    def send_buttons(self, to: str, body: str, buttons: list[dict], header: str = "") -> Optional[dict]:
        """buttons: list of {"id": str, "title": str} (max 3, title <= 20 chars)."""
        return self.send_payload(P.buttons_payload(to, body, buttons, header))

    def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict],
        header: str = "",
        footer: str = "",
    ) -> Optional[dict]:
        """sections: [{"title": str, "rows": [{"id","title","description"}]}]."""
        return self.send_payload(P.list_payload(to, body, button_text, sections, header, footer))

    def mark_read(self, message_id: str, typing: bool = True) -> Optional[dict]:
        """Mark a message read and (optionally) show the typing indicator.

        The typing indicator auto-dismisses when you send the next message or
        after ~25 seconds.
        """
        return self.send_payload(P.read_payload(message_id, typing))

    # ----------------------------------------------------------------- media
    def download_media(self, media_id: str) -> Optional[bytes]:
        """Resolve a media id to a temporary URL, then download the bytes.

        Used for inbound voice notes. Hand the returned bytes to
        ``app.transcribe.transcribe_audio`` (faster-whisper) to get text.
        Not available in dry-run mode (there is no real media to fetch).
        """
        if self.dry_run:
            log.info("[dry-run] cannot download media %s", media_id)
            return None
        http = self.transport.http  # type: ignore[attr-defined]
        auth = {"Authorization": f"Bearer {self.settings.whatsapp_token}"}
        try:
            meta = http.get(f"{self.settings.graph_base_url}/{media_id}", headers=auth)
            meta.raise_for_status()
            url = meta.json().get("url")
            if not url:
                return None
            media = http.get(url, headers=auth)
            media.raise_for_status()
            return media.content
        except httpx.HTTPError as exc:
            log.error("Media download failed for %s: %s", media_id, exc)
            return None

    def close(self) -> None:
        http = getattr(self.transport, "http", None)
        if http is not None:
            http.close()
