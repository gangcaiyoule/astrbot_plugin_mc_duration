<div align="center">

# 🎮 Minecraft 玩家时长统计

[![Plugin Version](https://img.shields.io/badge/Latest_Version-v1.7.0-blue.svg?style=for-the-badge&color=4aac3d)](https://github.com/gangcaiyoule/astrbot_plugin_mc_duration)
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
*   **📮 定时主动推送**：
    *   支持在 WebUI 中配置多个定时任务。
    *   支持定时执行 `/mc_rank`、`/mc_daily`、`/mc_season`、`/mc_me 玩家ID`。
    *   支持将多个命令结果合并成一条日报，主动推送到已绑定会话。

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
| `player_blacklist` | 玩家黑名单，多个 ID 用英文逗号分隔 | `""` |
| `push_scheduler.enabled` | 是否启用定时推送总开关 | `False` |
| `push_scheduler.timezone` | 定时任务时区 | `Asia/Shanghai` |
| `push_scheduler.tasks` | 定时任务列表，需在 WebUI 中添加“定时推送任务”模板项 | `[]` |

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
| `/mc_push_bind <alias>` | 将当前会话绑定为推送目标别名 | `/mc_push_bind mc_group` | 管理员 |
| `/mc_push_bind list` | 查看当前已绑定的推送目标 | `/mc_push_bind list` | 管理员 |
| `/mc_push_bind del <alias>` | 删除一个已绑定的推送目标 | `/mc_push_bind del mc_group` | 管理员 |

## 指令详解

<details>
<summary><strong>基础查询指令</strong></summary>

### `/mc_rank [日期]`
- 功能：查看当前激活存档指定日期的游玩时长排行
- 用法：`/mc_rank` 或 `/mc_rank 2024-01-01`
- 示例：`/mc_rank 昨天`
- 权限：所有人

### `/mc_rank all`
- 功能：查看当前激活存档的累计总榜
- 用法：`/mc_rank all`
- 示例：`/mc_rank all`
- 权限：所有人

### `/mc_daily [日期]`
- 功能：查看当前激活存档指定日期的早起玩家和熬夜玩家
- 用法：`/mc_daily` 或 `/mc_daily 2024-08-05`
- 示例：`/mc_daily 昨天`
- 权限：所有人

### `/mc_season`
- 功能：查看当前激活存档本月的赛季榜
- 用法：`/mc_season`
- 示例：`/mc_season`
- 权限：所有人

### `/mc_me [玩家ID]`
- 功能：查看自己或指定玩家在当前激活存档中的统计信息
- 用法：`/mc_me` 或 `/mc_me Steve`
- 示例：`/mc_me Steve`
- 权限：所有人

</details>

<details>
<summary><strong>监控控制指令</strong></summary>

### `/mc_stat_on`
- 功能：开启游玩时长监控任务
- 用法：`/mc_stat_on`
- 示例：`/mc_stat_on`
- 权限：管理员

### `/mc_stat_off`
- 功能：停止游玩时长监控任务
- 用法：`/mc_stat_off`
- 示例：`/mc_stat_off`
- 权限：管理员

</details>

<details>
<summary><strong>推送绑定指令</strong></summary>

### `/mc_push_bind <alias>`
- 功能：把当前会话绑定成一个可用于定时推送的别名
- 用法：`/mc_push_bind <alias>`
- 示例：`/mc_push_bind mc_group`
- 权限：管理员

### `/mc_push_bind list`
- 功能：查看当前所有已绑定的推送目标
- 用法：`/mc_push_bind list`
- 示例：`/mc_push_bind list`
- 权限：管理员

### `/mc_push_bind del <alias>`
- 功能：删除一个已经绑定的推送目标
- 用法：`/mc_push_bind del <alias>`
- 示例：`/mc_push_bind del mc_group`
- 权限：管理员

</details>

<details>
<summary><strong>存档管理指令</strong></summary>

### `/mc_save_list`
- 功能：查看所有存档以及当前激活存档
- 用法：`/mc_save_list`
- 示例：`/mc_save_list`
- 权限：所有人

### `/mc_save_current`
- 功能：查看当前正在统计的存档
- 用法：`/mc_save_current`
- 示例：`/mc_save_current`
- 权限：所有人

### `/mc_save_create <存档名>`
- 功能：创建一个新存档并立即切换过去开始统计
- 用法：`/mc_save_create <存档名>`
- 示例：`/mc_save_create 落幕雨存档`
- 权限：管理员

### `/mc_save_switch <存档名或ID>`
- 功能：切换到指定存档进行统计和展示
- 用法：`/mc_save_switch <存档名或ID>`
- 示例：`/mc_save_switch 落幕雨存档`
- 权限：管理员

### `/mc_save_delete <存档名或ID> confirm`
- 功能：删除一个存档及其全部数据
- 用法：`/mc_save_delete <存档名或ID> confirm`
- 示例：`/mc_save_delete 落幕雨存档 confirm`
- 权限：管理员

### `/mc_save_player_delete <存档名或ID> <玩家名> confirm`
- 功能：删除某个玩家在指定存档中的全部数据
- 用法：`/mc_save_player_delete <存档名或ID> <玩家名> confirm`
- 示例：`/mc_save_player_delete 落幕雨存档 Steve confirm`
- 权限：管理员

</details>

## 📮 定时推送使用教程

### 1. 先绑定推送目标会话

在你想接收推送的群聊或私聊中发送：

```text
/mc_push_bind <alias>
```

例如把当前群绑定为 `mc_group`：

```text
/mc_push_bind mc_group
```

说明：

- 一定要在“目标会话本身”里执行绑定。
- `alias` 只是你自定义的别名，后续配置任务时填写这个名字即可。
- 如果想查看已绑定的会话，可以使用 `/mc_push_bind list`。
- 如果要删除绑定，可以使用 `/mc_push_bind del <alias>`。

### 2. 打开定时推送总开关

在 AstrBot 插件配置页面中：

- 将 `push_scheduler.enabled` 打开。
- 按需设置 `push_scheduler.timezone`，国内通常保持 `Asia/Shanghai` 即可。

如果这个总开关没有打开，日志里会出现：

```text
[MCDuration] 无法推送，推送调度器未启用
```

这不是报错，只是表示你还没有启用定时推送。

### 3. 在 WebUI 中添加定时任务

在 `push_scheduler.tasks` 中点击新增，选择 `定时推送任务` 模板，然后填写以下字段：

| 字段 | 说明 |
| :--- | :--- |
| `name` | 任务名称，建议唯一，方便看日志 |
| `enabled` | 是否启用该任务 |
| `cron` | Cron 表达式，格式为“分 时 日 月 周” |
| `targets` | 推送目标别名列表，填写前面用 `/mc_push_bind` 绑定的 alias |
| `commands` | 要定时执行的命令列表 |
| `merge_mode` | `merged` 为合并成一条消息，`separate` 为逐条发送 |
| `title` | 推送标题，可留空 |
| `separator` | 合并模式下，不同命令结果之间的分隔符 |
| `skip_if_empty` | 如果所有结果都为空，是否跳过本次发送 |

### 4. commands 支持哪些命令

当前定时任务支持以下命令：

```text
/mc_rank
/mc_rank 昨天
/mc_daily
/mc_daily 昨天
/mc_season
/mc_me Steve
```

注意：

- `/mc_me` 在定时任务里必须显式填写玩家 ID，例如 `/mc_me Steve`。
- 不支持在定时任务里写别的插件命令。

### 5. 常见配置示例

每天早上 9 点向 `mc_group` 推送一条排行榜：

```text
name: daily_rank
cron: 0 9 * * *
targets: [mc_group]
commands: [/mc_rank]
merge_mode: merged
```

每天早上 9 点推送合并日报：

```text
name: morning_report
cron: 0 9 * * *
targets: [mc_group]
commands:
  - /mc_rank 昨天
  - /mc_daily 昨天
  - /mc_me Steve
merge_mode: merged
title: 今日 MC 日报
```

每天晚上 11 点逐条发送多个统计结果：

```text
name: night_push
cron: 0 23 * * *
targets: [mc_group]
commands:
  - /mc_rank
  - /mc_season
merge_mode: separate
```

### 6. 使用建议

- 先确认 `/mc_push_bind <alias>` 已经绑定成功，再去配置 `targets`。
- 改完任务配置后记得保存插件配置。
- 如果任务没生效，先检查总开关 `push_scheduler.enabled` 是否已开启。
- 如果完全没有推送，优先看 AstrBot 控制台日志中的任务注册和 cron 解析信息。

## 更新日志
### v1.5
- 添加黑名单功能
### v1.6
- 添加定时主动推送功能
- 支持会话绑定命令 `/mc_push_bind`
- 支持在 WebUI 中配置多个定时推送任务
### v1.7
- 重构数据管理系统，使用sqlite
- 实现不同存档间的数据隔离
## ❗ 注意事项

> [!NOTE]
> 插件默认每 30 秒连接一次 RCON 获取在线列表，流量消耗极低。所有统计数据存储在 `AstrBot/data/plugin_data/astrbot_plugin_mc_duration/data.json` 中。

> [!WARNING]
> 如果在云服务器或 Docker 环境运行，请确保 AstrBot 能访问到 Minecraft 服务器的 RCON 端口（需配置防火墙/安全组）。

> [!IMPORTANT]
> 本插件依赖 RCON 协议，请务必在 `server.properties` 中启用 RCON 并设置强密码，避免暴露在公网。

如果有任何 Bug 反馈或功能建议，欢迎联系作者 QQ: **964389211**
