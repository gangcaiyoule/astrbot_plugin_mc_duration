from __future__ import annotations

import datetime
import time
from typing import Any

from ..message_style import Emoji
from ..models import ReportResult
from ..storage import Storage
from ..utils import (
    calculate_overlap,
    format_time,
    get_time_window,
    parse_date_str,
    seconds_to_text,
)
from .tracker_service import TrackerService


class ReportService:
    def __init__(
        self,
        storage: Storage,
        tracker: TrackerService,
        rank_start_hour: int,
        daily_start_hour: int,
        player_blacklist: set[str],
    ):
        self.storage = storage
        self.tracker = tracker
        self.rank_start_hour = rank_start_hour
        self.daily_start_hour = daily_start_hour
        self.player_blacklist = player_blacklist

    def _is_blacklisted(self, player_name: str | None) -> bool:
        return bool(player_name and player_name in self.player_blacklist)

    def _get_visible_players(self) -> dict[str, dict[str, Any]]:
        return {
            name: data
            for name, data in self.storage.get_all_players().items()
            if not self._is_blacklisted(name)
        }

    def _save_suffix(self) -> str:
        return f" [{Emoji.STORAGE} 存档: {self.storage.get_active_save().name}]"

    def resolve_date_arg(
        self, date_str: str
    ) -> tuple[datetime.date | None, str | None]:
        if not date_str:
            return datetime.date.today(), None

        target_date = parse_date_str(date_str)
        if not target_date:
            return (
                None,
                f"{Emoji.ERROR} 日期格式无法识别: {date_str}。请尝试 8.5、2024-01-01、昨天。",
            )
        return target_date, None

    def require_date(self, target_date: datetime.date | None) -> datetime.date:
        if target_date is None:
            raise ValueError("target_date should not be None after validation")
        return target_date

    def _calculate_daily_stats(
        self, target_date: datetime.date, all_players: dict[str, dict[str, Any]]
    ) -> tuple[str | None, str | None, str | None]:
        rank_start, rank_end = get_time_window(target_date, self.rank_start_hour)
        top_player, max_seconds = None, 0
        for name, data in all_players.items():
            seconds = sum(
                calculate_overlap(
                    session["start"], session["end"], rank_start, rank_end
                )
                for session in data.get("sessions", [])
            )
            if seconds > max_seconds:
                top_player, max_seconds = name, seconds

        daily_start, daily_end = get_time_window(target_date, self.daily_start_hour)
        first_player = last_player = None
        first_time = last_time = None
        for name, data in all_players.items():
            for session in data.get("sessions", []):
                if daily_start <= session["start"] < daily_end:
                    if first_time is None or session["start"] < first_time:
                        first_time, first_player = session["start"], name
                if daily_start < session["end"] <= daily_end:
                    if last_time is None or session["end"] > last_time:
                        last_time, last_player = session["end"], name
        return top_player, first_player, last_player

    def build_season_report(self) -> ReportResult:
        now = datetime.datetime.now()
        month_start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            next_month_dt = month_start_dt.replace(year=now.year + 1, month=1)
        else:
            next_month_dt = month_start_dt.replace(month=now.month + 1)
        month_start, month_end = month_start_dt.timestamp(), next_month_dt.timestamp()

        all_players = self._get_visible_players()
        curr_time = time.time()
        monthly_stats: list[dict[str, int | str]] = []
        for name, data in all_players.items():
            seconds = sum(
                calculate_overlap(
                    session["start"], session["end"], month_start, month_end
                )
                for session in data.get("sessions", [])
            )
            active_start = self.tracker.get_session_start(name)
            if active_start:
                seconds += calculate_overlap(
                    active_start, curr_time, month_start, month_end
                )
            if seconds > 0:
                monthly_stats.append({"name": name, "sec": seconds})

        if not monthly_stats:
            return ReportResult(
                f"{Emoji.INFO} 本月暂时还没有玩家游玩数据。{self._save_suffix()}",
                True,
            )

        achievements = {
            str(item["name"]): {"top": 0, "early": 0, "night": 0}
            for item in monthly_stats
        }
        for day in range(1, datetime.date.today().day + 1):
            top, first, last = self._calculate_daily_stats(
                datetime.date(now.year, now.month, day),
                all_players,
            )
            if top in achievements:
                achievements[top]["top"] += 1
            if first in achievements:
                achievements[first]["early"] += 1
            if last in achievements:
                achievements[last]["night"] += 1

        monthly_stats.sort(key=lambda item: int(item["sec"]), reverse=True)
        lines = [f"{Emoji.SEASON} 本月赛季榜 ({now:%Y-%m}){self._save_suffix()}"]
        for index, item in enumerate(monthly_stats[:15], start=1):
            name = str(item["name"])
            seconds = int(item["sec"])
            badges = achievements.get(name, {})
            badge_items = []
            if badges.get("top"):
                badge_items.append(f"{Emoji.TOP}日榜首 x{badges['top']}")
            if badges.get("early"):
                badge_items.append(f"{Emoji.EARLY}早起王 x{badges['early']}")
            if badges.get("night"):
                badge_items.append(f"{Emoji.NIGHT}熬夜王 x{badges['night']}")
            badge_suffix = f" [{' / '.join(badge_items)}]" if badge_items else ""
            status = Emoji.online_status(bool(self.tracker.get_session_start(name)))
            lines.append(
                f"{index}. {status} {name}: {seconds_to_text(seconds)}{badge_suffix}"
            )
        lines.extend(
            [
                "",
                f"图例: {Emoji.TOP}日榜首 / {Emoji.EARLY}早起王 / {Emoji.NIGHT}熬夜王",
            ]
        )
        return ReportResult("\n".join(lines))

    def build_daily_report(self, target_date: datetime.date) -> ReportResult:
        window_start, window_end = get_time_window(target_date, self.daily_start_hour)
        first_join = last_leave = None
        curr_time = time.time()

        for name, data in self._get_visible_players().items():
            check_list = list(data.get("sessions", []))
            active_start = self.tracker.get_session_start(name)
            if active_start:
                check_list.append({"start": active_start, "end": curr_time})
            for session in check_list:
                if session["end"] <= window_start or session["start"] >= window_end:
                    continue
                if session["start"] >= window_start:
                    if not first_join or session["start"] < first_join[1]:
                        first_join = (name, session["start"])
                if session["end"] <= window_end:
                    if not last_leave or session["end"] > last_leave[1]:
                        last_leave = (name, session["end"])

        lines = [
            f"{Emoji.DAILY} 方块荣誉榜 ({target_date:%Y-%m-%d}){self._save_suffix()}"
        ]
        lines.append(
            f"{Emoji.EARLY} 早起玩家: {first_join[0]} ({format_time(first_join[1])})"
            if first_join
            else f"{Emoji.EARLY} 早起玩家: 暂无"
        )
        lines.append(
            f"{Emoji.NIGHT} 熬夜玩家: {last_leave[0]} ({format_time(last_leave[1])})"
            if last_leave
            else f"{Emoji.NIGHT} 熬夜玩家: 暂无"
        )
        return ReportResult("\n".join(lines), not first_join and not last_leave)

    def build_rank_report(
        self, target_date: datetime.date, show_live_status: bool
    ) -> ReportResult:
        window_start, window_end = get_time_window(target_date, self.rank_start_hour)
        curr_time = time.time()
        ranked_data: list[tuple[str, int]] = []

        for name, data in self._get_visible_players().items():
            seconds = sum(
                calculate_overlap(
                    session["start"], session["end"], window_start, window_end
                )
                for session in data.get("sessions", [])
            )
            active_start = self.tracker.get_session_start(name)
            if active_start:
                seconds += calculate_overlap(
                    active_start, curr_time, window_start, window_end
                )
            if seconds > 0:
                ranked_data.append((name, seconds))

        ranked_data.sort(key=lambda item: item[1], reverse=True)
        lines = [
            f"{Emoji.RANK} MC 排行榜 ({target_date:%Y-%m-%d}){self._save_suffix()}"
        ]
        if not ranked_data:
            lines.append(f"{Emoji.INFO} 这一天还没有游玩记录。")
            return ReportResult("\n".join(lines), True)

        for index, (name, seconds) in enumerate(ranked_data[:10], start=1):
            status = ""
            if show_live_status:
                status = f"{Emoji.online_status(bool(self.tracker.get_session_start(name)))} "
            lines.append(f"{index}. {status}{name}: {seconds_to_text(int(seconds))}")

        if len(ranked_data) == 1:
            lines.append(f"\n{Emoji.SPARKLES} 今天只有一位玩家在守护这个世界。")
        elif len(ranked_data) == 2:
            lines.append(f"\n{Emoji.SPARKLES} 二人世界，方块传情。")
        elif len(ranked_data) < 5:
            lines.append(f"\n{Emoji.SPARKLES} 小团队也有小团队的快乐。")
        else:
            lines.append(f"\n{Emoji.SPARKLES} 今天服务器很热闹，大家都很爱 MC。")
        return ReportResult("\n".join(lines))

    def build_total_rank_report(self) -> ReportResult:
        ranked_data: list[tuple[str, int]] = []
        for name, data in self._get_visible_players().items():
            seconds = int(data.get("total_seconds", 0) or 0)
            if seconds > 0:
                ranked_data.append((name, seconds))

        ranked_data.sort(key=lambda item: item[1], reverse=True)
        lines = [f"{Emoji.TOTAL_RANK} MC 总榜{self._save_suffix()}"]
        if not ranked_data:
            lines.append(f"{Emoji.INFO} 当前存档还没有累计游玩记录。")
            return ReportResult("\n".join(lines), True)

        for index, (name, seconds) in enumerate(ranked_data[:15], start=1):
            status = Emoji.online_status(bool(self.tracker.get_session_start(name)))
            lines.append(f"{index}. {status} {name}: {seconds_to_text(seconds)}")

        return ReportResult("\n".join(lines))

    def build_player_report(self, player: str) -> ReportResult:
        if self._is_blacklisted(player):
            return ReportResult(
                f"{Emoji.ERROR} 玩家 {player} 在黑名单中，当前不展示统计数据。"
            )

        data = self.storage.get_player(player)
        if not data:
            return ReportResult(f"{Emoji.ERROR} 未找到玩家 {player} 的记录。")

        start_of_day = (
            datetime.datetime.now()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )
        today_sessions = [
            f"{format_time(session['start'])}~{format_time(session['end'])}"
            for session in data.get("sessions", [])
            if session["start"] >= start_of_day
        ]
        active_start = self.tracker.get_session_start(player)
        if active_start:
            today_sessions.append(f"{format_time(active_start)}~现在")

        join_times = len(today_sessions)
        if join_times >= 5:
            comment = f"{Emoji.SPARKLES} 今天进进出出的次数有点多，服务器都记住你了。"
        elif join_times >= 3:
            comment = f"{Emoji.SPARKLES} 今天状态不错，来来回回都很积极。"
        elif join_times == 2:
            comment = f"{Emoji.SPARKLES} 进退有度，是个成熟玩家。"
        elif join_times == 1:
            comment = f"{Emoji.SPARKLES} 一次上线，往往就是一整段冒险。"
        else:
            comment = f"{Emoji.SPARKLES} 今天还没看到你上线，服务器正在等你。"

        lines = [
            f"{Emoji.PLAYER} {player} 的统计{self._save_suffix()}",
            f"{Emoji.INFO} 累计: {seconds_to_text(data.get('total_seconds', 0))}",
            f"{Emoji.DAILY} 今日详情: " + "、".join(today_sessions)
            if today_sessions
            else f"{Emoji.DAILY} 今日暂无记录",
            "",
            comment,
        ]
        return ReportResult("\n".join(lines))

    def execute_task_command(self, command_text: str) -> ReportResult:
        normalized = command_text.strip()
        if normalized.startswith("/"):
            normalized = normalized[1:]
        if not normalized:
            return ReportResult("", True)

        command_name, _, argument = normalized.partition(" ")
        command_name = command_name.lower().strip()
        argument = argument.strip()

        if command_name == "mc_rank":
            if argument.lower() == "all":
                return self.build_total_rank_report()
            target_date, error = self.resolve_date_arg(argument)
            return (
                ReportResult(error)
                if error
                else self.build_rank_report(
                    self.require_date(target_date),
                    show_live_status=not argument,
                )
            )
        if command_name == "mc_daily":
            target_date, error = self.resolve_date_arg(argument)
            return (
                ReportResult(error)
                if error
                else self.build_daily_report(self.require_date(target_date))
            )
        if command_name == "mc_season":
            return self.build_season_report()
        if command_name == "mc_me":
            if not argument:
                return ReportResult(
                    f"{Emoji.ERROR} 定时任务中的 /mc_me 必须显式填写玩家 ID。"
                )
            return self.build_player_report(argument)
        return ReportResult(f"{Emoji.ERROR} 不支持的定时命令: {command_text}")
