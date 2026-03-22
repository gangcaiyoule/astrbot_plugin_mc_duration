from __future__ import annotations

import asyncio
import time

from astrbot.api import logger

from ..rcon import MCRcon
from ..storage import Storage


class TrackerService:
    def __init__(
        self,
        storage: Storage,
        rcon: MCRcon,
        interval: int,
        player_blacklist: set[str],
    ):
        self.storage = storage
        self.rcon = rcon
        self.interval = interval
        self.player_blacklist = player_blacklist

        self.session_start_cache: dict[str, float] = {}
        self.tracking_task: asyncio.Task | None = None
        self.last_check_time = 0.0
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def is_running(self) -> bool:
        return bool(self.tracking_task and not self.tracking_task.done())

    def _is_blacklisted(self, player_name: str | None) -> bool:
        return bool(player_name and player_name in self.player_blacklist)

    def filter_tracked_players(self, players: list[str]) -> list[str]:
        return [player for player in players if not self._is_blacklisted(player)]

    def get_online_players(self) -> list[str]:
        return list(self.session_start_cache.keys())

    def get_session_start(self, name: str) -> float | None:
        return self.session_start_cache.get(name)

    def remove_tracked_player(self, player_name: str) -> None:
        self.session_start_cache.pop(player_name, None)

    def start_session_for_players(
        self, players: list[str], current_time: float
    ) -> None:
        for player in players:
            self.session_start_cache[player] = current_time

    def _update_playtime(
        self, players: list[str], delta: float, current_time: float
    ) -> None:
        if not players:
            return

        increment = max(int(delta), 0)
        if increment > 0:
            self.storage.players.add_playtime(
                self.storage.get_active_save_id(),
                players,
                increment,
            )
        for player in players:
            self.session_start_cache.setdefault(player, current_time)

    def _handle_disconnects(
        self, disconnected_players: list[str], current_time: float
    ) -> None:
        if not disconnected_players:
            return

        session_rows: list[tuple[str, int, int]] = []
        for player in disconnected_players:
            start_ts = self.session_start_cache.pop(player, None)
            if start_ts is None or current_time <= start_ts:
                continue
            session_rows.append((player, int(start_ts), int(current_time)))

        if session_rows:
            self.storage.players.add_sessions(
                self.storage.get_active_save_id(),
                session_rows,
            )

    def activate_save_locked(self, save_id: str, switch_time: float):
        current = self.storage.get_active_save()
        if current.save_id == save_id:
            return current

        online_players = self.get_online_players()
        if online_players:
            self._handle_disconnects(online_players, switch_time)

        new_save = self.storage.set_active_save(save_id)
        resumed = [
            player for player in online_players if not self._is_blacklisted(player)
        ]
        if resumed:
            self.start_session_for_players(resumed, switch_time)
        self.last_check_time = switch_time
        return new_save

    def start(self) -> None:
        if self.is_running():
            return
        logger.info("[MCDuration] Monitor started for server %s", self.rcon.host)
        self.tracking_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        task = self.tracking_task
        if not task:
            return

        task.cancel()
        self.tracking_task = None
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _monitor_loop(self) -> None:
        self.last_check_time = time.time()
        while True:
            try:
                curr_time = time.time()
                delta = min(curr_time - self.last_check_time, self.interval * 2)
                self.last_check_time = curr_time
                players = await self.rcon.fetch_players()

                async with self._lock:
                    if players is not None:
                        tracked_players = self.filter_tracked_players(players)
                        self._update_playtime(tracked_players, delta, curr_time)
                        left_players = [
                            player
                            for player in self.get_online_players()
                            if player not in tracked_players
                        ]
                        if left_players:
                            self._handle_disconnects(left_players, curr_time)
                    else:
                        logger.warning(
                            "[MCDuration] Failed to fetch player list from RCON"
                        )
                        online_players = self.get_online_players()
                        if online_players:
                            self._handle_disconnects(online_players, curr_time)

                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[MCDuration] Monitor loop error: {exc}")
                await asyncio.sleep(self.interval)
