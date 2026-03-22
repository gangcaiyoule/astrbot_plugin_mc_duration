from __future__ import annotations

import time

from ..models import SaveRecord
from ..storage import Storage
from .tracker_service import TrackerService


class SaveService:
    def __init__(self, storage: Storage, tracker: TrackerService):
        self.storage = storage
        self.tracker = tracker

    async def create_and_switch(self, name: str) -> SaveRecord:
        async with self.tracker.lock:
            save = self.storage.create_save(name.strip(), activate=False)
            return self.tracker.activate_save_locked(save.save_id, time.time())

    async def switch(self, save_id: str) -> SaveRecord:
        async with self.tracker.lock:
            return self.tracker.activate_save_locked(save_id, time.time())

    async def delete_save(self, save_id: str) -> SaveRecord:
        async with self.tracker.lock:
            save = self.storage.resolve_save(save_id)
            if not save:
                raise LookupError("存档不存在。")

            all_saves = self.storage.list_saves()
            if save.is_active:
                if len(all_saves) <= 1:
                    raise ValueError("当前只剩一个存档，无法删除。")
                replacement = next(
                    item for item in all_saves if item.save_id != save.save_id
                )
                self.tracker.activate_save_locked(replacement.save_id, time.time())

            self.storage.delete_save(save.save_id)
            return save

    async def delete_player_data(
        self, save_id: str, player_name: str
    ) -> tuple[SaveRecord, bool]:
        async with self.tracker.lock:
            save = self.storage.resolve_save(save_id)
            if not save:
                raise LookupError("存档不存在。")

            deleted = self.storage.delete_player_data(save.save_id, player_name)
            if save.is_active:
                self.tracker.remove_tracked_player(player_name)
                self.tracker.last_check_time = time.time()
            return save, deleted
