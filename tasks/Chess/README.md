# 百鬼棋局（新赛季）

本目录从 `D:/OnmyojiAutoScript-xylolit-mu` 的 `0318977c` 版本移植。
玩法、阵容和识别资源按来源版本完整替换；任务标识仍为 `Chess`。

## 当前内容

- 七角山、海国两套阵容，默认七角山。旧配置中的流火、冥府、大江山、狐妖、荒川及其拼音值自动转为七角山。
- 开局处理六道场地必选页，完成选择后继续对局或退出恢复。
- 通过勾玉、金币、纹章标志定位卡牌，再读取头像及羁绊；同一截图复用识别结果。
- 保留来源版本的商店购买复核、两帧消失确认、御魂处理、符咒策略、保段位、局数/时长限制和满币结束逻辑。

## 目录

```text
Chess/
├─ script_task.py          任务与整局编排
├─ config.py               参数与旧阵容配置迁移
├─ assets.py               由规则生成的资产
├─ runtime/                状态循环、Frame 识别、经济和手牌操作
├─ strategy/               阵容、式神目录、符咒策略
├─ c/                      常规界面识别、点击及 OCR 规则
└─ resource/
   ├─ c_frame.json         手牌、商店和纹章的定位与相对区域规则
   ├─ card_index.json      手牌/商店头像索引及 Frame 布局指纹
   ├─ card/               手牌定位标志和头像
   ├─ store/              商店定位标志和头像
   ├─ fetter/             纹章定位标志、头像与索引
   ├─ badge/              符咒图标和索引
   ├─ board/              场上勾玉标志
   └─ soul/               御魂模板
```

`c_frame.json` 必须与头像索引配套；运行时会校验布局指纹。来源目录没有附带头像库重建脚本，调整布局时需要同时更新对应索引和裁剪图。

## 当前框架适配

- `module/atom/frame.py` 与 `BaseTask.runframe()` 提供相对区域读取；Frame 额外参数纳入当前图像缓存键。
- 图像服务支持多个定位标志、灰度及掩码匹配，继续使用当前项目的截图缓存和 RPC 失效回退。
- `BaseTask.ui_click_until_disappear()` 增加有界、多帧确认参数，供购买复核使用。
- 满币后的周目标调度调用当前项目的 `set_next_run_next_monday()`，继续遵循本项目的 cron 调度约定。
- 全局导航识别六道必选页和棋局结算标志；普通奖励页仍由公共奖励页面推进，避免误归到棋局。

重新生成本任务资源时，从仓库根目录执行：

```powershell
python -c "from dev_tools.assets_extract import AssetsExtractor; e = AssetsExtractor('tasks/Chess'); e.extract(); e.write_file()"
```

移植检查包括配置迁移、资源完整性、Frame 定位及读取、购买确认和已有公共流程回归。实际匹配与对局需要在目标模拟器上验证。
