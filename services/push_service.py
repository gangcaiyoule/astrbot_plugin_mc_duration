from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import logger
from astrbot.api.star import Context
from astrbot.core.message.message_event_result import MessageChain

from ..models import PushTaskConfig
from ..storage import Storage
from .report_service import ReportService


class PushService:
    def __init__(
        self,
        context: Context,
        storage: Storage,
        report_service: ReportService,
        *,
        enabled: bool,
        timezone_name: str,
        tasks: list[PushTaskConfig],
    ):
        self.context = context
        self.storage = storage
        self.report_service = report_service
        self.enabled = enabled
        self.timezone_name = timezone_name
        self.tasks = tasks
        self.scheduler: AsyncIOScheduler | None = None
        self.timezone = self._get_scheduler_timezone()

    @staticmethod
    def normalize_alias(alias: str) -> str:
        return alias.strip().lower()

    def _get_scheduler_timezone(self):
        try:
            return ZoneInfo(self.timezone_name)
        except Exception:
            logger.warning(
                "[MCDuration] 无效的时区 %s, 回退到本地时区",
                self.timezone_name,
            )
            return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc

    def supports_proactive_session(self, session: str) -> bool:
        parts = session.split(":", 2)
        if len(parts) < 3:
            return False
        platform_id = parts[0]
        for platform in self.context.platform_manager.get_insts():
            if platform.meta().id == platform_id:
                return platform.meta().support_proactive_message
        return False

    def _resolve_push_target(self, raw_target: str) -> str | None:
        alias = self.normalize_alias(raw_target)
        if not alias:
            return None

        session = self.storage.get_push_binding(alias)
        if session:
            return session
        if raw_target.count(":") >= 2 and self.supports_proactive_session(raw_target):
            return raw_target
        return None

    def _build_task_run_key(self) -> str:
        return datetime.datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M")

    def start(self) -> None:
        if self.scheduler and self.scheduler.running:
            return
        if not self.enabled:
            logger.info("[MCDuration] 禁用推送调度程序.")
            return

        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        registered_jobs = 0
        for task in self.tasks:
            if not task.enabled or not task.cron or not task.commands:
                continue
            try:
                trigger = CronTrigger.from_crontab(task.cron, timezone=self.timezone)
            except Exception as exc:
                logger.error(
                    "[MCDuration] 无效的cron表达式用于推送任务 %s: %s (%s)",
                    task.name,
                    task.cron,
                    exc,
                )
                continue

            self.scheduler.add_job(
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
            logger.info("[MCDuration] 没有有效的推送任务被注册.")
            return

        self.scheduler.start()
        logger.info(
            "[MCDuration] 推送调度程序已启动，包含 %s 个任务.", registered_jobs
        )

    def shutdown(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def get_bindings(self) -> dict[str, str]:
        return self.storage.get_push_bindings()

    def bind_alias(self, alias: str, session: str) -> str | None:
        return self.storage.set_push_binding(alias, session)

    def delete_binding(self, alias: str) -> bool:
        return self.storage.delete_push_binding(alias)

    async def _run_push_task(self, task: PushTaskConfig) -> None:
        run_key = self._build_task_run_key()
        state = self.storage.get_push_task_state(task.name)
        if state.get("last_run_key") == run_key:
            return

        try:
            reports = [
                self.report_service.execute_task_command(command)
                for command in task.commands
            ]
            reports = [report for report in reports if report.text.strip()]
            if not reports:
                self.storage.update_push_task_state(
                    task.name,
                    last_run_key=run_key,
                    last_status="empty",
                    last_run_at=datetime.datetime.now(self.timezone).isoformat(),
                    last_error="",
                )
                return

            if task.skip_if_empty and all(report.is_empty for report in reports):
                self.storage.update_push_task_state(
                    task.name,
                    last_run_key=run_key,
                    last_status="skipped_empty",
                    last_run_at=datetime.datetime.now(self.timezone).isoformat(),
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
                if session and self.supports_proactive_session(session):
                    if session not in targets:
                        targets.append(session)

            if not targets:
                self.storage.update_push_task_state(
                    task.name,
                    last_run_key=run_key,
                    last_status="no_target",
                    last_run_at=datetime.datetime.now(self.timezone).isoformat(),
                    last_error="No valid push target resolved",
                )
                return

            sent_count = 0
            for session in targets:
                for message in messages:
                    if await self.context.send_message(
                        session,
                        MessageChain().message(message),
                    ):
                        sent_count += 1

            self.storage.update_push_task_state(
                task.name,
                last_run_key=run_key,
                last_status="sent" if sent_count else "send_failed",
                last_run_at=datetime.datetime.now(self.timezone).isoformat(),
                last_error="",
            )
        except Exception as exc:
            logger.error(f"[MCDuration] Push task {task.name} failed: {exc}")
            self.storage.update_push_task_state(
                task.name,
                last_run_key=run_key,
                last_status="error",
                last_run_at=datetime.datetime.now(self.timezone).isoformat(),
                last_error=str(exc),
            )
