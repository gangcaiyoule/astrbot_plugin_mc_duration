from __future__ import annotations

import json
from typing import Any

from .database import Database


class PushRepository:
    def __init__(self, database: Database):
        self.database = database

    def get_push_bindings(self) -> dict[str, str]:
        with self.database.lock, self.database.connect() as conn:
            rows = conn.execute(
                "SELECT alias, session FROM push_bindings ORDER BY alias ASC"
            ).fetchall()
            return {str(row["alias"]): str(row["session"]) for row in rows}

    def get_push_binding(self, alias: str) -> str | None:
        with self.database.lock, self.database.connect() as conn:
            row = conn.execute(
                "SELECT session FROM push_bindings WHERE alias = ?",
                (alias,),
            ).fetchone()
            if not row:
                return None
            return str(row["session"])

    def set_push_binding(self, alias: str, session: str) -> str | None:
        previous = self.get_push_binding(alias)
        with self.database.lock, self.database.connect() as conn:
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
        with self.database.lock, self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM push_bindings WHERE alias = ?", (alias,))
            conn.commit()
            return cursor.rowcount > 0

    def get_push_task_state(self, task_name: str) -> dict[str, Any]:
        with self.database.lock, self.database.connect() as conn:
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
        with self.database.lock, self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO push_task_state (task_name, state_json)
                VALUES (?, ?)
                ON CONFLICT(task_name) DO UPDATE SET state_json = excluded.state_json
                """,
                (task_name, json.dumps(state, ensure_ascii=False)),
            )
            conn.commit()
