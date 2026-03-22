from __future__ import annotations

import asyncio
import datetime
import os
import time
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

from .rcon import MCRcon
from .storage import SaveRecord, Storage
from .utils import (
    calculate_overlap,
    format_time,
    get_time_window,
    parse_date_str,
    seconds_to_text,
)


@dataclass(slots=True)
class ReportResult:
    text: str
    is_empty: bool = False


@dataclass(slots=True)
class PushTaskConfig:
    name: str
    cron: str
    targets: list[str]
    commands: list[str]
    enabled: bool = True
    merge_mode: str = "merged"
    separator: str = "\n\n----------\n\n"
    title: str = ""
    skip_if_empty: bool = True


@register("astrbot_plugin_mc_duration", "gangcaiyoule", "MC时长统计插件", "1.7.0")
class MCDurationPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.server_ip = self.config.get("server_ip", "127.0.0.1")
        self.server_port = int(self.config.get("server_port", 25565))
        self.rcon_port = int(self.config.get("rcon_port", 25575))
        self.rcon_password = self.config.get("rcon_password", "")
        self.interval = int(self.config.get("interval", 30))
        self.auto_start = self.config.get("auto_start", True)
        self.rank_start_hour = int(self.config.get("rank_start_hour", 0))
        self.daily_start_hour = int(self.config.get("daily_start_hour", 5))
        self.player_blacklist = self._parse_blacklist(
            self.config.get("player_blacklist", "")
        )
        push_cfg = self.config.get("push_scheduler", {}) or {}
        self.push_scheduler_enabled = bool(push_cfg.get("enabled", False))
        self.push_scheduler_timezone_name = str(
            push_cfg.get("timezone", "Asia/Shanghai") or "Asia/Shanghai"
        )
        self.push_tasks = self._parse_push_tasks(push_cfg.get("tasks", []))
        self.push_scheduler: AsyncIOScheduler | None = None
        self.push_scheduler_timezone = self._get_scheduler_timezone()

        data_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        data_dir = os.path.join(data_root, "plugin_data", "astrbot_plugin_mc_duration")
        self.storage = Storage(data_dir)
        self.rcon = MCRcon(
            self.server_ip, self.server_port, self.rcon_password, self.rcon_port
        )
        self.tracking_task: asyncio.Task | None = None
        self.last_check_time = 0.0
        self.storage_lock = asyncio.Lock()

        if self.player_blacklist:
            logger.info(
                "[MCDuration] 黑名单已开启: %s",
                ", ".join(sorted(self.player_blacklist)),
            )
        if self.auto_start:
            asyncio.create_task(self._start_monitor())

    async def initialize(self):
        self._start_push_scheduler()

    def _parse_blacklist(self, raw_value: Any) -> set[str]:
        if raw_value is None:
            return set()
        if isinstance(raw_value, str):
            candidates = (
                raw_value.replace("，", ",")
                .replace("\n", ",")
                .replace(" ", ",")
                .split(",")
            )
        elif isinstance(raw_value, (list, tuple, set)):
            candidates = [str(item) for item in raw_value]
        else:
            candidates = [str(raw_value)]
        return {name.strip() for name in candidates if name and name.strip()}

    def _normalize_alias(self, alias: str) -> str:
        return alias.strip().lower()

    def _is_blacklisted(self, player_name: str | None) -> bool:
        return bool(player_name and player_name in self.player_blacklist)

    def _filter_tracked_players(self, players: list[str]) -> list[str]:
        return [player for player in players if not self._is_blacklisted(player)]

    def _get_visible_players(self) -> dict[str, dict]:
        return {
            name: data
            for name, data in self.storage.get_all_players().items()
            if not self._is_blacklisted(name)
        }

    def _get_active_save(self) -> SaveRecord:
        return self.storage.get_active_save()

    def _save_suffix(self) -> str:
        return f" [存档: {self._get_active_save().name}]"

    async def _start_monitor(self):
        if self.tracking_task and not self.tracking_task.done():
            return
        logger.info(f"[MCDuration] Monitor started for server {self.server_ip}")
        self.tracking_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        self.last_check_time = time.time()
        while True:
            try:
                curr_time = time.time()
                delta = min(curr_time - self.last_check_time, self.interval * 2)
                self.last_check_time = curr_time
                players = await self.rcon.fetch_players()
                async with self.storage_lock:
                    if players is not None:
                        players = self._filter_tracked_players(players)
                        self.storage.update_playtime(players, delta, curr_time)
                        left_players = [
                            player
                            for player in self.storage.get_online_players()
                            if player not in players
                        ]
                        if left_players:
                            self.storage.handle_disconnects(left_players, curr_time)
                    else:
                        logger.warning(
                            "[MCDuration] 从RCON获取玩家列表失败"
                        )
                        online_players = self.storage.get_online_players()
                        if online_players:
                            self.storage.handle_disconnects(online_players, curr_time)
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[MCDuration] 监视器环路错误: {exc}")
                await asyncio.sleep(self.interval)

    def _parse_push_tasks(self, raw_tasks: Any) -> list[PushTaskConfig]:
        if not isinstance(raw_tasks, list):
            return []
        tasks: list[PushTaskConfig] = []
        seen_names: set[str] = set()
        for index, raw_task in enumerate(raw_tasks, start=1):
            if not isinstance(raw_task, dict):
                continue
            raw_name = str(raw_task.get("name", "") or "").strip() or f"task_{index}"
            task_name = raw_name
            suffix = 2
            while task_name in seen_names:
                task_name = f"{raw_name}_{suffix}"
                suffix += 1
            seen_names.add(task_name)
            merge_mode = str(raw_task.get("merge_mode", "merged") or "merged").lower()
            tasks.append(
                PushTaskConfig(
                    name=task_name,
                    cron=str(raw_task.get("cron", "") or "").strip(),
                    targets=[
                        str(item).strip()
                        for item in raw_task.get("targets", [])
                        if str(item).strip()
                    ],
                    commands=[
                        str(item).strip()
                        for item in raw_task.get("commands", [])
                        if str(item).strip()
                    ],
                    enabled=bool(raw_task.get("enabled", True)),
                    merge_mode=merge_mode
                    if merge_mode in {"merged", "separate"}
                    else "merged",
                    separator=str(
                        raw_task.get("separator", "\n\n----------\n\n")
                        or "\n\n----------\n\n"
                    ),
                    title=str(raw_task.get("title", "") or "").strip(),
                    skip_if_empty=bool(raw_task.get("skip_if_empty", True)),
                )
            )
        return tasks

    def _get_scheduler_timezone(self):
        try:
            return ZoneInfo(self.push_scheduler_timezone_name)
        except Exception:
            logger.warning(
                "[MCDuration] Invalid timezone %s, fallback to local timezone",
                self.push_scheduler_timezone_name,
            )
            return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc

    def _start_push_scheduler(self):
        if self.push_scheduler and self.push_scheduler.running:
            return
        if not self.push_scheduler_enabled:
            logger.info("[MCDuration] Push scheduler is disabled.")
            return
        self.push_scheduler = AsyncIOScheduler(timezone=self.push_scheduler_timezone)
        registered_jobs = 0
        for task in self.push_tasks:
            if not task.enabled or not task.cron or not task.commands:
                continue
            try:
                trigger = CronTrigger.from_crontab(
                    task.cron, timezone=self.push_scheduler_timezone
                )
            except Exception as exc:
                logger.error(
                    "[MCDuration] Invalid cron for push task %s: %s (%s)",
                    task.name,
                    task.cron,
                    exc,
                )
                continue
            self.push_scheduler.add_job(
                self._run_push_task,
                trigger=trigger,
                id=f"mc_duration_push_{task.name}",
                replace_existing=True,
                args=[task],
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
            registered_jobs += 1
        if registered_jobs == 0:
            logger.info("[MCDuration] No valid push task was registered.")
            return
        self.push_scheduler.start()
        logger.info(
            "[MCDuration] Push scheduler started with %s tasks.", registered_jobs
        )

    def _supports_proactive_session(self, session: str) -> bool:
        parts = session.split(":", 2)
        if len(parts) < 3:
            return False
        platform_id = parts[0]
        for platform in self.context.platform_manager.get_insts():
            if platform.meta().id == platform_id:
                return platform.meta().support_proactive_message
        return False

    def _resolve_push_target(self, raw_target: str) -> str | None:
        alias = self._normalize_alias(raw_target)
        if not alias:
            return None
        session = self.storage.get_push_binding(alias)
        if session:
            return session
        if raw_target.count(":") >= 2 and self._supports_proactive_session(raw_target):
            return raw_target
        return None

    def _build_task_run_key(self) -> str:
        return datetime.datetime.now(self.push_scheduler_timezone).strftime(
            "%Y-%m-%d %H:%M"
        )

    async def _run_push_task(self, task: PushTaskConfig):
        run_key = self._build_task_run_key()
        state = self.storage.get_push_task_state(task.name)
        if state.get("last_run_key") == run_key:
            return
        try:
            reports = [self._execute_task_command(command) for command in task.commands]
            reports = [report for report in reports if report.text.strip()]
            if not reports:
                self.storage.update_push_task_state(
                    task.name,
                    last_run_key=run_key,
                    last_status="empty",
                    last_run_at=datetime.datetime.now(
                        self.push_scheduler_timezone
                    ).isoformat(),
                    last_error="",
                )
                return
            if task.skip_if_empty and all(report.is_empty for report in reports):
                self.storage.update_push_task_state(
                    task.name,
                    last_run_key=run_key,
                    last_status="skipped_empty",
                    last_run_at=datetime.datetime.now(
                        self.push_scheduler_timezone
                    ).isoformat(),
                    last_error="",
                )
                return
            messages = (
                [report.text for report in reports]
                if task.merge_mode == "separate"
                else [task.separator.join(report.text for report in reports)]
            )
            if task.title:
                messages = (
                    [task.title, *messages]
                    if task.merge_mode == "separate"
                    else [f"{task.title}\n\n{messages[0]}"]
                )
            targets: list[str] = []
            for raw_target in task.targets:
                session = self._resolve_push_target(raw_target)
                if session and self._supports_proactive_session(session):
                    if session not in targets:
                        targets.append(session)
            if not targets:
                self.storage.update_push_task_state(
                    task.name,
                    last_run_key=run_key,
                    last_status="no_target",
                    last_run_at=datetime.datetime.now(
                        self.push_scheduler_timezone
                    ).isoformat(),
                    last_error="No valid push target resolved",
                )
                return
            sent_count = 0
            for session in targets:
                for message in messages:
                    if await self.context.send_message(
                        session, MessageChain().message(message)
                    ):
                        sent_count += 1
            self.storage.update_push_task_state(
                task.name,
                last_run_key=run_key,
                last_status="sent" if sent_count else "send_failed",
                last_run_at=datetime.datetime.now(
                    self.push_scheduler_timezone
                ).isoformat(),
                last_error="",
            )
        except Exception as exc:
            logger.error(f"[MCDuration] Push task {task.name} failed: {exc}")
            self.storage.update_push_task_state(
                task.name,
                last_run_key=run_key,
                last_status="error",
                last_run_at=datetime.datetime.now(
                    self.push_scheduler_timezone
                ).isoformat(),
                last_error=str(exc),
            )

    def _resolve_date_arg(
        self, date_str: str
    ) -> tuple[datetime.date | None, str | None]:
        if not date_str:
            return datetime.date.today(), None
        target_date = parse_date_str(date_str)
        if not target_date:
            return (
                None,
                f"❌ 日期格式无法识别: {date_str}。请尝试 8.5、2024-01-01、昨天。",
            )
        return target_date, None

    def _require_date(self, target_date: datetime.date | None) -> datetime.date:
        if target_date is None:
            raise ValueError("target_date should not be None after validation")
        return target_date

    def _calculate_daily_stats(
        self, target_date: datetime.date, all_players: dict
    ) -> tuple[str | None, str | None, str | None]:
        rank_start, rank_end = get_time_window(target_date, self.rank_start_hour)
        top_player, max_sec = None, 0
        for name, data in all_players.items():
            seconds = sum(
                calculate_overlap(
                    session["start"], session["end"], rank_start, rank_end
                )
                for session in data.get("sessions", [])
            )
            if seconds > max_sec:
                top_player, max_sec = name, seconds
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

    def _build_season_report(self) -> ReportResult:
        now = datetime.datetime.now()
        cur_year, cur_month = now.year, now.month
        month_start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month_dt = (
            month_start_dt.replace(year=cur_year + 1, month=1)
            if cur_month == 12
            else month_start_dt.replace(month=cur_month + 1)
        )
        month_start, month_end = month_start_dt.timestamp(), next_month_dt.timestamp()
        all_players, curr_time = self._get_visible_players(), time.time()
        monthly_stats = []
        for name, data in all_players.items():
            seconds = sum(
                calculate_overlap(
                    session["start"], session["end"], month_start, month_end
                )
                for session in data.get("sessions", [])
            )
            active_start = self.storage.get_session_start(name)
            if active_start:
                seconds += calculate_overlap(
                    active_start, curr_time, month_start, month_end
                )
            if seconds > 0:
                monthly_stats.append({"name": name, "sec": seconds})
        if not monthly_stats:
            return ReportResult(
                f"📳 {cur_month} 月赛季暂无玩家数据。{self._save_suffix()}", True
            )
        achievements = {
            item["name"]: {"top": 0, "early": 0, "night": 0} for item in monthly_stats
        }
        for day in range(1, datetime.date.today().day + 1):
            top, first, last = self._calculate_daily_stats(
                datetime.date(cur_year, cur_month, day), all_players
            )
            if top in achievements:
                achievements[top]["top"] += 1
            if first in achievements:
                achievements[first]["early"] += 1
            if last in achievements:
                achievements[last]["night"] += 1
        monthly_stats.sort(key=lambda item: item["sec"], reverse=True)
        lines = [f"📦 **{cur_year} 年 {cur_month} 月赛季榜**{self._save_suffix()}"]
        for index, item in enumerate(monthly_stats[:15], start=1):
            badges = achievements.get(item["name"], {})
            badge_items = []
            if badges.get("top"):
                badge_items.append(f"🏆x{badges['top']}")
            if badges.get("early"):
                badge_items.append(f"🌅x{badges['early']}")
            if badges.get("night"):
                badge_items.append(f"🌙x{badges['night']}")
            badge_suffix = f" [{' '.join(badge_items)}]" if badge_items else ""
            status = "🟢" if self.storage.get_session_start(item["name"]) else "⚪"
            lines.append(
                f"{index}. {status} {item['name']}: {seconds_to_text(int(item['sec']))}{badge_suffix}"
            )
        lines.extend(["", "图例: 🏆 日榜榜首 | 🌅 早起玩家 | 🌙 熬夜玩家"])
        return ReportResult("\n".join(lines))

    def _build_daily_report(self, target_date: datetime.date) -> ReportResult:
        window_start, window_end = get_time_window(target_date, self.daily_start_hour)
        first_join = last_leave = None
        curr_time = time.time()
        for name, data in self._get_visible_players().items():
            check_list = list(data.get("sessions", []))
            active_start = self.storage.get_session_start(name)
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
        lines = [f"🧾 **方块荣誉榜 ({target_date:%Y-%m-%d})**{self._save_suffix()}"]
        lines.append(
            f"🌅 **早起玩家**: {first_join[0]} ({format_time(first_join[1])})"
            if first_join
            else "🌅 **早起玩家**: 暂无"
        )
        lines.append(
            f"🌙 **熬夜玩家**: {last_leave[0]} ({format_time(last_leave[1])})"
            if last_leave
            else "🌙 **熬夜玩家**: 暂无"
        )
        return ReportResult("\n".join(lines), not first_join and not last_leave)

    def _build_rank_report(
        self, target_date: datetime.date, show_live_status: bool
    ) -> ReportResult:
        window_start, window_end = get_time_window(target_date, self.rank_start_hour)
        curr_time, ranked_data = time.time(), []
        for name, data in self._get_visible_players().items():
            seconds = sum(
                calculate_overlap(
                    session["start"], session["end"], window_start, window_end
                )
                for session in data.get("sessions", [])
            )
            active_start = self.storage.get_session_start(name)
            if active_start:
                seconds += calculate_overlap(
                    active_start, curr_time, window_start, window_end
                )
            if seconds > 0:
                ranked_data.append((name, seconds))
        ranked_data.sort(key=lambda item: item[1], reverse=True)
        lines = [f"🏆 **MC 排行榜 ({target_date:%Y-%m-%d})**{self._save_suffix()}"]
        if not ranked_data:
            lines.append("🈳 该日期暂无游戏记录。")
            return ReportResult("\n".join(lines), True)
        for index, (name, seconds) in enumerate(ranked_data[:10], start=1):
            if show_live_status:
                status = "🟢" if self.storage.get_session_start(name) else "⚪"
            else:
                status = "👤"
            lines.append(f"{index}. {status} {name}: {seconds_to_text(int(seconds))}")
        if len(ranked_data) == 1:
            lines.append("\n🫶 今天只有一位玩家在守护这个世界。")
        elif len(ranked_data) == 2:
            lines.append("\n💕 二人世界，方块传情。")
        elif len(ranked_data) < 5:
            lines.append("\n✨ 小团队也有小团队的快乐。")
        else:
            lines.append("\n🔥 今天服务器很热闹，大家都很爱 MC。")
        return ReportResult("\n".join(lines))

    def _build_total_rank_report(self) -> ReportResult:
        ranked_data: list[tuple[str, int]] = []
        for name, data in self._get_visible_players().items():
            seconds = int(data.get("total_seconds", 0) or 0)
            if seconds > 0:
                ranked_data.append((name, seconds))

        ranked_data.sort(key=lambda item: item[1], reverse=True)
        lines = [f"🏆 **MC 总榜**{self._save_suffix()}"]
        if not ranked_data:
            lines.append("🈳 当前存档暂无累计游戏记录。")
            return ReportResult("\n".join(lines), True)

        for index, (name, seconds) in enumerate(ranked_data[:15], start=1):
            status = "🟢" if self.storage.get_session_start(name) else "⚪"
            lines.append(f"{index}. {status} {name}: {seconds_to_text(seconds)}")

        return ReportResult("\n".join(lines))

    def _build_player_report(self, player: str) -> ReportResult:
        if self._is_blacklisted(player):
            return ReportResult(f"❌ 玩家 {player} 已加入黑名单，当前不展示统计数据。")
        data = self.storage.get_player(player)
        if not data:
            return ReportResult(f"❌ 未找到玩家 {player} 的记录。")
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
        active_start = self.storage.get_session_start(player)
        if active_start:
            today_sessions.append(f"{format_time(active_start)}~现在")
        join_times = len(today_sessions)
        if join_times >= 5:
            comment = "🌟 今天进进出出的次数有点多，服务器都记住你了。"
        elif join_times >= 3:
            comment = "⚡ 今天状态不错，来来回回都很积极。"
        elif join_times == 2:
            comment = "🎆 进退有度，是个成熟玩家。"
        elif join_times == 1:
            comment = "🌇 一次上线，往往就是一整段冒险。"
        else:
            comment = "🙃 今天还没看到你上线，服务器正在等你。"
        lines = [
            f"👤 **{player} 的统计**{self._save_suffix()}",
            f"⏱️ 累计: {seconds_to_text(data.get('total_seconds', 0))}",
            "📦 **今日详情**: " + "、".join(today_sessions)
            if today_sessions
            else "📦 今日暂无记录",
            "",
            comment,
        ]
        return ReportResult("\n".join(lines))

    def _execute_task_command(self, command_text: str) -> ReportResult:
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
                return self._build_total_rank_report()
            target_date, error = self._resolve_date_arg(argument)
            return (
                ReportResult(error)
                if error
                else self._build_rank_report(
                    self._require_date(target_date), show_live_status=not argument
                )
            )
        if command_name == "mc_daily":
            target_date, error = self._resolve_date_arg(argument)
            return (
                ReportResult(error)
                if error
                else self._build_daily_report(self._require_date(target_date))
            )
        if command_name == "mc_season":
            return self._build_season_report()
        if command_name == "mc_me":
            return (
                ReportResult("❌ 定时任务中的 /mc_me 必须显式填写玩家 ID。")
                if not argument
                else self._build_player_report(argument)
            )
        return ReportResult(f"❌ 不支持的定时命令: {command_text}")

    def _activate_save_locked(self, save_id: str, switch_time: float) -> SaveRecord:
        current = self.storage.get_active_save()
        if current.save_id == save_id:
            return current
        online_players = self.storage.get_online_players()
        if online_players:
            self.storage.handle_disconnects(online_players, switch_time)
        new_save = self.storage.set_active_save(save_id)
        resumed = [
            player for player in online_players if not self._is_blacklisted(player)
        ]
        if resumed:
            self.storage.start_session_for_players(resumed, switch_time)
        self.last_check_time = switch_time
        return new_save

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        return event.is_admin()

    @filter.command("mc_season")
    async def cmd_season(self, event: AstrMessageEvent):
        yield event.plain_result(self._build_season_report().text)

    @filter.command("mc_daily")
    async def cmd_daily(self, event: AstrMessageEvent, date_str: str = ""):
        target_date, error = self._resolve_date_arg(date_str)
        if error:
            yield event.plain_result(error)
            return
        yield event.plain_result(
            self._build_daily_report(self._require_date(target_date)).text
        )

    @filter.command("mc_stat_on")
    async def cmd_on(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作。")
            return
        if not self.tracking_task or self.tracking_task.done():
            self.last_check_time = time.time()
            asyncio.create_task(self._start_monitor())
            yield event.plain_result(f"✅ 监控已开启 (interval={self.interval}s)")
        else:
            yield event.plain_result("⚠️ 监控已在运行中。")

    @filter.command("mc_stat_off")
    async def cmd_off(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作。")
            return
        if self.tracking_task:
            self.tracking_task.cancel()
            self.tracking_task = None
        yield event.plain_result("🛑 监控已停止。")

    @filter.command("mc_rank")
    async def cmd_rank(self, event: AstrMessageEvent, date_str: str = ""):
        if date_str.strip().lower() == "all":
            yield event.plain_result(self._build_total_rank_report().text)
            return
        target_date, error = self._resolve_date_arg(date_str)
        if error:
            yield event.plain_result(error)
            return
        yield event.plain_result(
            self._build_rank_report(
                self._require_date(target_date), show_live_status=not date_str
            ).text
        )

    @filter.command("mc_me")
    async def cmd_me(self, event: AstrMessageEvent, player: str = ""):
        yield event.plain_result(
            self._build_player_report(player or event.get_sender_name()).text
        )

    @filter.command("mc_push_bind")
    async def cmd_push_bind(
        self, event: AstrMessageEvent, action: str = "", value: str = ""
    ):
        if not self._is_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作。")
            return
        normalized_action = action.strip()
        if not normalized_action:
            yield event.plain_result(
                "用法:\n"
                "/mc_push_bind <alias> 绑定当前会话\n"
                "/mc_push_bind list 查看已绑定会话\n"
                "/mc_push_bind del <alias> 删除绑定"
            )
            return
        lowered = normalized_action.lower()
        if lowered == "list":
            bindings = self.storage.get_push_bindings()
            if not bindings:
                yield event.plain_result("📥 当前还没有已绑定的推送会话。")
                return
            lines = ["📦 已绑定推送会话："]
            for alias, session in bindings.items():
                lines.append(f"- {alias}: {session}")
            yield event.plain_result("\n".join(lines))
            return
        if lowered in {"del", "delete", "remove"}:
            alias = self._normalize_alias(value)
            if not alias:
                yield event.plain_result("❌ 请提供要删除的 alias。")
                return
            if self.storage.delete_push_binding(alias):
                yield event.plain_result(f"✅ 已删除推送绑定: {alias}")
            else:
                yield event.plain_result(f"❌ 未找到 alias: {alias}")
            return
        alias = self._normalize_alias(normalized_action)
        session = event.unified_msg_origin
        if not alias:
            yield event.plain_result("❌ alias 不能为空。")
            return
        if not self._supports_proactive_session(session):
            yield event.plain_result("❌ 当前平台不支持主动消息，无法绑定推送目标。")
            return
        previous = self.storage.set_push_binding(alias, session)
        if previous and previous != session:
            yield event.plain_result(
                f"✅ 已更新推送绑定: {alias}\n旧会话: {previous}\n新会话: {session}"
            )
        else:
            yield event.plain_result(
                f"✅ 已绑定当前会话到 alias: {alias}\n会话 ID: {session}"
            )

    @filter.command("mc_save_list")
    async def cmd_save_list(self, event: AstrMessageEvent):
        active_id = self.storage.get_active_save().save_id
        lines = ["📚 存档列表："]
        for save in self.storage.list_saves():
            marker = "⭐" if save.save_id == active_id else "•"
            lines.append(
                f"{marker} {save.name} [{save.save_id[:8]}] 玩家 {save.player_count} 人，会话 {save.session_count} 条"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("mc_save_current")
    async def cmd_save_current(self, event: AstrMessageEvent):
        active = self.storage.get_active_save()
        yield event.plain_result(
            f"📍 当前存档: {active.name}\nID: {active.save_id}\n创建时间: {active.created_at}"
        )

    @filter.command("mc_save_create")
    async def cmd_save_create(self, event: AstrMessageEvent, name: str = ""):
        if not self._is_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作。")
            return
        if not name.strip():
            yield event.plain_result("❌ 用法: /mc_save_create <存档名>")
            return
        try:
            async with self.storage_lock:
                save = self.storage.create_save(name.strip(), activate=False)
                save = self._activate_save_locked(save.save_id, time.time())
        except ValueError as exc:
            yield event.plain_result(f"❌ {exc}")
            return
        yield event.plain_result(
            f"✅ 已创建并切换到新存档: {save.name}\nID: {save.save_id}"
        )

    @filter.command("mc_save_switch")
    async def cmd_save_switch(self, event: AstrMessageEvent, identifier: str = ""):
        if not self._is_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作。")
            return
        target = identifier.strip()
        if not target:
            yield event.plain_result("❌ 用法: /mc_save_switch <存档名或ID>")
            return
        resolved = self.storage.resolve_save(target)
        if not resolved:
            yield event.plain_result(f"❌ 未找到存档: {target}")
            return
        if resolved.save_id == self.storage.get_active_save().save_id:
            yield event.plain_result(f"ℹ️ 当前已经在存档 {resolved.name}。")
            return
        async with self.storage_lock:
            save = self._activate_save_locked(resolved.save_id, time.time())
        yield event.plain_result(f"✅ 已切换到存档: {save.name}\nID: {save.save_id}")

    @filter.command("mc_save_delete")
    async def cmd_save_delete(
        self, event: AstrMessageEvent, identifier: str = "", confirm: str = ""
    ):
        if not self._is_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作。")
            return
        target = identifier.strip()
        if not target:
            yield event.plain_result("❌ 用法: /mc_save_delete <存档名或ID> confirm")
            return
        if confirm.strip().lower() != "confirm":
            yield event.plain_result(
                f"⚠️ 该操作会永久删除存档 {target} 的全部数据。\n"
                f"请使用 /mc_save_delete {target} confirm 确认执行。"
            )
            return
        async with self.storage_lock:
            save = self.storage.resolve_save(target)
            if not save:
                yield event.plain_result(f"❌ 未找到存档: {target}")
                return
            all_saves = self.storage.list_saves()
            if save.is_active:
                if len(all_saves) <= 1:
                    yield event.plain_result("❌ 当前只剩一个存档，无法删除。")
                    return
                replacement = next(
                    item for item in all_saves if item.save_id != save.save_id
                )
                self._activate_save_locked(replacement.save_id, time.time())
            self.storage.delete_save(save.save_id)
        yield event.plain_result(f"✅ 已删除存档: {save.name}")

    @filter.command("mc_save_player_delete")
    async def cmd_save_player_delete(
        self,
        event: AstrMessageEvent,
        save_identifier: str = "",
        player_name: str = "",
        confirm: str = "",
    ):
        if not self._is_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作。")
            return
        if not save_identifier.strip() or not player_name.strip():
            yield event.plain_result(
                "❌ 用法: /mc_save_player_delete <存档名或ID> <玩家名> confirm"
            )
            return
        if confirm.strip().lower() != "confirm":
            yield event.plain_result(
                f"⚠️ 该操作会永久删除玩家 {player_name} 在存档 {save_identifier} 中的数据。\n"
                f"请使用 /mc_save_player_delete {save_identifier} {player_name} confirm 确认执行。"
            )
            return
        async with self.storage_lock:
            save = self.storage.resolve_save(save_identifier.strip())
            if not save:
                yield event.plain_result(f"❌ 未找到存档: {save_identifier}")
                return
            deleted = self.storage.delete_player_data(save.save_id, player_name.strip())
            if save.is_active:
                self.last_check_time = time.time()
        if deleted:
            yield event.plain_result(
                f"✅ 已删除玩家 {player_name} 在存档 {save.name} 中的数据。"
            )
        else:
            yield event.plain_result(
                f"❌ 未找到玩家 {player_name} 在存档 {save_identifier} 中的数据。"
            )

    async def terminate(self):
        if self.tracking_task:
            self.tracking_task.cancel()
        if self.push_scheduler and self.push_scheduler.running:
            self.push_scheduler.shutdown(wait=False)
        self.storage.save_data()
