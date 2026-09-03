"""SQLite 存储：订单持久化。零第三方依赖。
线程安全：check_same_thread=False + RLock，供 Web 服务(多线程HTTP)与消息回调共用。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .models import STATUS_PENDING, Order


def _row_to_order(row: sqlite3.Row) -> Order:
    return Order(
        id=row["id"],
        source_group=row["source_group"] or "",
        source_group_name=row["source_group_name"] or "",
        source_sender=row["source_sender"] or "",
        source_sender_name=row["source_sender_name"] or "",
        raw=row["raw"] or "",
        otype=row["otype"],
        pages=row["pages"],
        amount=row["amount"],
        note=row["note"] or "",
        status=row["status"] or STATUS_PENDING,
        designer=row["designer"],
        designer_name=row["designer_name"],
        claim_mode=row["claim_mode"],
        claim_sent_at=row["claim_sent_at"],
        claim_deadline=row["claim_deadline"],
        queue_pos=row["queue_pos"] or 0,
        result_reason=row["result_reason"] or "",
        created_at=row["created_at"] or 0.0,
        updated_at=row["updated_at"] or 0.0,
    )


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_group TEXT,
                source_group_name TEXT,
                source_sender TEXT,
                source_sender_name TEXT,
                raw TEXT,
                otype TEXT,
                pages INTEGER,
                amount REAL,
                note TEXT,
                status TEXT,
                designer TEXT,
                designer_name TEXT,
                claim_mode TEXT,
                claim_sent_at REAL,
                claim_deadline REAL,
                queue_pos INTEGER DEFAULT 0,
                result_reason TEXT,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        self._conn.commit()

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM orders")
            self._conn.execute("DELETE FROM sqlite_sequence WHERE name='orders'")
            self._conn.commit()

    def add_order(self, o: Order) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO orders (source_group, source_group_name, source_sender, source_sender_name,
                    raw, otype, pages, amount, note, status, designer, designer_name, claim_mode,
                    claim_sent_at, claim_deadline, queue_pos, result_reason, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    o.source_group, o.source_group_name, o.source_sender, o.source_sender_name,
                    o.raw, o.otype, o.pages, o.amount, o.note, o.status, o.designer,
                    o.designer_name, o.claim_mode, o.claim_sent_at, o.claim_deadline,
                    o.queue_pos, o.result_reason, o.created_at or now, now,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get(self, order_id: int) -> Optional[Order]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            return _row_to_order(row) if row else None

    def list_all(self) -> list[Order]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM orders ORDER BY id").fetchall()
            return [_row_to_order(r) for r in rows]

    def list_by_status(self, status: str | tuple[str, ...]) -> list[Order]:
        if isinstance(status, str):
            status = (status,)
        marks = ",".join("?" * len(status))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM orders WHERE status IN ({marks}) ORDER BY id", status
            ).fetchall()
            return [_row_to_order(r) for r in rows]

    def update(self, order_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields = dict(fields)
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [order_id]
        with self._lock:
            self._conn.execute(f"UPDATE orders SET {cols} WHERE id=?", vals)
            self._conn.commit()

    def recent_raw(self, group: str, minutes: float) -> list[str]:
        since = time.time() - minutes * 60
        with self._lock:
            rows = self._conn.execute(
                "SELECT raw FROM orders WHERE source_group=? AND created_at>=? ORDER BY id",
                (group, since),
            ).fetchall()
            return [r["raw"] or "" for r in rows]
