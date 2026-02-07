import json
import os
import datetime
import time
from typing import Dict, List, Optional
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
                with open(self.data_path, 'r', encoding='utf-8') as f:
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
            with open(self.data_path, 'w', encoding='utf-8') as f:
                payload = {
                    "players": self.player_data,
                    "daily_meta": self.daily_meta
                }
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"MC统计数据保存失败: {e}")

    def update_playtime(self, players: List[str], delta: float, current_time: float):
        day_key = datetime.datetime.now().strftime("%Y-%m-%d")
        if day_key not in self.daily_meta:
            self.daily_meta[day_key] = {"first_join": None, "last_leave": None}

        # 记录新玩家上线
        for p in players:
            if p not in self.player_data:
                self.player_data[p] = {"total_seconds": 0, "sessions": []}
            
            self.player_data[p]["total_seconds"] += int(delta)

            # 缓存session开始时间
            if p not in self.session_start_cache:
                self.session_start_cache[p] = current_time
                # 记录每日首次上线
                if not self.daily_meta[day_key]["first_join"]:
                    self.daily_meta[day_key]["first_join"] = {"player": p, "time": current_time}

    def handle_disconnects(self, disconnected_players: List[str], current_time: float):
        day_key = datetime.datetime.now().strftime("%Y-%m-%d")
        
        for p in disconnected_players:
            start_ts = self.session_start_cache.pop(p, None)
            if start_ts:
                # 记录 Session
                if p not in self.player_data:
                     self.player_data[p] = {"total_seconds": 0, "sessions": []}
                     
                self.player_data[p]["sessions"].append({"start": int(start_ts), "end": int(current_time)})
                
                # 记录每日最后离开
                if day_key not in self.daily_meta:
                     self.daily_meta[day_key] = {"first_join": None, "last_leave": None}
                     
                self.daily_meta[day_key]["last_leave"] = {"player": p, "time": current_time}
        
        self.save_data()

    def get_player(self, name: str) -> Optional[Dict]:
        return self.player_data.get(name)

    def get_all_players(self) -> Dict[str, Dict]:
        return self.player_data

    def get_daily_meta(self, day_key: str) -> Optional[Dict]:
        return self.daily_meta.get(day_key)

    def get_session_start(self, name: str) -> Optional[float]:
        return self.session_start_cache.get(name)
