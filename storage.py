import json
import os
import datetime
import time
from typing import Dict, Iterable, List, Optional
from astrbot.api import logger


class Storage:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
        self.data_path = os.path.join(self.data_dir, "data.json")

        self.player_data: Dict[str, Dict] = {}
        self.daily_meta: Dict[str, Dict] = {}
        self.session_start_cache: Dict[str, float] = {}

        self.load_data()

    def load_data(self):
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    if "players" in raw_data:
                        self.player_data = raw_data["players"]
                        self.daily_meta = raw_data.get("daily_meta", {})
                    else:
                        self.player_data = raw_data
                        self.daily_meta = {}
            except Exception as e:
                logger.error(f"MC状态获取失败: {e}")

    def save_data(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                payload = {"players": self.player_data, "daily_meta": self.daily_meta}
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"MC统计数据保存失败: {e}")

    def update_playtime(self, players: List[str], delta: float, current_time: float):
        # 记录新玩家上线
        # 注意: daily_meta 已废弃，改为实时计算
        for p in players:
            if p not in self.player_data:
                self.player_data[p] = {"total_seconds": 0, "sessions": []}

            self.player_data[p]["total_seconds"] += int(delta)

            # 缓存session开始时间
            if p not in self.session_start_cache:
                self.session_start_cache[p] = current_time

    def handle_disconnects(self, disconnected_players: List[str], current_time: float):
        for p in disconnected_players:
            start_ts = self.session_start_cache.pop(p, None)
            if start_ts:
                # 记录 Session
                if p not in self.player_data:
                    self.player_data[p] = {"total_seconds": 0, "sessions": []}

                self.player_data[p]["sessions"].append(
                    {"start": int(start_ts), "end": int(current_time)}
                )

        self.save_data()

    def purge_players(self, players: Iterable[str]) -> int:
        """删除指定玩家的全部统计数据，并移除其在线缓存。"""
        targets = set()
        for player in players:
            if player is None:
                continue
            name = str(player).strip()
            if name:
                targets.add(name)

        if not targets:
            return 0

        removed_count = 0
        changed = False

        for name in targets:
            removed = False
            if name in self.player_data:
                self.player_data.pop(name, None)
                removed = True
                changed = True
            if name in self.session_start_cache:
                self.session_start_cache.pop(name, None)
                removed = True
                changed = True
            if removed:
                removed_count += 1

        if changed:
            self.save_data()

        return removed_count

    def get_player(self, name: str) -> Optional[Dict]:
        return self.player_data.get(name)

    def get_all_players(self) -> Dict[str, Dict]:
        return self.player_data

    def get_daily_meta(self, day_key: str) -> Optional[Dict]:
        return self.daily_meta.get(day_key)

    def get_session_start(self, name: str) -> Optional[float]:
        return self.session_start_cache.get(name)
