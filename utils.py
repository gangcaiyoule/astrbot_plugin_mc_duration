import datetime
import re
from typing import Optional, Tuple


def format_time(timestamp: float, full=False) -> str:
    fmt = "%Y-%m-%d %H:%M" if full else "%H:%M"
    return datetime.datetime.fromtimestamp(timestamp).strftime(fmt)


def seconds_to_text(seconds: int) -> str:
    """把秒数转换成中文可读文本"""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)

    parts = []
    if d > 0:
        parts.append(f"{int(d)}天")
    if h > 0:
        parts.append(f"{int(h)}小时")
    if m > 0:
        parts.append(f"{int(m)}分")
    if not parts:
        return "少于1分钟"
    return "".join(parts)


def parse_date_str(date_str: str) -> Optional[datetime.date]:
    """解析用户输入的日期字符串
    支持: "昨天", "yesterday", "8.5", "2023.8.5", "2023-8-5"
    """
    today = datetime.date.today()
    s = date_str.strip().lower()

    if s in ["昨天", "yesterday", "yes"]:
        return today - datetime.timedelta(days=1)
    if s in ["今天", "today"]:
        return today

    # Try YYYY.MM.DD or MM.DD separators: . - /
    # Regex for YYYY-MM-DD
    match_full = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if match_full:
        try:
            return datetime.date(
                int(match_full.group(1)),
                int(match_full.group(2)),
                int(match_full.group(3)),
            )
        except ValueError:
            return None

    # Regex for MM-DD (current year)
    match_short = re.match(r"(\d{1,2})[.\-/](\d{1,2})", s)
    if match_short:
        try:
            return datetime.date(
                today.year, int(match_short.group(1)), int(match_short.group(2))
            )
        except ValueError:
            return None

    return None


def get_time_window(target_date: datetime.date, start_hour: int) -> Tuple[float, float]:
    """获取指定日期的统计时间窗口 (timestamp start, timestamp end)"""
    start_dt = datetime.datetime.combine(target_date, datetime.time(hour=start_hour))
    end_dt = start_dt + datetime.timedelta(days=1)
    return start_dt.timestamp(), end_dt.timestamp()


def calculate_overlap(
    session_start: float, session_end: float, window_start: float, window_end: float
) -> int:
    """计算某个 session 在指定时间窗口内的时长（秒）"""
    # 取交集
    overlap_start = max(session_start, window_start)
    overlap_end = min(session_end, window_end)

    if overlap_start < overlap_end:
        return int(overlap_end - overlap_start)
    return 0
