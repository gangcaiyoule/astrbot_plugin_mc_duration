from __future__ import annotations


class Emoji:
    RANK = "🏆"
    TOTAL_RANK = "🏅"
    DAILY = "📅"
    SEASON = "📜"
    PLAYER = "👤"
    STORAGE = "💾"
    PUSH = "📬"
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    ONLINE = "🟢"
    OFFLINE = "⚪"
    EARLY = "🌅"
    NIGHT = "🌙"
    TOP = "🔥"
    SPARKLES = "✨"

    @classmethod
    def online_status(cls, is_online: bool) -> str:
        return cls.ONLINE if is_online else cls.OFFLINE
