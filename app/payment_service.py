"""NexgloTV payment configuration and verification boundary.

Payment details are ONLY provided by verified configuration / staff.
Never invented, never from LLM, never from customer messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml

log = logging.getLogger("nexglo.payment")

DEFAULT_PAYMENT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "payments.yaml"


@dataclass
class PaymentMethodConfig:
    """Verified payment method configuration."""
    method: str                    # orange_money, afrimoney, qmoney, bank_transfer, cash
    number: Optional[str] = None   # Phone/account number
    account_name: Optional[str] = None  # Official account holder name
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    approved_location: Optional[str] = None
    receipt_procedure: Optional[str] = None
    is_verified: bool = False      # Only True when all required fields present

    def is_complete(self) -> bool:
        """Check if this method has all required verified fields."""
        if self.method == "orange_money":
            return bool(self.number and self.account_name)
        elif self.method in ("afrimoney", "qmoney"):
            return bool(self.number and self.account_name)
        elif self.method == "bank_transfer":
            return bool(self.bank_name and self.account_name and self.account_number)
        elif self.method == "cash":
            return bool(self.approved_location and self.receipt_procedure)
        return False


class PaymentConfig:
    """Loads and manages verified payment configuration."""

    def __init__(self, path: Path = DEFAULT_PAYMENT_CONFIG_PATH):
        self.path = Path(path)
        self._methods: dict[str, PaymentMethodConfig] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._create_example()
            return
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            for method, config in data.get("payments", {}).items():
                # Remove 'method' from config if present to avoid duplicate keyword arg
                config_copy = dict(config)
                config_copy.pop("method", None)
                self._methods[method] = PaymentMethodConfig(method=method, **config_copy)
        except Exception as e:
            log.warning("Failed to load payment config: %s", e)
            self._create_example()

    def _create_example(self) -> None:
        """Create example config with all methods unverified."""
        example = {
            "payments": {
                "orange_money": {
                    "method": "orange_money",
                    "number": None,
                    "account_name": None,
                    "is_verified": False,
                },
                "afrimoney": {
                    "method": "afrimoney",
                    "number": None,
                    "account_name": None,
                    "is_verified": False,
                },
                "qmoney": {
                    "method": "qmoney",
                    "number": None,
                    "account_name": None,
                    "is_verified": False,
                },
                "bank_transfer": {
                    "method": "bank_transfer",
                    "bank_name": None,
                    "account_name": None,
                    "account_number": None,
                    "is_verified": False,
                },
                "cash": {
                    "method": "cash",
                    "approved_location": None,
                    "receipt_procedure": None,
                    "is_verified": False,
                },
            }
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.dump(example, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self._load()

    def get_method(self, method: str) -> Optional[PaymentMethodConfig]:
        return self._methods.get(method)

    def get_verified_methods(self) -> list[PaymentMethodConfig]:
        return [m for m in self._methods.values() if m.is_complete()]

    def get_preferred_method(self) -> Optional[PaymentMethodConfig]:
        """Orange Money is preferred if verified."""
        om = self._methods.get("orange_money")
        if om and om.is_complete():
            return om
        # Fallback to first verified
        verified = self.get_verified_methods()
        return verified[0] if verified else None

    def get_payment_instructions(self, method: str) -> Optional[dict]:
        """Get verified payment instructions for a method.
        Returns None if not verified (triggers staff verification)."""
        config = self.get_method(method)
        if not config or not config.is_complete():
            return None
        return {
            "method": config.method,
            "number": config.number,
            "account_name": config.account_name,
            "bank_name": config.bank_name,
            "account_number": config.account_number,
            "approved_location": config.approved_location,
            "receipt_procedure": config.receipt_procedure,
        }

    def update_method(self, method: str, **kwargs) -> PaymentMethodConfig:
        """Update payment method (staff use)."""
        if method not in self._methods:
            raise ValueError(f"Unknown payment method: {method}")
        config = self._methods[method]
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.is_verified = config.is_complete()
        self._save()
        return config

    def _save(self) -> None:
        data = {"payments": {k: {f: getattr(v, f) for f in v.__dataclass_fields__} for k, v in self._methods.items()}}
        self.path.write_text(yaml.dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


# Global instance
payment_config = PaymentConfig()


class PaymentVerificationError(Exception):
    """Raised when payment verification fails."""
    pass


def verify_payment(
    payment_id: str,
    expected_amount: int,
    method: str,
    transaction_reference: str,
    verified_by: str,
) -> bool:
    """Verify a payment - ONLY callable by authorized staff/payment API.
    
    This is a stub for the actual verification logic which would:
    - Check payment processor API
    - Verify amount matches
    - Verify reference is unique (not used before)
    - Verify recipient account matches official config
    - Check settlement status
    
    Returns True if verified, False otherwise.
    """
    # In production, this would call a payment processor API
    # For now, this is a placeholder that requires staff to implement
    raise PaymentVerificationError(
        "Payment verification not implemented. "
        "Integrate with payment processor API or use staff manual verification."
    )


def format_payment_message(
    package: str,
    amount: int,
    method: str = "orange_money",
    currency: str = "Le",
) -> tuple[str, bool]:
    """Format payment details message. Returns (message, is_verified)."""
    config = payment_config.get_method(method)
    if not config or not config.is_complete():
        return (
            "We accept Orange Money (preferred), AfriMoney, QMoney, bank transfer and cash.\n"
            "Let me get the correct official account details from our team — "
            "I'd rather confirm than send you a wrong number.",
            False,
        )

    other_methods = []
    for m in payment_config.get_verified_methods():
        if m.method != method:
            if m.method in ("orange_money", "afrimoney", "qmoney"):
                other_methods.append(f"{m.method.replace('_', ' ').title()}: {m.number} — {m.account_name}")
            elif m.method == "bank_transfer":
                other_methods.append(f"Bank: {m.bank_name} / {m.account_name} / {m.account_number}")
            elif m.method == "cash":
                other_methods.append(f"Cash at: {m.approved_location}")

    other_text = "\n".join(other_methods) if other_methods else "Ask our team for other options."

    return (
        f"*NexgloTV Official Payment*\n"
        f"Package: {package}\n"
        f"Amount: {currency}{amount:,}\n"
        f"Orange Money: {config.number} — {config.account_name}\n"
        f"Other verified methods:\n{other_text}\n\n"
        f"After paying, send the transaction reference so our team can confirm receipt.\n"
        f"**Never share your PIN or OTP.**",
        True,
    )