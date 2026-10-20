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
    SEED_SERVICE_ZONES,
    SEED_STAFF,
    TABLE_KEY_FIELD,
    TABLE_WA_FIELD,
    map_record,
    package_id_for,
)

log = logging.getLogger("nexglo.crm_lark")

BASE_NAME = "NexgloTV CRM"

TABLE_PRIMARY_DATE: dict[str, str] = {
    "01_Leads": "Created At",
    "02_Free_Trials": "Requested At",
    "03_Customers": "Date Joined",
    "04_Packages": "Valid From",
    "05_Subscriptions": "Activation Date",
    "06_Payments": "Received At",
    "07_Installations": "Requested At",
    "08_Devices": "Registered At",
    "09_Resellers": "Joined At",
    "10_Reseller_Sales": "Sale Date",
    "11_Commissions": "Earned On",
    "12_Reseller_Payouts": "Requested At",
    "13_Reseller_Wallet": "Transaction At",
    "14_Referrals": "Referral Date",
    "15_Staff": "Start Date",
    "16_Support_Tickets": "Opened At",
    "17_Activities": "Activity At",
    "18_Service_Zones": "Price Effective Date",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


TABLE_DATETIME_FIELDS: dict[str, set[str]] = {
    table: {f["name"] for f in fields if f.get("type") == "datetime"}
    for table, fields in FIELD_SCHEMAS.items()
}


def _to_lark_timestamp(val: Any) -> Optional[int]:
    """Convert string/datetime/numeric timestamps to Lark Base REST required ms integer."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        if val > 100_000_000_000:
            return int(val)
        return int(val * 1000)
    if isinstance(val, datetime):
        if not val.tzinfo:
            val = val.replace(tzinfo=timezone.utc)
        return int(val.timestamp() * 1000)
    s = str(val).strip()
    if not s:
        return None
    if s.isdigit():
        return _to_lark_timestamp(int(s))
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            pass
    return None


class LarkCLIError(RuntimeError):
    pass


class LarkScopeError(LarkCLIError):
    def __init__(self, message: str, required_scopes: Optional[list[str]] = None, help_url: str = ""):
        super().__init__(message)
        self.required_scopes = required_scopes or []
        self.help_url = help_url


KNOWN_TABLE_IDS: dict[str, str] = {
    "01_Leads": "tblYgrdr4wB2NBGw",
    "02_Free_Trials": "tbl4kPNhImMDIj7n",
    "03_Customers": "tblA2Ah3MinIz2W8",
    "04_Packages": "tblZj4WjOjYei4Cb",
    "05_Subscriptions": "tblNtdaKKOKHtJb0",
    "06_Payments": "tblDess1wSufYjMg",
    "07_Installations": "tblIY5fyZ9IK3YA9",
    "08_Devices": "tbl7GfQEGKdpfV9X",
    "09_Resellers": "tblwp7BmY9yd4x3O",
    "10_Reseller_Sales": "tblN4JhK2in01Q1s",
    "11_Commissions": "tbldUVwab4hK3Iet",
    "12_Reseller_Payouts": "tblCUEuV6KdcKW4Q",
    "13_Reseller_Wallet": "tblYcDq9LCXFG6nZ",
    "14_Referrals": "tblQo74armGm2rl2",
    "15_Staff": "tblNnAhuAqN3SVKx",
    "16_Support_Tickets": "tblik930RNoW8Bwy",
    "17_Activities": "tblu6xL2ZAgl0HoO",
    "18_Service_Zones": "tblpi7QuqgkAULz7",
    "19_Receipts": "tblq7wl8qDj1bxxr",
    "20_Installer_Earnings": "tbleg1SpmjYesAG9",
    "21_Installer_Monthly_Performance": "tblvEwRORY6geaXq",
}


class LarkRestClient:
    """Direct HTTPS REST client for Lark Open Platform APIs using app credentials."""

    def __init__(self, app_id: str, app_secret: str, base_token: str):
        import threading
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_token = base_token
        self._token: str = ""
        self._token_expires_at: float = 0.0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        import time
        with self._lock:
            now = time.time()
            if self._token and now < self._token_expires_at:
                return self._token
            import httpx
            url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
            data: dict = {}
            for attempt in range(3):
                try:
                    resp = httpx.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=30.0)
                    data = resp.json()
                    break
                except Exception as exc:
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise LarkCLIError(f"Lark auth request failed: {exc}") from exc

            if not data or data.get("code") != 0:
                raise LarkCLIError(f"Lark auth failed ({data.get('code')}): {data.get('msg')}")
            self._token = data["tenant_access_token"]
            self._token_expires_at = now + int(data.get("expire", 7200)) - 120
            return self._token

    def request(self, method: str, path: str, *, json_body: Optional[dict] = None, params: Optional[dict] = None, timeout: int = 60) -> dict:
        import httpx
        import time
        url = f"https://open.larksuite.com/open-apis{path}"
        data: dict = {}
        for attempt in range(3):
            token = self.get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            try:
                resp = httpx.request(method, url, headers=headers, json=json_body, params=params, timeout=timeout)
                data = resp.json()
                break
            except Exception as exc:
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise LarkCLIError(f"Lark API request {method} {path} failed: {exc}") from exc

        code = data.get("code", 0)
        if code != 0:
            msg = data.get("msg", "Unknown error")
            err_data = data.get("error", {})
            violations = [v.get("subject") for v in err_data.get("permission_violations", []) if isinstance(v, dict)]
            helps = [h.get("url") for h in err_data.get("helps", []) if isinstance(h, dict)]
            help_url = helps[0] if helps else f"https://open.larksuite.com/app/{self.app_id}/auth"
            if code == 99991672:
                scopes_str = ", ".join(violations or ["bitable:app"])
                raise LarkScopeError(
                    f"Lark Base API Access Denied (Code 99991672): Scope [{scopes_str}] required. "
                    f"Please open Developer Console at {help_url} to add permissions, publish a version, and add bot to Base.",
                    required_scopes=violations,
                    help_url=help_url,
                )
            raise LarkCLIError(f"Lark API error ({code}): {msg}")
        return data

    def list_tables(self) -> list[dict]:
        res = self.request("GET", f"/bitable/v1/apps/{self.base_token}/tables")
        data = res.get("data") or {}
        return data.get("items") or data.get("tables") or []

    def list_records(self, table_id: str, limit: int = 200, page_token: str = "") -> dict:
        params = {"page_size": min(limit, 500)}
        if page_token:
            params["page_token"] = page_token
        res = self.request("GET", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/records", params=params)
        return res.get("data") or {}

    def batch_create_records(self, table_id: str, records: list[dict]) -> list[dict]:
        body = {"records": [{"fields": r} for r in records]}
        res = self.request("POST", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/batch_create", json_body=body)
        data = res.get("data") or {}
        return data.get("records") or []

    def batch_update_records(self, table_id: str, update_dict: dict[str, dict]) -> list[dict]:
        body = {"records": [{"record_id": rid, "fields": f} for rid, f in update_dict.items()]}
        res = self.request("POST", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/batch_update", json_body=body)
        data = res.get("data") or {}
        return data.get("records") or []

    def search_records(self, table_id: str, field_name: str, keyword: str) -> list[dict]:
        body = {
            "filter": {
                "conjunction": "and",
                "conditions": [
                    {
                        "field_name": field_name,
                        "operator": "contains",
                        "value": [keyword],
                    }
                ],
            },
            "page_size": 10,
        }
        res = self.request("POST", f"/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/search", json_body=body)
        data = res.get("data") or {}
        return data.get("items") or data.get("records") or []


def _digits(phone: str) -> str:
    return re.sub(r"[^\d]", "", str(phone or ""))[-9:]  # last 9 digits


def _run_cli(args: list[str], timeout: int = 90, confirm: bool = False) -> dict:
    """Run `lark-cli base <args>` and return parsed JSON (ok=True checked).

    ``confirm=True`` appends ``--yes`` for high-risk-write commands (field
    updates). On Windows the .cmd shim mangles argv JSON, so we invoke the
    native binary or bundled node against the CLI's run.js directly when available.
    """
    import os
    import shutil

    default_hermes_home = Path.home() / "AppData" / "Local" / "hermes"
    hermes_home = Path(os.environ.get("HERMES_HOME") or default_hermes_home)

    exe = shutil.which("lark-cli")
    if exe is None:
        # Common Hermes tool install locations on Windows
        candidates = [
            hermes_home / "tools" / "node-26.7.0-win32-x64" / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe",
            hermes_home / "tools" / "node-26.7.0-win32-x64" / "lark-cli.cmd",
            hermes_home / "tools" / "node-26.7.0-win32-x64" / "lark-cli.exe",
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
    if exe.lower().endswith(".cmd"):
        exe_dir = Path(exe).parent
        native_bin = exe_dir / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe"
        run_js = exe_dir / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
        bundled_node = exe_dir / "node.exe"
        node_exe = str(bundled_node) if bundled_node.is_file() else shutil.which("node")
        if native_bin.is_file():
            cmd = [str(native_bin), *final_args]
        elif node_exe and run_js.is_file():
            cmd = [node_exe, str(run_js), *final_args]

    env = dict(os.environ)
    if "HERMES_HOME" not in env and (Path.home() / ".lark-cli" / "hermes" / "config.json").is_file():
        env["HERMES_HOME"] = str(hermes_home)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, shell=False, env=env)
    except FileNotFoundError as exc:
        raise LarkCLIError("lark-cli not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise LarkCLIError(f"lark-cli timeout: {' '.join(args[:2])}") from exc
    out = (proc.stdout or "").strip()
    if not out:
        err_out = (proc.stderr or "").strip()
        if err_out.startswith("{"):
            out = err_out
        else:
            raise LarkCLIError(f"lark-cli empty output: {err_out[:200]}")
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

    def __init__(
        self,
        base_token: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        auto_create: bool = True,
    ):
        import os
        import threading

        self.base_token = base_token if base_token is not None else (os.environ.get("LARK_BASE_TOKEN", "") or "E8jObNOAeaZqUHsyxRHjR9VcpBg")
        self.app_id = app_id if app_id is not None else os.environ.get("LARK_APP_ID", "")
        self.app_secret = app_secret if app_secret is not None else os.environ.get("LARK_APP_SECRET", "")
        self._lock = threading.RLock()
        self._table_ids: dict[str, str] = dict(KNOWN_TABLE_IDS) if self.base_token else {}
        self._id_cache: dict[str, dict[str, str]] = {}   # table -> {key_value: record_id}
        self._wa_cache: dict[str, dict[str, str]] = {}   # table -> {wa_digits: key_value}
        self._lead_records: dict[str, LeadRecord] = {}   # wa_digits -> LeadRecord
        self._customer_records: dict[str, CustomerRecord] = {}  # wa_digits -> CustomerRecord
        self._cache_loaded: set[str] = set()
        self._seq: int = 0
        self._init_error: Optional[str] = None

        self.rest_client: Optional[LarkRestClient] = None
        if self.app_id and self.app_secret:
            self.rest_client = LarkRestClient(self.app_id, self.app_secret, self.base_token)

        if auto_create:
            self._ensure_base()

    # ================================================================ bootstrap
    def _ensure_base(self) -> None:
        if not self.base_token:
            try:
                res = _run_cli(["+title-resolve", "--title", BASE_NAME])
                data = res.get("data") or res
                self.base_token = (
                    data.get("base_token")
                    or data.get("app_token")
                    or res.get("base_token", "")
                    or ""
                )
                if not self.base_token:
                    candidates = data.get("candidates") or []
                    for cand in candidates:
                        if cand.get("title") == BASE_NAME and cand.get("base_token"):
                            self.base_token = cand["base_token"]
                            break
                    if not self.base_token and candidates:
                        self.base_token = candidates[0].get("base_token", "")
            except LarkCLIError:
                self.base_token = ""
            if not self.base_token:
                self.base_token = "E8jObNOAeaZqUHsyxRHjR9VcpBg"
        try:
            self._load_tables()
        except Exception as exc:
            log.warning("Table loading deferred: %s", exc)
            self._init_error = str(exc)

    def _create_base(self) -> None:
        first = "01_Leads"
        fields = json.dumps(FIELD_SCHEMAS[first], ensure_ascii=False)
        res = _run_cli([
            "+base-create", "--name", BASE_NAME,
            "--table-name", first, "--fields", fields,
        ], timeout=180)
        data = res.get("data") or res
        base_obj = data.get("base") or {}
        self.base_token = (
            data.get("base_token")
            or data.get("app_token")
            or base_obj.get("base_token")
            or base_obj.get("app_token")
            or base_obj.get("token")
            or res.get("base_token", "")
        )
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
        if self.rest_client:
            try:
                items = self.rest_client.list_tables()
                if items:
                    for item in items:
                        name, tid = item.get("name", ""), item.get("table_id") or item.get("id", "")
                        if name in FIELD_SCHEMAS:
                            self._table_ids[name] = tid
                    return
            except LarkScopeError:
                pass
            except Exception as exc:
                log.warning("REST load_tables error: %s", exc)

        try:
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
        except LarkCLIError:
            if not self._table_ids:
                self._table_ids = dict(KNOWN_TABLE_IDS)

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
        date_col = TABLE_PRIMARY_DATE.get(table)
        if date_col and not fields.get(date_col):
            now_iso = _iso(_now())
            if table == "01_Leads":
                fields[date_col] = self._as_iso(fields.get("First Contact At") or fields.get("Last Contact At") or now_iso)
            else:
                fields[date_col] = now_iso
        return fields

    # ============================================================== cache/read
    @staticmethod
    def _unwrap(val: Any) -> Any:
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val[0].get("text") or val[0].get("name") or val[0].get("id") or ""
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

        if self.rest_client:
            page_token = ""
            while True:
                data = self.rest_client.list_records(tid, limit=200, page_token=page_token)
                items = data.get("items") or data.get("records") or []
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
                if not data.get("has_more") or not data.get("page_token"):
                    break
                page_token = data.get("page_token")
            self._id_cache[table] = id_cache
            self._wa_cache[table] = wa_cache
            self._cache_loaded.add(table)
            return

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
        digits = _digits(wa_id)
        if not digits:
            return None
        # 1. Exact match in cache
        key_value = self._wa_cache.get(table, {}).get(digits)
        # 2. Suffix match in cache (handles country code formatting variants)
        if not key_value and len(digits) >= 8:
            suffix = digits[-8:]
            for cached_wa, kv in self._wa_cache.get(table, {}).items():
                if cached_wa.endswith(suffix):
                    key_value = kv
                    break
        # 3. Live search fallback if not in cache
        if not key_value:
            raw = self._get_by_wa(table, wa_id)
            if raw:
                key_field = TABLE_KEY_FIELD[table]
                kv = str(raw.get(key_field) or "")
                if kv:
                    key_value = kv
                    self._wa_cache.setdefault(table, {})[digits] = kv
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

    def _resolve_links(self, table: str, fields: dict) -> dict:
        """Convert human keys on native Lark link columns into [{'id': record_id}].

        If a link column contains a value that does not resolve to a record in
        the target table (e.g. a free-text staff label or unverified code), the
        link column is omitted so Lark Base does not reject the write.
        """
        table_links = LINK_FIELDS.get(table, {})
        if not table_links:
            return fields
        resolved = dict(fields)
        for col, target_table in table_links.items():
            if col not in resolved:
                continue
            val = resolved[col]
            if val is None or val == "":
                resolved.pop(col, None)
                continue
            if isinstance(val, list) and val and isinstance(val[0], dict) and "id" in val[0]:
                continue
            sval = str(val).strip()
            if sval.startswith("rec") and len(sval) >= 10:
                resolved[col] = [{"id": sval}]
                continue
            rid = self._find_by_key(target_table, sval)
            if not rid and target_table == "15_Staff" and sval.lower() in ("staff", "admin", "manager", "bot"):
                rid = self._find_by_key("15_Staff", "STAFF-01")
            if not rid and target_table in TABLE_WA_FIELD:
                rid = self._find_by_wa(target_table, sval)
            if rid:
                resolved[col] = [{"id": rid}]
            else:
                resolved.pop(col, None)
        return resolved

    def _normalize_fields_for_rest(self, table: str, fields: dict) -> dict:
        """Ensure field types and link structures conform to Lark Base REST API spec.

        - Converts datetime fields to millisecond integer timestamps.
        - Converts link fields from [{'id': 'rec...'}] to ['rec...'].
        - Drops None and empty string values.
        """
        clean: dict[str, Any] = {}
        dt_fields = TABLE_DATETIME_FIELDS.get(table, set())
        for k, v in fields.items():
            if v is None or v == "":
                continue
            if k in dt_fields:
                ts = _to_lark_timestamp(v)
                if ts is not None:
                    clean[k] = ts
            elif isinstance(v, list) and v and isinstance(v[0], dict) and "id" in v[0]:
                clean[k] = [item["id"] for item in v if isinstance(item, dict) and "id" in item]
            elif isinstance(v, list) and v and isinstance(v[0], dict) and "record_id" in v[0]:
                clean[k] = [item["record_id"] for item in v if isinstance(item, dict) and "record_id" in item]
            else:
                clean[k] = v
        return clean

    def _upsert_by_key(self, table: str, fields: dict) -> tuple[bool, str]:
        tid = self._table_id(table)
        key = TABLE_KEY_FIELD[table]
        fields = self._ensure_ids(table, fields)
        fields = map_record(table, fields)  # bot enums -> manifest option labels
        key_value = str(fields.get(key, ""))
        if not key_value:
            return False, ""
        fields = self._resolve_links(table, fields)
        fields = {k: v for k, v in fields.items() if v is not None}
        rid = self._find_by_key(table, key_value)

        # Enforce unique constraint on WhatsApp Number across tables with a WA field (e.g. 01_Leads, 03_Customers)
        wa_field = TABLE_WA_FIELD.get(table)
        if not rid and wa_field and fields.get(wa_field):
            wa_val = str(fields.get(wa_field) or "")
            wa_digits = _digits(wa_val)
            existing_rid = self._find_by_wa(table, wa_val)
            if existing_rid:
                rid = existing_rid
                # Find and preserve existing primary key ID
                existing_key = self._wa_cache.get(table, {}).get(wa_digits)
                if not existing_key:
                    for k, r in self._id_cache.get(table, {}).items():
                        if r == existing_rid:
                            existing_key = k
                            break
                if existing_key:
                    key_value = existing_key
                    fields[key] = existing_key

        if self.rest_client:
            rest_fields = self._normalize_fields_for_rest(table, fields)
            try:
                if rid:
                    self.rest_client.batch_update_records(tid, {rid: rest_fields})
                    if wa_field and fields.get(wa_field):
                        self._wa_cache.setdefault(table, {})[_digits(str(fields[wa_field]))] = key_value
                    self._id_cache.setdefault(table, {})[key_value] = rid
                    return True, key_value
                created = self.rest_client.batch_create_records(tid, [rest_fields])
                if created and isinstance(created, list):
                    first = created[0]
                    new_rid = first.get("record_id", "") if isinstance(first, dict) else str(first)
                    if new_rid:
                        self._id_cache.setdefault(table, {})[key_value] = new_rid
                        if wa_field and fields.get(wa_field):
                            self._wa_cache.setdefault(table, {})[_digits(str(fields[wa_field]))] = key_value
                return True, key_value
            except LarkCLIError as exc:
                log.error("Lark REST upsert failed (%s key=%s): %s", table, key_value, exc)
                raise

        try:
            if rid:
                upd = json.dumps({"update_records": {rid: fields}}, ensure_ascii=False, default=str)
                _run_cli(["+record-batch-update", "--base-token", self.base_token,
                          "--table-id", tid, "--json", upd], timeout=120)
                if wa_field and fields.get(wa_field):
                    self._wa_cache.setdefault(table, {})[_digits(str(fields[wa_field]))] = key_value
                self._id_cache.setdefault(table, {})[key_value] = rid
                return True, key_value
            res = _run_cli(["+record-batch-create", "--base-token", self.base_token,
                            "--table-id", tid,
                            "--json", json.dumps({"create_records": [fields]}, ensure_ascii=False, default=str)],
                           timeout=120)
            data = res.get("data") or res
            new = data.get("record_id_list") or data.get("records") or []
            if new and isinstance(new, list):
                first = new[0]
                new_rid = first.get("record_id", "") if isinstance(first, dict) else str(first)
                if new_rid:
                    self._id_cache.setdefault(table, {})[key_value] = new_rid
                    if wa_field and fields.get(wa_field):
                        self._wa_cache.setdefault(table, {})[_digits(str(fields[wa_field]))] = key_value
            return True, key_value
        except LarkCLIError as exc:
            log.error("Lark upsert failed (%s key=%s): %s", table, key_value, exc)
            raise

    def _append(self, table: str, fields: dict) -> bool:
        tid = self._table_id(table)
        fields = self._ensure_ids(table, fields)
        fields = map_record(table, fields)  # bot enums -> manifest option labels
        key = TABLE_KEY_FIELD[table]
        key_value = str(fields.get(key, ""))
        fields = self._resolve_links(table, fields)
        fields = {k: v for k, v in fields.items() if v is not None}
        if self.rest_client:
            rest_fields = self._normalize_fields_for_rest(table, fields)
            try:
                created = self.rest_client.batch_create_records(tid, [rest_fields])
                if created and isinstance(created, list):
                    first = created[0]
                    new_rid = first.get("record_id", "") if isinstance(first, dict) else str(first)
                    if new_rid and key_value:
                        self._id_cache.setdefault(table, {})[key_value] = new_rid
                return True
            except LarkCLIError as exc:
                log.error("Lark REST append failed (%s): %s", table, exc)
                raise
        try:
            res = _run_cli(["+record-batch-create", "--base-token", self.base_token,
                            "--table-id", tid,
                            "--json", json.dumps({"create_records": [fields]}, ensure_ascii=False, default=str)],
                           timeout=120)
            data = res.get("data") or res
            new = data.get("record_id_list") or data.get("records") or []
            if new and isinstance(new, list):
                first = new[0]
                new_rid = first.get("record_id", "") if isinstance(first, dict) else str(first)
                if new_rid and key_value:
                    self._id_cache.setdefault(table, {})[key_value] = new_rid
            return True
        except LarkCLIError as exc:
            log.error("Lark append failed (%s): %s", table, exc)
            raise

    def _get_by_key(self, table: str, key_value: str) -> Optional[dict]:
        if not key_value:
            return None
        tid = self._table_id(table)
        key = TABLE_KEY_FIELD[table]
        if self.rest_client:
            try:
                items = self.rest_client.search_records(tid, key, str(key_value))
                if items:
                    return {k: self._unwrap(v) for k, v in items[0].get("fields", {}).items()}
            except Exception as exc:
                log.debug("REST get_by_key error (%s): %s", key_value, exc)
            return None
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
        digits = _digits(wa_id)
        if self.rest_client:
            try:
                # Try 8-digit mobile line first (matches international and local)
                search_query = digits[-8:] if len(digits) >= 8 else digits
                items = self.rest_client.search_records(tid, wa_field, search_query)
                if not items and search_query != digits:
                    items = self.rest_client.search_records(tid, wa_field, digits)
                if items:
                    return {k: self._unwrap(v) for k, v in items[0].get("fields", {}).items()}
            except Exception as exc:
                log.debug("REST get_by_wa error (%s): %s", wa_id, exc)
            return None
        res = _run_cli(["+record-search", "--base-token", self.base_token,
                        "--table-id", tid, "--keyword", digits,
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
        "account_username": "Account Username",
        "account_password": "Account Password",
        "server_url": "Server URL",
    }

    @staticmethod
    def _as_iso(val: Any) -> str:
        try:
            return datetime.fromisoformat(str(val)).isoformat(timespec="seconds")
        except (ValueError, TypeError):
            return _iso(_now())

    @staticmethod
    def _merge_notes(base_notes: str, extras: list[str]) -> str:
        """Idempotently replace any trailing [Summary: ...] block with fresh extras."""
        clean_base = re.sub(r"\s*(?:\|\s*)?\[Summary:.*\]\s*$", "", str(base_notes or "")).strip()
        if not extras:
            return clean_base
        summary = f"[Summary: {' | '.join(extras)}]"
        return f"{clean_base} | {summary}" if clean_base else summary

    def _build_lead_cols(self, lead: LeadRecord) -> tuple[dict[str, Any], str]:
        wa_key = _digits(lead.wa_id)
        existing = self._lead_records.get(wa_key)
        if existing and existing.lead_id:
            lead.lead_id = existing.lead_id
        elif not lead.lead_id or not str(lead.lead_id).startswith("LEAD-"):
            existing_lead_id = self._wa_cache.get("01_Leads", {}).get(wa_key)
            if existing_lead_id:
                lead.lead_id = existing_lead_id
            else:
                lead.lead_id = self._gen_id("01_Leads")
        if not getattr(lead, "created_at", None):
            lead.created_at = lead.first_contact_at or _iso(_now())
        cols: dict[str, Any] = {}
        for src, dst in self._LEAD_MAP.items():
            val = getattr(lead, src, None)
            if val in (None, ""):
                continue
            if dst in ("First Contact At", "Last Contact At", "Next Follow Up", "Created At"):
                val = self._as_iso(val)
            cols[dst] = val
        if "Created At" not in cols:
            cols["Created At"] = self._as_iso(lead.created_at or lead.first_contact_at or _iso(_now()))
        if lead.months and lead.device_count:
            pkg_id = package_id_for(lead.months, lead.device_count)
            if pkg_id:
                cols["Interested Package ID"] = pkg_id
        if lead.trial_requested and not cols.get("Trial Outcome"):
            cols["Trial Outcome"] = "requested"
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
        if lead.referrer_code:
            extras.append(f"RefCode: {lead.referrer_code}")
        merged_notes = self._merge_notes(cols.get("Lead Notes", ""), extras)
        if merged_notes:
            cols["Lead Notes"] = merged_notes
        if lead.opted_out:
            cols["Lead Stage"] = "OPTED_OUT"
        return cols, wa_key

    def upsert_lead(self, lead: LeadRecord) -> bool:
        with self._lock:
            cols, wa_key = self._build_lead_cols(lead)
            ok, key_val = self._upsert_by_key("01_Leads", cols)
            if ok and key_val:
                lead.lead_id = key_val
                if wa_key:
                    self._wa_cache.setdefault("01_Leads", {})[wa_key] = key_val
                    self._lead_records[wa_key] = lead
            return ok

    def batch_upsert_leads(self, leads: list[LeadRecord]) -> tuple[int, int, str]:
        """Bulk upsert leads with batching for high performance and zero timeout."""
        with self._lock:
            if not self.rest_client:
                synced = 0
                errors = 0
                last_err = ""
                for l in leads:
                    try:
                        if self.upsert_lead(l):
                            synced += 1
                    except Exception as e:
                        errors += 1
                        last_err = str(e)
                return synced, errors, last_err

            tid = self._table_id("01_Leads")
            self._load_cache("01_Leads")
            key_field = TABLE_KEY_FIELD["01_Leads"]
            wa_field = TABLE_WA_FIELD["01_Leads"]

            updates: dict[str, dict] = {}
            creates: list[dict] = []
            lead_map_for_update: dict[str, tuple[LeadRecord, str]] = {}
            lead_map_for_create: list[tuple[LeadRecord, str, str]] = []

            for lead in leads:
                try:
                    cols, wa_key = self._build_lead_cols(lead)
                    fields = self._ensure_ids("01_Leads", cols)
                    fields = map_record("01_Leads", fields)
                    key_value = str(fields.get(key_field, ""))
                    if not key_value:
                        continue
                    fields = self._resolve_links("01_Leads", fields)
                    fields = {k: v for k, v in fields.items() if v is not None}
                    rid = self._find_by_key("01_Leads", key_value)
                    wa_val = str(fields.get(wa_field) or "")
                    if not rid and wa_val:
                        existing_rid = self._find_by_wa("01_Leads", wa_val)
                        if existing_rid:
                            rid = existing_rid
                            existing_key = self._wa_cache.get("01_Leads", {}).get(_digits(wa_val))
                            if existing_key:
                                key_value = existing_key
                                fields[key_field] = existing_key

                    rest_fields = self._normalize_fields_for_rest("01_Leads", fields)
                    if rid:
                        updates[rid] = rest_fields
                        lead_map_for_update[rid] = (lead, key_value)
                    else:
                        creates.append(rest_fields)
                        lead_map_for_create.append((lead, key_value, wa_key))
                except Exception as exc:
                    log.error("Failed preparing lead for batch: %s", exc)

            synced = 0
            errors = 0
            last_err = ""

            # Execute batch updates (chunked by 500)
            if updates:
                items = list(updates.items())
                for i in range(0, len(items), 500):
                    chunk = dict(items[i:i+500])
                    try:
                        self.rest_client.batch_update_records(tid, chunk)
                        for rid in chunk.keys():
                            ld, kv = lead_map_for_update[rid]
                            ld.lead_id = kv
                            self._id_cache.setdefault("01_Leads", {})[kv] = rid
                            if ld.wa_id:
                                self._wa_cache.setdefault("01_Leads", {})[_digits(ld.wa_id)] = kv
                                self._lead_records[_digits(ld.wa_id)] = ld
                            synced += 1
                    except Exception as e:
                        errors += len(chunk)
                        last_err = str(e)
                        log.error("Batch update chunk failed: %s", e)

            # Execute batch creates (chunked by 500)
            if creates:
                for i in range(0, len(creates), 500):
                    chunk = creates[i:i+500]
                    map_chunk = lead_map_for_create[i:i+500]
                    try:
                        res = self.rest_client.batch_create_records(tid, chunk)
                        for idx, item in enumerate(res):
                            new_rid = item.get("record_id", "") if isinstance(item, dict) else str(item)
                            ld, kv, wa_key = map_chunk[idx]
                            ld.lead_id = kv
                            if new_rid:
                                self._id_cache.setdefault("01_Leads", {})[kv] = new_rid
                            if wa_key:
                                self._wa_cache.setdefault("01_Leads", {})[wa_key] = kv
                                self._lead_records[wa_key] = ld
                            synced += 1
                    except Exception as e:
                        errors += len(chunk)
                        last_err = str(e)
                        log.error("Batch create chunk failed: %s", e)

            return synced, errors, last_err

    def get_table_counts(self) -> dict[str, int]:
        """Fetch live record totals across primary Lark Base tables in parallel."""
        counts: dict[str, int] = {}
        if not self.rest_client:
            return counts
        from concurrent.futures import ThreadPoolExecutor

        target_tables = [
            "01_Leads", "02_Free_Trials", "03_Customers", "05_Subscriptions",
            "06_Payments", "07_Installations", "09_Resellers", "10_Reseller_Sales",
            "11_Commissions", "19_Receipts"
        ]

        def _fetch(name: str) -> tuple[str, int]:
            tid = self._table_ids.get(name) or KNOWN_TABLE_IDS.get(name)
            if not tid:
                return name, 0
            try:
                data = self.rest_client.list_records(tid, limit=1)
                return name, int(data.get("total") or 0)
            except Exception:
                return name, 0

        with ThreadPoolExecutor(max_workers=5) as ex:
            for name, total in ex.map(_fetch, target_tables):
                counts[name] = total
        return counts

    def get_lead_by_wa_id(self, wa_id: str) -> Optional[LeadRecord]:
        with self._lock:
            wa_key = _digits(wa_id)
            if wa_key in self._lead_records:
                return self._lead_records[wa_key]
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
            m = re.search(r"Quote: (\d+)mo x (\d+)dev", notes)
            if m:
                kwargs.setdefault("months", int(m.group(1)))
                kwargs.setdefault("device_count", int(m.group(2)))
            m = re.search(r"Total: Le([\d,]+)", notes)
            if m:
                kwargs.setdefault("subscription_quote_le", int(m.group(1).replace(",", "")))
            if "Ready to pay after setup" in notes:
                kwargs.setdefault("ready_to_pay_after_setup", True)
            if "App INSTALLED (reported)" in notes:
                kwargs.setdefault("app_installed_reported", True)
            if "Setup verified by staff" in notes:
                kwargs.setdefault("staff_setup_verified", True)
            m = re.search(r"Payment: (\w+)", notes)
            if m:
                kwargs.setdefault("payment_status", m.group(1))
            kwargs["notes"] = re.sub(r"\s*(?:\|\s*)?\[Summary:.*\]\s*$", "", notes).strip()
            valid = {k: v for k, v in kwargs.items() if k in LeadRecord.__dataclass_fields__}
            rec = LeadRecord(**valid)
            if wa_key:
                self._lead_records[wa_key] = rec
            return rec

    def upsert_customer(self, customer: CustomerRecord) -> bool:
        with self._lock:
            wa_key = _digits(customer.wa_id)
            existing = self._customer_records.get(wa_key)
            if existing and existing.customer_id:
                customer.customer_id = existing.customer_id
            elif not customer.customer_id or not str(customer.customer_id).startswith("CUST-"):
                existing_rid = self._find_by_wa("03_Customers", customer.wa_id)
                existing_cust_id = self._wa_cache.get("03_Customers", {}).get(wa_key)
                if existing_cust_id:
                    customer.customer_id = existing_cust_id
                else:
                    customer.customer_id = self._gen_id("03_Customers")
            if not getattr(customer, "activation_at", None):
                customer.activation_at = _iso(_now())
            cols: dict[str, Any] = {}
            for src, dst in self._CUSTOMER_MAP.items():
                val = getattr(customer, src, None)
                if val in (None, ""):
                    continue
                if dst in ("Date Joined", "Activation Date"):
                    val = self._as_iso(val)
                cols[dst] = val
            if "Date Joined" not in cols:
                cols["Date Joined"] = self._as_iso(customer.activation_at or _iso(_now()))
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
            if getattr(customer, "account_username", None):
                extras.append(f"User {customer.account_username}")
            if getattr(customer, "account_password", None):
                extras.append(f"Pass {customer.account_password}")
            if getattr(customer, "server_url", None):
                extras.append(f"Server {customer.server_url}")
            merged_notes = self._merge_notes(cols.get("Support Notes", ""), extras)
            if merged_notes:
                cols["Support Notes"] = merged_notes
            ok, key_val = self._upsert_by_key("03_Customers", cols)
            if ok and key_val:
                customer.customer_id = key_val
                if wa_key:
                    self._wa_cache.setdefault("03_Customers", {})[wa_key] = key_val
                    self._customer_records[wa_key] = customer
                # Also sync 05_Subscriptions and 08_Devices so relational tables stay complete
                self._sync_customer_subscription_and_device(customer)
            return ok

    def _sync_customer_subscription_and_device(self, customer: CustomerRecord) -> None:
        """Maintain corresponding rows in 05_Subscriptions and 08_Devices for an active customer."""
        if not customer.customer_id or not customer.subscription_months:
            return
        sub_id = f"SUB-{customer.customer_id.replace('CUST-', '')}-R{customer.renewal_count or 0}"
        pkg_id = package_id_for(customer.subscription_months, customer.device_count or 1)
        sub_fields: dict[str, Any] = {
            "Subscription ID": sub_id,
            "Customer ID": customer.customer_id,
            "Customer WhatsApp Number": customer.wa_id or customer.phone_e164 or "",
            "Package ID": pkg_id,
            "Device Count": customer.device_count or 1,
            "Duration Months": customer.subscription_months,
            "Activation Date": self._as_iso(customer.activation_at or _iso(_now())),
            "Subscription Status": customer.account_status or "active",
            "Amount Paid SLE": customer.amount_paid_le or 0,
            "Setup Verified": True,
        }
        if customer.subscription_expires_at:
            exp_iso = self._as_iso(customer.subscription_expires_at)
            sub_fields["Standard Expiry"] = exp_iso
            sub_fields["Final Expiry"] = exp_iso
        sub_fields = {k: v for k, v in sub_fields.items() if v not in (None, "")}
        try:
            self._upsert_by_key("05_Subscriptions", sub_fields)
            # Link Current Subscription ID on 03_Customers
            self._upsert_by_key("03_Customers", {
                "Customer ID": customer.customer_id,
                "Current Subscription ID": sub_id,
            })
        except LarkCLIError as exc:
            log.warning("Subscription sync skipped for %s: %s", customer.customer_id, exc)

        if customer.device_types:
            dev_id = f"DEV-{customer.customer_id.replace('CUST-', '')}-01"
            dev_fields: dict[str, Any] = {
                "Device ID": dev_id,
                "Customer ID": customer.customer_id,
                "Subscription ID": sub_id,
                "Device Type": customer.device_types,
                "Registered At": self._as_iso(customer.activation_at or _iso(_now())),
                "Device Status": "active",
            }
            try:
                self._upsert_by_key("08_Devices", dev_fields)
            except LarkCLIError as exc:
                log.warning("Device sync skipped for %s: %s", customer.customer_id, exc)

    def get_customer_by_wa_id(self, wa_id: str) -> Optional[CustomerRecord]:
        with self._lock:
            wa_key = _digits(wa_id)
            if wa_key in self._customer_records:
                return self._customer_records[wa_key]
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
            m = re.search(r"(\d+)mo x (\d+)dev", notes)
            if m:
                kwargs.setdefault("subscription_months", int(m.group(1)))
                kwargs.setdefault("device_count", int(m.group(2)))
            m = re.search(r"Paid Le([\d,]+)", notes)
            if m:
                kwargs.setdefault("amount_paid_le", int(m.group(1).replace(",", "")))
            m = re.search(r"Renewals: (\d+)", notes)
            if m:
                kwargs.setdefault("renewal_count", int(m.group(1)))
            m = re.search(r"Ref (\S+)", notes)
            if m:
                kwargs.setdefault("transaction_reference", m.group(1))
            m = re.search(r"Expires (\S+)", notes)
            if m:
                kwargs.setdefault("subscription_expires_at", m.group(1))
            m = re.search(r"User (\S+)", notes)
            if m:
                kwargs.setdefault("account_username", m.group(1))
            m = re.search(r"Pass (\S+)", notes)
            if m:
                kwargs.setdefault("account_password", m.group(1))
            m = re.search(r"Server (\S+)", notes)
            if m:
                kwargs.setdefault("server_url", m.group(1))
            valid = {k: v for k, v in kwargs.items() if k in CustomerRecord.__dataclass_fields__}
            rec = CustomerRecord(**valid)
            if wa_key:
                self._customer_records[wa_key] = rec
            return rec

    def upsert_payment(self, payment: PaymentRecord) -> bool:
        with self._lock:
            if not payment.payment_id or not str(payment.payment_id).startswith("PAY-"):
                payment.payment_id = self._gen_id("06_Payments")
            if not payment.created_at:
                payment.created_at = _iso(_now())
            notes_parts = [payment.note] if payment.note else []
            if payment.verified_by:
                notes_parts.append(f"Verified by: {payment.verified_by}")
            fields: dict[str, Any] = {
                "Payment ID": payment.payment_id,
                "Received At": self._as_iso(payment.created_at),
                "Lead ID": payment.lead_id or "",
                "Customer ID": payment.customer_id or "",
                "Payment For": "subscription",
                "Currency": "SLE",
                "Amount Due SLE": payment.expected_amount_le or 0,
                "Payment Method": payment.method or "other",
                "Payment Reference": payment.transaction_reference or "",
                "Payment Status": payment.status or "pending",
                "Confirmed By Staff ID": payment.verified_by or "",
                "Payment Notes": " | ".join(notes_parts),
            }
            if payment.status == "confirmed" and payment.expected_amount_le:
                fields["Amount Received SLE"] = payment.expected_amount_le
                fields["Balance Due SLE"] = 0
            fields = {k: v for k, v in fields.items() if v not in (None, "")}
            return self._upsert_by_key("06_Payments", fields)[0]

    def get_payment_by_ref(self, ref: str) -> Optional[PaymentRecord]:
        if not ref:
            return None
        with self._lock:
            try:
                tid = self._table_id("06_Payments")
                res = _run_cli(["+record-search", "--base-token", self.base_token,
                                "--table-id", tid, "--keyword", str(ref),
                                "--limit", "1"], timeout=60)
                row = self._parse_search(res)
                if not row:
                    return None
                return PaymentRecord(
                    payment_id=str(row.get("Payment ID", "")),
                    customer_id=str(row.get("Customer ID", "")),
                    lead_id=str(row.get("Lead ID", "")),
                    expected_amount_le=int(row.get("Amount Due SLE") or row.get("Amount Received SLE") or 0),
                    method=str(row.get("Payment Method", "")),
                    transaction_reference=str(row.get("Payment Reference", "")),
                    status=str(row.get("Payment Status", "pending")),
                    verified_by=str(row.get("Confirmed By Staff ID", "")),
                    created_at=str(row.get("Received At", "")),
                    note=str(row.get("Payment Notes", "")),
                )
            except Exception as exc:
                log.warning("Payment search by ref failed (%s): %s", ref, exc)
                return None

    def upsert_installation(self, installation: InstallationRecord) -> bool:
        with self._lock:
            inst = installation
            if not inst.installation_id or not str(inst.installation_id).startswith("INST-"):
                inst.installation_id = self._gen_id("07_Installations")
            notes_parts = [inst.issue_note] if inst.issue_note else []
            if inst.assigned_staff:
                notes_parts.append(f"Staff: {inst.assigned_staff}")
            fields: dict[str, Any] = {
                "Installation ID": inst.installation_id,
                "Lead ID": inst.lead_id or "",
                "Requested At": _iso(_now()),
                "Device Type": inst.device_platform or "",
                "Setup Type": inst.installation_method or "self_install",
                "Address and Landmark": (inst.area or "").strip(),
                "Visit Fee Quoted SLE": inst.visit_fee_le or 0,
                "Assigned Technician ID": inst.assigned_staff or "",
                "App Installed": bool(inst.app_installed_reported_at or inst.setup_status == "verified"),
                "Booking Status": {"verified": "completed"}.get(inst.setup_status, inst.setup_status or "pending"),
                "Issue or Visit Notes": " | ".join(notes_parts),
            }
            if inst.setup_verified_at:
                fields["Completed At"] = self._as_iso(inst.setup_verified_at)
                fields["Account Configured"] = True
                fields["Playback Tested"] = True
            if getattr(inst, "credited_sales_reseller_id", None):
                fields["Credited Sales Reseller ID"] = inst.credited_sales_reseller_id
            if getattr(inst, "assigned_installer_reseller_id", None):
                fields["Assigned Installer Reseller ID"] = inst.assigned_installer_reseller_id
            if getattr(inst, "installer_assignment_status", None):
                fields["Installer Assignment Status"] = inst.installer_assignment_status
            if getattr(inst, "assigned_at", None):
                fields["Assigned At"] = self._as_iso(inst.assigned_at)
            if getattr(inst, "accepted_at", None):
                fields["Accepted At"] = self._as_iso(inst.accepted_at)
            if getattr(inst, "install_mode", None):
                fields["Install Mode"] = inst.install_mode
            if getattr(inst, "approved_fee_sle", None):
                fields["Approved Fee SLE"] = inst.approved_fee_sle
            if getattr(inst, "fee_quote_version", None):
                fields["Fee Quote Version"] = inst.fee_quote_version
            if getattr(inst, "fee_approved_by", None):
                fields["Fee Approved By"] = inst.fee_approved_by
            if getattr(inst, "fee_approved_at", None):
                fields["Fee Approved At"] = self._as_iso(inst.fee_approved_at)
            if getattr(inst, "fee_received_verified_sle", None):
                fields["Fee Received Verified SLE"] = inst.fee_received_verified_sle
            if getattr(inst, "fee_payment_status", None):
                fields["Fee Payment Status"] = inst.fee_payment_status
            if getattr(inst, "customer_confirmed_working_at", None):
                fields["Customer Confirmed Working At"] = self._as_iso(inst.customer_confirmed_working_at)
            if getattr(inst, "completion_verified_by", None):
                fields["Completion Verified By"] = inst.completion_verified_by
            if getattr(inst, "completion_verified_at", None):
                fields["Completion Verified At"] = self._as_iso(inst.completion_verified_at)
            if getattr(inst, "qualified_at", None):
                fields["Qualified At"] = self._as_iso(inst.qualified_at)
            if getattr(inst, "qualified_month", None):
                fields["Qualified Month YYYY-MM"] = inst.qualified_month
            if getattr(inst, "commission_rate_snapshot", None):
                fields["Commission Rate Snapshot %"] = inst.commission_rate_snapshot
            if getattr(inst, "installation_earning_id", None):
                fields["Installation Earning ID"] = inst.installation_earning_id
            if getattr(inst, "monthly_count_eligible", None):
                fields["Monthly Count Eligible"] = bool(inst.monthly_count_eligible)
            fields = {k: v for k, v in fields.items() if v not in (None, "")}
            return self._upsert_by_key("07_Installations", fields)[0]

    def upsert_trial(self, trial: TrialRecord) -> bool:
        with self._lock:
            if not trial.trial_id or not str(trial.trial_id).startswith("TRIAL-"):
                trial.trial_id = self._gen_id("02_Free_Trials")
            status = trial.trial_status or trial.approval_status or "requested"
            notes_parts = [trial.note] if trial.note else []
            if trial.approved_by:
                notes_parts.append(f"Approved by: {trial.approved_by}")
            fields: dict[str, Any] = {
                "Trial ID": trial.trial_id,
                "Lead ID": trial.lead_id or "",
                "Requested At": self._as_iso(trial.requested_at or _iso(_now())),
                "Trial Duration Hours": _hours_between(trial.start_at, trial.end_at) or 24,
                "Trial Status": {"active": "active", "approved": "approved", "pending": "requested"}.get(status, status),
                "Approved By Staff ID": trial.approved_by or "",
                "Trial Notes": " | ".join(notes_parts),
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
        with self._lock:
            if not handoff.handoff_id or not str(handoff.handoff_id).startswith("ACT-"):
                handoff.handoff_id = self._gen_id("17_Activities")
            raw_outcome = handoff.resolution or ("resolved" if handoff.status == "resolved" else "need_follow_up")
            fields: dict[str, Any] = {
                "Activity ID": handoff.handoff_id,
                "Lead ID": handoff.lead_id or "",
                "Activity Type": "handoff",
                "Activity At": self._as_iso(handoff.requested_at or _iso(_now())),
                "Status": {"pending": "pending", "accepted": "done", "resolved": "done"}.get(handoff.status, "pending"),
                "Outcome": raw_outcome,
                "Next Action": handoff.reason or "",
                "Notes": f"Reason: {handoff.reason or '-'} | Assigned: {handoff.assigned_staff or 'unassigned'} | Next: {handoff.next_stage or '-'}",
            }
            fields = {k: v for k, v in fields.items() if v not in (None, "")}
            return self._upsert_by_key("17_Activities", fields)[0]

    def upsert_followup(self, followup: FollowUpRecord) -> bool:
        with self._lock:
            fu = followup
            if not fu.followup_id or not str(fu.followup_id).startswith("ACT-"):
                fu.followup_id = self._gen_id("17_Activities")
            fields: dict[str, Any] = {
                "Activity ID": fu.followup_id,
                "Lead ID": fu.lead_id or "",
                "Activity Type": "follow_up",
                "Activity At": _iso(_now()),
                "Status": {"pending": "pending", "manual_pending": "pending",
                           "sent": "done", "suppressed": "cancelled"}.get(fu.status, "pending"),
                "Outcome": "resolved" if fu.status == "sent" else "need_follow_up",
                "Next Action": fu.reason or "",
                "Notes": " | ".join(p for p in [fu.reason, fu.suppressed_reason, fu.template_name_if_required] if p),
            }
            if fu.due_at:
                fields["Due At"] = self._as_iso(fu.due_at)
            fields = {k: v for k, v in fields.items() if v not in (None, "")}
            return self._upsert_by_key("17_Activities", fields)[0]

    def upsert_referral(self, referral: ReferralRecord) -> bool:
        with self._lock:
            ref = referral
            if not ref.referral_id or not str(ref.referral_id).startswith("REF-"):
                ref.referral_id = self._gen_id("14_Referrals")
            fields: dict[str, Any] = {
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
        with self._lock:
            fields: dict[str, Any] = {
                "Activity ID": self._gen_id("17_Activities"),
                "Lead ID": lead_id or "",
                "Activity Type": activity_type,
                "Activity At": _iso(_now()),
                "Status": "done",
                "Outcome": outcome or "other",
                "Notes": notes or "",
            }
            fields = {k: v for k, v in fields.items() if v not in (None, "")}
            try:
                return self._append("17_Activities", fields)
            except LarkCLIError:
                return False

    def create_ticket(self, wa_id: str, customer_id: str, issue_type: str,
                      subject: str, description: str, priority: str = "medium") -> str:
        with self._lock:
            fields: dict[str, Any] = {
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

    def seed_staff(self) -> int:
        """Insert/refresh default staff desks into 15_Staff (idempotent)."""
        inserted = 0
        for st in SEED_STAFF:
            try:
                ok, _ = self._upsert_by_key("15_Staff", dict(st))
                inserted += 1 if ok else 0
            except LarkCLIError as exc:
                log.warning("Staff seed %s failed: %s", st.get("Staff ID"), exc)
        log.info("Seeded %d staff rows into 15_Staff", inserted)
        return inserted

    def seed_service_zones(self) -> int:
        """Insert/refresh default service zones into 18_Service_Zones (idempotent)."""
        inserted = 0
        for zn in SEED_SERVICE_ZONES:
            try:
                ok, _ = self._upsert_by_key("18_Service_Zones", dict(zn))
                inserted += 1 if ok else 0
            except LarkCLIError as exc:
                log.warning("Service zone seed %s failed: %s", zn.get("Zone ID"), exc)
        log.info("Seeded %d service zones into 18_Service_Zones", inserted)
        return inserted

    def _parse_record_list(self, res: dict) -> list[dict]:
        data = res.get("data") or res
        items = data.get("records") or data.get("items") or []
        if not items and isinstance(data.get("data"), list) and data.get("fields"):
            names = data["fields"]
            rids = data.get("record_id_list") or [""] * len(data["data"])
            items = [
                {"record_id": rid, "fields": dict(zip(names, row))}
                for rid, row in zip(rids, data["data"])
            ]
        return [{k: self._unwrap(v) for k, v in it.get("fields", {}).items()} for it in items]

    def get_zones(self) -> list[dict]:
        """Read 18_Service_Zones for visit-fee quoting."""
        tid = self._table_id("18_Service_Zones")
        res = _run_cli(["+record-list", "--base-token", self.base_token,
                        "--table-id", tid, "--limit", "200"], timeout=90)
        return self._parse_record_list(res)

    def get_staff(self, role: Optional[str] = None) -> list[dict]:
        """Read 15_Staff for assignment."""
        tid = self._table_id("15_Staff")
        res = _run_cli(["+record-list", "--base-token", self.base_token,
                        "--table-id", tid, "--limit", "200"], timeout=90)
        rows = self._parse_record_list(res)
        if role:
            rows = [r for r in rows if r.get("Role") == role]
        return rows

    # ======================================================== Lark Base Workflows
    def _field_id_map(self, table: str) -> dict[str, str]:
        tid = self._table_id(table)
        res = _run_cli(["+field-list", "--base-token", self.base_token, "--table-id", tid], timeout=60)
        data = res.get("data") or res
        flds = data.get("fields") or data.get("items") or []
        return {
            (f.get("name") or f.get("field_name", "")): (f.get("id") or f.get("field_id", ""))
            for f in flds
            if (f.get("name") or f.get("field_name")) and (f.get("id") or f.get("field_id"))
        }

    def list_workflows(self) -> list[dict]:
        """List all native workflows in the Lark Base."""
        res = _run_cli(["+workflow-list", "--base-token", self.base_token], timeout=60)
        data = res.get("data") or res
        return data.get("workflows") or data.get("items") or []

    def ensure_workflows(self) -> list[dict]:
        """Idempotently create and enable NexgloTV CRM native Lark Base workflows."""
        existing = {w.get("title"): w for w in self.list_workflows() if w.get("title")}
        lead_f = self._field_id_map("01_Leads")
        trial_f = self._field_id_map("02_Free_Trials")
        sub_f = self._field_id_map("05_Subscriptions")
        pay_f = self._field_id_map("06_Payments")
        tkt_f = self._field_id_map("16_Support_Tickets")

        specs: list[dict] = [
            {
                "title": "Auto: New Lead Follow-up Activity",
                "steps": [
                    {
                        "id": "step_trigger",
                        "type": "AddRecordTrigger",
                        "title": "When New Lead Added",
                        "next": "step_add_activity",
                        "data": {
                            "table_name": "01_Leads",
                            "watched_field_name": "Lead ID",
                            "condition_list": None,
                        },
                    },
                    {
                        "id": "step_add_activity",
                        "type": "AddRecordAction",
                        "title": "Create Planned Follow-up Activity",
                        "next": None,
                        "data": {
                            "table_name": "17_Activities",
                            "field_values": [
                                {"field_name": "Activity Type", "value": [{"value_type": "option", "value": {"name": "WhatsApp"}}]},
                                {"field_name": "Status", "value": [{"value_type": "option", "value": {"name": "Planned"}}]},
                                {"field_name": "Outcome", "value": [{"value_type": "option", "value": {"name": "Interested"}}]},
                                {"field_name": "Next Action", "value": [{"value_type": "text", "value": "Qualify lead package & setup method"}]},
                                {
                                    "field_name": "Notes",
                                    "value": [
                                        {"value_type": "text", "value": "Auto-created from Lead: "},
                                        {"value_type": "ref", "value": f"$.step_trigger.{lead_f.get('Lead ID', '')}"},
                                        {"value_type": "text", "value": " | WA: "},
                                        {"value_type": "ref", "value": f"$.step_trigger.{lead_f.get('WhatsApp Number', '')}"},
                                    ],
                                },
                            ],
                        },
                    },
                ],
            },
            {
                "title": "Auto: Free Trial Request Review Task",
                "steps": [
                    {
                        "id": "step_trigger",
                        "type": "AddRecordTrigger",
                        "title": "When Free Trial Requested",
                        "next": "step_add_activity",
                        "data": {
                            "table_name": "02_Free_Trials",
                            "watched_field_name": "Trial ID",
                            "condition_list": None,
                        },
                    },
                    {
                        "id": "step_add_activity",
                        "type": "AddRecordAction",
                        "title": "Create Trial Review Activity",
                        "next": None,
                        "data": {
                            "table_name": "17_Activities",
                            "field_values": [
                                {"field_name": "Activity Type", "value": [{"value_type": "option", "value": {"name": "Follow-up"}}]},
                                {"field_name": "Status", "value": [{"value_type": "option", "value": {"name": "Due"}}]},
                                {"field_name": "Outcome", "value": [{"value_type": "option", "value": {"name": "Need Follow-up"}}]},
                                {"field_name": "Next Action", "value": [{"value_type": "text", "value": "Review trial request & follow up after 24h"}]},
                                {
                                    "field_name": "Notes",
                                    "value": [
                                        {"value_type": "text", "value": "Trial requested: "},
                                        {"value_type": "ref", "value": f"$.step_trigger.{trial_f.get('Trial ID', '')}"},
                                    ],
                                },
                            ],
                        },
                    },
                ],
            },
            {
                "title": "Auto: Payment Verification Task",
                "steps": [
                    {
                        "id": "step_trigger",
                        "type": "AddRecordTrigger",
                        "title": "When Payment Logged",
                        "next": "step_add_activity",
                        "data": {
                            "table_name": "06_Payments",
                            "watched_field_name": "Payment ID",
                            "condition_list": None,
                        },
                    },
                    {
                        "id": "step_add_activity",
                        "type": "AddRecordAction",
                        "title": "Create Payment Verification Activity",
                        "next": None,
                        "data": {
                            "table_name": "17_Activities",
                            "field_values": [
                                {"field_name": "Activity Type", "value": [{"value_type": "option", "value": {"name": "Payment Reminder"}}]},
                                {"field_name": "Status", "value": [{"value_type": "option", "value": {"name": "Due"}}]},
                                {"field_name": "Outcome", "value": [{"value_type": "option", "value": {"name": "Need Follow-up"}}]},
                                {"field_name": "Next Action", "value": [{"value_type": "text", "value": "Verify payment receipt & activate subscription"}]},
                                {
                                    "field_name": "Notes",
                                    "value": [
                                        {"value_type": "text", "value": "Payment logged: "},
                                        {"value_type": "ref", "value": f"$.step_trigger.{pay_f.get('Payment ID', '')}"},
                                    ],
                                },
                            ],
                        },
                    },
                ],
            },
            {
                "title": "Auto: Support Ticket Escalation Task",
                "steps": [
                    {
                        "id": "step_trigger",
                        "type": "AddRecordTrigger",
                        "title": "When Support Ticket Opened",
                        "next": "step_add_activity",
                        "data": {
                            "table_name": "16_Support_Tickets",
                            "watched_field_name": "Ticket ID",
                            "condition_list": None,
                        },
                    },
                    {
                        "id": "step_add_activity",
                        "type": "AddRecordAction",
                        "title": "Create Support Escalation Activity",
                        "next": None,
                        "data": {
                            "table_name": "17_Activities",
                            "field_values": [
                                {"field_name": "Activity Type", "value": [{"value_type": "option", "value": {"name": "Follow-up"}}]},
                                {"field_name": "Status", "value": [{"value_type": "option", "value": {"name": "Due"}}]},
                                {"field_name": "Outcome", "value": [{"value_type": "option", "value": {"name": "Need Follow-up"}}]},
                                {"field_name": "Next Action", "value": [{"value_type": "text", "value": "Respond to customer support ticket"}]},
                                {
                                    "field_name": "Notes",
                                    "value": [
                                        {"value_type": "text", "value": "Ticket opened: "},
                                        {"value_type": "ref", "value": f"$.step_trigger.{tkt_f.get('Ticket ID', '')}"},
                                        {"value_type": "text", "value": " | Subject: "},
                                        {"value_type": "ref", "value": f"$.step_trigger.{tkt_f.get('Subject', '')}"},
                                    ],
                                },
                            ],
                        },
                    },
                ],
            },
            {
                "title": "Auto: Daily Subscription Renewal Check (09:00)",
                "steps": [
                    {
                        "id": "step_timer",
                        "type": "TimerTrigger",
                        "title": "Every Day at 09:00",
                        "next": "step_find_subs",
                        "data": {
                            "rule": "DAILY",
                            "start_time": "2026-10-13 09:00",
                            "is_never_end": True,
                        },
                    },
                    {
                        "id": "step_find_subs",
                        "type": "FindRecordAction",
                        "title": "Find Renewal Due Subscriptions",
                        "next": "step_loop_subs",
                        "data": {
                            "table_name": "05_Subscriptions",
                            "field_names": ["Subscription ID"],
                            "should_proceed_when_no_results": False,
                            "filter_info": {
                                "conjunction": "and",
                                "conditions": [
                                    {
                                        "field_name": "Subscription Status",
                                        "operator": "is",
                                        "value": [{"value_type": "option", "value": {"name": "Renewal Due"}}],
                                    }
                                ],
                            },
                        },
                    },
                    {
                        "id": "step_loop_subs",
                        "type": "Loop",
                        "title": "Loop Over Renewal Due Subscriptions",
                        "children": {
                            "links": [
                                {"kind": "loop_start", "to": "step_add_renewal_activity"}
                            ]
                        },
                        "next": None,
                        "data": {
                            "loop_mode": "continue",
                            "max_loop_times": 5,
                            "data": [
                                {
                                    "value_type": "ref",
                                    "value": "$.step_find_subs.fieldRecords",
                                }
                            ],
                        },
                    },
                    {
                        "id": "step_add_renewal_activity",
                        "type": "AddRecordAction",
                        "title": "Create Renewal Reminder Activity",
                        "next": None,
                        "data": {
                            "table_name": "17_Activities",
                            "field_values": [
                                {"field_name": "Activity Type", "value": [{"value_type": "option", "value": {"name": "Renewal Reminder"}}]},
                                {"field_name": "Status", "value": [{"value_type": "option", "value": {"name": "Due"}}]},
                                {"field_name": "Outcome", "value": [{"value_type": "option", "value": {"name": "Need Follow-up"}}]},
                                {"field_name": "Next Action", "value": [{"value_type": "text", "value": "Contact customer for subscription renewal"}]},
                                {
                                    "field_name": "Notes",
                                    "value": [
                                        {"value_type": "text", "value": "Renewal due for Subscription: "},
                                        {"value_type": "ref", "value": f"$.step_loop_subs.item.{sub_f.get('Subscription ID', '')}"},
                                    ],
                                },
                            ],
                        },
                    },
                ],
            },
        ]

        results: list[dict] = []
        for wf in specs:
            title = wf["title"]
            if title in existing:
                wf_id = existing[title].get("workflow_id", "")
                if wf_id and existing[title].get("status") != "enabled":
                    try:
                        _run_cli(["+workflow-enable", "--base-token", self.base_token, "--workflow-id", wf_id], timeout=60)
                    except LarkCLIError as exc:
                        log.warning("Could not enable workflow %s: %s", wf_id, exc)
                results.append({"title": title, "workflow_id": wf_id, "action": "existing_enabled"})
                continue

            payload = {
                "client_token": str(uuid4()),
                "title": title,
                "steps": wf["steps"],
            }
            res = _run_cli(
                ["+workflow-create", "--base-token", self.base_token, "--json", json.dumps(payload, ensure_ascii=False)],
                timeout=90,
            )
            data = res.get("data") or res
            wf_id = data.get("workflow_id", "")
            if wf_id:
                try:
                    _run_cli(["+workflow-enable", "--base-token", self.base_token, "--workflow-id", wf_id], timeout=60)
                except LarkCLIError as exc:
                    log.warning("Could not enable workflow %s: %s", wf_id, exc)
            results.append({"title": title, "workflow_id": wf_id, "action": "created_and_enabled"})
        return results


def _hours_between(start: str, end: str) -> int:
    try:
        s = datetime.fromisoformat(str(start))
        e = datetime.fromisoformat(str(end))
        return max(0, int((e - s).total_seconds() // 3600))
    except (ValueError, TypeError):
        return 0


def create_lark_provider(
    base_token: str = "",
    app_id: str = "",
    app_secret: str = "",
    auto_create: bool = False,
    seed_packages: bool = False,
) -> LarkBaseCRMProvider:
    """Factory. Raises LarkCLIError if lark-cli isn't configured/authorized."""
    provider = LarkBaseCRMProvider(
        base_token=base_token,
        app_id=app_id,
        app_secret=app_secret,
        auto_create=auto_create,
    )
    if seed_packages:
        try:
            provider.seed_packages()
        except LarkCLIError as exc:
            log.warning("Package seeding skipped: %s", exc)
    return provider