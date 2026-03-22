import json
import os
from typing import Any

from astrbot.api import logger


class Storage:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
        self.data_path = os.path.join(self.data_dir, "data.json")

        self.player_data: dict[str, dict[str, Any]] = {}
        self.daily_meta: dict[str, dict[str, Any]] = {}
        self.session_start_cache: dict[str, float] = {}
        # alias -> unified_msg_origin，用于主动推送目标绑定。
        self.push_bindings: dict[str, str] = {}
        # 记录每个定时任务的最近执行状态，避免重启后在同一分钟重复发送。
        self.push_task_state: dict[str, dict[str, Any]] = {}

        self.load_data()

    def load_data(self):
        if not os.path.exists(self.data_path):
            return

        try:
            with open(self.data_path, encoding="utf-8") as file:
                raw_data = json.load(file)

            if "players" in raw_data:
                self.player_data = raw_data.get("players", {})
                self.daily_meta = raw_data.get("daily_meta", {})
                self.push_bindings = raw_data.get("push_bindings", {})
                self.push_task_state = raw_data.get("push_task_state", {})
            else:
                self.player_data = raw_data
                self.daily_meta = {}
                self.push_bindings = {}
                self.push_task_state = {}
        except Exception as exc:
            logger.error(f"[MCDuration] Failed to load storage data: {exc}")

    def save_data(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as file:
                # 统一写回新结构；旧版本数据会在 load_data 时自动兼容。
                payload = {
                    "players": self.player_data,
                    "daily_meta": self.daily_meta,
                    "push_bindings": self.push_bindings,
                    "push_task_state": self.push_task_state,
                }
                json.dump(payload, file, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error(f"[MCDuration] Failed to save storage data: {exc}")

    def update_playtime(self, players: list[str], delta: float, current_time: float):
        for player in players:
            if player not in self.player_data:
                self.player_data[player] = {"total_seconds": 0, "sessions": []}

            self.player_data[player]["total_seconds"] += int(delta)

            if player not in self.session_start_cache:
                self.session_start_cache[player] = current_time

    def handle_disconnects(self, disconnected_players: list[str], current_time: float):
        for player in disconnected_players:
            start_ts = self.session_start_cache.pop(player, None)
            if not start_ts:
                continue

            if player not in self.player_data:
                self.player_data[player] = {"total_seconds": 0, "sessions": []}

            self.player_data[player]["sessions"].append(
                {"start": int(start_ts), "end": int(current_time)}
            )

        self.save_data()

    def get_player(self, name: str) -> dict[str, Any] | None:
        return self.player_data.get(name)

    def get_all_players(self) -> dict[str, dict[str, Any]]:
        return self.player_data

    def get_daily_meta(self, day_key: str) -> dict[str, Any] | None:
        return self.daily_meta.get(day_key)

    def get_session_start(self, name: str) -> float | None:
        return self.session_start_cache.get(name)

    def get_push_bindings(self) -> dict[str, str]:
        return dict(sorted(self.push_bindings.items()))

    def get_push_binding(self, alias: str) -> str | None:
        return self.push_bindings.get(alias)

    def set_push_binding(self, alias: str, session: str) -> str | None:
        previous = self.push_bindings.get(alias)
        self.push_bindings[alias] = session
        self.save_data()
        return previous

    def delete_push_binding(self, alias: str) -> bool:
        if alias not in self.push_bindings:
            return False
        self.push_bindings.pop(alias, None)
        self.save_data()
        return True

    def get_push_task_state(self, task_name: str) -> dict[str, Any]:
        return self.push_task_state.get(task_name, {})

    def update_push_task_state(self, task_name: str, **fields: Any):
        state = self.push_task_state.setdefault(task_name, {})
        state.update(fields)
        self.save_data()
