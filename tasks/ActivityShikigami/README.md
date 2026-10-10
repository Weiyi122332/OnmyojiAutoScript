# 式神活动

保留四种活动：体力（古迹演武）、百体（刹那试炼）、首领、伪神/爬塔（磐长故地）。
`script_task.py` 按配置列表从上到下执行，次数为 0 或从列表中删除的活动不运行。
体力和百体均支持活动主页入口、磐长故地地图左侧入口。
首领保留原有入口模板、次数限制、御魂切换与战斗流程；该分支执行时才加入首领页面识别。

## 配置核对

| 配置组 | 保留字段 | 实际用途 |
| --- | --- | --- |
| `scheduler` | `enable`、`next_run`、`priority`、`success_interval`、`failure_interval`、`float_time`、`cron` | 共用任务调度器读取 |
| `general_config` | `task_sequence` | 活动列表、执行顺序和开关；可清空列表 |
| `general_config` | `ap_limit`、`boss_limit`、`ap100_limit`、`fakegod_limit` | 各活动最多开始的战斗场数；0 表示不执行 |
| `general_config` | `limit_time` | 整项活动的时间上限；到时完成当前流程，再停止下一场 |
| `general_config` | `active_souls_clean` | 全部活动结束后接续执行御魂清理 |
| `general_config` | `random_sleep` | 下一场战斗开始前随机休眠；醒来重新检查时限 |
| `general_config` | `use_penta_pass` | 仅体力挑战使用五倍券；券耗尽时关闭；仍按战斗场数计数 |
| `general_config` | `climb_drink_break`、`climb_drink_interval` | 体力、首领和百体达到运行间隔后休息 2～20 分钟；休息时间不计入任务时限 |
| `switch_soul_config` | 每种活动的 `enable_switch_*`、`*_group_team`、`enable_switch_*_by_name`、`*_group_team_name` | 四种活动各自的御魂预设；同时启用两种方式时名称优先；默认不切换 |
| `ap_battle_conf`、`boss_battle_conf`、`ap100_battle_conf`、`fakegod_battle_conf` | `lock_team_enable`、`preset_enable`、`preset_group`、`preset_team` | 确认阵容锁定及切换战斗预设 |
| 同上 | `green_enable`、`green_mark_type`、`green_mark`、`green_mark_name` | 绿标目标选择 |
| 同上 | `random_click_swipt_enable`、`battle_timeout` | 战斗中随机点击/滑动、战斗超时 |
| 同上 | `continuous_battle`、`max_continuous`、`quick_exit` | 通用战斗引擎内部控制；界面隐藏，保留共用模型字段 |

体力、首领、百体的计数和执行位于 `activities/normal.py`，伪神位于
`activities/fake_god.py`；时限、随机休眠、御魂切换及结束处理位于 `base_act.py`。
配置以 `config.py` 的模型为准；`config/template.json` 必须与模型默认值一致。

## 已移除配置与旧配置迁移

- 旧门票战：`pass_limit`（简单/困难次数）、四个门票御魂字段、`pass_battle_conf`。
- 探索和大富翁：不再提供执行选项、次数、御魂或战斗配置。

载入旧列表时忽略以上玩法，保留其余活动的顺序；旧“爬塔”展开为体力、首领和百体。
过期配置字段在模型中不再存在，序列化保存后会从实例配置中去除。
旧 `general_climb` 中仍有效的次数、时限、休息和五倍券设置迁移到 `general_config`；
已有的新配置优先，包括空活动列表和次数 0。

独立伪神任务的旧 `pass_limit`、门票御魂和 `pass_battle_conf` 仍作为迁移输入，
分别转换为 `fakegod_limit`、伪神御魂和 `fakegod_battle_conf`。
式神活动和武道会各自保留首领配置。

开发源码为 `D:\OAS\OnmyojiAutoScript`；部署实例为 `D:\OnmyojiAutoScript`，
按项目使用约定，经用户确认后同步更新。

## 添加活动

同时更新活动枚举、默认列表、名称映射、次数和御魂/战斗模型、执行分派、页面入口、
默认模板及界面翻译。保留旧配置读取兼容，并验证加载、保存、界面参数和执行顺序。

回归检查：

```powershell
python -m unittest discover -s tests -p test_activity_shikigami_modes.py -v
python dev_tools/check_structure.py
```
