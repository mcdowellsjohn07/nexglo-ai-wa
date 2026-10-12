"""NexgloTV Lark Base (Bitable) CRM provider — 18-table schema.

Implements the CRMProvider interface from crm_sheets.py against Lark Base via
lark-cli. Activated with CRM_PROVIDER=lark_base.

- Base "NexgloTV CRM" auto-created with all 18 tables + Packages seed data.
- Upserts keyed by each table's ID field (Lead ID, Customer ID, ...).
- Lead/Customer lookup by WhatsApp Number.
- Failed CRM calls raise LarkCLIError; CRMService callers degrade gracefully
  so the customer conversation never blocks (spec §8.3).
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from .crm_sheets import (
    CRMProvider,
    CustomerRecord,
    FollowUpRecord,
    InstallationRecord,
    LeadRecord,
    PaymentRecord,
    ReferralRecord,
    StaffHandoffRecord,
    TrialRecord,
)
from .nexglo_lark_schema import (
    FIELD_SCHEMAS,
    LINK_FIELDS,
    LINKS,
    SEED_PACKAGES,
    TABLE_KEY_FIELD,
    TABLE_WA_FIELD,
    map_record,
)

log = logging.getLogger("nexglo.crm_lark")

BASE_NAME = "NexgloTV CRM"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


class LarkCLIError(RuntimeError):
    pass


def _digits(phone: str) -> str:
    return re.sub(r"[^\d]", "", str(phone or ""))[-9:]  # last 9 digits


def _run_cli(args: list[str], timeout: int = 90, confirm: bool = False) -> dict:
    """Run `lark-cli base <args>` and return parsed JSON (ok=True checked).

    ``confirm=True`` appends ``--yes`` for high-risk-write commands (field
    updates). On Windows the .cmd shim mangles argv JSON, so we invoke node
    against the CLI's run.js directly when available.
    """
    import os
    import shutil

    exe = shutil.which("lark-cli")
    if exe is None:
        # Common Hermes tool install locations (npm .cmd shims on Windows)
        candidates = [
            Path(os.environ.get("HERMES_HOME", "")) / "tools" / "node-26.7.0-win32-x64" / "lark-cli.cmd",
            Path(os.environ.get("HERMES_HOME", "")) / "tools" / "node-26.7.0-win32-x64" / "lark-cli.exe",
            Path.home() / "AppData" / "Local" / "hermes" / "tools" / "node-26.7.0-win32-x64" / "lark-cli.cmd",
            Path.home() / "AppData" / "Local" / "hermes" / "tools" / "node-26.7.0-win32-x64" / "lark-cli.exe",
        ]
        for cand in candidates:
            if cand.is_file():
                exe = str(cand)
                break
    if not exe:
        raise LarkCLIError("lark-cli not found on PATH")
    final_args = ["base", *args, "--format", "json", "--as", "user"]
    if confirm:
        final_args.append("--yes")
    cmd = [exe, *final_args]
    # Windows .cmd shims re-quote argv and mangle JSON payloads; bypass the shim
    # by invoking node against the CLI's run.js entrypoint directly.
    if exe.lower().endswith(".cmd"):
        node_exe = shutil.which("node")
        run_js = Path(exe).parent / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
        if node_exe and run_js.is_file():
            cmd = [node_exe, str(run_js), *final_args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              shell=False)
    except FileNotFoundError as exc:
        raise LarkCLIError("lark-cli not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise LarkCLIError(f"lark-cli timeout: {' '.join(args[:2])}") from exc
    out = (proc.stdout or "").strip()
    if not out:
        raise LarkCLIError(f"lark-cli empty output: {(proc.stderr or '')[:200]}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise LarkCLIError(f"lark-cli bad JSON: {out[:200]}") from exc
    if not data.get("ok", False):
        err = data.get("error", {})
        raise LarkCLIError(f"lark-cli: {err.get('message', out[:200])}")
    return data


class LarkBaseCRMProvider(CRMProvider):
    """Lark Base CRM with the owner's 18-table schema."""

    def __init__(self, base_token: str = "", auto_create: bool = True):
        self.base_token = base_token
        self._table_ids: dict[str, str] = {}
        self._id_cache: dict[str, dict[str, str]] = {}   # table -> {key_value: record_id}
        self._wa_cache: dict[str, dict[str, str]] = {}   # table -> {wa_digits: key_value}
        self._cache_loaded: set[str] = set()
        self._seq: int = 0
        if auto_create:
            self._ensure_base()

    # ================================================================ bootstrap
    def _ensure_base(self) -> None:
        if not self.base_token:
            try:
                res = _run_cli(["+title-resolve", "--title", BASE_NAME])
                self.base_token = res.get("base_token") or res.get("app_token", "") or ""
                if self.base_token:
                    log.info("Found existing Lark Base %r", BASE_NAME)
            except LarkCLIError:
                self.base_token = ""
        if not self.base_token:
            self._create_base()
        self._load_tables()

    def _create_base(self) -> None:
        first = "01_Leads"
        fields = json.dumps(FIELD_SCHEMAS[first], ensure_ascii=False)
        res = _run_cli([
            "+base-create", "--name", BASE_NAME,
            "--table-name", first, "--fields", fields,
        ], timeout=180)
        data = res.get("data") or res
        self.base_token = data.get("base_token") or data.get("app_token") or res.get("base_token", "")
        if not self.base_token:
            raise LarkCLIError(f"base-create returned no token: {res}")
        tbl = (data.get("table") or {})
        tid = data.get("table_id") or tbl.get("id", "")
        if tid:
            self._table_ids[first] = tid
        for name, schema in FIELD_SCHEMAS.items():
            if name != first:
                self._create_table(name, schema)
        self._create_link_fields()
        log.info("Created Lark Base %r token=%s", BASE_NAME, self.base_token)

    def _create_table(self, name: str, schema: list[dict]) -> str:
        fields = json.dumps(schema, ensure_ascii=False)
        try:
            res = _run_cli([
                "+table-create", "--base-token", self.base_token,
                "--name", name, "--fields", fields,
            ], timeout=180)
            data = res.get("data") or res
            tbl = data.get("table") or {}
            tid = data.get("table_id") or tbl.get("id", "")
        except LarkCLIError as exc:
            log.error("Failed to create table %s: %s", name, exc)
            return ""
        if tid:
            self._table_ids[name] = tid
        return tid

    def _create_link_fields(self) -> None:
        """Create the 79 manifest cross-table links as native link fields.

        Runs after every table exists (link targets must exist). Fields whose
        name collides with an existing text column are skipped — the manifest
        column keeps its data as text and the link is skipped rather than
        silently replacing it.
        """
        created = skipped = failed = 0
        for link in LINKS:
            table, field, target = link["table"], link["field"], link["target"]
            if table not in self._table_ids or target not in self._table_ids:
                failed += 1
                continue
            try:
                existing = self._field_exists(table, field)
                payload = {"name": field, "type": "link", "link_table": target}
                if existing:
                    # Convert the existing text column into a link field
                    res = _run_cli([
                        "+field-update", "--base-token", self.base_token,
                        "--table-id", self._table_ids[table],
                        "--field-id", field,
                        "--json", json.dumps(payload, ensure_ascii=False),
                    ], timeout=120, confirm=True)
                else:
                    res = _run_cli([
                        "+field-create", "--base-token", self.base_token,
                        "--table-id", self._table_ids[table],
                        "--json", json.dumps(payload, ensure_ascii=False),
                    ], timeout=120)
                if res.get("ok", False):
                    created += 1
                else:
                    failed += 1
                    log.warning("Link field %s.%s rejected: %s", table, field,
                                str(res)[:200])
            except LarkCLIError as exc:
                failed += 1
                log.warning("Link field %s.%s failed: %s", table, field, exc)
        log.info("Link fields: created=%d failed=%d", created, failed)

    def _field_exists(self, table: str, field_name: str) -> bool:
        try:
            res = _run_cli([
                "+field-list", "--base-token", self.base_token,
                "--table-id", self._table_ids[table],
            ], timeout=60)
            data = res.get("data") or res
            items = data.get("fields") or data.get("items") or []
            return any(f.get("name") == field_name for f in items)
        except LarkCLIError:
            return False

    def _load_tables(self) -> None:
        res = _run_cli(["+table-list", "--base-token", self.base_token], timeout=60)
        data = res.get("data") or res
        items = data.get("tables") or data.get("items") or []
        for item in items:
            name, tid = item.get("name", ""), item.get("table_id") or item.get("id", "")
            if name in FIELD_SCHEMAS:
                self._table_ids[name] = tid
        created_any = False
        for name, schema in FIELD_SCHEMAS.items():
            if name not in self._table_ids:
                self._create_table(name, schema)
                created_any = True
        if created_any:
            self._create_link_fields()

    def _table_id(self, name: str) -> str:
        tid = self._table_ids.get(name)
        if not tid:
            self._load_tables()
            tid = self._table_ids.get(name, "")
        if not tid:
            raise LarkCLIError(f"table {name} unavailable in base {self.base_token}")
        return tid

    # ============================================================== id helpers
    def _gen_id(self, table: str) -> str:
        """Generate a readable unique ID, e.g. LEAD-000001-A3F9C2."""
        prefix_map = {
            "01_Leads": "LEAD", "02_Free_Trials": "TRIAL", "03_Customers": "CUST",
            "05_Subscriptions": "SUB", "06_Payments": "PAY", "07_Installations": "INST",
            "08_Devices": "DEV", "14_Referrals": "REF", "16_Support_Tickets": "TICK",
            "17_Activities": "ACT",
        }
        prefix = prefix_map.get(table, table.split("_", 1)[-1][:4].upper())
        self._seq += 1
        return f"{prefix}-{self._seq:06d}-{uuid4().hex[:6].upper()}"

    def _ensure_ids(self, table: str, fields: dict) -> dict:
        key = TABLE_KEY_FIELD[table]
        if not fields.get(key):
            fields[key] = self._gen_id(table)
        return fields

    # ============================================================== cache/read
    @staticmethod
    def _unwrap(val: Any) -> Any:
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val[0].get("text") or val[0].get("name") or ""
        if isinstance(val, list) and val and isinstance(val[0], str):
            return val[0]  # select fields return ["Option"]
        return val

    def _load_cache(self, table: str) -> None:
        if table in self._cache_loaded:
            return
        tid = self._table_id(table)
        key_field = TABLE_KEY_FIELD[table]
        wa_field = TABLE_WA_FIELD.get(table, "")
        id_cache: dict[str, str] = {}
        wa_cache: dict[str, str] = {}
        offset = 0
        while True:
            req = [
                "+record-list", "--base-token", self.base_token,
                "--table-id", tid, "--limit", "200", "--offset", str(offset),
            ]
            if wa_field:
                req += ["--field-id", key_field, "--field-id", wa_field]
            else:
                req += ["--field-id", key_field]
            res = _run_cli(req, timeout=120)
            data = res.get("data") or res
            # +record-list has two shapes: {records: [{record_id, fields}]} and
            # {data: [rows], fields: [names], record_id_list: [ids]}
            items = data.get("records") or data.get("items") or []
            if not items and isinstance(data.get("data"), list) and data.get("fields"):
                names = data["fields"]
                rids = data.get("record_id_list") or [""] * len(data["data"])
                items = [
                    {"record_id": rid, "fields": dict(zip(names, row))}
                    for rid, row in zip(rids, data["data"])
                ]
            for item in items:
                rid = item.get("record_id", "")
                f = item.get("fields", {})
                kv = self._unwrap(f.get(key_field))
                if rid and kv:
                    id_cache[str(kv)] = rid
                if wa_field:
                    wa = _digits(self._unwrap(f.get(wa_field)))
                    if wa and kv:
                        wa_cache[wa] = str(kv)
            if len(items) < 200:
                break
            offset += 200
        self._id_cache[table] = id_cache
        self._wa_cache[table] = wa_cache
        self._cache_loaded.add(table)

    def _find_by_key(self, table: str, key_value: str) -> Optional[str]:
        self._load_cache(table)
        return self._id_cache.get(table, {}).get(str(key_value))

    def _find_by_wa(self, table: str, wa_id: str) -> Optional[str]:
        self._load_cache(table)
        wa_field = TABLE_WA_FIELD.get(table)
        if not wa_field:
            return None
        key_value = self._wa_cache.get(table, {}).get(_digits(wa_id))
        if not key_value:
            return None
        return self._id_cache.get(table, {}).get(key_value)

    # ============================================================ record write
    @staticmethod
    def _to_cell(value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        return str(value)

    def _upsert_by_key(self, table: str, fields: dict) -> tuple[bool, str]:
        tid = self._table_id(table)
        key = TABLE_KEY_FIELD[table]
        fields = self._ensure_ids(table, fields)
        fields = map_record(table, fields)  # bot enums -> manifest option labels
        key_value = str(fields.get(key, ""))
        if not key_value:
            return False, ""
        fields = {k: v for k, v in fields.items() if v is not None}
        rid = self._find_by_key(table, key_value)
        try:
            if rid:
                upd = json.dumps({"update_records": {rid: fields}}, ensure_ascii=False, default=str)
                _run_cli(["+record-batch-update", "--base-token", self.base_token,
                          "--table-id", tid, "--json", upd], timeout=120)
                return True, key_value
            res = _run_cli(["+record-batch-create", "--base-token", self.base_token,
                            "--table-id", tid,
                            "--json", json.dumps({"create_records": [fields]}, ensure_ascii=False, default=str)],
                           timeout=120)
            data = res.get("data") or res
            key = TABLE_KEY_FIELD[table]
            new = data.get("record_id_list") or data.get("records") or []
            if new and isinstance(new, list):
                first = new[0]
                new_rid = first.get("record_id", "") if isinstance(first, dict) else str(first)
                if new_rid:
                    self._id_cache.setdefault(table, {})[key_value] = new_rid
            return True, key_value
        except LarkCLIError as exc:
            log.error("Lark upsert failed (%s key=%s): %s", table, key_value, exc)
            raise

    def _append(self, table: str, fields: dict) -> bool:
        tid = self._table_id(table)
        fields = self._ensure_ids(table, fields)
        fields = map_record(table, fields)  # bot enums -> manifest option labels
        fields = {k: v for k, v in fields.items() if v is not None}
        try:
            res = _run_cli(["+record-batch-create", "--base-token", self.base_token,
                            "--table-id", tid,
                            "--json", json.dumps({"create_records": [fields]}, ensure_ascii=False, default=str)],
                           timeout=120)
            data = res.get("data") or res
            key = TABLE_KEY_FIELD[table]
            new = data.get("record_id_list") or data.get("records") or []
            if new and isinstance(new, list):
                first = new[0]
                new_rid = first.get("record_id", "") if isinstance(first, dict) else str(first)
                if new_rid:
                    self._id_cache.setdefault(table, {})[str(fields.get(key, ""))] = new_rid
            return True
        except LarkCLIError as exc:
            log.error("Lark append failed (%s): %s", table, exc)
            raise

    def _get_by_key(self, table: str, key_value: str) -> Optional[dict]:
        if not key_value:
            return None
        tid = self._table_id(table)
        key = TABLE_KEY_FIELD[table]
        res = _run_cli(["+record-search", "--base-token", self.base_token,
                        "--table-id", tid, "--keyword", str(key_value),
                        "--search-field", key, "--limit", "1"], timeout=60)
        return self._parse_search(res)

    def _get_by_wa(self, table: str, wa_id: str) -> Optional[dict]:
        if not wa_id:
            return None
        wa_field = TABLE_WA_FIELD.get(table)
        if not wa_field:
            return None
        tid = self._table_id(table)
        res = _run_cli(["+record-search", "--base-token", self.base_token,
                        "--table-id", tid, "--keyword", _digits(wa_id),
                        "--search-field", wa_field, "--limit", "1"], timeout=60)
        return self._parse_search(res)

    def _parse_search(self, res: dict) -> Optional[dict]:
        data = res.get("data") or res
        items = data.get("records") or data.get("items") or []
        # columnar shape: {data: [rows], fields: [names]}
        if not items and isinstance(data.get("data"), list) and data.get("fields"):
            names = data["fields"]
            rids = data.get("record_id_list") or [""] * len(data["data"])
            items = [{"record_id": rid, "fields": dict(zip(names, row))}
                     for rid, row in zip(rids, data["data"])]
        if not items:
            return None
        return {k: self._unwrap(v) for k, v in items[0].get("fields", {}).items()}

    # ==================================================== CRMProvider contract
    # Maps CRMService dataclasses onto the owner's 18-table Lark schema.
    # Extra business facts that have no dedicated CRMService field are merged
    # into the Lead/Customer notes columns so nothing is lost.

    _LEAD_MAP = {
        "lead_id": "Lead ID", "wa_id": "WhatsApp Number",
        "phone_e164": "Alternate Phone", "name": "Lead Name",
        "source": "Lead Source", "campaign": "Campaign Code",
        "referrer_code": "Referral ID", "reseller_code": "Reseller ID",
        "lead_stage": "Lead Stage", "first_contact_at": "First Contact At",
        "last_message_at": "Last Contact At", "device_types": "Device Type",
        "device_count": "Device Count", "area": "Town or Community",
        "install_method": "Setup Method", "assigned_staff": "Sales Agent ID",
        "followup_due_at": "Next Follow Up", "notes": "Lead Notes",
        "internet_type": "Internet Type", "trial_status": "Trial Outcome",
        "created_at": "Created At",
    }

    _CUSTOMER_MAP = {
        "customer_id": "Customer ID", "source_lead_id": "Original Lead ID",
        "wa_id": "WhatsApp Number", "phone_e164": "Alternative Phone",
        "name": "Customer Name", "location_area": "Town or Community",
        "device_types": "Primary Device Type", "assigned_staff": "Sales Agent ID",
        "referrer_code": "Referral Code", "reseller_code": "Reseller ID",
        "account_status": "Customer Status", "activation_at": "Date Joined",
        "created_at": "Date Joined",
    }

    @staticmethod
    def _as_iso(val: Any) -> str:
        try:
            return datetime.fromisoformat(str(val)).isoformat(timespec="seconds")
        except (ValueError, TypeError):
            return _iso(_now())

    def upsert_lead(self, lead: LeadRecord) -> bool:
        cols: dict[str, Any] = {}
        for src, dst in self._LEAD_MAP.items():
            val = getattr(lead, src, None)
            if val in (None, ""):
                continue
            if dst in ("First Contact At", "Last Contact At", "Next Follow Up", "Created At"):
                val = self._as_iso(val)
            cols[dst] = val
        extras = []
        if lead.months:
            extras.append(f"Quote: {lead.months}mo x {lead.device_count or '?'}dev")
        if lead.subscription_quote_le:
            extras.append(f"Total: Le{lead.subscription_quote_le:,} ({lead.discount_pct or 0}% off, {lead.quote_version or 'v1'})")
        if lead.app_name:
            extras.append(f"App: {lead.app_name}")
        if lead.app_url_sent:
            extras.append(lead.app_url_sent)
        if lead.app_installed_reported:
            extras.append("App INSTALLED (reported)")
        if lead.ready_to_pay_after_setup:
            extras.append("Ready to pay after setup")
        if lead.trial_requested:
            extras.append("Trial requested")
        if lead.trial_offered:
            extras.append("Trial offered")
        if lead.handoff_status:
            extras.append(f"Handoff: {lead.handoff_status}")
        if lead.staff_setup_verified:
            extras.append("Setup verified by staff")
        if lead.payment_status:
            extras.append(f"Payment: {lead.payment_status}")
        if lead.visit_fee_quote_le:
            extras.append(f"Visit fee quoted: Le{lead.visit_fee_quote_le:,}")
        if extras:
            base = str(cols.get("Lead Notes", "") or "")
            cols["Lead Notes"] = f"{base} | {' | '.join(extras)}" if base else " | ".join(extras)
        if lead.opted_out:
            cols["Lead Stage"] = "OPTED_OUT"
        ok, _ = self._upsert_by_key("01_Leads", cols)
        return ok

    def get_lead_by_wa_id(self, wa_id: str) -> Optional[LeadRecord]:
        raw = self._get_by_wa("01_Leads", wa_id)
        if not raw:
            return None
        reverse = {v: k for k, v in self._LEAD_MAP.items()}
        kwargs: dict[str, Any] = {"wa_id": wa_id}
        for col, val in raw.items():
            src = reverse.get(col)
            if src and src in LeadRecord.__dataclass_fields__:
                kwargs[src] = val
        # Recover staged facts from notes
        notes = str(raw.get("Lead Notes", "") or "")
        import re as _re
        m = _re.search(r"Quote: (\d+)mo x (\d+)dev", notes)
        if m:
            kwargs.setdefault("months", int(m.group(1)))
            kwargs.setdefault("device_count", int(m.group(2)))
        m = _re.search(r"Total: Le([\d,]+)", notes)
        if m:
            kwargs.setdefault("subscription_quote_le", int(m.group(1).replace(",", "")))
        if "Ready to pay after setup" in notes:
            kwargs.setdefault("ready_to_pay_after_setup", True)
        if "App INSTALLED (reported)" in notes:
            kwargs.setdefault("app_installed_reported", True)
        if "Setup verified by staff" in notes:
            kwargs.setdefault("staff_setup_verified", True)
        m = _re.search(r"Payment: (\w+)", notes)
        if m:
            kwargs.setdefault("payment_status", m.group(1))
        valid = {k: v for k, v in kwargs.items() if k in LeadRecord.__dataclass_fields__}
        return LeadRecord(**valid)

    def upsert_customer(self, customer: CustomerRecord) -> bool:
        cols: dict[str, Any] = {}
        for src, dst in self._CUSTOMER_MAP.items():
            val = getattr(customer, src, None)
            if val in (None, ""):
                continue
            if dst == "Date Joined":
                val = self._as_iso(val)
            cols[dst] = val
        extras = []
        if customer.subscription_months:
            extras.append(f"{customer.subscription_months}mo x {customer.device_count or '?'}dev")
        if customer.amount_paid_le:
            extras.append(f"Paid Le{customer.amount_paid_le:,}")
        if customer.payment_method:
            extras.append(f"via {customer.payment_method}")
        if customer.transaction_reference:
            extras.append(f"Ref {customer.transaction_reference}")
        if customer.subscription_expires_at:
            extras.append(f"Expires {customer.subscription_expires_at}")
        if customer.renewal_count:
            extras.append(f"Renewals: {customer.renewal_count}")
        if customer.package_code:
            extras.append(f"Package {customer.package_code}")
        if extras:
            base = str(cols.get("Support Notes", "") or "")
            cols["Support Notes"] = f"{base} | {' | '.join(extras)}" if base else " | ".join(extras)
        ok, _ = self._upsert_by_key("03_Customers", cols)
        return ok

    def get_customer_by_wa_id(self, wa_id: str) -> Optional[CustomerRecord]:
        raw = self._get_by_wa("03_Customers", wa_id)
        if not raw:
            return None
        reverse = {v: k for k, v in self._CUSTOMER_MAP.items()}
        kwargs: dict[str, Any] = {"wa_id": wa_id}
        for col, val in raw.items():
            src = reverse.get(col)
            if src and src in CustomerRecord.__dataclass_fields__:
                kwargs[src] = val
        notes = str(raw.get("Support Notes", "") or "")
        import re as _re
        m = _re.search(r"(\d+)mo x (\d+)dev", notes)
        if m:
            kwargs.setdefault("subscription_months", int(m.group(1)))
            kwargs.setdefault("device_count", int(m.group(2)))
        m = _re.search(r"Paid Le([\d,]+)", notes)
        if m:
            kwargs.setdefault("amount_paid_le", int(m.group(1).replace(",", "")))
        m = _re.search(r"Renewals: (\d+)", notes)
        if m:
            kwargs.setdefault("renewal_count", int(m.group(1)))
        m = _re.search(r"Ref (\S+)", notes)
        if m:
            kwargs.setdefault("transaction_reference", m.group(1))
        valid = {k: v for k, v in kwargs.items() if k in CustomerRecord.__dataclass_fields__}
        return CustomerRecord(**valid)

    def upsert_payment(self, payment: PaymentRecord) -> bool:
        if not payment.payment_id:
            payment.payment_id = self._gen_id("06_Payments")
        if not payment.created_at:
            payment.created_at = _iso(_now())
        fields = {
            "Payment ID": payment.payment_id,
            "Received At": self._as_iso(payment.created_at),
            "Lead ID": payment.lead_id or "",
            "Customer ID": payment.customer_id or "",
            "Amount Due SLE": payment.expected_amount_le or 0,
            "Payment Method": payment.method or "",
            "Payment Reference": payment.transaction_reference or "",
            "Payment Status": payment.status or "pending",
            "Confirmed By Staff ID": payment.verified_by or "",
            "Payment Notes": payment.note or "",
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        return self._append("06_Payments", fields)

    def upsert_installation(self, installation: InstallationRecord) -> bool:
        inst = installation
        if not inst.installation_id:
            inst.installation_id = self._gen_id("07_Installations")
        fields = {
            "Installation ID": inst.installation_id,
            "Lead ID": inst.lead_id or "",
            "Device Type": inst.device_platform or "",
            "Setup Type": inst.installation_method or "",
            "Address and Landmark": inst.area or "",
            "Visit Fee Quoted SLE": inst.visit_fee_le or 0,
            "Assigned Technician ID": inst.assigned_staff or "",
            "App Installed": bool(inst.app_installed_reported_at),
            "Booking Status": {"verified": "completed"}.get(inst.setup_status, inst.setup_status or "pending"),
            "Issue or Visit Notes": inst.issue_note or "",
        }
        if inst.setup_verified_at:
            fields["Completed At"] = self._as_iso(inst.setup_verified_at)
        if inst.wa_id:
            fields["Address and Landmark"] = f"{fields.get('Address and Landmark', '')}".strip()
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        return self._upsert_by_key("07_Installations", fields)[0]

    def upsert_trial(self, trial: TrialRecord) -> bool:
        if not trial.trial_id:
            trial.trial_id = self._gen_id("02_Free_Trials")
        status = trial.trial_status or trial.approval_status or "requested"
        fields = {
            "Trial ID": trial.trial_id,
            "Lead ID": trial.lead_id or "",
            "Requested At": self._as_iso(trial.requested_at or _iso(_now())),
            "Trial Duration Hours": _hours_between(trial.start_at, trial.end_at),
            "Trial Status": {"active": "active", "approved": "approved"}.get(status, status),
            "Approved By Staff ID": trial.approved_by or "",
            "Trial Notes": trial.note or "",
        }
        if trial.start_at:
            fields["Activated At"] = self._as_iso(trial.start_at)
        if trial.end_at:
            fields["Expires At"] = self._as_iso(trial.end_at)
        if isinstance(trial.converted_to_paid, str) and trial.converted_to_paid:
            fields["Converted Customer ID"] = trial.converted_to_paid
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        return self._upsert_by_key("02_Free_Trials", fields)[0]

    def upsert_handoff(self, handoff: StaffHandoffRecord) -> bool:
        if not handoff.handoff_id:
            handoff.handoff_id = self._gen_id("17_Activities")
        fields = {
            "Activity ID": handoff.handoff_id,
            "Lead ID": handoff.lead_id or "",
            "Activity Type": "handoff",
            "Activity At": self._as_iso(handoff.requested_at or _iso(_now())),
            "Status": {"pending": "pending", "accepted": "done", "resolved": "done"}.get(handoff.status, "pending"),
            "Outcome": handoff.resolution or handoff.reason or "",
            "Notes": f"Assigned: {handoff.assigned_staff or 'unassigned'} | Next: {handoff.next_stage or '-'}",
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        return self._upsert_by_key("17_Activities", fields)[0]

    def upsert_followup(self, followup: FollowUpRecord) -> bool:
        fu = followup
        if not fu.followup_id:
            fu.followup_id = self._gen_id("17_Activities")
        fields = {
            "Activity ID": fu.followup_id,
            "Lead ID": fu.lead_id or "",
            "Activity Type": "follow_up",
            "Activity At": _iso(_now()),
            "Status": {"pending": "pending", "manual_pending": "pending",
                       "sent": "done", "suppressed": "cancelled"}.get(fu.status, "pending"),
            "Outcome": fu.reason or "",
            "Notes": fu.suppressed_reason or fu.template_name_if_required or "",
        }
        if fu.due_at:
            fields["Due At"] = self._as_iso(fu.due_at)
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        return self._upsert_by_key("17_Activities", fields)[0]

    def upsert_referral(self, referral: ReferralRecord) -> bool:
        ref = referral
        if not ref.referral_id:
            ref.referral_id = self._gen_id("14_Referrals")
        fields = {
            "Referral ID": ref.referral_id,
            "Referrer Customer ID": ref.referrer_id or "",
            "Referred Lead ID": ref.referred_lead_id or "",
            "Referral Date": _iso(_now()),
            "Referral Code": ref.referral_code or "",
            "Reseller ID - If Any": ref.reseller_code or "",
            "Qualified Payment ID": ref.qualified_payment_id or "",
            "Reward Status": ref.reward_status or "pending",
            "Approved By Staff ID": ref.verified_by or "",
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        return self._upsert_by_key("14_Referrals", fields)[0]

    # ======================================================== Lark-only extras
    def log_activity(self, wa_id: str, lead_id: str, activity_type: str,
                     outcome: str = "", notes: str = "") -> bool:
        """Append an audit activity row (spec §8.3 write-ahead events)."""
        fields = {
            "Activity ID": self._gen_id("17_Activities"),
            "Lead ID": lead_id or "",
            "Activity Type": activity_type,
            "Activity At": _iso(_now()),
            "Status": "done",
            "Outcome": outcome or "",
            "Notes": notes or "",
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        try:
            return self._append("17_Activities", fields)
        except LarkCLIError:
            return False

    def create_ticket(self, wa_id: str, customer_id: str, issue_type: str,
                      subject: str, description: str, priority: str = "medium") -> str:
        fields = {
            "Ticket ID": self._gen_id("16_Support_Tickets"),
            "Customer ID": customer_id or "",
            "Issue Type": issue_type or "other",
            "Priority": priority or "medium",
            "Subject": subject or "",
            "Description": description or "",
            "Opened At": _iso(_now()),
            "Ticket Status": "open",
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        self._append("16_Support_Tickets", fields)
        return str(fields["Ticket ID"])

    def seed_packages(self) -> int:
        """Insert/refresh the 16 PKG rows from the owner's file (idempotent)."""
        inserted = 0
        for pkg in SEED_PACKAGES:
            try:
                ok, _ = self._upsert_by_key("04_Packages", dict(pkg))
                inserted += 1 if ok else 0
            except LarkCLIError as exc:
                log.warning("Package seed %s failed: %s", pkg.get("Package ID"), exc)
        log.info("Seeded %d packages into 04_Packages", inserted)
        return inserted

    def get_zones(self) -> list[dict]:
        """Read 18_Service_Zones for visit-fee quoting."""
        tid = self._table_id("18_Service_Zones")
        res = _run_cli(["+record-list", "--base-token", self.base_token,
                        "--table-id", tid, "--limit", "200"], timeout=90)
        data = res.get("data") or res
        items = data.get("records") or data.get("items") or []
        return [{k: self._unwrap(v) for k, v in it.get("fields", {}).items()} for it in items]

    def get_staff(self, role: Optional[str] = None) -> list[dict]:
        """Read 15_Staff for assignment."""
        tid = self._table_id("15_Staff")
        res = _run_cli(["+record-list", "--base-token", self.base_token,
                        "--table-id", tid, "--limit", "200"], timeout=90)
        data = res.get("data") or res
        items = data.get("records") or data.get("items") or []
        rows = [{k: self._unwrap(v) for k, v in it.get("fields", {}).items()} for it in items]
        if role:
            rows = [r for r in rows if r.get("Role") == role]
        return rows


def _hours_between(start: str, end: str) -> int:
    try:
        s = datetime.fromisoformat(str(start))
        e = datetime.fromisoformat(str(end))
        return max(0, int((e - s).total_seconds() // 3600))
    except (ValueError, TypeError):
        return 0


def create_lark_provider(base_token: str = "", auto_create: bool = True,
                         seed_packages: bool = True) -> LarkBaseCRMProvider:
    """Factory. Raises LarkCLIError if lark-cli isn't configured/authorized."""
    provider = LarkBaseCRMProvider(base_token=base_token, auto_create=auto_create)
    if seed_packages:
        try:
            provider.seed_packages()
        except LarkCLIError as exc:
            log.warning("Package seeding skipped: %s", exc)
    return provider