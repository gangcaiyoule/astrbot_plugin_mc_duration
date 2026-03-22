from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger

DEFAULT_SAVE_NAME = "默认存档"


@dataclass(slots=True)
class SaveRecord:
    save_id: str
    name: str
    created_at: str
    is_active: bool
    player_count: int = 0
    session_count: int = 0


class Storage:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "mc_duration.db"
        self.legacy_data_path = self.data_dir / "data.json"

        self.session_start_cache: dict[str, float] = {}
        self._lock = threading.RLock()

        self._initialize_database()
        self._migrate_legacy_data_if_needed()
        self._ensure_active_save()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize_database(self) -> None:
        with self._lock, self._connect() as conn:
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

    def _migrate_legacy_data_if_needed(self) -> None:
        if not self.legacy_data_path.exists():
            return

        with self._lock, self._connect() as conn:
            if self._has_existing_data(conn):
                return

            save_id = self._ensure_default_save(conn).save_id

            try:
                with self.legacy_data_path.open(encoding="utf-8") as file:
                    raw_data = json.load(file)
            except Exception as exc:
                logger.error(f"[MCDuration] Failed to load legacy storage data: {exc}")
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
                "[MCDuration] Migrated legacy JSON data into SQLite save storage."
            )

    def _backup_legacy_data_file(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = self.legacy_data_path.with_name(f"data.json.bak.{timestamp}")
        try:
            shutil.copy2(self.legacy_data_path, backup_path)
        except Exception as exc:
            logger.warning(f"[MCDuration] Failed to backup legacy data.json: {exc}")

    def _ensure_default_save(self, conn: sqlite3.Connection) -> SaveRecord:
        row = conn.execute(
            "SELECT save_id, name, created_at, is_active FROM saves WHERE is_active = 1"
        ).fetchone()
        if row:
            return self._row_to_save(row, conn)

        row = conn.execute(
            "SELECT save_id, name, created_at, is_active FROM saves ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row:
            conn.execute("UPDATE saves SET is_active = 0")
            conn.execute(
                "UPDATE saves SET is_active = 1 WHERE save_id = ?", (row["save_id"],)
            )
            conn.commit()
            return self._row_to_save(row, conn, is_active=True)

        save = SaveRecord(
            save_id=str(uuid.uuid4()),
            name=DEFAULT_SAVE_NAME,
            created_at=datetime.now().isoformat(timespec="seconds"),
            is_active=True,
        )
        conn.execute(
            """
            INSERT INTO saves (save_id, name, created_at, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (save.save_id, save.name, save.created_at),
        )
        conn.commit()
        return save

    def _ensure_active_save(self) -> None:
        with self._lock, self._connect() as conn:
            self._ensure_default_save(conn)

    def _row_to_save(
        self,
        row: sqlite3.Row,
        conn: sqlite3.Connection,
        *,
        is_active: bool | None = None,
    ) -> SaveRecord:
        save_id = row["save_id"]
        player_count = conn.execute(
            "SELECT COUNT(*) FROM player_totals WHERE save_id = ?",
            (save_id,),
        ).fetchone()[0]
        session_count = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE save_id = ?",
            (save_id,),
        ).fetchone()[0]
        return SaveRecord(
            save_id=save_id,
            name=row["name"],
            created_at=row["created_at"],
            is_active=bool(row["is_active"] if is_active is None else is_active),
            player_count=player_count,
            session_count=session_count,
        )

    def save_data(self) -> None:
        # Kept for backward compatibility with the old JSON storage interface.
        return

    def get_active_save(self) -> SaveRecord:
        with self._lock, self._connect() as conn:
            return self._ensure_default_save(conn)

    def get_active_save_id(self) -> str:
        return self.get_active_save().save_id

    def list_saves(self) -> list[SaveRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT save_id, name, created_at, is_active
                FROM saves
                ORDER BY datetime(created_at) ASC, name ASC
                """
            ).fetchall()
            return [self._row_to_save(row, conn) for row in rows]

    def resolve_save(self, identifier: str) -> SaveRecord | None:
        value = identifier.strip()
        if not value:
            return None

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT save_id, name, created_at, is_active
                FROM saves
                WHERE save_id = ? OR lower(name) = lower(?)
                ORDER BY CASE WHEN save_id = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (value, value, value),
            ).fetchone()
            if not row:
                return None
            return self._row_to_save(row, conn)

    def create_save(self, name: str, *, activate: bool = False) -> SaveRecord:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("存档名称不能为空。")

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM saves WHERE lower(name) = lower(?)",
                (normalized_name,),
            ).fetchone()
            if existing:
                raise ValueError(f"存档 {normalized_name} 已存在。")

            if activate:
                conn.execute("UPDATE saves SET is_active = 0")

            save = SaveRecord(
                save_id=str(uuid.uuid4()),
                name=normalized_name,
                created_at=datetime.now().isoformat(timespec="seconds"),
                is_active=activate,
            )
            conn.execute(
                """
                INSERT INTO saves (save_id, name, created_at, is_active)
                VALUES (?, ?, ?, ?)
                """,
                (save.save_id, save.name, save.created_at, int(activate)),
            )
            conn.commit()
            return save

    def set_active_save(self, save_id: str) -> SaveRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT save_id, name, created_at, is_active FROM saves WHERE save_id = ?",
                (save_id,),
            ).fetchone()
            if not row:
                raise ValueError("目标存档不存在。")

            conn.execute("UPDATE saves SET is_active = 0")
            conn.execute("UPDATE saves SET is_active = 1 WHERE save_id = ?", (save_id,))
            conn.commit()
            return self._row_to_save(row, conn, is_active=True)

    def delete_save(self, save_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM saves WHERE save_id = ?", (save_id,))
            conn.commit()

    def delete_player_data(self, save_id: str, player_name: str) -> bool:
        with self._lock, self._connect() as conn:
            existed = conn.execute(
                """
                SELECT 1 FROM player_totals WHERE save_id = ? AND player_name = ?
                UNION
                SELECT 1 FROM sessions WHERE save_id = ? AND player_name = ?
                LIMIT 1
                """,
                (save_id, player_name, save_id, player_name),
            ).fetchone()
            if not existed:
                return False

            conn.execute(
                "DELETE FROM player_totals WHERE save_id = ? AND player_name = ?",
                (save_id, player_name),
            )
            conn.execute(
                "DELETE FROM sessions WHERE save_id = ? AND player_name = ?",
                (save_id, player_name),
            )
            conn.commit()

            active_save = self.get_active_save()
            if active_save.save_id == save_id:
                self.session_start_cache.pop(player_name, None)
            return True

    def get_online_players(self) -> list[str]:
        return list(self.session_start_cache.keys())

    def start_session_for_players(
        self, players: list[str], current_time: float
    ) -> None:
        for player in players:
            self.session_start_cache[player] = current_time

    def get_session_start(self, name: str) -> float | None:
        return self.session_start_cache.get(name)

    def update_playtime(
        self, players: list[str], delta: float, current_time: float
    ) -> None:
        if not players:
            return

        increment = max(int(delta), 0)
        save_id = self.get_active_save_id()

        with self._lock, self._connect() as conn:
            for player in players:
                conn.execute(
                    """
                    INSERT INTO player_totals (save_id, player_name, total_seconds)
                    VALUES (?, ?, ?)
                    ON CONFLICT(save_id, player_name)
                    DO UPDATE SET total_seconds = total_seconds + excluded.total_seconds
                    """,
                    (save_id, player, increment),
                )
                if player not in self.session_start_cache:
                    self.session_start_cache[player] = current_time
            conn.commit()

    def handle_disconnects(
        self, disconnected_players: list[str], current_time: float
    ) -> None:
        if not disconnected_players:
            return

        save_id = self.get_active_save_id()
        with self._lock, self._connect() as conn:
            for player in disconnected_players:
                start_ts = self.session_start_cache.pop(player, None)
                if start_ts is None:
                    continue
                if current_time <= start_ts:
                    continue
                conn.execute(
                    """
                    INSERT INTO sessions (save_id, player_name, start_ts, end_ts)
                    VALUES (?, ?, ?, ?)
                    """,
                    (save_id, player, int(start_ts), int(current_time)),
                )
            conn.commit()

    def _load_player_rows(self, save_id: str) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as conn:
            players: dict[str, dict[str, Any]] = {}

            for row in conn.execute(
                """
                SELECT player_name, total_seconds
                FROM player_totals
                WHERE save_id = ?
                ORDER BY total_seconds DESC, player_name ASC
                """,
                (save_id,),
            ):
                players[row["player_name"]] = {
                    "total_seconds": int(row["total_seconds"]),
                    "sessions": [],
                }

            for row in conn.execute(
                """
                SELECT player_name, start_ts, end_ts
                FROM sessions
                WHERE save_id = ?
                ORDER BY start_ts ASC
                """,
                (save_id,),
            ):
                player = players.setdefault(
                    row["player_name"],
                    {"total_seconds": 0, "sessions": []},
                )
                player["sessions"].append(
                    {"start": int(row["start_ts"]), "end": int(row["end_ts"])}
                )

            return players

    def get_all_players(self, save_id: str | None = None) -> dict[str, dict[str, Any]]:
        target_save_id = save_id or self.get_active_save_id()
        return self._load_player_rows(target_save_id)

    def get_player(
        self, name: str, save_id: str | None = None
    ) -> dict[str, Any] | None:
        players = self.get_all_players(save_id)
        return players.get(name)

    def get_push_bindings(self) -> dict[str, str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT alias, session FROM push_bindings ORDER BY alias ASC"
            ).fetchall()
            return {row["alias"]: row["session"] for row in rows}

    def get_push_binding(self, alias: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session FROM push_bindings WHERE alias = ?",
                (alias,),
            ).fetchone()
            if not row:
                return None
            return str(row["session"])

    def set_push_binding(self, alias: str, session: str) -> str | None:
        previous = self.get_push_binding(alias)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO push_bindings (alias, session)
                VALUES (?, ?)
                ON CONFLICT(alias) DO UPDATE SET session = excluded.session
                """,
                (alias, session),
            )
            conn.commit()
        return previous

    def delete_push_binding(self, alias: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM push_bindings WHERE alias = ?", (alias,))
            conn.commit()
            return cursor.rowcount > 0

    def get_push_task_state(self, task_name: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM push_task_state WHERE task_name = ?",
                (task_name,),
            ).fetchone()
            if not row:
                return {}
            try:
                return json.loads(row["state_json"])
            except json.JSONDecodeError:
                return {}

    def update_push_task_state(self, task_name: str, **fields: Any) -> None:
        state = self.get_push_task_state(task_name)
        state.update(fields)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO push_task_state (task_name, state_json)
                VALUES (?, ?)
                ON CONFLICT(task_name) DO UPDATE SET state_json = excluded.state_json
                """,
                (task_name, json.dumps(state, ensure_ascii=False)),
            )
            conn.commit()
