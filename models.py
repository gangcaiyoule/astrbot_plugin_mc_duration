from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SAVE_NAME = "默认存档"


@dataclass(slots=True)
class SaveRecord:
    save_id: str
    name: str
    created_at: str
    is_active: bool
    player_count: int = 0
    session_count: int = 0


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
