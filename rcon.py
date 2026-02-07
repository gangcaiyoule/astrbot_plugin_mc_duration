import asyncio
import struct
from typing import Optional, List
from astrbot.api import logger

class MCRcon:
    def __init__(self, host: str, port: int, password: str, rcon_port: int):
        self.host = host
        self.port = port
        self.rcon_port = rcon_port
        self.password = password

    async def send_command(self, command: str) -> Optional[str]:
        """Send a command via RCON and return the response."""
        reader, writer = None, None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.rcon_port), timeout=5.0
            )

            async def send_packet(pkt_type: int, payload: str, pkt_id: int):
                data = struct.pack("<ii", pkt_id, pkt_type) + payload.encode('utf-8') + b"\x00\x00"
                writer.write(struct.pack("<i", len(data)) + data)
                await writer.drain()

            async def read_packet():
                length_pkt = await reader.readexactly(4)
                length = struct.unpack("<i", length_pkt)[0]
                data = await reader.readexactly(length)
                pkt_id, pkt_type = struct.unpack("<ii", data[:8])
                return pkt_id, pkt_type, data[8:-2].decode('utf-8')

            # 1. Auth
            await send_packet(3, self.password, 1)
            auth_id, _, _ = await read_packet()
            if auth_id == -1:
                logger.error(f"[MCDuration] RCON 认证失败: 密码错误。 IP: {self.host}")
                return None

            # 2. Command
            await send_packet(2, command, 2)
            _, _, response = await read_packet()
            return response
        except asyncio.TimeoutError:
            logger.error(f"[MCDuration] RCON 连接超时，请检查防火墙/安全组 {self.rcon_port} 端口是否开放。")
            return None
        except ConnectionRefusedError:
            logger.error(f"[MCDuration] RCON 连接被拒绝，请检查服端 server.properties 中 enable-rcon 是否为 true。")
            return None
        except Exception as e:
            logger.error(f"[MCDuration] RCON 运行异常: {str(e)}")
            return None

        finally:
            if writer:
                writer.close()
                await writer.wait_closed()

    async def fetch_players(self) -> Optional[List[str]]:
        """Fetch player list using RCON /list."""
        resp = await self.send_command("list")
        if not resp:
            return None
        
        # Vanilla/Paper output: "There are X of Y players online: name1, name2"
        # Or: "There are X players online: name1, name2"
        if ":" not in resp:
            return []
        
        names_str = resp.split(":", 1)[1].strip()
        if not names_str:
            return []
            
        names = [n.strip() for n in names_str.split(",")]
        return [n for n in names if n]
