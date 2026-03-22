from __future__ import annotations

import os

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .config import PluginSettings
from .rcon import MCRcon
from .services import PushService, ReportService, SaveService, TrackerService
from .storage import Storage


@register("astrbot_plugin_mc_duration", "gangcaiyoule", "MC时长统计插件", "1.7.0")
class MCDurationPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.settings = PluginSettings.from_config(config)

        data_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        data_dir = os.path.join(data_root, "plugin_data", "astrbot_plugin_mc_duration")

        self.storage = Storage(data_dir)
        self.rcon = MCRcon(
            self.settings.server_ip,
            self.settings.server_port,
            self.settings.rcon_password,
            self.settings.rcon_port,
        )
        self.tracker_service = TrackerService(
            storage=self.storage,
            rcon=self.rcon,
            interval=self.settings.interval,
            player_blacklist=self.settings.player_blacklist,
        )
        self.report_service = ReportService(
            storage=self.storage,
            tracker=self.tracker_service,
            rank_start_hour=self.settings.rank_start_hour,
            daily_start_hour=self.settings.daily_start_hour,
            player_blacklist=self.settings.player_blacklist,
        )
        self.save_service = SaveService(
            storage=self.storage,
            tracker=self.tracker_service,
        )
        self.push_service = PushService(
            context=self.context,
            storage=self.storage,
            report_service=self.report_service,
            enabled=self.settings.push_scheduler_enabled,
            timezone_name=self.settings.push_scheduler_timezone_name,
            tasks=self.settings.push_tasks,
        )

        if self.settings.player_blacklist:
            logger.info(
                "[MCDuration] Blacklist enabled: %s",
                ", ".join(sorted(self.settings.player_blacklist)),
            )
        if self.settings.auto_start:
            self.tracker_service.start()

    async def initialize(self):
        self.push_service.start()

    @staticmethod
    def _is_admin(event: AstrMessageEvent) -> bool:
        return event.is_admin()

    @filter.command("mc_season")
    async def cmd_season(self, event: AstrMessageEvent):
        yield event.plain_result(self.report_service.build_season_report().text)

    @filter.command("mc_daily")
    async def cmd_daily(self, event: AstrMessageEvent, date_str: str = ""):
        target_date, error = self.report_service.resolve_date_arg(date_str)
        if error:
            yield event.plain_result(error)
            return
        yield event.plain_result(
            self.report_service.build_daily_report(
                self.report_service.require_date(target_date)
            ).text
        )

    @filter.command("mc_stat_on")
    async def cmd_on(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员可以操作。")
            return
        if self.tracker_service.is_running():
            yield event.plain_result("监控已经在运行中了。")
            return
        self.tracker_service.start()
        yield event.plain_result(f"监控已开启 (interval={self.settings.interval}s)")

    @filter.command("mc_stat_off")
    async def cmd_off(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员可以操作。")
            return
        await self.tracker_service.stop()
        yield event.plain_result("监控已停止。")

    @filter.command("mc_rank")
    async def cmd_rank(self, event: AstrMessageEvent, date_str: str = ""):
        if date_str.strip().lower() == "all":
            yield event.plain_result(self.report_service.build_total_rank_report().text)
            return
        target_date, error = self.report_service.resolve_date_arg(date_str)
        if error:
            yield event.plain_result(error)
            return
        yield event.plain_result(
            self.report_service.build_rank_report(
                self.report_service.require_date(target_date),
                show_live_status=not date_str,
            ).text
        )

    @filter.command("mc_me")
    async def cmd_me(self, event: AstrMessageEvent, player: str = ""):
        yield event.plain_result(
            self.report_service.build_player_report(
                player or event.get_sender_name()
            ).text
        )

    @filter.command("mc_push_bind")
    async def cmd_push_bind(
        self, event: AstrMessageEvent, action: str = "", value: str = ""
    ):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员可以操作。")
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
            bindings = self.push_service.get_bindings()
            if not bindings:
                yield event.plain_result("当前还没有已绑定的推送会话。")
                return
            lines = ["已绑定推送会话:"]
            for alias, session in bindings.items():
                lines.append(f"- {alias}: {session}")
            yield event.plain_result("\n".join(lines))
            return

        if lowered in {"del", "delete", "remove"}:
            alias = self.push_service.normalize_alias(value)
            if not alias:
                yield event.plain_result("请提供要删除的 alias。")
                return
            if self.push_service.delete_binding(alias):
                yield event.plain_result(f"已删除推送绑定: {alias}")
            else:
                yield event.plain_result(f"未找到 alias: {alias}")
            return

        alias = self.push_service.normalize_alias(normalized_action)
        session = event.unified_msg_origin
        if not alias:
            yield event.plain_result("alias 不能为空。")
            return
        if not self.push_service.supports_proactive_session(session):
            yield event.plain_result("当前平台不支持主动消息，无法绑定推送目标。")
            return

        previous = self.push_service.bind_alias(alias, session)
        if previous and previous != session:
            yield event.plain_result(
                f"已更新推送绑定: {alias}\n旧会话: {previous}\n新会话: {session}"
            )
        else:
            yield event.plain_result(
                f"已绑定当前会话到 alias: {alias}\n会话 ID: {session}"
            )

    @filter.command("mc_save_list")
    async def cmd_save_list(self, event: AstrMessageEvent):
        active_id = self.storage.get_active_save().save_id
        lines = ["存档列表:"]
        for save in self.storage.list_saves():
            marker = "*" if save.save_id == active_id else "-"
            lines.append(
                f"{marker} {save.name} [{save.save_id[:8]}] 玩家 {save.player_count} 人，会话 {save.session_count} 条"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("mc_save_current")
    async def cmd_save_current(self, event: AstrMessageEvent):
        active = self.storage.get_active_save()
        yield event.plain_result(
            f"当前存档: {active.name}\nID: {active.save_id}\n创建时间: {active.created_at}"
        )

    @filter.command("mc_save_create")
    async def cmd_save_create(self, event: AstrMessageEvent, name: str = ""):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员可以操作。")
            return
        if not name.strip():
            yield event.plain_result("用法: /mc_save_create <存档名>")
            return
        try:
            save = await self.save_service.create_and_switch(name)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        yield event.plain_result(
            f"已创建并切换到新存档: {save.name}\nID: {save.save_id}"
        )

    @filter.command("mc_save_switch")
    async def cmd_save_switch(self, event: AstrMessageEvent, identifier: str = ""):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员可以操作。")
            return

        target = identifier.strip()
        if not target:
            yield event.plain_result("用法: /mc_save_switch <存档名或ID>")
            return

        resolved = self.storage.resolve_save(target)
        if not resolved:
            yield event.plain_result(f"未找到存档: {target}")
            return
        if resolved.save_id == self.storage.get_active_save().save_id:
            yield event.plain_result(f"当前已经在存档 {resolved.name}。")
            return

        save = await self.save_service.switch(resolved.save_id)
        yield event.plain_result(f"已切换到存档: {save.name}\nID: {save.save_id}")

    @filter.command("mc_save_delete")
    async def cmd_save_delete(
        self, event: AstrMessageEvent, identifier: str = "", confirm: str = ""
    ):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员可以操作。")
            return

        target = identifier.strip()
        if not target:
            yield event.plain_result("用法: /mc_save_delete <存档名或ID> confirm")
            return
        if confirm.strip().lower() != "confirm":
            yield event.plain_result(
                f"该操作会永久删除存档 {target} 的全部数据。\n"
                f"请使用 /mc_save_delete {target} confirm 确认执行。"
            )
            return

        try:
            save = await self.save_service.delete_save(target)
        except LookupError:
            yield event.plain_result(f"未找到存档: {target}")
            return
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return

        yield event.plain_result(f"已删除存档: {save.name}")

    @filter.command("mc_save_player_delete")
    async def cmd_save_player_delete(
        self,
        event: AstrMessageEvent,
        save_identifier: str = "",
        player_name: str = "",
        confirm: str = "",
    ):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员可以操作。")
            return
        if not save_identifier.strip() or not player_name.strip():
            yield event.plain_result(
                "用法: /mc_save_player_delete <存档名或ID> <玩家名> confirm"
            )
            return
        if confirm.strip().lower() != "confirm":
            yield event.plain_result(
                f"该操作会永久删除玩家 {player_name} 在存档 {save_identifier} 中的数据。\n"
                f"请使用 /mc_save_player_delete {save_identifier} {player_name} confirm 确认执行。"
            )
            return

        try:
            save, deleted = await self.save_service.delete_player_data(
                save_identifier.strip(),
                player_name.strip(),
            )
        except LookupError:
            yield event.plain_result(f"未找到存档: {save_identifier}")
            return

        if deleted:
            yield event.plain_result(
                f"已删除玩家 {player_name} 在存档 {save.name} 中的数据。"
            )
        else:
            yield event.plain_result(
                f"未找到玩家 {player_name} 在存档 {save_identifier} 中的数据。"
            )

    async def terminate(self):
        await self.tracker_service.stop()
        self.push_service.shutdown()
        self.storage.save_data()
