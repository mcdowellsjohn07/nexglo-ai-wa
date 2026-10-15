"""Staff HTTP API for human handoff and bookings (``/admin``).

Protected by a bearer token: set ``ADMIN_TOKEN`` and send
``Authorization: Bearer <ADMIN_TOKEN>``. Without ``ADMIN_TOKEN`` every endpoint
answers 503, so a fresh deployment never exposes customer data by accident.

    GET  /admin/handoffs                         open queue (+ last messages)
    GET  /admin/conversations/{wa_id}            transcript, state, bookings
    POST /admin/conversations/{wa_id}/reply      {"text": "..."}  -> WhatsApp
    POST /admin/handoffs/{wa_id}/resolve         {"notify": true} -> bot back on
    GET  /admin/bookings?date=YYYY-MM-DD&status= confirmed|cancelled|conflict|all
    POST /admin/bookings/{id}/cancel             {"notify": true}

The rules (24-hour window, opt-out, takeover) live in ``app/staff.py``.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .deps import Services
from .staff import StaffDesk, StaffError
from .webhook import get_services

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard", response_class=HTMLResponse)
@router.get("/dashboard/", response_class=HTMLResponse)
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def admin_dashboard() -> HTMLResponse:
    """Sleek web-based Staff & Admin Console for NexgloTV."""
    from .dashboard_html import DASHBOARD_HTML

    return HTMLResponse(content=DASHBOARD_HTML)




def staff_desk(
    authorization: Optional[str] = Header(default=None),
    services: Services = Depends(get_services),
) -> StaffDesk:
    settings = services.settings
    if not settings.admin_enabled:
        raise HTTPException(status_code=503, detail="Admin API disabled: set ADMIN_TOKEN to enable it.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), settings.admin_token.encode()):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return StaffDesk(services)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except StaffError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class NotifyIn(BaseModel):
    notify: bool = True


class VerifyPaymentIn(BaseModel):
    wa_id: str = Field(min_length=1)
    payment_id: str = ""
    verified_by: str = "staff"


class ConfirmSetupIn(BaseModel):
    wa_id: str = Field(min_length=1)
    staff_name: str = "staff"


class ApproveTrialIn(BaseModel):
    duration_hours: int = Field(default=24, ge=1, le=720)
    approved_by: str = "staff"


class VisitQuoteIn(BaseModel):
    wa_id: str = Field(min_length=1)
    fee_le: int = Field(ge=0)
    approved_by: str = "staff"


class RunAutomationsIn(BaseModel):
    stalled_after_hours: float = Field(default=2.0, ge=0.0, le=720.0)
    payment_remind_after_hours: float = Field(default=1.0, ge=0.0, le=720.0)
    renewal_days_before: int = Field(default=3, ge=0, le=90)


class DryRunIn(BaseModel):
    enabled: bool


class AutoReplyModeIn(BaseModel):
    mode: str = Field(pattern="^(all|selective)$")


class ContactModeIn(BaseModel):
    mode: str = Field(pattern="^(bot|human|ai|staff)$")


@router.get("/settings")
def get_settings(desk: StaffDesk = Depends(staff_desk)) -> dict:
    default_mode = getattr(desk.store, "default_auto_reply_mode", "all")
    return {
        "dry_run": desk.services.wa.dry_run,
        "auto_reply_mode": desk.store.get_setting("auto_reply_mode", default_mode),
        "whatsapp_configured": desk.settings.whatsapp_configured,
    }


@router.post("/settings/dry-run")
def set_dry_run(body: DryRunIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    try:
        new_val = desk.services.wa.set_dry_run(body.enabled)
        return {"status": "success", "dry_run": new_val}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/settings/auto-reply-mode")
def set_auto_reply_mode(body: AutoReplyModeIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    desk.store.set_setting("auto_reply_mode", body.mode)
    if body.mode == "all":
        desk.store.set_all_conversations_mode("bot")
    elif body.mode == "selective":
        desk.store.set_all_conversations_mode("human")
    return {"status": "success", "auto_reply_mode": body.mode}


@router.get("/handoffs")
def list_handoffs(last: int = Query(5, ge=0, le=50), desk: StaffDesk = Depends(staff_desk)) -> dict:
    items = desk.queue(last_messages=last)
    return {"count": len(items), "handoffs": items}


@router.get("/conversations")
def list_conversations(limit: int = Query(50, ge=1, le=500), desk: StaffDesk = Depends(staff_desk)) -> dict:
    items = desk.recent_conversations(limit=limit)
    return {"count": len(items), "conversations": items}


@router.get("/conversations/{wa_id}")
def get_conversation(wa_id: str, limit: int = Query(50, ge=1, le=500), desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.conversation, wa_id, limit=limit)


@router.post("/conversations/{wa_id}/mode")
def set_contact_mode(wa_id: str, body: ContactModeIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.set_contact_mode, wa_id, body.mode)


@router.post("/conversations/{wa_id}/reply")
def reply(wa_id: str, body: ReplyIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.reply, wa_id, body.text)


@router.post("/handoffs/{wa_id}/resolve")
def resolve(wa_id: str, body: Optional[NotifyIn] = None, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.resolve, wa_id, notify=(body or NotifyIn()).notify)


@router.post("/handoffs/{wa_id}/takeover")
def takeover(wa_id: str, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.takeover, wa_id)


@router.post("/payments/verify")
def verify_payment(body: VerifyPaymentIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.verify_payment, body.wa_id, body.payment_id, body.verified_by)


@router.post("/leads/confirm-setup")
def confirm_setup(body: ConfirmSetupIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.confirm_setup, body.wa_id, body.staff_name)


@router.post("/trials/{wa_id}/approve")
def approve_trial(wa_id: str, body: Optional[ApproveTrialIn] = None, desk: StaffDesk = Depends(staff_desk)) -> dict:
    req = body or ApproveTrialIn()
    return _run(desk.approve_trial, wa_id, req.duration_hours, req.approved_by)


@router.post("/leads/visit-quote")
def issue_visit_quote(body: VisitQuoteIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.issue_visit_quote, body.wa_id, body.fee_le, body.approved_by)


@router.get("/bookings")
def bookings(
    date: Optional[str] = Query(None, description="YYYY-MM-DD; default: today onwards"),
    status: str = Query("confirmed", pattern="^(confirmed|cancelled|conflict|all)$"),
    desk: StaffDesk = Depends(staff_desk),
) -> dict:
    rows = _run(desk.bookings, date, status=status)
    return {"count": len(rows), "bookings": rows}


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, body: Optional[NotifyIn] = None, desk: StaffDesk = Depends(staff_desk)) -> dict:
    return _run(desk.cancel_booking, booking_id, notify=(body or NotifyIn()).notify)


@router.get("/automations/status")
def automations_status(desk: StaffDesk = Depends(staff_desk)) -> dict:
    from .automations import AutomationRunner
    runner = desk.services.automations or AutomationRunner(desk.services)
    desk.services.automations = runner
    return runner.status()


@router.post("/automations/run")
def run_automations(
    body: Optional[RunAutomationsIn] = None,
    desk: StaffDesk = Depends(staff_desk),
) -> dict:
    from .automations import AutomationRunner
    req = body or RunAutomationsIn()
    runner = desk.services.automations or AutomationRunner(desk.services)
    desk.services.automations = runner
    return runner.run_all(
        stalled_after_hours=req.stalled_after_hours,
        payment_remind_after_hours=req.payment_remind_after_hours,
        renewal_days_before=req.renewal_days_before,
    )


class ResellerWebhookIn(BaseModel):
    event_type: str = Field(default="promote_intake_and_sync")
    reseller_code: str = Field(min_length=1)
    source_table: str = ""
    record_id: str = ""
    portal_base_token: str = ""


@router.post("/reseller/sync-webhook")
def reseller_sync_webhook(
    body: ResellerWebhookIn,
    desk: StaffDesk = Depends(staff_desk),
) -> dict:
    """Event-driven webhook endpoint for Lark Base HTTPClientAction workflows (Part D)."""
    from .reseller_lark import ResellerSystemManager
    mgr = ResellerSystemManager()
    return mgr.process_reseller_webhook_event(
        event_type=body.event_type,
        reseller_code=body.reseller_code,
        source_table=body.source_table,
        record_id=body.record_id,
        portal_base_token=body.portal_base_token,
    )


@router.post("/reseller/sync/{reseller_code}")
def reseller_sync_portal(
    reseller_code: str,
    portal_base_token: str = Query(default=""),
    desk: StaffDesk = Depends(staff_desk),
) -> dict:
    """On-demand 1-click projection of Master CRM approved records to a reseller's isolated Portal Base."""
    from .reseller_lark import ResellerSystemManager
    mgr = ResellerSystemManager()
    return mgr.sync_approved_master_to_reseller_portal(
        reseller_code=reseller_code,
        portal_base_token=portal_base_token,
    )


class SelectModelIn(BaseModel):
    model: str = Field(min_length=1)


@router.get("/models")
def list_models(desk: StaffDesk = Depends(staff_desk)) -> dict:
    """List the active LLM model and recommended model catalog (OpenRouter or NVIDIA NIM)."""
    from .llm import RECOMMENDED_NVIDIA_MODELS, RECOMMENDED_OPENROUTER_MODELS

    services = desk.services
    is_nvidia = services.settings.llm_provider in ("nvidia", "nim")
    recommended = RECOMMENDED_NVIDIA_MODELS if is_nvidia else RECOMMENDED_OPENROUTER_MODELS
    return {
        "provider": services.settings.llm_provider,
        "configured": services.llm.available,
        "current_model": services.llm.model,
        "recommended": recommended,
    }


@router.post("/models/select")
def select_model(body: SelectModelIn, desk: StaffDesk = Depends(staff_desk)) -> dict:
    """Hot-swap the active OpenRouter/LLM model dynamically without server restart."""
    services = desk.services
    new_model = services.llm.set_model(body.model)
    return {
        "status": "success",
        "current_model": new_model,
        "provider": services.settings.llm_provider,
    }

