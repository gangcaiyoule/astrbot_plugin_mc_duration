import datetime

def format_time(timestamp: float, full=False) -> str:
    fmt = '%Y-%m-%d %H:%M' if full else '%H:%M'
    return datetime.datetime.fromtimestamp(timestamp).strftime(fmt)

def seconds_to_text(seconds: int) -> str:
    """把秒数转换成中文可读文本"""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    
    parts = []
    if d > 0: parts.append(f"{int(d)}天")
    if h > 0: parts.append(f"{int(h)}小时")
    if m > 0: parts.append(f"{int(m)}分")
    if not parts: return "少于1分钟"
    return "".join(parts)
