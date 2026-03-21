from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import asyncio
import time
import datetime
import os
from typing import Optional

from .rcon import MCRcon
from .storage import Storage
from .utils import seconds_to_text, format_time, parse_date_str, get_time_window, calculate_overlap

@register("astrbot_plugin_mc_duration", "YourName", "MC时长统计插件", "1.3.0")
class MCDurationPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        
        # 配置处理
        self.server_ip = self.config.get("server_ip", "127.0.0.1")
        self.server_port = int(self.config.get("server_port", 25565))
        self.rcon_port = int(self.config.get("rcon_port", 25575))
        self.rcon_password = self.config.get("rcon_password", "")
        self.interval = int(self.config.get("interval", 30))
        self.auto_start = self.config.get("auto_start", True)
        self.rank_start_hour = int(self.config.get("rank_start_hour", 0))    # 默认按自然日
        self.daily_start_hour = int(self.config.get("daily_start_hour", 5))  # 默认按逻辑日(5点)

        # 初始化组件
        # 建议将数据存放在 data/plugin_data/ 目录下，避免插件更新导致数据丢失
        # 定位到 data/ 目录 (假设插件在 data/plugins/plugin_name/)
        data_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        data_dir = os.path.join(data_root, "plugin_data", "astrbot_plugin_mc_duration")
        
        self.storage = Storage(data_dir)
        self.rcon = MCRcon(self.server_ip, self.server_port, self.rcon_password, self.rcon_port)
        
        self.tracking_task: Optional[asyncio.Task] = None
        self.last_check_time = 0.0

        # 自动启动
        if self.auto_start:
            asyncio.create_task(self._start_monitor())

    # ==========================
    # 核心监控逻辑
    # ==========================
    
    async def _start_monitor(self):
        if self.tracking_task and not self.tracking_task.done(): return
        logger.info(f"[MCDuration] 监控启动: {self.server_ip}")
        self.tracking_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        self.last_check_time = time.time()
        while True:
            try:
                curr_time = time.time()
                delta = min(curr_time - self.last_check_time, self.interval * 2)
                self.last_check_time = curr_time
                
                players = await self.rcon.fetch_players()

                if players is not None:
                    # 更新在线时长 & 处理上线逻辑
                    self.storage.update_playtime(players, delta, curr_time)

                    # 处理下线逻辑
                    # 找出在 cache 中但不在当前 players 列表中的人
                    online_in_cache = list(self.storage.session_start_cache.keys())
                    left_players = [p for p in online_in_cache if p not in players]
                    
                    if left_players:
                        self.storage.handle_disconnects(left_players, curr_time)

                    self.storage.save_data()
                else:
                    logger.warning(f"[MCDuration] RCON 获取玩家列表失败")
                    # 如果连接失败，假设所有当前在线的人都下线了（为了数据安全，防止无限累计时间）
                    online_players = list(self.storage.session_start_cache.keys())
                    if online_players:
                        self.storage.handle_disconnects(online_players, curr_time)

                await asyncio.sleep(self.interval)
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"[MCDuration] Loop error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(self.interval)

    # ==========================
    # 指令
    # ==========================
    def _calculate_daily_stats(self, target_date: datetime.date, all_players: dict) -> tuple[str | None, str | None, str | None]:
        """计算指定日期的各项魔人归属 (榜首, 早起, 熬夜)"""
        # 1. 计算排行榜首 (使用 rank_start_hour)
        t_start, t_end = get_time_window(target_date, self.rank_start_hour)
        max_sec = 0
        top_player = None
        
        for name, data in all_players.items():
            sec = 0
            for s in data.get("sessions", []):
                sec += calculate_overlap(s["start"], s["end"], t_start, t_end)
            
            # 这里是离线计算历史数据，不考虑 curr_time 在线情况，只看已落库的sessions
            # 如果要非常精确，需要传入当时的“实时”数据，但对于过去日期，sessions已足够
            if sec > max_sec:
                max_sec = sec
                top_player = name
                
        # 2. 计算作息魔人 (使用 daily_start_hour)
        t_start_d, t_end_d = get_time_window(target_date, self.daily_start_hour)
        first_p, last_p = None, None
        first_t, last_t = None, None

        for name, data in all_players.items():
            for s in data.get("sessions", []):
                # 早起: Start 在窗口内，且最早
                if s["start"] >= t_start_d and s["start"] < t_end_d:
                    if first_t is None or s["start"] < first_t:
                        first_t = s["start"]
                        first_p = name
                        
                # 熬夜: End 在窗口内，且最晚 (end <= t_end_d 防止判定明天)
                # 使用 calculate_overlap 判定是否在窗口内有交集也可以
                if s["end"] > t_start_d and s["end"] <= t_end_d:
                    if last_t is None or s["end"] > last_t:
                        last_t = s["end"]
                        last_p = name

        return top_player, first_p, last_p

    @filter.command("mc_season")
    async def cmd_season(self, event: AstrMessageEvent):
        '''赛季魔人榜 (本月排行榜)'''
        # 赛季依然按自然月计算 (1号0点 - 下月1号0点)
        now = datetime.datetime.now()
        cur_year, cur_month = now.year, now.month
        
        month_start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Handle December case
        if now.month == 12:
            next_month_dt = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month_dt = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
        month_start = month_start_dt.timestamp()
        month_end = next_month_dt.timestamp()
        
        monthly_stats = []
        all_players = self.storage.get_all_players()
        curr_time = time.time()

        # ==========================================
        # 1. 统计本月总时长
        # ==========================================
        for name, data in all_players.items():
            sec = 0
            # Archive sessions
            for s in data.get("sessions", []):
                sec += calculate_overlap(s["start"], s["end"], month_start, month_end)
            
            # Current session
            start = self.storage.get_session_start(name)
            if start:
                sec += calculate_overlap(start, curr_time, month_start, month_end)

            if sec > 0:
                monthly_stats.append({"name": name, "sec": sec, "badges": []})

        if not monthly_stats:
            yield event.plain_result(f"📊 {cur_month}月赛季暂无玩家数据。")
            return

        # ==========================================
        # 2. 回溯本月每一天，统计成就
        # ==========================================
        # 统计计数器: {player_name: {"top": 0, "early": 0, "night": 0}}
        achievements = {entry["name"]: {"top": 0, "early": 0, "night": 0} for entry in monthly_stats}
        
        # 遍历从1号到昨天 (今天仍在进行中，也可以算，但为了稳定建议算到昨天? )
        # 需求里隐含是“获得过”，通常包含今天(如果今天榜单已初具雏形)
        # 遍历: 1号 -> 今天 (now.day)
        today = datetime.date.today()
        # 构造日期列表: 1号 ... 今天
        date_list = [datetime.date(cur_year, cur_month, d) for d in range(1, today.day + 1)]
        
        for d in date_list:
            top, first, last = self._calculate_daily_stats(d, all_players)
            if top and top in achievements: achievements[top]["top"] += 1
            if first and first in achievements: achievements[first]["early"] += 1
            if last and last in achievements: achievements[last]["night"] += 1

        # ==========================================
        # 3. 格式化输出
        # ==========================================
        monthly_stats.sort(key=lambda x: x["sec"], reverse=True)
        msg = [f"📅 **{cur_month}月赛季魔人榜 ({cur_year})** 📅"]
        
        for i, item in enumerate(monthly_stats[:15], 1): # Top 15
            name = item["name"]
            sec_str = seconds_to_text(int(item["sec"]))
            # Online status
            is_online = self.storage.get_session_start(name) is not None
            status = "👑" if is_online else "🌙"
            
            # Build Badge String
            ach = achievements.get(name, {})
            badges_str = ""
            b_list = []
            if ach.get("top", 0) > 0: b_list.append(f"🏆x{ach['top']}")
            if ach.get("early", 0) > 0: b_list.append(f"🐔x{ach['early']}")
            if ach.get("night", 0) > 0: b_list.append(f"🦉x{ach['night']}")
            if b_list:
                badges_str = f"  [{' '.join(b_list)}]"

            msg.append(f"{i}. {status} {name}: {sec_str}{badges_str}")
        
        msg.append("\n----------------")
        msg.append("图例: 🏆魔人榜首 | 🐔早起魔人 | 🦉熬夜魔人")
        yield event.plain_result("\n".join(msg))

    @filter.command("mc_daily")
    async def cmd_daily(self, event: AstrMessageEvent, date_str: str = ""):
        '''每日荣誉榜 [日期]'''
        target_date = parse_date_str(date_str) if date_str else datetime.date.today()
        if not target_date:
            yield event.plain_result(f"❌ 日期格式无法识别: {date_str}。请尝试 '8.5', '2023-01-01', '昨天'")
            return
            
        # 使用配置的 daily_start_hour 计算时间窗口
        t_start, t_end = get_time_window(target_date, self.daily_start_hour)
        
        first_join = None # (player, time)
        last_leave = None # (player, time)

        all_players = self.storage.get_all_players()
        curr_time = time.time()

        for name, data in all_players.items():
            sessions = data.get("sessions", [])
            # 检查是否有在这个时间段内的活动
            
            # 合并历史 session 和当前 session
            check_list = sessions.copy()
            active_start = self.storage.get_session_start(name)
            if active_start:
                check_list.append({"start": active_start, "end": curr_time})

            for s in check_list:
                s_start, s_end = s["start"], s["end"]
                
                # 判定: 只关心在这个窗口内有效发生的行为
                # 忽略完全在窗口外的
                if s_end <= t_start or s_start >= t_end:
                    continue

                # 早起判定: Start time 必须在窗口内
                # 如果 s_start < t_start，说明他是前一天玩到今天的，不算“今天早起”
                if s_start >= t_start:
                    if not first_join or s_start < first_join[1]:
                        first_join = (name, s_start)
                
                # 熬夜判定: End time 必须在窗口内
                # 如果 s_end > t_end，说明他玩到了明天，会在明天的 daily 中被归类（或不算熬夜，待定）
                # 这里我们寻找最晚离开的人
                if s_end <= t_end:
                     if not last_leave or s_end > last_leave[1]:
                        last_leave = (name, s_end)
                else:
                    # 此时 s_end > t_end, 说明一直在线没下线，或者下线时间在明天
                    # 在逻辑日结算时，还没下线通常被视为“修仙中”，暂不判定为熬夜（因为还没睡）
                    # 或者可以将当前时刻视作“暂时的下线时间”来参与评比?
                    # 按照原需求“熬夜魔人”通常指很晚下线。如果还在玩，可能不在此列。
                    # 这里按 Logic: 只看已发生的 end <= t_end. 如果还没下线，不算做"熬夜结束"
                    pass

        date_disp = target_date.strftime("%Y-%m-%d")
        msg = [f"🌅 **今日方块荣誉 ({date_disp})**"]
        
        if first_join:
            msg.append(f"🐔 **早起魔人**: {first_join[0]} ({format_time(first_join[1])})")
        else:
            msg.append("🐔 **早起魔人**: 暂无")
            
        if last_leave:
            msg.append(f"🦉 **熬夜魔人**: {last_leave[0]} ({format_time(last_leave[1])})")
        else:
            msg.append("🦉 **熬夜魔人**: 暂无")
            
        yield event.plain_result("\n".join(msg))

    @filter.command("mc_stat_on")
    async def cmd_on(self, event: AstrMessageEvent):
        '''开启统计 (Admin)'''
        if not event.is_admin():
            yield event.plain_result("❌ 只有管理员可以操作")
            return
            
        if not self.tracking_task or self.tracking_task.done():
            self.last_check_time = time.time()
            asyncio.create_task(self._start_monitor())
            yield event.plain_result(f"✅ 监控已开启 (interval={self.interval}s)")
        else:
            yield event.plain_result("⚠️ 监控已在运行中")

    @filter.command("mc_stat_off")
    async def cmd_off(self, event: AstrMessageEvent):
        '''关闭统计 (Admin)'''
        if not event.is_admin():
            yield event.plain_result("❌ 只有管理员可以操作")
            return

        if self.tracking_task:
            self.tracking_task.cancel()
            self.tracking_task = None
        yield event.plain_result("🛑 监控已停止")

    @filter.command("mc_rank")
    async def cmd_rank(self, event: AstrMessageEvent, date_str: str = ""):
        '''MC魔人排行榜 [日期]'''
        target_date = parse_date_str(date_str) if date_str else datetime.date.today()
        if not target_date:
            yield event.plain_result(f"❌ 日期格式无法识别: {date_str}。")
            return

        # 使用配置的 rank_start_hour 计算时间窗口
        t_start, t_end = get_time_window(target_date, self.rank_start_hour)
        
        # 计算该时间段内的活跃玩家和时长
        ranked_data = [] # (name, seconds)
        all_players = self.storage.get_all_players()
        curr_time = time.time()
        
        online_count = 0 

        for name, data in all_players.items():
            sec = 0
            # 1. 历史 sessions
            for s in data.get("sessions", []):
                sec += calculate_overlap(s["start"], s["end"], t_start, t_end)
            
            # 2. 当前 session
            active_start = self.storage.get_session_start(name)
            if active_start:
                # 只有当这是查“今天”时，统计当前在线才算作“当前在线人数”
                # 如果查历史日期，current_online_names 意义不大，online_count 仅指当时活跃过的人?
                # 这里为了简单，online_count 仍指 *此刻* 在线，用于输出彩蛋 (仅当查询今天时有效)
                pass 
                sec += calculate_overlap(active_start, curr_time, t_start, t_end)

            if sec > 0:
                ranked_data.append((name, sec))

        ranked_data.sort(key=lambda x: x[1], reverse=True)
        
        date_disp = target_date.strftime("%Y-%m-%d")
        msg = [f"🏆 **MC魔人排行榜 ({date_disp})**"]
        
        for i, (name, sec) in enumerate(ranked_data[:10], 1):
            is_online = self.storage.get_session_start(name) is not None
            # 只有查今天才显示在线状态徽章，否则都是离线
            status = ("👑" if is_online else "🐶") if date_str == "" else "👤"
            msg.append(f"{i}. {status} {name}: {seconds_to_text(int(sec))}")

        if not ranked_data:
            msg.append("📊 该日期暂无游戏记录。")
            yield event.plain_result("\n".join(msg))
            return

        # 彩蛋逻辑 (仅当查询今日时准确)
        # 如果是查询历史，根据当天的活跃人数来发彩蛋
        active_count = len(ranked_data)
        
        if active_count == 0:
            msg.append("\n🌙 这一天服务器静悄悄的。")
        elif active_count == 1:
            msg.append("\n🧑‍💻 孤独的守望者，一个人撑起一片天。")
        elif active_count == 2:
            msg.append("\n💞 二人世界，方块传情。")
        elif active_count < 5:
            msg.append("\n✨ 小团体的快乐，属于你们的方块宇宙。")
        else:
            msg.append("\n🔥 火热的一天，大家都爱MC！")
            
        yield event.plain_result("\n".join(msg))

    @filter.command("mc_me")
    async def cmd_me(self, event: AstrMessageEvent, player: Optional[str] = None):
        '''查询详情 /mc_me [ID]'''
        if not player:
            player = event.get_sender_name()

        data = self.storage.get_player(player)
        if not data:
            yield event.plain_result(f"❌ 未找到玩家 {player} 的记录")
            return

        total = seconds_to_text(data.get("total_seconds", 0))
        sessions = data.get("sessions", [])
        
        # 筛选“今天”的记录
        today_sessions = []
        now = datetime.datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        
        for s in sessions:
            if s["start"] >= start_of_day:
                s_str = format_time(s["start"])
                e_str = format_time(s["end"])
                today_sessions.append(f"{s_str}~{e_str}")

        # 如果当前在线
        start_ts = self.storage.get_session_start(player)
        if start_ts:
            s_str = format_time(start_ts)
            today_sessions.append(f"{s_str}~现在")

        msg = [f"👤 **{player} 的统计**"]
        msg.append(f"⏱️ 累计: {total}")
        
        if today_sessions:
            msg.append(f"📅 **今日详情**: " + "、".join(today_sessions))
        else:
            msg.append("📅 今日暂无记录")

        # 评语
        join_times = len(today_sessions)
        if join_times >= 5:
            comment = "🚪 你这是把服务器当旋转门啊，进进出出比末影人还快。"
        elif join_times >= 3:
            comment = "⚡ 虽然我不够持久，但我胜在进出速度快！"
        elif join_times == 2:
            comment = "🎮 今天状态不错，属于是‘进退有度’的成熟玩家。"
        elif join_times == 1:
            comment = "🪵 哥玩的就是持久，一上线就是一整段史诗。"
        else:
            comment = "👻 今天你还没出现…服务器都在想你。"

        msg.append("\n" + comment)
        yield event.plain_result("\n".join(msg))

    async def terminate(self):
        if self.tracking_task: self.tracking_task.cancel()
        self.storage.save_data()
