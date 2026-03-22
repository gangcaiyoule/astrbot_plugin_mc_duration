from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from ..models import DEFAULT_SAVE_NAME, SaveRecord
from .database import Database


class SaveRepository:
    def __init__(self, database: Database):
        self.database = database

    def _row_to_save(
        self,
        row: sqlite3.Row,
        conn: sqlite3.Connection,
        *,
        is_active: bool | None = None,
    ) -> SaveRecord:
        save_id = str(row["save_id"])
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
            name=str(row["name"]),
            created_at=str(row["created_at"]),
            is_active=bool(row["is_active"] if is_active is None else is_active),
            player_count=player_count,
            session_count=session_count,
        )

    def _ensure_default_save(self, conn: sqlite3.Connection) -> SaveRecord:
        row = conn.execute(
            "SELECT save_id, name, created_at, is_active FROM saves WHERE is_active = 1"
        ).fetchone()
        if row:
            return self._row_to_save(row, conn)

        row = conn.execute(
            "SELECT save_id, name, created_at, is_active FROM saves ORDER BY datetime(created_at) ASC LIMIT 1"
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

    def ensure_active_save(self) -> None:
        with self.database.lock, self.database.connect() as conn:
            self._ensure_default_save(conn)

    def get_active_save(self) -> SaveRecord:
        with self.database.lock, self.database.connect() as conn:
            return self._ensure_default_save(conn)

    def get_active_save_id(self) -> str:
        return self.get_active_save().save_id

    def list_saves(self) -> list[SaveRecord]:
        with self.database.lock, self.database.connect() as conn:
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

        with self.database.lock, self.database.connect() as conn:
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

        with self.database.lock, self.database.connect() as conn:
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
        with self.database.lock, self.database.connect() as conn:
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
        with self.database.lock, self.database.connect() as conn:
            conn.execute("DELETE FROM saves WHERE save_id = ?", (save_id,))
            conn.commit()
