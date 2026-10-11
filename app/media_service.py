"""NexgloTV media service: price card and app icon sending with fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .wa_client import WhatsAppClient


@dataclass
class MediaSendResult:
    success: bool
    message: str
    media_id: Optional[str] = None


class MediaService:
    """Handles sending approved media (price card, app icons) with fallback."""

    def __init__(
        self,
        wa: Optional[WhatsAppClient] = None,
        price_card_media_url: str = "",
        price_card_media_id: str = "",
    ):
        self.wa = wa
        self.price_card_media_url = price_card_media_url
        self.price_card_media_id = price_card_media_id

    async def send_price_card(
        self,
        wa_id: str,
        caption: str = "NexgloTV — 20% OFF Subscription Packages",
    ) -> MediaSendResult:
        """Send the approved price card image. Falls back to text on failure."""
        if not self.wa:
            return MediaSendResult(False, "no_wa_client", None)
        # Try media_id first (already uploaded to Meta)
        if self.price_card_media_id:
            try:
                await self.wa.send_image(wa_id, media_id=self.price_card_media_id, caption=caption)
                return MediaSendResult(True, "price_card_sent_via_media_id", self.price_card_media_id)
            except Exception as e:
                pass  # Fall through to URL

        # Try public HTTPS URL
        if self.price_card_media_url:
            try:
                await self.wa.send_image(wa_id, image_url=self.price_card_media_url, caption=caption)
                return MediaSendResult(True, "price_card_sent_via_url", None)
            except Exception as e:
                pass  # Fall through to text

        return MediaSendResult(False, "price_card_send_failed_no_media_configured", None)

    async def send_app_icon(
        self,
        wa_id: str,
        app_icon_url: str,
        caption: str = "",
    ) -> MediaSendResult:
        """Send an approved app icon."""
        if not self.wa:
            return MediaSendResult(False, "no_wa_client", None)
        if not app_icon_url:
            return MediaSendResult(False, "no_app_icon_url", None)
        try:
            await self.wa.send_image(wa_id, image_url=app_icon_url, caption=caption)
            return MediaSendResult(True, "app_icon_sent", None)
        except Exception as e:
            return MediaSendResult(False, f"app_icon_send_failed: {e}", None)