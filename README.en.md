<div align="center">

# 🎮 Minecraft Playtime Statistics

[![Plugin Version](https://img.shields.io/badge/Latest_Version-v1.7.4-blue.svg?style=for-the-badge&color=4aac3d)](https://github.com/gangcaiyoule/astrbot_plugin_mc_duration)
[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-ff69b4?style=for-the-badge)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)

[中文](./README.md) | [English](./README.en.md)

_✨ Monitor online Minecraft players in real time through RCON, track playtime, and generate rankings plus fun statistics. ✨_

<img src="https://count.getloli.com/@astrbot-plugin-mc-duration?name=astrbot-plugin-mc-duration&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="count" />

</div>

<details>
<summary><strong>Project Structure</strong></summary>

```text
astrbot_plugin_mc_duration/
  main.py                 # Plugin registration, command entrypoints, dependency wiring
  config.py               # Config parsing, PushTaskConfig / PluginSettings
  models.py               # dataclass: SaveRecord / ReportResult / PushTaskConfig
  message_style.py        # Shared emoji and text style definitions
  services/
    tracker_service.py    # RCON polling, online player state, incremental tracking
    report_service.py     # rank/daily/season/player reports
    push_service.py       # Scheduled task parsing, dispatching, and message delivery
    save_service.py       # Save creation/switch/delete workflows
  repositories/
    database.py           # sqlite connection, table creation, migration
    save_repository.py    # CRUD for saves
    player_repository.py  # CRUD for player_totals / sessions
    push_repository.py    # CRUD for push_bindings / push_task_state
  rcon.py                 # RCON client
  storage.py              # Repository facade
  utils.py                # Pure helper functions only
```

</details>

## ✨ Features

*   **⏱️ Accurate and logical playtime tracking**:
    *   Supports a custom **logical day** start time, so you can define when a "day" begins, such as 05:00.
    *   **Late-night friendly**: playing at 2 AM can still count toward the previous day's late-night session instead of the next day's early-morning activity.
*   **🏆 Multi-dimensional leaderboards**:
    *   **Season leaderboard**: monthly playtime ranking with **achievement badges** for things like daily champion, early bird, and night owl titles earned during the month.
    *   **Daily honor board**: automatically selects the early bird and night owl players for a specified date.
    *   **Single-day ranking**: view today's ranking or a ranking for any supported historical date.
*   **📊 Personal daily report**: query your own or another player's detailed records, including today's duration, historical total time, and login/logout periods.
*   **📮 Scheduled push delivery**:
    *   Supports multiple scheduled tasks in the WebUI.
    *   Supports scheduled execution of `/mc_rank`, `/mc_daily`, `/mc_season`, and `/mc_me <player_id>`.
    *   Supports merging multiple command results into one daily report and pushing it to bound sessions.

## 🛠️ Server Configuration (Required)

This plugin relies on the **RCON** protocol to communicate with your Minecraft server. Please make sure your `server.properties` file contains the following settings:

```properties
enable-rcon=true
rcon.password=your_strong_password
rcon.port=25575
```

> [!NOTE]
> Restart the Minecraft server after changing the configuration.

## ⚙️ Plugin Configuration

After installing the plugin, fill in the following fields in the AstrBot plugin configuration panel:

| Option | Description | Default |
| :--- | :--- | :--- |
| `server_ip` | Minecraft server IP address | `127.0.0.1` |
| `server_port` | Game port, display only | `25565` |
| `rcon_port` | **RCON port**; must match the server setting | `25575` |
| `rcon_password` | **RCON password**; must match the server setting | `""` |
| `interval` | Polling interval in seconds | `30` |
| `auto_start` | Automatically start tracking when AstrBot boots | `True` |
| `rank_start_hour` | **Leaderboard day start** (0-23)<br>Determines when daily playtime starts accumulating. Use `0` for natural calendar days. | `0` |
| `daily_start_hour` | **Daily behavior boundary** (0-23)<br>Determines the cutoff for early-bird and night-owl calculations. Use `5` so logout before 5 AM still counts as the previous night's late session. | `5` |
| `player_blacklist` | Blacklisted player IDs separated by commas | `""` |
| `push_scheduler.enabled` | Master switch for scheduled pushing | `False` |
| `push_scheduler.timezone` | Time zone used by scheduled tasks | `Asia/Shanghai` |
| `push_scheduler.tasks` | Scheduled task list; add items through the `Scheduled Push Task` template in WebUI | `[]` |

## 💻 Command List

Supported date formats: `8.5` (August 5), `2024-1-1`, `昨天`, `yesterday`. If omitted, today is used by default.

| Command | Description | Example | Permission |
| :--- | :--- | :--- | :--- |
| `/mc_rank [date]` | Show the playtime ranking for a **specific date** | `/mc_rank`<br>`/mc_rank yesterday` | Everyone |
| `/mc_rank all` | Show the cumulative ranking for the current save | / | Everyone |
| `/mc_daily [date]` | Show the **early-bird / night-owl** board for a specific date | `/mc_daily`<br>`/mc_daily 8.5` | Everyone |
| `/mc_season` | Show the **current monthly season ranking** with badge stats | `/mc_season` | Everyone |
| `/mc_me [ID]` | Show detailed statistics for yourself or a specific player | `/mc_me`<br>`/mc_me Notch` | Everyone |
| `/mc_stat_on` | Start the tracking task | / | Admin |
| `/mc_stat_off` | Pause the tracking task | / | Admin |
| `/mc_push_bind <alias>` | Bind the current session as a push target alias | `/mc_push_bind mc_group` | Admin |
| `/mc_push_bind list` | List currently bound push targets | `/mc_push_bind list` | Admin |
| `/mc_push_bind del <alias>` | Delete a bound push target | `/mc_push_bind del mc_group` | Admin |
| `/mc_save_list` | List available saves | / | Everyone |
| `/mc_save_current` | Show the currently active save | / | Everyone |
| `/mc_save_create <save_name>` | Create a new save and switch to it | `/mc_save_create RainyEnding` | Admin |
| `/mc_save_switch <save_name_or_id>` | Switch to a specified save for tracking | `/mc_save_switch RainyEnding` | Admin |
| `/mc_save_delete <save_name_or_id> confirm` | Delete a save and all its data | `/mc_save_delete RainyEnding confirm` | Admin |
| `/mc_save_player_delete <save_name_or_id> <player_name> confirm` | Delete one player's data from the specified save | `/mc_save_player_delete RainyEnding Steve confirm` | Admin |

## Command Details

<details>
<summary><strong>Basic Query Commands</strong></summary>

### `/mc_rank [date]`
- Purpose: show the playtime ranking for the specified date in the current active save.
- Usage: `/mc_rank` or `/mc_rank 2024-01-01`
- Example: `/mc_rank yesterday`
- Permission: Everyone

### `/mc_rank all`
- Purpose: show the cumulative leaderboard for the current active save.
- Usage: `/mc_rank all`
- Example: `/mc_rank all`
- Permission: Everyone

### `/mc_daily [date]`
- Purpose: show the early-bird and night-owl players for the specified date in the current active save.
- Usage: `/mc_daily` or `/mc_daily 2024-08-05`
- Example: `/mc_daily yesterday`
- Permission: Everyone

### `/mc_season`
- Purpose: show the current month's season leaderboard for the active save.
- Usage: `/mc_season`
- Example: `/mc_season`
- Permission: Everyone

### `/mc_me [player_id]`
- Purpose: show statistics for yourself or a specified player in the current active save.
- Usage: `/mc_me` or `/mc_me Steve`
- Example: `/mc_me Steve`
- Permission: Everyone

</details>

<details>
<summary><strong>Tracking Control Commands</strong></summary>

### `/mc_stat_on`
- Purpose: start the playtime tracking task.
- Usage: `/mc_stat_on`
- Example: `/mc_stat_on`
- Permission: Admin

### `/mc_stat_off`
- Purpose: stop the playtime tracking task.
- Usage: `/mc_stat_off`
- Example: `/mc_stat_off`
- Permission: Admin

</details>

<details>
<summary><strong>Push Binding Commands</strong></summary>

### `/mc_push_bind <alias>`
- Purpose: bind the current session to an alias used by scheduled push tasks.
- Usage: `/mc_push_bind <alias>`
- Example: `/mc_push_bind mc_group`
- Permission: Admin

### `/mc_push_bind list`
- Purpose: list all currently bound push targets.
- Usage: `/mc_push_bind list`
- Example: `/mc_push_bind list`
- Permission: Admin

### `/mc_push_bind del <alias>`
- Purpose: delete an existing bound push target.
- Usage: `/mc_push_bind del <alias>`
- Example: `/mc_push_bind del mc_group`
- Permission: Admin

</details>

<details>
<summary><strong>Save Management Commands</strong></summary>

### `/mc_save_list`
- Purpose: list all saves and show the currently active one.
- Usage: `/mc_save_list`
- Example: `/mc_save_list`
- Permission: Everyone

### `/mc_save_current`
- Purpose: show the save that is currently being tracked.
- Usage: `/mc_save_current`
- Example: `/mc_save_current`
- Permission: Everyone

### `/mc_save_create <save_name>`
- Purpose: create a new save and switch to it immediately for tracking.
- Usage: `/mc_save_create <save_name>`
- Example: `/mc_save_create RainyEnding`
- Permission: Admin

### `/mc_save_switch <save_name_or_id>`
- Purpose: switch to a specified save for statistics and display.
- Usage: `/mc_save_switch <save_name_or_id>`
- Example: `/mc_save_switch RainyEnding`
- Permission: Admin

### `/mc_save_delete <save_name_or_id> confirm`
- Purpose: delete a save and all of its data.
- Usage: `/mc_save_delete <save_name_or_id> confirm`
- Example: `/mc_save_delete RainyEnding confirm`
- Permission: Admin

### `/mc_save_player_delete <save_name_or_id> <player_name> confirm`
- Purpose: delete all data for a specific player in the specified save.
- Usage: `/mc_save_player_delete <save_name_or_id> <player_name> confirm`
- Example: `/mc_save_player_delete RainyEnding Steve confirm`
- Permission: Admin

</details>

## 📮 Scheduled Push Guide

### 1. Bind the target session first

Send the following command in the group chat or private chat that should receive the push messages:

```text
/mc_push_bind <alias>
```

For example, bind the current group as `mc_group`:

```text
/mc_push_bind mc_group
```

Notes:

- Run the bind command inside the target session itself.
- `alias` is just a custom name. Use that same name later in task configuration.
- To view existing bindings, use `/mc_push_bind list`.
- To remove a binding, use `/mc_push_bind del <alias>`.

### 2. Enable the master scheduled push switch

In the AstrBot plugin configuration page:

- Enable `push_scheduler.enabled`.
- Set `push_scheduler.timezone` if needed. `Asia/Shanghai` is usually fine for users in China.

If the master switch is still off, the log will show:

```text
[MCDuration] Unable to push: scheduler is disabled
```

This is not an error. It only means scheduled pushing has not been enabled yet.

### 3. Add scheduled tasks in WebUI

Inside `push_scheduler.tasks`, click Add, choose the `Scheduled Push Task` template, and fill in the following fields:

| Field | Description |
| :--- | :--- |
| `name` | Task name; keep it unique so logs are easy to read |
| `enabled` | Whether the task is enabled |
| `cron` | Cron expression in the form `minute hour day month weekday` |
| `targets` | List of target aliases bound earlier with `/mc_push_bind` |
| `commands` | List of commands to execute on schedule |
| `merge_mode` | `merged` combines results into one message; `separate` sends each result separately |
| `title` | Optional push title |
| `separator` | Separator between command results in merged mode |
| `skip_if_empty` | Skip sending when every result is empty |

### 4. Supported commands in `commands`

The following commands are currently supported by scheduled tasks:

```text
/mc_rank
/mc_rank 昨天
/mc_daily
/mc_daily 昨天
/mc_season
/mc_me Steve
```

Notes:

- `/mc_me` must explicitly include a player ID in scheduled tasks, for example `/mc_me Steve`.
- Commands from other plugins are not supported in scheduled tasks.

### 5. Common configuration examples

Push one ranking message to `mc_group` every day at 9:00 AM:

```text
name: daily_rank
cron: 0 9 * * *
targets: [mc_group]
commands: [/mc_rank]
merge_mode: merged
```

Push a merged morning report every day at 9:00 AM:

```text
name: morning_report
cron: 0 9 * * *
targets: [mc_group]
commands:
  - /mc_rank 昨天
  - /mc_daily 昨天
  - /mc_me Steve
merge_mode: merged
title: Today's MC Daily Report
```

Send multiple statistic messages separately every day at 11:00 PM:

```text
name: night_push
cron: 0 23 * * *
targets: [mc_group]
commands:
  - /mc_rank
  - /mc_season
merge_mode: separate
```

### 6. Practical tips

- Make sure `/mc_push_bind <alias>` succeeded before filling `targets`.
- Save the plugin configuration after modifying scheduled tasks.
- If tasks do not run, first check whether `push_scheduler.enabled` is on.
- If nothing is pushed at all, check AstrBot console logs for task registration and cron parsing messages.

## Changelog

### v1.5
- Added blacklist support

### v1.6
- Added scheduled proactive push support
- Added the session binding command `/mc_push_bind`
- Added support for multiple scheduled push tasks in WebUI

### v1.7
- Refactored the data management system to use sqlite
- Implemented data isolation across different saves
- Refactored the code structure

## ❗ Notes

> [!NOTE]
> By default, the plugin connects to RCON every 30 seconds to fetch the online player list. Network usage is extremely low. All statistics are stored in `AstrBot/data/plugin_data/astrbot_plugin_mc_duration/mc_duration.db`.

> [!NOTE]
> To make future data management easier, this plugin migrated storage from `data.json` to `mc_duration.db`. A small amount of data loss may occur. The original `data.json` file is not deleted, and a backup is also created as `data.json.bak.<timestamp>`.

> [!WARNING]
> If you run AstrBot on a cloud server or in Docker, make sure AstrBot can access the Minecraft server's RCON port, including firewall or security group settings.

> [!IMPORTANT]
> This plugin depends on the RCON protocol. Please enable RCON in `server.properties` and set a strong password to avoid exposing the service to the public internet.

If you find any bugs or have feature suggestions, feel free to contact the author on QQ: **964389211**
