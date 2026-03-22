from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astrbot.api import AstrBotConfig

from .models import PushTaskConfig


def parse_blacklist(raw_value: Any) -> set[str]:
    if raw_value is None:
        return set()
    if isinstance(raw_value, str):
        candidates = raw_value.replace("，", ",").replace("\n", ",").replace(" ", ",")
        values = candidates.split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        values = [str(item) for item in raw_value]
    else:
        values = [str(raw_value)]
    return {name.strip() for name in values if name and name.strip()}


def parse_push_tasks(raw_tasks: Any) -> list[PushTaskConfig]:
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


@dataclass(slots=True)
class PluginSettings:
    server_ip: str
    server_port: int
    rcon_port: int
    rcon_password: str
    interval: int
    auto_start: bool
    rank_start_hour: int
    daily_start_hour: int
    player_blacklist: set[str]
    push_scheduler_enabled: bool
    push_scheduler_timezone_name: str
    push_tasks: list[PushTaskConfig]

    @classmethod
    def from_config(cls, config: AstrBotConfig) -> PluginSettings:
        push_cfg = config.get("push_scheduler", {}) or {}
        return cls(
            server_ip=config.get("server_ip", "127.0.0.1"),
            server_port=int(config.get("server_port", 25565)),
            rcon_port=int(config.get("rcon_port", 25575)),
            rcon_password=config.get("rcon_password", ""),
            interval=int(config.get("interval", 30)),
            auto_start=bool(config.get("auto_start", True)),
            rank_start_hour=int(config.get("rank_start_hour", 0)),
            daily_start_hour=int(config.get("daily_start_hour", 5)),
            player_blacklist=parse_blacklist(config.get("player_blacklist", "")),
            push_scheduler_enabled=bool(push_cfg.get("enabled", False)),
            push_scheduler_timezone_name=str(
                push_cfg.get("timezone", "Asia/Shanghai") or "Asia/Shanghai"
            ),
            push_tasks=parse_push_tasks(push_cfg.get("tasks", [])),
        )
