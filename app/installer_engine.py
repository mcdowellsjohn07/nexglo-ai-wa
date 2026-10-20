"""NexgloTV Unified Reseller + Installer Calculation and Workflow Engine.

Implements the official specification for:
1. Unified Partner Model (single partner entity in 09_Resellers, 'Reseller Only' vs 'Reseller + Installer').
2. 20% Subscription Sales Commission (unchanged, isolated in 11_Commissions).
3. 40% Physical Installation Commission (min SLE 100 fee, 40% to installer, 60% company retained).
4. Monthly Installer Performance Bands:
   - 0-4 jobs: Starter (SLE 0)
   - 5-9 jobs: Bronze (SLE 50)
   - 10-19 jobs: Silver (SLE 125)
   - 20-29 jobs: Gold (SLE 250)
   - 30-49 jobs: Platinum (SLE 450)
   - 50+ jobs: Diamond (SLE 750)
   Paid once per month, non-cumulative, deterministic cutoff at later of staff & finance verification.
5. Strict Idempotency & Separation of Funds:
   - Keys: INSTALL40:<InstallationID> and BONUS:<ResellerID>:<YYYY-MM>
   - Wallet balances are completely isolated from unpaid commissions and installation earnings.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.crm_sheets import (
    InstallationRecord,
    InstallerEarningRecord,
    InstallerMonthlyPerformanceRecord,
)
from app.reseller_bot import normalize_phone_sl, phone_matches

log = logging.getLogger("nexglo.installer_engine")

BAND_THRESHOLDS = [
    (50, "Diamond", 750),
    (30, "Platinum", 450),
    (20, "Gold", 250),
    (10, "Silver", 125),
    (5, "Bronze", 50),
    (1, "Starter", 0),
    (0, "None", 0),
]


def calculate_installer_earning(fee_sle: float, rate_pct: float = 40.0) -> dict[str, Any]:
    """Calculate installer earning and company retained share for a physical installation.
    
    Minimum standard physical visit fee is SLE 100.
    """
    basis = max(0.0, float(fee_sle or 0.0))
    earning = round(basis * (rate_pct / 100.0), 2)
    retained = round(basis - earning, 2)
    return {
        "basis_fee_sle": basis,
        "rate_pct": rate_pct,
        "installer_earning_sle": earning,
        "company_retained_sle": retained,
        "qualifying": basis >= 100.0,
    }


def get_monthly_performance_band(qualifying_count: int) -> tuple[str, int]:
    """Return (band_name, bonus_sle) for a given monthly qualifying physical job count.
    
    Highest tier is awarded once per month. Non-cumulative.
    """
    count = max(0, int(qualifying_count or 0))
    for min_count, band_name, bonus_sle in BAND_THRESHOLDS:
        if count >= min_count:
            return band_name, bonus_sle
    return "None", 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _current_month_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class InstallerManager:
    """Manages installation work orders, installer assignments, verifications, and earnings."""

    def __init__(self, crm=None, reseller_mgr=None, store=None, wa=None):
        self.crm = crm
        self.reseller_mgr = reseller_mgr
        self.store = store
        self.wa = wa

        # In-memory storage / caches
        self._installations: dict[str, InstallationRecord] = {}
        self._installer_earnings: list[InstallerEarningRecord] = []
        self._monthly_perf: dict[str, InstallerMonthlyPerformanceRecord] = {}  # key: "{reseller_id}:{YYYY-MM}"

    # =========================================================================
    # Partner Lookup & Verification
    # =========================================================================

    def get_installer_profile(self, identifier: str):
        """Find reseller partner by ID, code, or phone number."""
        clean = (identifier or "").strip()
        if not clean or not self.reseller_mgr:
            return None

        # Check by phone first
        prof = self.reseller_mgr.identify_reseller(clean)
        if prof:
            return prof

        # Search registered profiles in memory or Lark
        clean_upper = clean.upper()
        for p in self.reseller_mgr._resellers_by_code.values():
            if p.reseller_id.upper() == clean_upper or p.reseller_code.upper() == clean_upper:
                return p
        for p in self.reseller_mgr._resellers_by_phone.values():
            if p.reseller_id.upper() == clean_upper or p.reseller_code.upper() == clean_upper:
                return p

        return None

    def is_approved_installer(self, partner) -> bool:
        """Check if partner has verified Reseller + Installer status."""
        if not partner:
            return False
        role = getattr(partner, "partner_role", "Reseller Only")
        status = getattr(partner, "installer_approval_status", "Not Applied")
        return role == "Reseller + Installer" and status == "Approved"

    # =========================================================================
    # Installation Jobs Lifecycle
    # =========================================================================

    def create_installation_job(
        self,
        customer_phone: str,
        customer_name: str,
        area: str,
        quoted_fee_sle: int = 100,
        device_platform: str = "Smart TV",
        device_count: int = 1,
        install_mode: str = "Paid Physical",
        notes: str = "",
        credited_sales_reseller_id: str = "",
        assigned_installer_reseller_id: str = "",
        staff_id: str = "ADMIN",
    ) -> InstallationRecord:
        """Create a new installation booking in 07_Installations."""
        phone = normalize_phone_sl(customer_phone)
        inst_id = f"INS-{len(self._installations) + 101}"

        fee = max(0, int(quoted_fee_sle))
        inst = InstallationRecord(
            installation_id=inst_id,
            wa_id=phone,
            customer_name=customer_name,
            device_platform=device_platform,
            device_count=max(1, device_count),
            installation_method="physical_visit" if install_mode == "Paid Physical" else "remote",
            area=area,
            visit_fee_le=fee,
            quoted_fee_sle=fee,
            approved_fee_sle=fee,
            fee_quote_version="v1.0",
            fee_approved_by=staff_id,
            fee_approved_at=_now_iso(),
            install_mode=install_mode,
            setup_status="pending",
            issue_note=notes,
            credited_sales_reseller_id=credited_sales_reseller_id,
            assigned_installer_reseller_id=assigned_installer_reseller_id,
            installer_assignment_status="Assigned" if assigned_installer_reseller_id else "Unassigned",
            assigned_at=_now_iso() if assigned_installer_reseller_id else "",
        )

        self._installations[inst_id] = inst

        # Sync to CRM provider (Lark Base)
        if self.crm and hasattr(self.crm, "provider") and hasattr(self.crm.provider, "upsert_installation"):
            try:
                self.crm.provider.upsert_installation(inst)
            except Exception as exc:
                log.warning("Lark Base upsert_installation error: %s", exc)

        return inst

    def get_installation(self, install_id: str) -> Optional[InstallationRecord]:
        """Retrieve installation record by ID."""
        clean = (install_id or "").strip().upper()
        if clean in self._installations:
            return self._installations[clean]
        # Search case-insensitive
        for k, v in self._installations.items():
            if k.upper() == clean:
                return v
        return None

    def offer_job(self, install_id: str, reseller_id: str, staff_id: str = "ADMIN") -> tuple[bool, str]:
        """Offer an unassigned installation job to an approved installer partner."""
        inst = self.get_installation(install_id)
        if not inst:
            return False, f"❌ Installation job `{install_id}` not found."

        installer = self.get_installer_profile(reseller_id)
        if not installer:
            return False, f"❌ Reseller partner `{reseller_id}` not found."

        if not self.is_approved_installer(installer):
            return False, f"⚠️ Partner *{installer.name}* (`{installer.reseller_id}`) is not an approved installer.\nRole: `{installer.partner_role}`, Status: `{installer.installer_approval_status}`."

        inst.assigned_installer_reseller_id = installer.reseller_id
        inst.installer_assignment_status = "Offered"
        inst.assigned_at = _now_iso()

        # Update CRM
        self._sync_installation(inst)

        # Notify installer via WhatsApp if client available
        if self.wa and hasattr(self.wa, "send_text") and installer.phone:
            quote = calculate_installer_earning(inst.approved_fee_sle or inst.visit_fee_le)
            msg = (
                f"🔧 *New Installation Job Offer: {inst.installation_id}*\n\n"
                f"• *Customer:* {inst.customer_name}\n"
                f"• *Area:* {inst.area}\n"
                f"• *Device:* {inst.device_platform} ({inst.device_count} screen(s))\n"
                f"• *Installation Fee:* SLE {inst.approved_fee_sle:,}\n"
                f"• *Your 40% Commission:* *SLE {quote['installer_earning_sle']:,}*\n\n"
                f"To accept this job, reply:\n👉 *ACCEPT {inst.installation_id}*\n"
                f"To decline, reply:\n👉 *DECLINE {inst.installation_id}*"
            )
            try:
                self.wa.send_text(installer.phone, msg)
            except Exception as exc:
                log.warning("Could not send WhatsApp offer to installer %s: %s", installer.phone, exc)

        return True, f"✅ Installation `{inst.installation_id}` offered to *{installer.name}* (`{installer.reseller_id}`)."

    def installer_accept_job(self, install_id: str, caller_phone: str) -> tuple[bool, str]:
        """Installer accepts an offered installation job from their registered WhatsApp phone."""
        inst = self.get_installation(install_id)
        if not inst:
            return False, f"❌ Installation job `{install_id}` not found."

        caller = self.get_installer_profile(caller_phone)
        if not caller:
            return False, "❌ Sender is not recognized as a registered partner."

        if inst.assigned_installer_reseller_id and not (
            inst.assigned_installer_reseller_id == caller.reseller_id or
            phone_matches(caller.phone, caller_phone)
        ):
            return False, f"⚠️ This job was offered to a different partner."

        inst.assigned_installer_reseller_id = caller.reseller_id
        inst.installer_assignment_status = "Accepted"
        inst.accepted_at = _now_iso()
        inst.setup_status = "in_progress"
        self._sync_installation(inst)

        return True, (
            f"✅ *Job Accepted: {inst.installation_id}*\n\n"
            f"• *Customer:* {inst.customer_name} (`{inst.wa_id}`)\n"
            f"• *Location:* {inst.area}\n"
            f"• *Screens:* {inst.device_count} × {inst.device_platform}\n\n"
            f"When completed, send completion proof:\n👉 *DONE {inst.installation_id}*"
        )

    def installer_decline_job(self, install_id: str, caller_phone: str, reason: str = "") -> tuple[bool, str]:
        """Installer declines an offered installation job."""
        inst = self.get_installation(install_id)
        if not inst:
            return False, f"❌ Installation job `{install_id}` not found."

        caller = self.get_installer_profile(caller_phone)
        if not caller:
            return False, "❌ Sender is not recognized as a registered partner."

        inst.installer_assignment_status = "Declined"
        inst.assigned_installer_reseller_id = ""
        inst.issue_note = f"Declined by {caller.name}: {reason}" if reason else f"Declined by {caller.name}"
        self._sync_installation(inst)

        return True, f"ℹ️ Job `{inst.installation_id}` has been declined and returned to dispatch queue."

    def installer_submit_completion(self, install_id: str, caller_phone: str, notes: str = "") -> tuple[bool, str]:
        """Installer reports job completed (pending independent staff verification)."""
        inst = self.get_installation(install_id)
        if not inst:
            return False, f"❌ Installation job `{install_id}` not found."

        caller = self.get_installer_profile(caller_phone)
        if not caller:
            return False, "❌ Sender is not recognized as a registered partner."

        inst.customer_confirmed_working_at = _now_iso()
        inst.app_installed_reported_at = _now_iso()
        inst.setup_status = "completion_reported"
        if notes:
            inst.issue_note = f"{inst.issue_note} | Completion Note: {notes}".strip(" |")

        self._sync_installation(inst)

        return True, (
            f"📋 *Completion Evidence Received: {inst.installation_id}*\n\n"
            "Your completion report has been submitted.\n"
            "Status: *Pending Independent Staff & Finance Verification*.\n\n"
            "⚠️ Commission is awarded only after staff confirms playback & finance verifies the fee."
        )

    def staff_verify_completion(self, install_id: str, staff_id: str = "ADMIN") -> tuple[bool, str]:
        """Admin or staff verifies physical playback and app installation."""
        inst = self.get_installation(install_id)
        if not inst:
            return False, f"❌ Installation job `{install_id}` not found."

        inst.completion_verified_by = staff_id
        inst.completion_verified_at = _now_iso()
        inst.setup_status = "verified"
        inst.setup_verified_at = _now_iso()

        # Check qualification gate
        qualified_msg = self._check_and_qualify(inst, staff_id)
        self._sync_installation(inst)

        base_msg = f"✅ Physical installation `{inst.installation_id}` verified by staff `{staff_id}`."
        if qualified_msg:
            return True, f"{base_msg}\n\n{qualified_msg}"
        else:
            return True, f"{base_msg}\n⏳ *Awaiting finance verification of installation fee* before qualifying commission."

    def finance_verify_fee(
        self,
        install_id: str,
        amount_received_sle: int,
        payment_reference: str = "",
        staff_id: str = "FINANCE",
    ) -> tuple[bool, str]:
        """Finance verifies full collection of physical installation fee."""
        inst = self.get_installation(install_id)
        if not inst:
            return False, f"❌ Installation job `{install_id}` not found."

        inst.fee_received_verified_sle = int(amount_received_sle)
        inst.fee_payment_status = "Verified"
        inst.fee_approved_by = staff_id
        inst.fee_approved_at = _now_iso()
        if payment_reference:
            inst.installation_fee_payment_id = payment_reference

        # Check qualification gate
        qualified_msg = self._check_and_qualify(inst, staff_id)
        self._sync_installation(inst)

        base_msg = f"💰 Installation fee of *SLE {amount_received_sle:,}* verified for `{inst.installation_id}`."
        if qualified_msg:
            return True, f"{base_msg}\n\n{qualified_msg}"
        else:
            return True, f"{base_msg}\n⏳ *Awaiting staff completion verification* before qualifying commission."

    # =========================================================================
    # Qualification Gate & Earnings Creation
    # =========================================================================

    def _check_and_qualify(self, inst: InstallationRecord, staff_id: str) -> Optional[str]:
        """Check if installation satisfies both completion and fee verification gates."""
        # 1. Must have assigned installer
        reseller_id = inst.assigned_installer_reseller_id
        if not reseller_id:
            return None

        # 2. Must be Paid Physical mode
        if inst.install_mode != "Paid Physical":
            return None

        # 3. Must be completed & verified by staff
        if not inst.completion_verified_at:
            return None

        # 4. Must have verified installation fee
        if inst.fee_payment_status != "Verified" or inst.fee_received_verified_sle <= 0:
            return None

        # 5. Must not be on dispute/refund hold
        if inst.refund_dispute_hold:
            return None

        # 6. Idempotency guard: do not qualify twice
        if inst.installation_earning_id or inst.qualified_at:
            return None

        # Check partner approval
        partner = self.get_installer_profile(reseller_id)
        if not partner or not self.is_approved_installer(partner):
            return f"⚠️ Installation verified, but partner `{reseller_id}` is not an approved installer. Commission held."

        # Qualification timestamp is later of staff completion and finance fee verification
        qualified_dt = max(
            inst.completion_verified_at or _now_iso(),
            inst.fee_approved_at or _now_iso(),
        )
        qualified_month = qualified_dt[:7]  # YYYY-MM

        inst.qualified_at = qualified_dt
        inst.qualified_month = qualified_month
        inst.monthly_count_eligible = True

        # Calculate 40% earning
        fee = inst.fee_received_verified_sle
        split = calculate_installer_earning(fee, rate_pct=40.0)
        earning_sle = int(split["installer_earning_sle"])
        retained_sle = int(split["company_retained_sle"])

        earning_id = f"EARN-INS-{inst.installation_id}"
        idempotency_key = f"INSTALL40:{inst.installation_id}"
        inst.installation_earning_id = earning_id

        # Create Earning Record
        earning_rec = InstallerEarningRecord(
            earning_id=earning_id,
            reseller_id=reseller_id,
            earning_type="INSTALLATION_BASE",
            installation_id=inst.installation_id,
            performance_month=qualified_month,
            idempotency_key=idempotency_key,
            basis_fee_sle=fee,
            rate_snapshot_pct=40,
            signed_earning_sle=earning_sle,
            status="Approved",
            qualified_at=qualified_dt,
            approved_by=staff_id,
            approved_at=_now_iso(),
            outstanding_sle=earning_sle,
            created_at=_now_iso(),
        )
        self._installer_earnings.append(earning_rec)

        # Update partner unpaid installer earnings in memory
        partner.unpaid_installer_earnings = getattr(partner, "unpaid_installer_earnings", 0) + earning_sle

        # Update Monthly Performance
        perf = self._get_or_create_monthly_perf(reseller_id, qualified_month)
        inst_ids = [x for x in perf.qualifying_installation_ids.split(",") if x]
        if inst.installation_id not in inst_ids:
            inst_ids.append(inst.installation_id)
        perf.qualifying_installation_ids = ",".join(inst_ids)
        perf.qualifying_count = len(inst_ids)

        # Update provisional band
        new_band, new_bonus = get_monthly_performance_band(perf.qualifying_count)
        perf.provisional_band = new_band
        perf.provisional_bonus_sle = new_bonus

        return (
            f"🎉 *Installation Qualified!*\n"
            f"• Partner: *{partner.name}* (`{partner.reseller_id}`)\n"
            f"• Installation Fee: SLE {fee:,}\n"
            f"• 40% Installer Earning: *SLE {earning_sle:,}* (ID: `{earning_id}`)\n"
            f"• Company Retained: SLE {retained_sle:,}\n"
            f"• Qualifying Jobs This Month ({qualified_month}): *{perf.qualifying_count}*\n"
            f"• Current Performance Band: *{new_band}* (Provisional Bonus: SLE {new_bonus:,})"
        )

    def _get_or_create_monthly_perf(self, reseller_id: str, month: str) -> InstallerMonthlyPerformanceRecord:
        """Fetch or initialize monthly performance tracking record."""
        key = f"{reseller_id}:{month}"
        if key in self._monthly_perf:
            return self._monthly_perf[key]

        perf = InstallerMonthlyPerformanceRecord(
            performance_id=f"PERF:{reseller_id}:{month}",
            reseller_id=reseller_id,
            performance_month=month,
            period_start=f"{month}-01T00:00:00Z",
            period_end=f"{month}-28T23:59:59Z",
            qualifying_count=0,
            provisional_band="None",
            provisional_bonus_sle=0,
            closure_status="Open",
        )
        self._monthly_perf[key] = perf
        return perf

    def lock_month_and_award_bonus(self, reseller_id: str, month: str, locked_by: str = "FINANCE") -> tuple[bool, str]:
        """Finance locks a completed month and posts exactly one non-cumulative bonus earning."""
        perf = self._get_or_create_monthly_perf(reseller_id, month)
        if perf.closure_status == "Locked":
            return False, f"⚠️ Month `{month}` for `{reseller_id}` is already locked."

        count = perf.qualifying_count
        band, bonus = get_monthly_performance_band(count)
        perf.closed_band = band
        perf.approved_bonus_amount_sle = bonus
        perf.closure_status = "Locked"
        perf.locked_at = _now_iso()
        perf.locked_by = locked_by

        if bonus > 0:
            bonus_earning_id = f"EARN-BONUS-{reseller_id}-{month}"
            perf.bonus_earning_id = bonus_earning_id
            bonus_rec = InstallerEarningRecord(
                earning_id=bonus_earning_id,
                reseller_id=reseller_id,
                earning_type="MONTHLY_BONUS",
                performance_month=month,
                idempotency_key=f"BONUS:{reseller_id}:{month}",
                basis_fee_sle=0,
                rate_snapshot_pct=0,
                signed_earning_sle=bonus,
                status="Approved",
                qualified_at=_now_iso(),
                approved_by=locked_by,
                approved_at=_now_iso(),
                outstanding_sle=bonus,
                created_at=_now_iso(),
            )
            self._installer_earnings.append(bonus_rec)

            partner = self.get_installer_profile(reseller_id)
            if partner:
                partner.unpaid_installer_earnings = getattr(partner, "unpaid_installer_earnings", 0) + bonus

            return True, (
                f"🏆 *Month {month} Locked for {reseller_id}*\n"
                f"• Final Qualifying Installs: *{count}*\n"
                f"• Achieved Band: *{band}*\n"
                f"• One-time Approved Bonus: *SLE {bonus:,}* (Earning ID: `{bonus_earning_id}`)"
            )

        return True, f"ℹ️ Month `{month}` locked for `{reseller_id}`. Count: {count}, Bonus: SLE 0."

    # =========================================================================
    # Reporting & Sync
    # =========================================================================

    def get_installer_stats(self, identifier: str, month: Optional[str] = None) -> dict[str, Any]:
        """Aggregate stats for an installer partner."""
        partner = self.get_installer_profile(identifier)
        if not partner:
            return {"found": False, "error": f"Partner `{identifier}` not found."}

        target_month = month or _current_month_str()
        perf = self._get_or_create_monthly_perf(partner.reseller_id, target_month)

        # Calculate total earnings from ledger
        install_earnings = [
            e.signed_earning_sle for e in self._installer_earnings
            if e.reseller_id == partner.reseller_id and e.earning_type == "INSTALLATION_BASE"
        ]
        bonus_earnings = [
            e.signed_earning_sle for e in self._installer_earnings
            if e.reseller_id == partner.reseller_id and e.earning_type == "MONTHLY_BONUS"
        ]

        return {
            "found": True,
            "reseller_id": partner.reseller_id,
            "reseller_code": partner.reseller_code,
            "name": partner.name,
            "phone": partner.phone,
            "partner_role": getattr(partner, "partner_role", "Reseller Only"),
            "approval_status": getattr(partner, "installer_approval_status", "Not Applied"),
            "availability": getattr(partner, "installer_availability_status", "Available"),
            "target_month": target_month,
            "month_qualifying_jobs": perf.qualifying_count,
            "provisional_band": perf.provisional_band,
            "provisional_bonus_sle": perf.provisional_bonus_sle,
            "total_install_earnings_sle": sum(install_earnings),
            "total_bonus_earnings_sle": sum(bonus_earnings),
            "unpaid_installer_earnings_sle": getattr(partner, "unpaid_installer_earnings", 0),
            "subscription_commissions_unpaid_sle": getattr(partner, "unpaid_commissions", 0),
            "wallet_balance_sle": getattr(partner, "wallet_balance", 0),
        }

    def _sync_installation(self, inst: InstallationRecord) -> None:
        """Update installation in local cache and push to CRM."""
        self._installations[inst.installation_id] = inst
        if self.crm and hasattr(self.crm, "provider") and hasattr(self.crm.provider, "upsert_installation"):
            try:
                self.crm.provider.upsert_installation(inst)
            except Exception as exc:
                log.warning("CRM upsert_installation error: %s", exc)
