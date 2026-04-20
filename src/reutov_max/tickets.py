from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiosqlite

log = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_name TEXT,
    chat_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    category TEXT,
    original_text TEXT,
    transcript TEXT,
    photo_url TEXT,
    ai_summary TEXT,
    address TEXT,
    lat REAL,
    lon REAL,
    geo_source TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    operator_message_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
"""


@dataclass
class Ticket:
    id: int
    user_id: int
    user_name: str | None
    chat_id: int
    created_at: str
    kind: str
    category: str | None
    original_text: str | None
    transcript: str | None
    photo_url: str | None
    ai_summary: str | None
    address: str | None
    lat: float | None
    lon: float | None
    geo_source: str | None
    status: str
    operator_message_id: str | None


class TicketRepo:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def create(self, **fields: Any) -> Ticket:
        fields.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        fields.setdefault("status", "new")
        cols = ",".join(fields.keys())
        ph = ",".join("?" * len(fields))
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                f"INSERT INTO tickets ({cols}) VALUES ({ph})", tuple(fields.values())
            )
            await db.commit()
            ticket_id = cursor.lastrowid
        return await self.get(ticket_id)  # type: ignore[arg-type,return-value]

    async def get(self, ticket_id: int) -> Ticket | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)) as cur:
                row = await cur.fetchone()
        return Ticket(**dict(row)) if row else None

    async def update(self, ticket_id: int, **fields: Any) -> None:
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE tickets SET {sets} WHERE id=?", (*fields.values(), ticket_id)
            )
            await db.commit()

    async def latest_awaiting_location(self, user_id: int) -> Ticket | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tickets WHERE user_id=? AND status='awaiting_location' "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
        return Ticket(**dict(row)) if row else None
