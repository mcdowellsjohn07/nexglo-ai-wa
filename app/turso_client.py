"""HTTP-based Turso / libSQL client with full DB-API compatibility.

Operates over Turso's v2 pipeline HTTP endpoint using `httpx`.
Requires zero native/C/Rust extensions and works seamlessly on both
local Windows development and Heroku Linux containers.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Iterator, Mapping, Optional, Sequence, Union

import httpx

log = logging.getLogger("whatsapp_agent.turso")


class TursoRow(Mapping[str, Any]):
    """A row mapping that supports both dict-key access (`row['id']`) and tuple index (`row[0]`)."""

    __slots__ = ("_data", "_keys", "_values")

    def __init__(self, cols: Sequence[str], values: Sequence[Any]):
        self._keys = list(cols)
        self._values = list(values)
        self._data = dict(zip(self._keys, self._values))

    def __getitem__(self, item: Union[str, int]) -> Any:
        if isinstance(item, int):
            return self._values[item]
        return self._data[item]

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def keys(self) -> list[str]:
        return list(self._keys)

    def values(self) -> list[Any]:
        return list(self._values)

    def items(self) -> list[tuple[str, Any]]:
        return list(self._data.items())

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __repr__(self) -> str:
        return f"TursoRow({self._data})"


class TursoCursor:
    """Cursor returned by `TursoConnection.execute`."""

    def __init__(
        self,
        cols: Sequence[str],
        rows: Sequence[Sequence[Any]],
        rowcount: int = 0,
        lastrowid: Optional[int] = None,
    ):
        self._cols = list(cols)
        self._rows = [TursoRow(self._cols, r) for r in rows]
        self._idx = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> Optional[TursoRow]:
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None

    def fetchall(self) -> list[TursoRow]:
        if self._idx == 0:
            self._idx = len(self._rows)
            return list(self._rows)
        remaining = self._rows[self._idx :]
        self._idx = len(self._rows)
        return remaining

    def __iter__(self) -> Iterator[TursoRow]:
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row


class TursoConnection:
    """Connection executing queries against Turso v2 pipeline."""

    def __init__(self, database_url: str, auth_token: str, timeout: float = 30.0):
        url = database_url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://") :]
        elif url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        elif not url.startswith("https://"):
            url = f"https://{url}"

        self.base_url = url.rstrip("/")
        self.pipeline_url = f"{self.base_url}/v2/pipeline"
        self.auth_token = auth_token.strip()
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.auth_token}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()
        self._client = None

    def __enter__(self) -> "TursoConnection":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    @staticmethod
    def _format_arg(val: Any) -> dict[str, Any]:
        if val is None:
            return {"type": "null"}
        elif isinstance(val, bool):
            return {"type": "integer", "value": "1" if val else "0"}
        elif isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        elif isinstance(val, float):
            return {"type": "float", "value": val}
        elif isinstance(val, bytes):
            import base64
            return {"type": "blob", "base64": base64.b64encode(val).decode("ascii")}
        else:
            return {"type": "text", "value": str(val)}

    @staticmethod
    def _parse_row_val(cell: dict[str, Any]) -> Any:
        cell_type = cell.get("type")
        val = cell.get("value")
        if cell_type == "null" or val is None:
            return None
        elif cell_type == "integer":
            try:
                return int(val)
            except (ValueError, TypeError):
                return val
        elif cell_type == "float":
            try:
                return float(val)
            except (ValueError, TypeError):
                return val
        elif cell_type == "blob":
            import base64
            b64 = cell.get("base64", "")
            return base64.b64decode(b64)
        return val

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> TursoCursor:
        stmt: dict[str, Any] = {"sql": sql}
        if params:
            stmt["args"] = [self._format_arg(p) for p in params]

        payload = {
            "requests": [
                {"type": "execute", "stmt": stmt},
                {"type": "close"},
            ]
        }

        client = self._get_client()
        resp = client.post(self.pipeline_url, json=payload)
        if resp.status_code != 200:
            raise sqlite3.OperationalError(f"Turso HTTP error {resp.status_code}: {resp.text}")

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return TursoCursor([], [])

        first = results[0]
        if first.get("type") == "error":
            err = first.get("error", {})
            msg = err.get("message", "Unknown Turso error")
            code = err.get("code", "")
            if "CONSTRAINT" in code or "UNIQUE" in msg.upper() or "PRIMARY KEY" in msg.upper():
                raise sqlite3.IntegrityError(msg)
            raise sqlite3.OperationalError(f"[{code}] {msg}")

        res_inner = first.get("response", {}).get("result", {})
        cols = [c["name"] for c in res_inner.get("cols", [])]
        raw_rows = res_inner.get("rows", [])
        parsed_rows = [[self._parse_row_val(cell) for cell in row] for row in raw_rows]
        affected = res_inner.get("affected_row_count", 0)
        last_id_raw = res_inner.get("last_insert_rowid")
        last_id = int(last_id_raw) if last_id_raw is not None else None

        return TursoCursor(cols, parsed_rows, rowcount=affected, lastrowid=last_id)

    def executescript(self, script: str) -> None:
        clean = re.sub(r"--[^\n]*", "", script)
        stmts = [s.strip() for s in clean.split(";") if s.strip() and not s.strip().upper().startswith("PRAGMA")]
        if not stmts:
            return

        requests = [{"type": "execute", "stmt": {"sql": s}} for s in stmts]
        requests.append({"type": "close"})

        client = self._get_client()
        resp = client.post(self.pipeline_url, json={"requests": requests})
        if resp.status_code != 200:
            raise sqlite3.OperationalError(f"Turso HTTP error {resp.status_code}: {resp.text}")

        for r in resp.json().get("results", []):
            if r.get("type") == "error":
                err = r.get("error", {})
                msg = err.get("message", "Script error")
                code = err.get("code", "")
                if "CONSTRAINT" in code:
                    raise sqlite3.IntegrityError(msg)
                raise sqlite3.OperationalError(f"[{code}] {msg}")
