"""NexgloTV conversation state machine and per-contact store.

Replaces the barbershop appointment states with subscription sales states.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .db import Database


class State:
    """Conversation states for NexgloTV subscription flow."""
    # --- Main states ---
    IDLE = "idle"
    HUMAN = "human"
    OPTED_OUT = "opted_out"

    # --- Sales funnel ---
    PRICES_SENT = "prices_sent"           # Price card shown, awaiting package choice
    PACKAGE_SELECTED = "package_selected"  # Months + devices chosen, quote given
    PAYMENT_READINESS = "payment_readiness"  # Confirmed willing to pay after setup
    DEVICE_SELECTED = "device_selected"    # Device platform chosen
    DEVICE_MODEL = "device_model"          # Specific model provided
    INSTALL_METHOD = "install_method"      # Self-install vs staff visit chosen
    AREA_CAPTURED = "area_captured"        # Area for visit fee quote
    APP_LINK_SENT = "app_link_sent"        # Approved app link sent
    APP_INSTALLED = "app_installed"        # Customer reported INSTALLED
    HANDOFF_REQUESTED = "handoff_requested"  # Handoff created, awaiting staff
    HUMAN_OWNED = "human_owned"            # Staff has taken over
    SETUP_VERIFIED = "setup_verified"      # Staff confirmed setup works
    PAYMENT_DUE = "payment_due"            # Payment details sent, awaiting proof
    PAYMENT_VERIFICATION = "payment_verification"  # Staff verifying payment
    CONVERTED = "converted"                # Lead converted to paying customer

    # --- Branches ---
    FAQ_ONLY = "faq_only"                  # Just answered a question
    SUPPORT = "support"                    # Technical support
    COMPATIBILITY_CHECK = "compatibility_check"  # Device compatibility question
    TRIAL_REQUESTED = "trial_requested"    # Customer asked for trial
    TRIAL_APPROVAL = "trial_approval"      # Awaiting staff trial approval
    TRIAL_ACTIVE = "trial_active"          # Trial active
    FOLLOW_UP = "follow_up"                # Scheduled follow-up
    REFERRAL = "referral"                  # Referral/reseller interest
    LOST = "lost"                          # Lead lost/declined
    ESCALATED = "escalated"                # Escalated to staff for other reasons

    # --- Existing customer ---
    RENEWAL = "renewal"                    # Existing customer renewal

    # --- Reseller flows ---
    RESELLER_MENU = "reseller_menu"
    RESELLER_DIRECT_SALE = "reseller_direct_sale"
    RESELLER_WALLET_ACTIVATE = "reseller_wallet_activate"


ALL_STATES: frozenset[str] = frozenset({
    State.IDLE, State.HUMAN, State.OPTED_OUT,
    State.PRICES_SENT, State.PACKAGE_SELECTED, State.PAYMENT_READINESS,
    State.DEVICE_SELECTED, State.DEVICE_MODEL, State.INSTALL_METHOD,
    State.AREA_CAPTURED, State.APP_LINK_SENT, State.APP_INSTALLED,
    State.HANDOFF_REQUESTED, State.HUMAN_OWNED, State.SETUP_VERIFIED,
    State.PAYMENT_DUE, State.PAYMENT_VERIFICATION, State.CONVERTED,
    State.FAQ_ONLY, State.SUPPORT, State.COMPATIBILITY_CHECK,
    State.TRIAL_REQUESTED, State.TRIAL_APPROVAL, State.TRIAL_ACTIVE,
    State.FOLLOW_UP, State.REFERRAL, State.LOST, State.ESCALATED,
    State.RENEWAL,
    State.RESELLER_MENU, State.RESELLER_DIRECT_SALE, State.RESELLER_WALLET_ACTIVATE,
})

# Legal transitions. Every state may return to IDLE (reset) or escalate to HUMAN.
# Human-owned states can only be resolved by staff.
TRANSITIONS: dict[str, set[str]] = {
    State.IDLE: {
        State.PRICES_SENT, State.DEVICE_SELECTED, State.FAQ_ONLY, State.SUPPORT,
        State.COMPATIBILITY_CHECK, State.HUMAN, State.REFERRAL,
        State.TRIAL_REQUESTED, State.RENEWAL, State.LOST,
        State.RESELLER_MENU, State.RESELLER_DIRECT_SALE, State.RESELLER_WALLET_ACTIVATE,
    },
    State.RESELLER_MENU: {
        State.IDLE, State.HUMAN, State.RESELLER_DIRECT_SALE, State.RESELLER_WALLET_ACTIVATE,
    },
    State.RESELLER_DIRECT_SALE: {
        State.IDLE, State.HUMAN, State.RESELLER_MENU,
    },
    State.RESELLER_WALLET_ACTIVATE: {
        State.IDLE, State.HUMAN, State.RESELLER_MENU,
    },
    State.PRICES_SENT: {
        State.PACKAGE_SELECTED, State.FAQ_ONLY, State.IDLE, State.HUMAN,
    },
    State.PACKAGE_SELECTED: {
        State.PAYMENT_READINESS, State.PRICES_SENT, State.IDLE, State.HUMAN,
    },
    State.PAYMENT_READINESS: {
        State.DEVICE_SELECTED, State.DEVICE_MODEL, State.PACKAGE_SELECTED, State.IDLE, State.HUMAN,
    },
    State.DEVICE_SELECTED: {
        State.DEVICE_MODEL, State.INSTALL_METHOD, State.AREA_CAPTURED,
        State.APP_LINK_SENT, State.PAYMENT_READINESS, State.IDLE, State.HUMAN,
    },
    State.DEVICE_MODEL: {
        State.INSTALL_METHOD, State.DEVICE_SELECTED, State.IDLE, State.HUMAN,
    },
    State.INSTALL_METHOD: {
        State.AREA_CAPTURED, State.APP_LINK_SENT, State.DEVICE_MODEL, State.IDLE, State.HUMAN,
    },
    State.AREA_CAPTURED: {
        State.APP_LINK_SENT, State.HUMAN, State.IDLE,  # Visit quote pending
    },
    State.APP_LINK_SENT: {
        State.APP_INSTALLED, State.INSTALL_METHOD, State.IDLE, State.HUMAN,
    },
    State.APP_INSTALLED: {
        State.HANDOFF_REQUESTED, State.APP_LINK_SENT, State.IDLE, State.HUMAN,
    },
    State.HANDOFF_REQUESTED: {
        State.HUMAN_OWNED, State.APP_INSTALLED, State.IDLE,
    },
    State.HUMAN_OWNED: {
        State.SETUP_VERIFIED, State.HANDOFF_REQUESTED,  # Staff resolves or re-queues
    },
    State.SETUP_VERIFIED: {
        State.PAYMENT_DUE, State.HUMAN_OWNED, State.IDLE,
    },
    State.PAYMENT_DUE: {
        State.PAYMENT_VERIFICATION, State.SETUP_VERIFIED, State.IDLE, State.HUMAN,
    },
    State.PAYMENT_VERIFICATION: {
        State.CONVERTED, State.PAYMENT_DUE, State.HUMAN, State.IDLE,
    },
    State.CONVERTED: {
        State.RENEWAL, State.SUPPORT, State.IDLE,
    },
    # Branches - can return to main flow or idle
    State.FAQ_ONLY: {State.IDLE, State.PRICES_SENT, State.HUMAN},
    State.SUPPORT: {State.IDLE, State.HUMAN, State.ESCALATED},
    State.COMPATIBILITY_CHECK: {State.DEVICE_SELECTED, State.IDLE, State.HUMAN},
    State.TRIAL_REQUESTED: {State.TRIAL_APPROVAL, State.IDLE, State.HUMAN},
    State.TRIAL_APPROVAL: {State.TRIAL_ACTIVE, State.TRIAL_REQUESTED, State.IDLE, State.HUMAN},
    State.TRIAL_ACTIVE: {State.PAYMENT_READINESS, State.CONVERTED, State.IDLE, State.HUMAN},
    State.FOLLOW_UP: {State.IDLE, State.HUMAN},
    State.REFERRAL: {State.IDLE, State.PRICES_SENT, State.HUMAN},
    State.LOST: {State.IDLE},
    State.ESCALATED: {State.HUMAN, State.IDLE},
    State.RENEWAL: {State.PACKAGE_SELECTED, State.PAYMENT_DUE, State.IDLE, State.HUMAN},
    State.HUMAN: {State.IDLE},  # Customer can reset from human
    State.OPTED_OUT: {State.IDLE},  # Opt-in returns to idle
}

# States where the bot is actively guiding a flow (not idle, not human-owned)
IN_FLOW_STATES: frozenset[str] = frozenset({
    State.PRICES_SENT, State.PACKAGE_SELECTED, State.PAYMENT_READINESS,
    State.DEVICE_SELECTED, State.DEVICE_MODEL, State.INSTALL_METHOD,
    State.AREA_CAPTURED, State.APP_LINK_SENT, State.APP_INSTALLED,
    State.HANDOFF_REQUESTED, State.SETUP_VERIFIED, State.PAYMENT_DUE,
    State.PAYMENT_VERIFICATION, State.FAQ_ONLY, State.SUPPORT,
    State.COMPATIBILITY_CHECK, State.TRIAL_REQUESTED, State.TRIAL_APPROVAL,
    State.TRIAL_ACTIVE, State.FOLLOW_UP, State.REFERRAL, State.RENEWAL,
})

# States that can be entered from IDLE without following the full chain
ENTRY_STATES: frozenset[str] = frozenset({
    State.PRICES_SENT, State.DEVICE_SELECTED, State.FAQ_ONLY, State.SUPPORT,
    State.COMPATIBILITY_CHECK, State.HUMAN, State.REFERRAL,
    State.TRIAL_REQUESTED, State.RENEWAL,
    State.RESELLER_MENU, State.RESELLER_DIRECT_SALE, State.RESELLER_WALLET_ACTIVATE,
})


# Interactive payload kinds and which states accept them
# Format: "kind:value" - validated in payload_allowed()
PAYLOAD_STATES: dict[str, Optional[frozenset[str]]] = {
    "menu": None,
    "reseller": None,  # Any state
    "pkg": frozenset({State.PRICES_SENT, State.PACKAGE_SELECTED, State.RENEWAL}),
    "ready": frozenset({State.PACKAGE_SELECTED, State.PAYMENT_READINESS}),
    "device": frozenset({State.PAYMENT_READINESS, State.DEVICE_SELECTED}),
    "install": frozenset({State.DEVICE_SELECTED, State.INSTALL_METHOD}),
    "app_installed": frozenset({State.APP_LINK_SENT, State.APP_INSTALLED}),
    "trial": frozenset({State.TRIAL_REQUESTED}),
    "renewal": frozenset({State.RENEWAL, State.CONVERTED}),
    "reset": None,  # Any non-human state
}


def can_transition(current: str, target: str) -> bool:
    """True if moving current -> target is allowed by the machine."""
    if target not in ALL_STATES or current not in ALL_STATES:
        return False
    # Reset to idle and escalation to human are always permitted.
    if target in (State.IDLE, State.HUMAN, State.OPTED_OUT):
        return True
    if current == target:
        return True  # re-prompting the same step
    if target in ENTRY_STATES and current not in (State.HUMAN, State.HUMAN_OWNED, State.OPTED_OUT):
        return True
    return target in TRANSITIONS.get(current, set())


def payload_allowed(kind: str, state: str) -> bool:
    """True if an interactive reply of this kind belongs to ``state``."""
    if kind not in PAYLOAD_STATES or state in (State.HUMAN, State.HUMAN_OWNED, State.OPTED_OUT):
        return False
    allowed = PAYLOAD_STATES[kind]
    return allowed is None or state in allowed


class IllegalTransition(RuntimeError):
    pass


@dataclass
class Conversation:
    wa_id: str
    state: str
    lang: str
    draft: dict
    handoff: bool
    profile_name: Optional[str]
    opted_out: bool = False
    last_user_at: Optional[str] = None
    # NexgloTV specific fields
    is_existing_customer: bool = False
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    updated_at: Optional[str] = None


class Store(Database):
    """SQLite-backed conversation store for NexgloTV."""

    # ---------------------------------------------------------- conversations
    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
            row = con.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
            con.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))

    def ensure_conversation(self, wa_id: str, profile_name: Optional[str] = None) -> None:
        auto_mode = self.get_setting("auto_reply_mode", "all")
        # In 'selective' mode, new incoming contacts start in Human mode (bot paused)
        initial_handoff = 1 if auto_mode == "selective" else 0
        initial_state = State.HUMAN if initial_handoff else State.IDLE
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO conversations (wa_id, profile_name, state, handoff, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (wa_id, profile_name, initial_state, initial_handoff, self._ts(), self._ts()),
            )
            if profile_name:
                con.execute(
                    "UPDATE conversations SET profile_name = ? "
                    "WHERE wa_id = ? AND (profile_name IS NULL OR profile_name = '')",
                    (profile_name, wa_id),
                )

    def get_conversation(self, wa_id: str) -> Conversation:
        with self._connect() as con:
            row = con.execute(
                "SELECT wa_id, state, lang, draft, handoff, profile_name, opted_out, last_user_at, "
                "is_existing_customer, customer_id, lead_id, updated_at "
                "FROM conversations WHERE wa_id = ?",
                (wa_id,),
            ).fetchone()
        if row is None:
            return Conversation(wa_id, State.IDLE, "en", {}, False, None)
        return Conversation(
            wa_id=row["wa_id"],
            state=row["state"],
            lang=row["lang"],
            draft=json.loads(row["draft"] or "{}"),
            handoff=bool(row["handoff"]),
            profile_name=row["profile_name"],
            opted_out=bool(row["opted_out"]),
            last_user_at=row["last_user_at"],
            is_existing_customer=bool(row["is_existing_customer"]),
            customer_id=row["customer_id"],
            lead_id=row["lead_id"],
            updated_at=row["updated_at"],
        )

    def list_conversations(self, states: Optional[set[str]] = None) -> list[Conversation]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT wa_id, state, lang, draft, handoff, profile_name, opted_out, last_user_at, "
                "is_existing_customer, customer_id, lead_id, updated_at "
                "FROM conversations ORDER BY updated_at ASC"
            ).fetchall()
        convs = [
            Conversation(
                wa_id=row["wa_id"],
                state=row["state"],
                lang=row["lang"],
                draft=json.loads(row["draft"] or "{}"),
                handoff=bool(row["handoff"]),
                profile_name=row["profile_name"],
                opted_out=bool(row["opted_out"]),
                last_user_at=row["last_user_at"],
                is_existing_customer=bool(row["is_existing_customer"]),
                customer_id=row["customer_id"],
                lead_id=row["lead_id"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
        if states is not None:
            convs = [c for c in convs if c.state in states]
        return convs

    def conversation_exists(self, wa_id: str) -> bool:
        with self._connect() as con:
            row = con.execute("SELECT 1 FROM conversations WHERE wa_id = ?", (wa_id,)).fetchone()
        return row is not None

    def _update(self, wa_id: str, column: str, value) -> None:
        with self._connect() as con:
            con.execute(
                f"UPDATE conversations SET {column} = ?, updated_at = ? WHERE wa_id = ?",
                (value, self._ts(), wa_id),
            )

    def set_state(self, wa_id: str, state: str) -> None:
        self._update(wa_id, "state", state)

    def set_lang(self, wa_id: str, lang: str) -> None:
        self._update(wa_id, "lang", lang)

    def set_handoff(self, wa_id: str, value: bool) -> None:
        self._update(wa_id, "handoff", 1 if value else 0)

    def set_opted_out(self, wa_id: str, value: bool) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE conversations SET opted_out = ?, opted_out_at = ?, updated_at = ? "
                "WHERE wa_id = ?",
                (1 if value else 0, self._ts() if value else None, self._ts(), wa_id),
            )

    def set_customer_flag(self, wa_id: str, is_customer: bool, customer_id: Optional[str] = None) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE conversations SET is_existing_customer = ?, customer_id = ?, updated_at = ? "
                "WHERE wa_id = ?",
                (1 if is_customer else 0, customer_id, self._ts(), wa_id),
            )

    def set_lead_id(self, wa_id: str, lead_id: str) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE conversations SET lead_id = ?, updated_at = ? WHERE wa_id = ?",
                (lead_id, self._ts(), wa_id),
            )

    def touch_user(self, wa_id: str, when: Optional[str] = None) -> None:
        """Record the customer's latest inbound message (opens the 24h window)."""
        self._update(wa_id, "last_user_at", when or self._ts())

    def update_draft(self, wa_id: str, patch: dict) -> dict:
        with self._connect() as con:
            row = con.execute(
                "SELECT draft FROM conversations WHERE wa_id = ?", (wa_id,)
            ).fetchone()
            draft = json.loads(row["draft"] or "{}") if row else {}
            for key, value in patch.items():
                if value is None:
                    draft.pop(key, None)
                else:
                    draft[key] = value
            con.execute(
                "UPDATE conversations SET draft = ?, updated_at = ? WHERE wa_id = ?",
                (json.dumps(draft, ensure_ascii=False), self._ts(), wa_id),
            )
            return draft

    def clear_draft(self, wa_id: str) -> None:
        self._update(wa_id, "draft", "{}")

    # -------------------------------------------------------------- messages
    def add_message(self, wa_id: str, role: str, content: str, author: Optional[str] = None) -> None:
        author = author or ("customer" if role == "user" else "bot")
        with self._connect() as con:
            con.execute(
                "INSERT INTO messages (wa_id, role, content, author, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (wa_id, role, content, author, self._ts()),
            )

    def history(self, wa_id: str, limit: int = 10) -> list[dict]:
        """Last ``limit`` turns as LLM chat messages (role/content)."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT role, content FROM messages WHERE wa_id = ? ORDER BY id DESC LIMIT ?",
                (wa_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def transcript(self, wa_id: str, limit: int = 50) -> list[dict]:
        """Last ``limit`` messages with author and timestamp (staff console)."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, author, role, content, created_at FROM messages "
                "WHERE wa_id = ? ORDER BY id DESC LIMIT ?",
                (wa_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]