<div align="center">

# 🎮 Minecraft 玩家时长统计

[![Plugin Version](https://img.shields.io/badge/Latest_Version-v1.4.1-blue.svg?style=for-the-badge&color=4aac3d)](https://github.com/gangcaiyoule/astrbot_plugin_mc_duration)
[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-ff69b4?style=for-the-badge)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)

_✨ 通过 RCON 协议实时监控 Minecraft 服务器在线玩家，记录游戏时长，提供排行榜和趣味数据统计功能。✨_

<img src="https://count.getloli.com/@astrbot-plugin-mc-duration?name=astrbot-plugin-mc-duration&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="count" />

</div>

## ✨ 功能特性

*   **⏱️ 精准/逻辑时长统计**：
    *   支持**逻辑日**设置：可自定义“一天”的开始时间（例如凌晨 05:00）。
    *   **熬夜党友好**：凌晨 2 点玩游戏会被智能归算到“前一天”的深夜，而不是“第二天”的早起。
*   **🏆 多维度排行榜**：
    *   **赛季魔人榜**：按月统计时长，并附带**成就徽章**（统计本月获得过多少次“日榜首”、“早起王”、“熬夜王”）。
    *   **每日荣誉榜**：自动评选指定日期的“早起魔人”和“熬夜魔人”。
    *   **单日排行榜**：查看今日（或历史指定日期）的肝度排名。
*   **📊 个人日报**：查询自己或他人的详细游戏记录（今日时长、历史总长、进出时间段等）。

## 🛠️ 服务端配置 (必读)

本插件依赖 **RCON** 协议与 Minecraft 服务器通信。请务必在服务器目录下的 `server.properties` 文件中进行如下配置：

```properties
enable-rcon=true
rcon.password=你的强密码
rcon.port=25575
```

> [!NOTE]
> 修改配置后需要重启 Minecraft 服务器。

## ⚙️ 插件配置

安装插件后，请在 AstrBot 的插件配置面板中填写以下信息：

| 配置项 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `server_ip` | Minecraft 服务器 IP 地址 | `127.0.0.1` |
| `server_port` | 游戏端口 (仅作展示) | `25565` |
| `rcon_port` | **RCON 端口** (必须与服务端一致) | `25575` |
| `rcon_password` | **RCON 密码** (必须与服务端一致) | `""` |
| `interval` | 监控轮询间隔 (秒) | `30` |
| `auto_start` | AstrBot 启动时自动开始监控 | `True` |
| `rank_start_hour` | **排行榜起始时间** (0-23)<br>决定每日时长从几点开始累计。填 `0` 代表按自然日计算。 | `0` |
| `daily_start_hour` | **作息判定起始时间** (0-23)<br>决定早起/熬夜的判定界限。填 `5` 代表凌晨 5 点前下线依然算作前一天的深夜。 | `5` |

## 💻 指令列表

日期参数支持格式：`8.5` (8月5日), `2024-1-1`, `昨天`, `yesterday`。不填默认查询今日。

| 指令 | 描述 | 示例 | 权限 |
| :--- | :--- | :--- | :--- |
| `/mc_rank [日期]` | 查看**指定日期**的时长排行榜 | `/mc_rank`<br>`/mc_rank 昨天` | 所有人 |
| `/mc_daily [日期]` | 查看**指定日期**的“早起/熬夜”魔人榜 | `/mc_daily`<br>`/mc_daily 8.5` | 所有人 |
| `/mc_season` | 查看**本月赛季榜** (含成就徽章统计) | `/mc_season` | 所有人 |
| `/mc_me [ID]` | 查询个人或指定玩家的详细统计 | `/mc_me`<br>`/mc_me Notch` | 所有人 |
| `/mc_stat_on` | 开启监控任务 | / | 管理员 |
| `/mc_stat_off` | 暂停监控任务 | / | 管理员 |

## ❗ 注意事项

> [!NOTE]
> 插件默认每 30 秒连接一次 RCON 获取在线列表，流量消耗极低。所有统计数据存储在 `AstrBot/data/plugin_data/astrbot_plugin_mc_duration/data.json` 中。

> [!WARNING]
> 如果在云服务器或 Docker 环境运行，请确保 AstrBot 能访问到 Minecraft 服务器的 RCON 端口（需配置防火墙/安全组）。

> [!IMPORTANT]
> 本插件依赖 RCON 协议，请务必在 `server.properties` 中启用 RCON 并设置强密码，避免暴露在公网。

如果有任何 Bug 反馈或功能建议，欢迎联系作者 QQ: **964389211**
