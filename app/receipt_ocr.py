"""Optical Character Recognition and Financial Vision Analysis for Payment Receipts.

Supports mobile money operators and banks in Sierra Leone:
- Orange Money (Cash-In, Transfer, Txn ID, OM...)
- Afrimoney (Cash-In, Transfer, Txn ID...)
- Bank Transfers (Rokel Commercial Bank, Sierra Leone Commercial Bank, Ecobank, UBA, Zenith, GTBank)
- Cash Receipts / Invoices / POS Slips

Primary Vision Engine: NVIDIA NIM Vision (meta/llama-3.2-11b-vision-instruct)
Fallback: OpenAI Vision / OpenRouter / Regex & Heuristic Parser
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

log = logging.getLogger("whatsapp_agent.receipt_ocr")


@dataclass
class ReceiptDetails:
    is_receipt: bool
    provider: str
    reference: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "SLE"
    timestamp: Optional[str] = None
    sender_name: Optional[str] = None
    sender_phone: Optional[str] = None
    raw_summary: Optional[str] = None

    @property
    def formatted_amount(self) -> str:
        if self.amount is not None:
            return f"{self.currency} {self.amount:,.2f}"
        return f"{self.currency} 0.00"


def _clean_ref(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = re.sub(r"[^\w\-]", "", raw.strip()).upper()
    return cleaned if len(cleaned) >= 4 else None


def _clean_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw.strip())
    if digits.startswith("232") and len(digits) >= 11:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 9:
        return f"+232{digits[1:]}"
    if len(digits) == 8:
        return f"+232{digits}"
    return raw.strip()


def extract_receipt_from_text(text: str) -> Optional[ReceiptDetails]:
    """Heuristic / Regex extraction of payment details from receipt text or caption."""
    if not text:
        return None
    clean_text = text.strip()

    # Identify Provider
    lower = clean_text.lower()
    provider = "Mobile Money"
    if "orange" in lower:
        provider = "Orange Money"
    elif "afri" in lower:
        provider = "Afrimoney"
    elif "rokel" in lower:
        provider = "Rokel Commercial Bank"
    elif "ecobank" in lower:
        provider = "Ecobank"
    elif "uba" in lower:
        provider = "UBA"
    elif "zenith" in lower:
        provider = "Zenith Bank"
    elif "slcb" in lower or "sierra leone commercial" in lower:
        provider = "Sierra Leone Commercial Bank"
    elif "cash" in lower:
        provider = "Cash"

    # Identify Reference / Txn ID
    ref = None
    ref_match = re.search(
        r"(?:ref(?:erence)?(?:\s*no\.?|\s*id)?|txn(?:\s*id)?|trans(?:action)?\s*id|id\s*de\s*trans|receipt\s*no\.?)[:\s#]*([a-zA-Z0-9\-_]{5,32})",
        clean_text,
        re.I,
    )
    if ref_match:
        ref = _clean_ref(ref_match.group(1))

    # Pattern for standalone OM / CI / TXN / NGT codes
    if not ref:
        code_match = re.search(r"\b((?:OM|CI|TXN|REF|PP|RCP)[A-Z0-9\-]{5,25})\b", clean_text, re.I)
        if code_match:
            ref = _clean_ref(code_match.group(1))

    # Identify Amount
    amount = None
    currency = "SLE"
    if "$" in clean_text or "usd" in lower:
        currency = "USD"
    elif "nle" in lower:
        currency = "NLe"
    elif "le" in lower and "sle" not in lower:
        currency = "Le"

    # Match amount tied to keywords or currency to avoid capturing numbers inside txn IDs or phone numbers
    amt_patterns = [
        # Keyword prefix + optional currency + number
        r"(?:amount|amt|paid|total|sum|payment\s*of|transfer\s*of|cash-in\s*of)\s*(?:is|:)?\s*(?:(?:sle|nle|le|sll|usd|\$)\s*)?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
        # Currency prefix + number
        r"(?:\b(?:sle|nle|le|sll|usd)\b|\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
        # Number + currency suffix
        r"\b([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*(?:\b(?:sle|nle|le|sll|usd)\b|\$)",
    ]

    for pat in amt_patterns:
        match = re.search(pat, clean_text, re.I)
        if match:
            try:
                raw_amt = match.group(1).replace(",", "")
                val = float(raw_amt)
                if val > 0:
                    amount = val
                    break
            except ValueError:
                continue

    # Identify Phone with Sierra Leone mobile prefixes (7, 8, 3, 2)
    phone = None
    phone_match = re.search(r"\b(?:\+?232[23789]\d{7}|0[23789]\d{7})\b", clean_text)
    if phone_match:
        phone = _clean_phone(phone_match.group(0))

    # Is this a valid receipt?
    is_receipt = bool(ref or (amount and amount > 0 and provider != "Mobile Money"))

    if is_receipt:
        return ReceiptDetails(
            is_receipt=True,
            provider=provider,
            reference=ref or f"TXN-{abs(hash(clean_text)) % 10000000:07d}",
            amount=amount,
            currency=currency,
            sender_phone=phone,
            raw_summary=clean_text[:120],
        )

    return None


def analyze_receipt_image(
    image_bytes: bytes,
    caption: Optional[str] = None,
    settings: Optional[Any] = None,
) -> Optional[ReceiptDetails]:
    """Analyze image using Vision LLM (NVIDIA NIM or OpenAI-compatible) and extract payment details."""
    if not image_bytes:
        if caption:
            return extract_receipt_from_text(caption)
        return None

    api_key = getattr(settings, "nvidia_api_key", "")
    nim_base_url = getattr(settings, "nim_base_url", "https://integrate.api.nvidia.com/v1")
    model = "meta/llama-3.2-11b-vision-instruct"

    # Fallback to OpenRouter or OpenAI if NVIDIA key missing
    if not api_key:
        api_key = getattr(settings, "openrouter_api_key", "")
        if api_key:
            nim_base_url = "https://openrouter.ai/api/v1"
            model = "meta-llama/llama-3.2-11b-vision-instruct"

    if not api_key:
        log.info("No vision API key configured; falling back to heuristic text parsing")
        if caption:
            return extract_receipt_from_text(caption)
        return None

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    # Detect mime type from header
    mime = "image/jpeg"
    if image_bytes.startswith(b"\x89PNG"):
        mime = "image/png"
    elif image_bytes.startswith(b"GIF8"):
        mime = "image/gif"
    elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        mime = "image/webp"

    prompt = (
        "You are an expert financial auditor specializing in mobile money receipts, banking SMS screenshots, "
        "and payment vouchers in Sierra Leone (Orange Money, Afrimoney, Rokel Commercial Bank, SLCB, Ecobank, UBA, etc.).\n"
        "Carefully analyze this image. Extract:\n"
        "1. Is this a payment receipt or successful money transfer screenshot? (is_receipt: boolean)\n"
        "2. Payment provider / Mobile Money operator (provider: string)\n"
        "3. Transaction ID or Reference Number (reference: string or null)\n"
        "4. Amount paid (amount: numeric float or null)\n"
        "5. Currency (currency: 'SLE', 'NLe', 'Le', or 'USD')\n"
        "6. Date/Time (timestamp: string or null)\n"
        "7. Sender name (sender_name: string or null)\n"
        "8. Sender phone number (sender_phone: string or null)\n"
        "9. A concise 1-line summary (summary: string)\n\n"
        "Respond ONLY with a valid JSON object matching this schema, with no markdown or formatting:\n"
        "{\n"
        '  "is_receipt": true,\n'
        '  "provider": "Orange Money",\n'
        '  "reference": "OM12345678",\n'
        '  "amount": 150.0,\n'
        '  "currency": "SLE",\n'
        '  "timestamp": "2026-10-18 14:32:00",\n'
        '  "sender_name": "John Doe",\n'
        '  "sender_phone": "+23276000000",\n'
        '  "summary": "Orange Money payment of SLE 150.00 to NexgloTV"\n'
        "}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64_image}"},
                    },
                ],
            }
        ],
        "max_tokens": 400,
        "temperature": 0.1,
    }

    try:
        url = f"{nim_base_url.rstrip('/')}/chat/completions"
        resp = httpx.post(url, headers=headers, json=payload, timeout=25.0)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # Extract JSON block
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                if parsed.get("is_receipt") or parsed.get("reference"):
                    return ReceiptDetails(
                        is_receipt=bool(parsed.get("is_receipt", True)),
                        provider=str(parsed.get("provider") or "Mobile Money"),
                        reference=_clean_ref(parsed.get("reference")),
                        amount=float(parsed["amount"]) if parsed.get("amount") is not None else None,
                        currency=str(parsed.get("currency") or "SLE"),
                        timestamp=parsed.get("timestamp"),
                        sender_name=parsed.get("sender_name"),
                        sender_phone=_clean_phone(parsed.get("sender_phone")),
                        raw_summary=str(parsed.get("summary") or "Payment receipt detected"),
                    )
        else:
            log.warning("Vision API returned status %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.warning("Vision API request failed: %s", exc)

    # Fallback to caption heuristic
    if caption:
        return extract_receipt_from_text(caption)

    return None
