from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from astrbot.api import logger

from ..models import DEFAULT_SAVE_NAME


class Database:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "mc_duration.db"
        self.legacy_data_path = self.data_dir / "data.json"
        self.lock = threading.RLock()

        self._initialize_schema()
        self._migrate_legacy_data_if_needed()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize_schema(self) -> None:
        with self.lock, self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS saves (
                    save_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS player_totals (
                    save_id TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    total_seconds INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (save_id, player_name),
                    FOREIGN KEY (save_id) REFERENCES saves(save_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    save_id TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    start_ts INTEGER NOT NULL,
                    end_ts INTEGER NOT NULL,
                    FOREIGN KEY (save_id) REFERENCES saves(save_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_save_player
                ON sessions(save_id, player_name, start_ts);

                CREATE TABLE IF NOT EXISTS push_bindings (
                    alias TEXT PRIMARY KEY,
                    session TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS push_task_state (
                    task_name TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _has_existing_data(self, conn: sqlite3.Connection) -> bool:
        queries = (
            "SELECT COUNT(*) FROM player_totals",
            "SELECT COUNT(*) FROM sessions",
            "SELECT COUNT(*) FROM push_bindings",
            "SELECT COUNT(*) FROM push_task_state",
        )
        return any(conn.execute(query).fetchone()[0] > 0 for query in queries)

    def _ensure_default_save(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT save_id FROM saves WHERE is_active = 1").fetchone()
        if row:
            return str(row["save_id"])

        row = conn.execute(
            "SELECT save_id FROM saves ORDER BY datetime(created_at) ASC LIMIT 1"
        ).fetchone()
        if row:
            conn.execute("UPDATE saves SET is_active = 0")
            conn.execute(
                "UPDATE saves SET is_active = 1 WHERE save_id = ?", (row["save_id"],)
            )
            conn.commit()
            return str(row["save_id"])

        save_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO saves (save_id, name, created_at, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (
                save_id,
                DEFAULT_SAVE_NAME,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return save_id

    def _migrate_legacy_data_if_needed(self) -> None:
        if not self.legacy_data_path.exists():
            return

        with self.lock, self.connect() as conn:
            if self._has_existing_data(conn):
                return

            save_id = self._ensure_default_save(conn)

            try:
                with self.legacy_data_path.open(encoding="utf-8") as file:
                    raw_data = json.load(file)
            except Exception as exc:
                logger.error(f"[MCDuration] 加载遗留存储数据失败: {exc}")
                return

            if "players" in raw_data:
                players = raw_data.get("players", {})
                push_bindings = raw_data.get("push_bindings", {})
                push_task_state = raw_data.get("push_task_state", {})
            else:
                players = raw_data
                push_bindings = {}
                push_task_state = {}

            for player_name, player_data in players.items():
                total_seconds = int(player_data.get("total_seconds", 0) or 0)
                conn.execute(
                    """
                    INSERT INTO player_totals (save_id, player_name, total_seconds)
                    VALUES (?, ?, ?)
                    ON CONFLICT(save_id, player_name)
                    DO UPDATE SET total_seconds = excluded.total_seconds
                    """,
                    (save_id, player_name, total_seconds),
                )

                for session in player_data.get("sessions", []):
                    start_ts = int(session.get("start", 0) or 0)
                    end_ts = int(session.get("end", 0) or 0)
                    if start_ts <= 0 or end_ts <= 0 or end_ts <= start_ts:
                        continue
                    conn.execute(
                        """
                        INSERT INTO sessions (save_id, player_name, start_ts, end_ts)
                        VALUES (?, ?, ?, ?)
                        """,
                        (save_id, player_name, start_ts, end_ts),
                    )

            for alias, session in push_bindings.items():
                conn.execute(
                    """
                    INSERT INTO push_bindings (alias, session)
                    VALUES (?, ?)
                    ON CONFLICT(alias) DO UPDATE SET session = excluded.session
                    """,
                    (alias, session),
                )

            for task_name, state in push_task_state.items():
                conn.execute(
                    """
                    INSERT INTO push_task_state (task_name, state_json)
                    VALUES (?, ?)
                    ON CONFLICT(task_name) DO UPDATE SET state_json = excluded.state_json
                    """,
                    (task_name, json.dumps(state, ensure_ascii=False)),
                )

            conn.commit()
            self._backup_legacy_data_file()
            logger.info(
                "[MCDuration] 将遗留JSON数据迁移到SQLite保存存储中."
            )

    def _backup_legacy_data_file(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = self.legacy_data_path.with_name(f"data.json.bak.{timestamp}")
        try:
            shutil.copy2(self.legacy_data_path, backup_path)
        except Exception as exc:
            logger.warning(f"[MCDuration] 备份旧数据data.json失败: {exc}")
