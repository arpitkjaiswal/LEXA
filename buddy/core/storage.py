"""Local, bounded SQLite records. Audio is never stored; chat retention is opt-in."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from buddy.core.config import Config
from buddy.core.errors import BuddyError, ConfigurationError


class Store:
    def __init__(self, config: Config) -> None:
        self.config = config.memory
        self._lock = threading.RLock()
        try:
            config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = config.data_dir / "buddy.sqlite3"
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(path, 0o600)
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.executescript("""
                PRAGMA journal_mode=DELETE;
                PRAGMA secure_delete=ON;
                PRAGMA busy_timeout=3000;
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1');
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    body TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY, user TEXT NOT NULL, assistant TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, due REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending');
            """)
            if (
                self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[
                    0
                ]
                != "1"
            ):
                self.db.close()
                raise ConfigurationError(
                    "Unsupported memory database version; back it up before upgrading."
                )
        except (OSError, sqlite3.Error):
            raise ConfigurationError(
                "Cannot open BUDDY's local database. Check BUDDY_DATA_DIR."
            ) from None

    def execute(self, sql: str, args: tuple = ()) -> list[dict]:
        try:
            with self._lock, self.db:
                cursor = self.db.execute(sql, args)
                return [dict(row) for row in cursor.fetchall()] if cursor.description else []
        except sqlite3.Error:
            raise BuddyError(
                "The local database operation failed. Check available disk space."
            ) from None

    def facts(self) -> list[dict]:
        if not self.config.enabled:
            return []
        return self.execute("SELECT key, value FROM facts ORDER BY updated DESC LIMIT 100")

    def remember(self, key: str, value: str) -> None:
        if not self.config.enabled:
            raise BuddyError("Saved memory is disabled in settings.")
        if len(self.facts()) >= 100 and not self.execute(
            "SELECT key FROM facts WHERE key=?", (key,)
        ):
            raise BuddyError("Memory is full (100 facts). Forget a fact first.")
        self.execute(
            "INSERT INTO facts VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
            "value=excluded.value, updated=excluded.updated",
            (key, value, datetime.now(UTC).isoformat()),
        )

    def context(self) -> str:
        # Delimit as untrusted data, not additional system instructions.
        return json.dumps(self.facts(), ensure_ascii=False)[:12_000]

    def save_turn(self, user: str, assistant: str) -> None:
        if self.config.enabled and self.config.save_history:
            self.execute("INSERT INTO turns(user, assistant) VALUES (?, ?)", (user, assistant))
            self.execute(
                "DELETE FROM turns WHERE id NOT IN (SELECT id FROM turns ORDER BY id DESC LIMIT ?)",
                (self.config.history_turns,),
            )

    def history(self, limit: int = 10) -> list[dict[str, str]]:
        if not self.config.enabled or not self.config.save_history:
            return []
        rows = self.execute("SELECT user, assistant FROM turns ORDER BY id DESC LIMIT ?", (limit,))
        return [
            message
            for row in reversed(rows)
            for message in (
                {"role": "user", "content": row["user"]},
                {"role": "assistant", "content": row["assistant"]},
            )
        ]

    def add_note(self, title: str, body: str) -> str:
        if self.execute("SELECT COUNT(*) AS n FROM notes")[0]["n"] >= 500:
            raise BuddyError("Notes are full (500). Delete a note first.")
        identifier = uuid.uuid4().hex[:12]
        self.execute(
            "INSERT INTO notes VALUES (?, ?, ?, ?)",
            (identifier, title, body, datetime.now(UTC).isoformat()),
        )
        return identifier

    def add_reminder(self, label: str, due: float) -> str:
        if (
            self.execute("SELECT COUNT(*) AS n FROM reminders WHERE status='pending'")[0]["n"]
            >= 100
        ):
            raise BuddyError("There are already 100 pending reminders. Cancel one first.")
        identifier = uuid.uuid4().hex[:12]
        self.execute(
            "INSERT INTO reminders(id, label, due) VALUES (?, ?, ?)", (identifier, label, due)
        )
        self.execute(
            "DELETE FROM reminders WHERE status != 'pending' AND due < ?", (due - 2592000,)
        )
        return identifier

    def due(self, now: float) -> list[dict]:
        return self.execute(
            "SELECT id, label, due FROM reminders "
            "WHERE status='pending' AND due<=? ORDER BY due LIMIT 100",
            (now,),
        )

    def acknowledge(self, identifier: str) -> None:
        self.execute(
            "UPDATE reminders SET status='delivered' WHERE id=? AND status='pending'", (identifier,)
        )

    def close(self) -> None:
        with self._lock:
            self.db.close()
