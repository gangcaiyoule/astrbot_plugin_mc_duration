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
from .storage import Storage
from .utils import (
    calculate_overlap,
    format_time,
    get_time_window,
    parse_date_str,
    seconds_to_text,
)


@dataclass
class ReportResult:
    text: str
    is_empty: bool = False


@dataclass
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


@register("astrbot_plugin_mc_duration", "gangcaiyoule", "MC时长统计插件", "1.6.0")
class MCDurationPlugin(Star):
    # 初始化插件配置、存储和后台任务所需的运行状态。
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

        # 定时推送配置单独挂在 push_scheduler 下，tasks 使用 list[dict] 结构。
        push_scheduler_cfg = self.config.get("push_scheduler", {}) or {}
        self.push_scheduler_enabled = bool(push_scheduler_cfg.get("enabled", False))
        self.push_scheduler_timezone_name = str(
            push_scheduler_cfg.get("timezone", "Asia/Shanghai") or "Asia/Shanghai"
        )
        self.push_tasks = self._parse_push_tasks(push_scheduler_cfg.get("tasks", []))
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

        if self.player_blacklist:
            logger.info(
                f"[MCDuration] 玩家黑名单已开启: {', '.join(sorted(self.player_blacklist))}"
            )
        # auto_start 仍然只控制原有的在线时长监控任务。
        if self.auto_start:
            asyncio.create_task(self._start_monitor())

    # 在插件加载完成后启动定时推送调度器。
    async def initialize(self):
        self._start_push_scheduler()

    # 将配置里的黑名单输入统一解析成玩家名集合。
    def _parse_blacklist(self, raw_value: Any) -> set[str]:
        if raw_value is None:
            return set()

        if isinstance(raw_value, str):
            normalized = (
                raw_value.replace("，", ",").replace("\n", ",").replace(" ", ",")
            )
            candidates = normalized.split(",")
        elif isinstance(raw_value, (list, tuple, set)):
            candidates = [str(item) for item in raw_value]
        else:
            candidates = [str(raw_value)]

        return {name.strip() for name in candidates if name and name.strip()}

    # 统一处理推送别名，避免大小写和空白差异。
    def _normalize_alias(self, alias: str) -> str:
        return alias.strip().lower()

    # 判断某个玩家当前是否在黑名单中。
    def _is_blacklisted(self, player_name: str | None) -> bool:
        return bool(player_name and player_name in self.player_blacklist)

    # 过滤在线玩家列表，黑名单玩家不会继续被记录时长。
    def _filter_tracked_players(self, players: list[str]) -> list[str]:
        # 黑名单玩家从这一刻开始不再继续累计时长，但历史数据会保留在存档里。
        return [player for player in players if not self._is_blacklisted(player)]

    # 获取允许出现在榜单和日报中的玩家数据视图。
    def _get_visible_players(self) -> dict[str, dict]:
        # 展示层统一走这里，确保榜单和日报都不会把黑名单玩家算进去。
        return {
            name: data
            for name, data in self.storage.get_all_players().items()
            if not self._is_blacklisted(name)
        }

    # 启动主监控循环，避免重复创建同一个后台任务。
    async def _start_monitor(self):
        if self.tracking_task and not self.tracking_task.done():
            return
        logger.info(f"[MCDuration] Monitor started for server {self.server_ip}")
        self.tracking_task = asyncio.create_task(self._monitor_loop())

    # 定期从 RCON 拉取在线玩家并累计时长。
    async def _monitor_loop(self):
        self.last_check_time = time.time()
        while True:
            try:
                curr_time = time.time()
                delta = min(curr_time - self.last_check_time, self.interval * 2)
                self.last_check_time = curr_time
                players = await self.rcon.fetch_players()

                if players is not None:
                    players = self._filter_tracked_players(players)
                    self.storage.update_playtime(players, delta, curr_time)

                    online_in_cache = list(self.storage.session_start_cache.keys())
                    left_players = [
                        player for player in online_in_cache if player not in players
                    ]
                    if left_players:
                        self.storage.handle_disconnects(left_players, curr_time)

                    self.storage.save_data()
                else:
                    logger.warning("[MCDuration] Failed to fetch player list from RCON")
                    online_players = list(self.storage.session_start_cache.keys())
                    if online_players:
                        self.storage.handle_disconnects(online_players, curr_time)

                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[MCDuration] Monitor loop error: {exc}")
                await asyncio.sleep(self.interval)

    # 解析配置中的定时任务列表，整理成内部统一结构。
    def _parse_push_tasks(self, raw_tasks: Any) -> list[PushTaskConfig]:
        if not isinstance(raw_tasks, list):
            return []

        # 将配置中的 list[dict] 或 template_list 条目归一化为内部任务对象，顺便兜底非法字段。
        tasks: list[PushTaskConfig] = []
        seen_names: set[str] = set()

        for index, raw_task in enumerate(raw_tasks, start=1):
            if not isinstance(raw_task, dict):
                logger.warning(
                    f"[MCDuration] Ignored invalid push task at index {index}: not an object"
                )
                continue

            raw_name = str(raw_task.get("name", "") or "").strip() or f"task_{index}"
            task_name = raw_name
            suffix = 2
            while task_name in seen_names:
                task_name = f"{raw_name}_{suffix}"
                suffix += 1
            seen_names.add(task_name)

            cron = str(raw_task.get("cron", "") or "").strip()
            targets = [
                str(item).strip()
                for item in raw_task.get("targets", [])
                if str(item).strip()
            ]
            commands = [
                str(item).strip()
                for item in raw_task.get("commands", [])
                if str(item).strip()
            ]
            merge_mode = str(raw_task.get("merge_mode", "merged") or "merged").lower()
            if merge_mode not in {"merged", "separate"}:
                merge_mode = "merged"

            tasks.append(
                PushTaskConfig(
                    name=task_name,
                    cron=cron,
                    targets=targets,
                    commands=commands,
                    enabled=bool(raw_task.get("enabled", True)),
                    merge_mode=merge_mode,
                    separator=str(
                        raw_task.get("separator", "\n\n----------\n\n")
                        or "\n\n----------\n\n"
                    ),
                    title=str(raw_task.get("title", "") or "").strip(),
                    skip_if_empty=bool(raw_task.get("skip_if_empty", True)),
                )
            )

        return tasks

    # 根据配置读取定时调度所使用的时区。
    def _get_scheduler_timezone(self):
        try:
            return ZoneInfo(self.push_scheduler_timezone_name)
        except Exception:
            logger.warning(
                f"[MCDuration] Invalid timezone {self.push_scheduler_timezone_name}, fallback to local timezone"
            )
            return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc

    # 注册并启动所有启用中的定时推送任务。
    def _start_push_scheduler(self):
        if self.push_scheduler and self.push_scheduler.running:
            return

        if not self.push_scheduler_enabled:
            logger.info("[MCDuration] 无法推送，推送调度器未启用")
            return

        self.push_scheduler = AsyncIOScheduler(timezone=self.push_scheduler_timezone)
        registered_jobs = 0

        for task in self.push_tasks:
            if not task.enabled:
                continue
            if not task.cron or not task.commands:
                continue

            try:
                trigger = CronTrigger.from_crontab(
                    task.cron, timezone=self.push_scheduler_timezone
                )
            except Exception as exc:
                logger.error(
                    f"[MCDuration] 推送任务的cron无效 {task.name}: {task.cron} ({exc})"
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
            logger.info("[MCDuration] 未注册有效的推送任务")
            return

        self.push_scheduler.start()
        logger.info(f"[MCDuration] 推送调度器已启动，共 {registered_jobs} 个任务")

    # 判断某个平台会话是否支持主动消息发送。
    def _supports_proactive_session(self, session: str) -> bool:
        parts = session.split(":", 2)
        if len(parts) < 3:
            return False

        platform_id = parts[0]
        for platform in self.context.platform_manager.get_insts():
            meta = platform.meta()
            if meta.id == platform_id:
                return meta.support_proactive_message
        return False

    # 将配置中的目标解析成可发送的会话 ID。
    def _resolve_push_target(self, raw_target: str) -> str | None:
        alias = self._normalize_alias(raw_target)
        if not alias:
            return None

        # 优先把 target 当成绑定别名解析，解析不到时再尝试直接把它当 session。
        session = self.storage.get_push_binding(alias)
        if session:
            return session

        if raw_target.count(":") >= 2 and self._supports_proactive_session(raw_target):
            return raw_target

        return None

    # 生成当前分钟粒度的执行键，用来避免重复推送。
    def _build_task_run_key(self) -> str:
        now = datetime.datetime.now(self.push_scheduler_timezone)
        return now.strftime("%Y-%m-%d %H:%M")

    # 执行单个定时任务并将结果主动发送到目标会话。
    async def _run_push_task(self, task: PushTaskConfig):
        run_key = self._build_task_run_key()
        state = self.storage.get_push_task_state(task.name)
        if state.get("last_run_key") == run_key:
            logger.info(f"[MCDuration] Skip duplicate push task run: {task.name}")
            return

        try:
            # 定时任务本质上是“命令列表 -> 报表文本 -> 主动发送”这条链路。
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

            messages = self._build_push_messages(task, reports)
            resolved_targets: list[str] = []
            for raw_target in task.targets:
                # target 既可以是绑定别名，也可以直接写支持主动消息的 session。
                session = self._resolve_push_target(raw_target)
                if not session:
                    logger.warning(
                        f"[MCDuration] 推送任务 {task.name} 目标未找到: {raw_target}"
                    )
                    continue
                if not self._supports_proactive_session(session):
                    logger.warning(
                        f"[MCDuration] 推送任务 {task.name} 目标不支持主动消息: {session}"
                    )
                    continue
                if session not in resolved_targets:
                    resolved_targets.append(session)

            if not resolved_targets:
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
            for session in resolved_targets:
                for message in messages:
                    ok = await self.context.send_message(
                        session, MessageChain().message(message)
                    )
                    if ok:
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
            logger.error(f"[MCDuration] 推送任务 {task.name} 执行失败: {exc}")
            self.storage.update_push_task_state(
                task.name,
                last_run_key=run_key,
                last_status="error",
                last_run_at=datetime.datetime.now(
                    self.push_scheduler_timezone
                ).isoformat(),
                last_error=str(exc),
            )

    # 按配置决定将多段结果合并成一条消息还是分别发送。
    def _build_push_messages(
        self, task: PushTaskConfig, reports: list[ReportResult]
    ) -> list[str]:
        # merged 合并成一条日报；separate 则逐条发送每段结果。
        if task.merge_mode == "separate":
            messages = [report.text for report in reports]
            if task.title:
                return [task.title, *messages]
            return messages

        merged = task.separator.join(report.text for report in reports)
        if task.title:
            merged = f"{task.title}\n\n{merged}"
        return [merged]

    # 解析命令里的日期参数，支持自然语言日期和显式日期。
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

    # 在完成错误分支判断后，将可空日期收窄为确定存在的日期对象。
    def _require_date(self, target_date: datetime.date | None) -> datetime.date:
        if target_date is None:
            raise ValueError("target_date should not be None after validation")
        return target_date

    # 统计某一天的榜首、早起玩家和熬夜玩家。
    def _calculate_daily_stats(
        self, target_date: datetime.date, all_players: dict
    ) -> tuple[str | None, str | None, str | None]:
        rank_start, rank_end = get_time_window(target_date, self.rank_start_hour)
        top_player = None
        max_sec = 0

        for name, data in all_players.items():
            seconds = 0
            for session in data.get("sessions", []):
                seconds += calculate_overlap(
                    session["start"], session["end"], rank_start, rank_end
                )
            if seconds > max_sec:
                max_sec = seconds
                top_player = name

        daily_start, daily_end = get_time_window(target_date, self.daily_start_hour)
        first_player = None
        last_player = None
        first_time = None
        last_time = None

        for name, data in all_players.items():
            for session in data.get("sessions", []):
                if daily_start <= session["start"] < daily_end:
                    if first_time is None or session["start"] < first_time:
                        first_time = session["start"]
                        first_player = name

                if daily_start < session["end"] <= daily_end:
                    if last_time is None or session["end"] > last_time:
                        last_time = session["end"]
                        last_player = name

        return top_player, first_player, last_player

    # 生成当月赛季榜和附加成就统计。
    def _build_season_report(self) -> ReportResult:
        now = datetime.datetime.now()
        cur_year = now.year
        cur_month = now.month

        month_start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            next_month_dt = now.replace(
                year=now.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        else:
            next_month_dt = now.replace(
                month=now.month + 1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

        month_start = month_start_dt.timestamp()
        month_end = next_month_dt.timestamp()
        all_players = self._get_visible_players()
        curr_time = time.time()

        monthly_stats: list[dict[str, Any]] = []
        for name, data in all_players.items():
            seconds = 0
            for session in data.get("sessions", []):
                seconds += calculate_overlap(
                    session["start"], session["end"], month_start, month_end
                )

            active_start = self.storage.get_session_start(name)
            if active_start:
                seconds += calculate_overlap(
                    active_start, curr_time, month_start, month_end
                )

            if seconds > 0:
                monthly_stats.append({"name": name, "sec": seconds})

        if not monthly_stats:
            return ReportResult(f"📊 {cur_month} 月赛季暂无玩家数据。", True)

        achievements = {
            item["name"]: {"top": 0, "early": 0, "night": 0} for item in monthly_stats
        }

        today = datetime.date.today()
        for day in range(1, today.day + 1):
            target_date = datetime.date(cur_year, cur_month, day)
            top, first, last = self._calculate_daily_stats(target_date, all_players)
            if top and top in achievements:
                achievements[top]["top"] += 1
            if first and first in achievements:
                achievements[first]["early"] += 1
            if last and last in achievements:
                achievements[last]["night"] += 1

        monthly_stats.sort(key=lambda item: item["sec"], reverse=True)
        lines = [f"📮 **{cur_year} 年 {cur_month} 月赛季魔人榜**"]

        for index, item in enumerate(monthly_stats[:15], start=1):
            name = item["name"]
            is_online = self.storage.get_session_start(name) is not None
            status = "🟢" if is_online else "⚪"
            badges = achievements.get(name, {})
            badge_items = []
            if badges.get("top", 0) > 0:
                badge_items.append(f"🏆x{badges['top']}")
            if badges.get("early", 0) > 0:
                badge_items.append(f"🌅x{badges['early']}")
            if badges.get("night", 0) > 0:
                badge_items.append(f"🌙x{badges['night']}")

            badge_suffix = f" [{' '.join(badge_items)}]" if badge_items else ""
            lines.append(
                f"{index}. {status} {name}: {seconds_to_text(int(item['sec']))}{badge_suffix}"
            )

        lines.append("")
        lines.append("图例：🏆 日榜榜首 | 🌅 早起魔人 | 🌙 熬夜魔人")
        return ReportResult("\n".join(lines))

    # 生成指定统计日的早起/熬夜日报。
    def _build_daily_report(self, target_date: datetime.date) -> ReportResult:
        window_start, window_end = get_time_window(target_date, self.daily_start_hour)
        first_join = None
        last_leave = None

        all_players = self._get_visible_players()
        curr_time = time.time()

        for name, data in all_players.items():
            check_list = list(data.get("sessions", []))
            active_start = self.storage.get_session_start(name)
            if active_start:
                check_list.append({"start": active_start, "end": curr_time})

            for session in check_list:
                session_start = session["start"]
                session_end = session["end"]

                if session_end <= window_start or session_start >= window_end:
                    continue

                if session_start >= window_start:
                    if not first_join or session_start < first_join[1]:
                        first_join = (name, session_start)

                if session_end <= window_end:
                    if not last_leave or session_end > last_leave[1]:
                        last_leave = (name, session_end)

        date_display = target_date.strftime("%Y-%m-%d")
        lines = [f"📘 **方块荣誉榜 ({date_display})**"]

        if first_join:
            lines.append(
                f"🌅 **早起魔人**: {first_join[0]} ({format_time(first_join[1])})"
            )
        else:
            lines.append("🌅 **早起魔人**: 暂无")

        if last_leave:
            lines.append(
                f"🌙 **熬夜魔人**: {last_leave[0]} ({format_time(last_leave[1])})"
            )
        else:
            lines.append("🌙 **熬夜魔人**: 暂无")

        return ReportResult("\n".join(lines), not first_join and not last_leave)

    # 生成指定统计日的游玩时长排行榜。
    def _build_rank_report(
        self, target_date: datetime.date, show_live_status: bool
    ) -> ReportResult:
        window_start, window_end = get_time_window(target_date, self.rank_start_hour)
        all_players = self._get_visible_players()
        curr_time = time.time()

        ranked_data: list[tuple[str, int]] = []
        for name, data in all_players.items():
            seconds = 0
            for session in data.get("sessions", []):
                seconds += calculate_overlap(
                    session["start"], session["end"], window_start, window_end
                )

            active_start = self.storage.get_session_start(name)
            if active_start:
                seconds += calculate_overlap(
                    active_start, curr_time, window_start, window_end
                )

            if seconds > 0:
                ranked_data.append((name, seconds))

        ranked_data.sort(key=lambda item: item[1], reverse=True)

        date_display = target_date.strftime("%Y-%m-%d")
        lines = [f"🏆 **MC 魔人排行榜 ({date_display})**"]

        if not ranked_data:
            lines.append("🏳️ 该日期暂无游戏记录。")
            return ReportResult("\n".join(lines), True)

        for index, (name, seconds) in enumerate(ranked_data[:10], start=1):
            is_online = self.storage.get_session_start(name) is not None
            if show_live_status:
                status = "🟢" if is_online else "⚪"
            else:
                status = "👤"
            lines.append(f"{index}. {status} {name}: {seconds_to_text(int(seconds))}")

        active_count = len(ranked_data)
        if active_count == 1:
            lines.append("\n🧍 今天只有一位玩家在守护这个世界。")
        elif active_count == 2:
            lines.append("\n💕 二人世界，方块传情。")
        elif active_count < 5:
            lines.append("\n✨ 小团队也有小团队的快乐。")
        else:
            lines.append("\n🔥 今天服务器很热闹，大家都很爱 MC。")

        return ReportResult("\n".join(lines))

    # 生成单个玩家的累计时长与今日明细。
    def _build_player_report(self, player: str) -> ReportResult:
        if self._is_blacklisted(player):
            return ReportResult(f"❌ 玩家 {player} 已加入黑名单，当前不展示统计数据。")

        data = self.storage.get_player(player)
        if not data:
            return ReportResult(f"❌ 未找到玩家 {player} 的记录。")

        total = seconds_to_text(data.get("total_seconds", 0))
        sessions = data.get("sessions", [])

        today_sessions: list[str] = []
        now = datetime.datetime.now()
        start_of_day = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        for session in sessions:
            if session["start"] >= start_of_day:
                today_sessions.append(
                    f"{format_time(session['start'])}~{format_time(session['end'])}"
                )

        active_start = self.storage.get_session_start(player)
        if active_start:
            today_sessions.append(f"{format_time(active_start)}~现在")

        lines = [f"👤 **{player} 的统计**", f"⏱️ 累计: {total}"]

        if today_sessions:
            lines.append("📮 **今日详情**: " + "、".join(today_sessions))
        else:
            lines.append("📮 今日暂无记录")

        join_times = len(today_sessions)
        if join_times >= 5:
            comment = "🌀 今天进进出出的次数有点夸张，服务器都记住你了。"
        elif join_times >= 3:
            comment = "⚡ 今天状态不错，来来回回都很积极。"
        elif join_times == 2:
            comment = "🎯 进退有度，是个成熟玩家。"
        elif join_times == 1:
            comment = "🪨 一次上线，往往就是一整段冒险。"
        else:
            comment = "👀 今天还没看到你上线，服务器正在等你。"

        lines.append("")
        lines.append(comment)
        return ReportResult("\n".join(lines))

    # 供定时任务使用，解析并执行本插件允许的命令集合。
    def _execute_task_command(self, command_text: str) -> ReportResult:
        normalized = command_text.strip()
        if not normalized:
            return ReportResult("", True)

        # 这里只解析本插件自己的白名单命令，避免定时任务越界执行别的插件逻辑。
        if normalized.startswith("/"):
            normalized = normalized[1:]

        command_name, _, argument = normalized.partition(" ")
        command_name = command_name.lower().strip()
        argument = argument.strip()

        if command_name == "mc_rank":
            target_date, error = self._resolve_date_arg(argument)
            if error:
                return ReportResult(error)
            return self._build_rank_report(
                self._require_date(target_date), show_live_status=not argument
            )

        if command_name == "mc_daily":
            target_date, error = self._resolve_date_arg(argument)
            if error:
                return ReportResult(error)
            return self._build_daily_report(self._require_date(target_date))

        if command_name == "mc_season":
            return self._build_season_report()

        if command_name == "mc_me":
            if not argument:
                return ReportResult("❌ 定时任务中的 /mc_me 必须显式填写玩家 ID。")
            return self._build_player_report(argument)

        return ReportResult(f"❌ 不支持的定时命令: {command_text}")

    # 手动查询当前月份赛季榜。
    @filter.command("mc_season")
    async def cmd_season(self, event: AstrMessageEvent):
        yield event.plain_result(self._build_season_report().text)

    # 手动查询指定日期的日报信息。
    @filter.command("mc_daily")
    async def cmd_daily(self, event: AstrMessageEvent, date_str: str = ""):
        target_date, error = self._resolve_date_arg(date_str)
        if error:
            yield event.plain_result(error)
            return
        yield event.plain_result(
            self._build_daily_report(self._require_date(target_date)).text
        )

    # 手动开启时长监控任务。
    @filter.command("mc_stat_on")
    async def cmd_on(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("❌ 只有管理员可以操作")
            return

        if not self.tracking_task or self.tracking_task.done():
            self.last_check_time = time.time()
            asyncio.create_task(self._start_monitor())
            yield event.plain_result(f"✅ 监控已开启 (interval={self.interval}s)")
        else:
            yield event.plain_result("⚠️ 监控已在运行中")

    # 手动关闭时长监控任务。
    @filter.command("mc_stat_off")
    async def cmd_off(self, event: AstrMessageEvent):
        if not event.is_admin():
            yield event.plain_result("❌ 只有管理员可以操作")
            return

        if self.tracking_task:
            self.tracking_task.cancel()
            self.tracking_task = None
        yield event.plain_result("🛑 监控已停止")

    # 手动查询指定日期的时长排行榜。
    @filter.command("mc_rank")
    async def cmd_rank(self, event: AstrMessageEvent, date_str: str = ""):
        target_date, error = self._resolve_date_arg(date_str)
        if error:
            yield event.plain_result(error)
            return
        yield event.plain_result(
            self._build_rank_report(
                self._require_date(target_date), show_live_status=not date_str
            ).text
        )

    # 手动查询某个玩家的个人统计。
    @filter.command("mc_me")
    async def cmd_me(self, event: AstrMessageEvent, player: str = ""):
        target_player = player or event.get_sender_name()
        yield event.plain_result(self._build_player_report(target_player).text)

    # 绑定、查看或删除定时推送所使用的会话别名。
    @filter.command("mc_push_bind")
    async def cmd_push_bind(
        self, event: AstrMessageEvent, action: str = "", value: str = ""
    ):
        if not event.is_admin():
            yield event.plain_result("❌ 只有管理员可以操作")
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
                yield event.plain_result("📭 当前还没有已绑定的推送会话。")
                return

            lines = ["📮 已绑定推送会话："]
            for alias, session in bindings.items():
                lines.append(f"- {alias}: {session}")
            yield event.plain_result("\n".join(lines))
            return

        if lowered in {"del", "delete", "remove"}:
            alias = self._normalize_alias(value)
            if not alias:
                yield event.plain_result("❌ 请提供要删除的 alias。")
                return
            if not self.storage.delete_push_binding(alias):
                yield event.plain_result(f"❌ 未找到 alias: {alias}")
                return
            yield event.plain_result(f"✅ 已删除推送绑定: {alias}")
            return

        alias = self._normalize_alias(normalized_action)
        if not alias:
            yield event.plain_result("❌ alias 不能为空。")
            return

        session = event.unified_msg_origin
        if not self._supports_proactive_session(session):
            yield event.plain_result("❌ 当前平台不支持主动消息，无法绑定推送目标。")
            return

        previous = self.storage.set_push_binding(alias, session)
        if previous and previous != session:
            yield event.plain_result(
                f"✅ 已更新推送绑定: {alias}\n旧会话: {previous}\n新会话: {session}"
            )
            return

        yield event.plain_result(
            f"✅ 已绑定当前会话到 alias: {alias}\n会话 ID: {session}"
        )

    # 插件卸载时停止后台任务并持久化当前数据。
    async def terminate(self):
        if self.tracking_task:
            self.tracking_task.cancel()

        if self.push_scheduler and self.push_scheduler.running:
            self.push_scheduler.shutdown(wait=False)

        self.storage.save_data()
