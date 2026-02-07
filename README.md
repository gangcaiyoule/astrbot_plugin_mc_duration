# 🎮 Minecraft 玩家时长统计 (astrbot_plugin_mc_duration)

一个用于 AstrBot 的 Minecraft 服务器玩家在线时长统计插件。通过 RCON 协议实时监控服务器在线玩家，记录游戏时长，并在群内提供丰富的排行榜和趣味数据统计功能。

## ✨ 功能特性

*   **⏱️ 精准时长统计**：基于定时轮询 (RCON)，精准记录每位玩家的游戏时长。
*   **🏆 多维度排行榜**：
    *   **赛季魔人榜**：按月统计，看看谁是当月“肝帝”。
    *   **每日荣誉榜**：自动评选“早起魔人”和“熬夜魔人”。
    *   **总排行榜**：服务器历史总时长排行。
*   **📊 个人日报**：查询自己或他人的详细游戏记录（今日时长、历史总长、进出时间段等）。

## 🛠️ 服务端配置 (必读)

本插件依赖 **RCON** 协议与 Minecraft 服务器通信。请务必在服务器目录下的 `server.properties` 文件中进行如下配置：

```properties
enable-rcon=true
rcon.password=你的强密码
rcon.port=25575
```

*修改配置后需要重启 Minecraft 服务器。*

## ⚙️ 插件配置

安装插件后，请在 AstrBot 的插件配置面板中填写以下信息：

| 配置项 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `server_ip` | Minecraft 服务器 IP 地址 | `127.0.0.1` |
| `server_port` | 游戏端口 (仅作展示) | `25565(可选)` |
| `rcon_port` | **RCON 端口** (必须与服务端一致) | `25575` |
| `rcon_password` | **RCON 密码** (必须与服务端一致) | `""` |
| `interval` | 监控轮询间隔 (秒) | `30` |
| `auto_start` | AstrBot 启动时自动开始监控 | `True` |

## 💻 指令列表

| 指令 | 描述 | 权限 |
| :--- | :--- | :--- |
| `/mc_rank` | 查看服务器总时长排行榜及当前在线状态 | 所有人 |
| `/mc_season` | 查看本月赛季时长排行榜 | 所有人 |
| `/mc_daily` | 查看今日“早起/熬夜”魔人榜 | 所有人 |
| `/mc_me [ID]` | 查询个人或指定玩家的详细统计 | 所有人 |
| `/mc_stat_on` | 开启监控任务 | 管理员 |
| `/mc_stat_off` | 暂停监控任务 | 管理员 |

## ❗ 注意事项

*   插件默认每 30 秒连接一次 RCON 获取在线列表，流量消耗极低。
*   所有的统计数据存储在 `AstrBot/data/plugin_data/astrbot_plugin_mc_duration/data.json` 中。
*   如果在云服务器或 Docker 环境运行，请确保 AstrBot 能访问到 Minecraft 服务器的 RCON 端口 (防火墙/安全组)。

---
*Developed for AstrBot*
