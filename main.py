from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import asyncio
import json
import os
import time
import datetime
import struct
from typing import Dict, List, Optional

@register("astrbot_plugin_mc_duration", "YourName", "MC时长统计插件", "1.2.0")
class MCDurationPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        
        # 配置处理
        self.server_ip = self.config.get("server_ip")
        if not self.server_ip:
            self.server_ip = "127.0.0.1"

        self.server_port = int(self.config.get("server_port", 25565))

        self.interval = int(self.config.get("interval", 30))

        self.auto_start = self.config.get("auto_start", True)

        
        self.tracking_task: Optional[asyncio.Task] = None
        
        # 修正路径: data/plugins/plugin_name/data/data.json
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
        self.data_path = os.path.join(self.data_dir, "data.json")
        
        # 数据结构: 
        # { 
        #   "PlayerName": { 
        #       "total_seconds": 0, 
        #       "sessions": [ {"start": 170000, "end": 170060}, ... ] 
        #   } 
        # }
        self.player_data: Dict[str, Dict] = {} 
        
        # 运行时缓存
        self.current_online_names: List[str] = []
        self.session_start_cache: Dict[str, float] = {}
        self.last_check_time = 0.0

        self._load_data()
        # 自动启动
        if self.auto_start:
            asyncio.create_task(self._start_monitor())



    # ==========================
    # 数据管理
    # ==========================

    def _load_data(self):
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    self.player_data = json.load(f)
            except Exception as e:
                logger.error(f"MC统计数据加载失败: {e}")
                self.player_data = {}
        else:
            self.player_data = {}

    def _save_data(self):
        try:
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(self.player_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"MC统计数据保存失败: {e}")

    def _format_time(self, timestamp: float) -> str:
        """时间戳转 HH:MM"""
        return datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M')

    def _seconds_to_text(self, seconds: int) -> str:
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

    # ==========================
    # MC 协议层 (TCP Ping)
    # ==========================

    def _pack_varint(self, val):
        total = b""
        if val < 0: val = (1 << 32) + val
        while True:
            byte = val & 0x7F
            val >>= 7
            if val != 0: byte |= 0x80
            total += bytes([byte])
            if val == 0: break
        return total

    async def _read_varint(self, reader):
        val = 0
        shift = 0
        read_count = 0
        while True:
            byte = await reader.read(1)
            if len(byte) == 0: raise Exception("Connection closed")
            b = byte[0]
            val |= (b & 0x7F) << shift
            read_count += 1
            if read_count > 5: raise Exception("VarInt too big")
            if (b & 0x80) == 0: break
            shift += 7
        return val

    async def _fetch_players(self) -> Optional[List[str]]:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.server_ip, self.server_port), timeout=5.0
            )

            # Handshake
            host = self.server_ip.encode('utf-8') # type: ignore
            port = self.server_port
            handshake = b"\x00" + self._pack_varint(-1) + self._pack_varint(len(host)) + host + struct.pack(">H", port) + self._pack_varint(1)
            writer.write(self._pack_varint(len(handshake)) + handshake)

            # Request
            writer.write(self._pack_varint(1) + b"\x00")
            await writer.drain()

            # Response
            _ = await self._read_varint(reader)
            packet_id = await self._read_varint(reader)
            
            if packet_id == 0:
                json_len = await self._read_varint(reader)
                data_bytes = await reader.readexactly(json_len)
                data = json.loads(data_bytes.decode("utf-8"))
                
                players_list = []
                if "players" in data and "sample" in data["players"]:
                    for p in data["players"]["sample"]:
                        players_list.append(p.get("name", "Unknown"))
                return players_list
            return None
        except Exception:
            return None
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except: pass

    # ==========================
    # 核心监控逻辑
    # ==========================

    async def _start_monitor(self):
        if self.tracking_task and not self.tracking_task.done(): return
        logger.info(f"[MCDuration] 监控启动: {self.server_ip}:{self.server_port}")
        self.tracking_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        # 初始化时间基准
        self.last_check_time = time.time()
        
        while True:
            try:
                # 1. 动态计算 Delta (防止 sleep 误差)
                current_time = time.time()
                delta = current_time - self.last_check_time
                self.last_check_time = current_time
                
                # 异常处理：如果你调试暂停了脚本，delta 可能会巨大，这里限制一下最大只能是 interval * 2
                if delta > self.interval * 2: 
                    delta = float(self.interval)

                fetched_players = await self._fetch_players()

                if fetched_players is not None:
                    # 2. 补全缓存 (重启后自动把在线玩家视为‘刚上线’，防止 start_ts 丢失)
                    for p in fetched_players:
                        if p not in self.session_start_cache:
                            self.session_start_cache[p] = current_time
                        
                        # 初始化数据结构
                        if p not in self.player_data:
                            self.player_data[p] = {"total_seconds": 0, "sessions": []}
                    
                    # 3. 【核心修改 - 方案B】在线玩家累加时长
                    # 每轮都加，而不是下线才加。这样崩服也不会丢最近的数据。
                    for p in fetched_players:
                        self.player_data[p]["total_seconds"] += int(delta) # 强制 int

                    # 4. 处理下线 (End Session)
                    for p in list(self.current_online_names):
                        if p not in fetched_players:
                            # 玩家离开了
                            start_ts = self.session_start_cache.pop(p, None)
                            if start_ts:
                                # 记录 Session，注意！不要再加 total_seconds 了，上面循环已经加了
                                self.player_data[p]["sessions"].append({
                                    "start": int(start_ts),
                                    "end": int(current_time)
                                })

                    self.current_online_names = fetched_players
                    self._save_data()
                
                else:
                    # 获取失败（关服），结算所有人的 Session
                    for p in list(self.current_online_names):
                        start_ts = self.session_start_cache.pop(p, None)
                        if start_ts:
                            self.player_data[p]["sessions"].append({
                                "start": int(start_ts),
                                "end": int(current_time)
                            })
                    self.current_online_names = []
                
                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MCDuration] Loop error: {e}")
                await asyncio.sleep(self.interval)

    # ==========================
    # 指令
    # ==========================

    @filter.command("mc_stat_on")
    async def cmd_on(self, event: AstrMessageEvent):
        '''开启统计 (Admin)'''
        if not event.is_admin():
            yield event.plain_result("❌ 只有管理员可以操作")
            return
            
        if not self.tracking_task or self.tracking_task.done():
            self.last_check_time = time.time() # Reset clock
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
    async def cmd_rank(self, event: AstrMessageEvent):
        # ===== 今日活跃玩家统计 =====
        now = datetime.datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        today_active_players = set()

        for name, data in self.player_data.items():
            sessions = data.get("sessions", [])

            # 1）今天有上线记录的人
            for s in sessions:
                if s["start"] >= start_of_day:
                    today_active_players.add(name)
                    break

            # 2）今天仍在线的人（还没写入 session）
            if name in self.current_online_names:
                today_active_players.add(name)

        today_count = len(today_active_players)

        '''在线时长排行榜(前10)'''
        if not self.player_data:
            yield event.plain_result("📊 暂无数据")
            return

        sorted_players = sorted(
            self.player_data.items(), 
            key=lambda x: x[1].get("total_seconds", 0), 
            reverse=True
        )
        
        msg = ["🏆 **MC魔人排行榜**"]
        for i, (name, data) in enumerate(sorted_players[:10], 1):
            sec = data.get("total_seconds", 0)
            status = "👑" if name in self.current_online_names else "🐶"
            msg.append(f"{i}. {status} {name}: {self._seconds_to_text(sec)}")
            # ===== 彩蛋评语系统 =====
        online_count = today_count

        if online_count == 0:
            msg.append("\n🌙 服务器空空如也，连苦力怕都开始emo了。")

        elif online_count == 1:
            msg.append("\n🧑‍💻 现在知道卷王是怎么练成的吧？一个人撑起整个服务器。")

        elif online_count == 2:
            msg.append("\n💞 我能想到最浪漫的事，就是在MC里和你一起挖到天荒地老。")

        elif online_count < 5:
            msg.append("\n✨ 小团体的快乐，属于你们的方块宇宙。")

        else:
            msg.append("\n🔥 大型网吧现场，全员不睡觉是吧？")
        yield event.plain_result("\n".join(msg))

    @filter.command("mc_me")
    async def cmd_me(self, event: AstrMessageEvent, player: Optional[str] = None):
        '''查询详情 /mc_me [ID]'''
        # 修正：参数可选，没传则取发送者
        if not player:
            player = event.get_sender_name()

        data = self.player_data.get(player)
        if not data:
            yield event.plain_result(f"❌ 未找到玩家 {player} 的记录")
            return

        total = self._seconds_to_text(data.get("total_seconds", 0))
        sessions = data.get("sessions", [])
        
        # 筛选“今天”的记录
        today_sessions = []
        now = datetime.datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        
        for s in sessions:
            if s["start"] >= start_of_day:
                s_str = self._format_time(s["start"])
                e_str = self._format_time(s["end"])
                today_sessions.append(f"{s_str}~{e_str}")

        # 如果当前在线，加一个“进行中”
        if player in self.current_online_names:
            start_ts = self.session_start_cache.get(player, time.time())
            s_str = self._format_time(start_ts)
            today_sessions.append(f"{s_str}~现在")

        msg = [f"👤 **{player} 的统计**"]
        msg.append(f"⏱️ 累计: {total}")
        
        if today_sessions:
            msg.append(f"📅 **今日详情**: " + "、".join(today_sessions))
        else:
            msg.append("📅 今日暂无记录")

        # ===== 玩家评语系统 =====
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
        self._save_data()