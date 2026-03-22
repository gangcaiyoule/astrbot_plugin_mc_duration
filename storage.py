from __future__ import annotations

from .models import SaveRecord
from .repositories import Database, PlayerRepository, PushRepository, SaveRepository


class Storage:
    def __init__(self, data_dir: str):
        self.database = Database(data_dir)
        self.saves = SaveRepository(self.database)
        self.players = PlayerRepository(self.database)
        self.push = PushRepository(self.database)
        self.saves.ensure_active_save()

    def save_data(self) -> None:
        # Kept for backward compatibility with the old JSON storage interface.
        return

    def get_active_save(self) -> SaveRecord:
        return self.saves.get_active_save()

    def get_active_save_id(self) -> str:
        return self.saves.get_active_save_id()

    def list_saves(self) -> list[SaveRecord]:
        return self.saves.list_saves()

    def resolve_save(self, identifier: str) -> SaveRecord | None:
        return self.saves.resolve_save(identifier)

    def create_save(self, name: str, *, activate: bool = False) -> SaveRecord:
        return self.saves.create_save(name, activate=activate)

    def set_active_save(self, save_id: str) -> SaveRecord:
        return self.saves.set_active_save(save_id)

    def delete_save(self, save_id: str) -> None:
        self.saves.delete_save(save_id)

    def delete_player_data(self, save_id: str, player_name: str) -> bool:
        return self.players.delete_player_data(save_id, player_name)

    def get_all_players(self, save_id: str | None = None):
        return self.players.get_all_players(save_id or self.get_active_save_id())

    def get_player(self, name: str, save_id: str | None = None):
        return self.players.get_player(name, save_id or self.get_active_save_id())

    def get_push_bindings(self) -> dict[str, str]:
        return self.push.get_push_bindings()

    def get_push_binding(self, alias: str) -> str | None:
        return self.push.get_push_binding(alias)

    def set_push_binding(self, alias: str, session: str) -> str | None:
        return self.push.set_push_binding(alias, session)

    def delete_push_binding(self, alias: str) -> bool:
        return self.push.delete_push_binding(alias)

    def get_push_task_state(self, task_name: str):
        return self.push.get_push_task_state(task_name)

    def update_push_task_state(self, task_name: str, **fields):
        self.push.update_push_task_state(task_name, **fields)
