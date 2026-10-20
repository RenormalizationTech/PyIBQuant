"""Transactional local event journal. Contains private account data; never commit it."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


class Journal:
    def __init__(self, path: str | Path, *, readonly: bool = False) -> None:
        self.path = Path(path)
        self.readonly = readonly
        self.lock = RLock()
        if readonly:
            self.db = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False
            )
            if self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
                self.db.close()
                raise ValueError("Unsupported trading journal version")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError(f"Unsupported trading journal version {version}")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session TEXT NOT NULL, account TEXT NOT NULL, "
            "received_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS account_events ON events(account, sequence)")
        self.db.execute("PRAGMA user_version=1")
        self.db.commit()
        self.path.chmod(0o600)

    def append(
        self, session: str, account: str, stamp: str, kind: str, payload: dict[str, Any]
    ) -> int:
        if self.readonly:
            raise ValueError("Journal is read-only")
        encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        with self.lock, self.db:
            cursor = self.db.execute(
                "INSERT INTO events(session,account,received_at,kind,payload) VALUES(?,?,?,?,?)",
                (session, account, stamp, kind, encoded),
            )
            return int(cursor.lastrowid or 0)

    def events(self, account: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            query = "SELECT sequence,session,account,received_at,kind,payload FROM events"
            rows = self.db.execute(
                query + (" WHERE account=?" if account else "") + " ORDER BY sequence",
                (account,) if account else (),
            ).fetchall()
        return [
            dict(
                sequence=r[0],
                session=r[1],
                account=r[2],
                received_at=r[3],
                kind=r[4],
                payload=json.loads(r[5]),
            )
            for r in rows
        ]

    def close(self) -> None:
        with self.lock:
            self.db.close()
