from __future__ import annotations

from typing import Any

from .database import Database


class PlayerRepository:
    def __init__(self, database: Database):
        self.database = database

    def delete_player_data(self, save_id: str, player_name: str) -> bool:
        with self.database.lock, self.database.connect() as conn:
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
            return True

    def add_playtime(self, save_id: str, players: list[str], seconds: int) -> None:
        if not players:
            return

        increment = max(int(seconds), 0)
        with self.database.lock, self.database.connect() as conn:
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
            conn.commit()

    def add_sessions(
        self, save_id: str, session_rows: list[tuple[str, int, int]]
    ) -> None:
        if not session_rows:
            return

        with self.database.lock, self.database.connect() as conn:
            conn.executemany(
                """
                INSERT INTO sessions (save_id, player_name, start_ts, end_ts)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (save_id, player, start_ts, end_ts)
                    for player, start_ts, end_ts in session_rows
                ],
            )
            conn.commit()

    def _load_player_rows(self, save_id: str) -> dict[str, dict[str, Any]]:
        with self.database.lock, self.database.connect() as conn:
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
                players[str(row["player_name"])] = {
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
                    str(row["player_name"]),
                    {"total_seconds": 0, "sessions": []},
                )
                player["sessions"].append(
                    {"start": int(row["start_ts"]), "end": int(row["end_ts"])}
                )

            return players

    def get_all_players(self, save_id: str) -> dict[str, dict[str, Any]]:
        return self._load_player_rows(save_id)

    def get_player(self, name: str, save_id: str) -> dict[str, Any] | None:
        players = self.get_all_players(save_id)
        return players.get(name)
