# 百鬼棋局资源与全局依赖核对

核对日期：2026-10-27。来源目录：`D:/OnmyojiAutoScript-xylolit-mu`，版本 `9674276d`；目标项目：`D:/OAS/OnmyojiAutoScript`。

## 公开仓库复核

2026-10-23 曾核对作者公开仓库 [xylolit-mu/OnmyojiAutoScript](https://github.com/xylolit-mu/OnmyojiAutoScript)，当时默认 `self` 分支为 `47a3a3bc6173e6560ab8cc3658d3e55bc2c80287`（2026-10-22）。按 Git blob 比较，该公开快照的全部 456 个棋局文件与本地来源的 `a5b8f7aa` 基线一致，59 条共用规则涉及的 62 个图片及规则类文件也一致。本次同步以本地参考仓库 `9674276d` 为准。

- [全局浮窗红叉](https://github.com/xylolit-mu/OnmyojiAutoScript/blob/47a3a3bc6173e6560ab8cc3658d3e55bc2c80287/tasks/GameUi/page/page_close_red.png)确实存在于公开库；完整流程移植时已作为棋局专用副本加入。
- [百鬼投掷资源清单](https://github.com/xylolit-mu/OnmyojiAutoScript/blob/47a3a3bc6173e6560ab8cc3658d3e55bc2c80287/tasks/Chess/resource/hyakki_soul/manifest.json)仍明确缺少狂骨和地藏像。公开库已有的同名图片位于普通手牌御魂目录，不能直接作为投掷阶段模板。
- 额外检查 `mine`、`pr`、`test` 三个分支：没有找到这两种百鬼投掷专用模板。`test` 的旧版普通御魂目录也有同名图片，仍属于不同用途。

## 完整流程移植结果

本次按“保留现有脚本功能”的要求，将 14 项存在差异或缺失的公共识别复制到 `tasks/Chess/shared_ui`，由 `runtime/shared_ui.py` 在棋局实例内部使用。公共规则定义、公共页面图、其他任务和调度器没有修改。

- 来源模板优先，当前模板作为回退；按原始规则的对象身份映射，避免规则同名时互相覆盖。每个棋局实例拥有独立的来源规则对象。
- 共用页面图仍通过原 `GameUi` 进入庭院、町中、娱乐和棋局；模板选择同时覆盖页面识别、按钮点击及批量匹配缓存。点击使用当前帧实际命中的模板坐标，跨帧不沿用旧命中记录。
- 浮窗红叉独立生效；邀请处理后继续复核红叉，清理弹窗后重新截图，避免把被遮挡的旧画面交给回目状态机。
- 网络异常按当前配置等待 10 秒或立即进入异常重启，也兼容来源的 5 秒等待值。连接失败时先退出当前回目调用栈，最多执行一次 30 秒重连；重连登录沿用当前登录服务并增加棋局专用识别。失败或再次断线使用现有 `GameStuckError` 重启通道，保留原有重启次数限制。
- 重连成功后重新执行棋局入口恢复，清空旧回合、百鬼投掷、特殊回合及页面命中状态，局号继续递增。
- 完整保留已移植的六道选择、四套阵容、买卡/刷新/升级、符咒、部署/御魂/复制术、百鬼投掷、奖励/分享/排名、保段位和满币调度流程。

`shared_ui/image.json` 维护规则，`shared_ui/bindings.json` 保存来源路径和文件 SHA-256。`assets.py` 可由现有工具重新生成；本次没有手写生成文件。

## 7cc93181 修复同步

- 原样同步参考仓库的购买前容量检查、星级日志、连续两帧升星确认、百鬼投掷偏好及 300 秒无活动保护；保留本项目的公共模板隔离、网络恢复和周调度适配。
- 容量扫描统计手牌定位标志和御魂图片，不要求识别式神身份，并排除不占容量的白藏主守护之印。
- `hyakki_draft_enabled` 的含义由投掷开关改为“百鬼优先所需御魂”；关闭时继续投掷。中文界面仅补充这一项翻译，保留现有配置值。
- 用户报错截图离线识别出 10 张手牌，场上 11 号位确实有式神。参考版本只在购买前腾位，最后一次购买填满手牌后，下阵仍可能失败；本项目额外在单张及整场下阵前检查空位。清理非阵容卡、装备御魂后仍满手牌，或备阶段已结束时，本次下阵暂缓。
- 参考提交中逢魔结算和斗技周调度的修改不属于棋局，本次未移植。

## 9674276d 修复同步

- 商店不再使用五个静态卡槽点击规则，改为多目标 Frame 实际定位后的第六个相对区域；空槽的刷新采样范围由 Frame 搜索区域划分。
- 同一购买流程在清理手牌前后累计最多点击三次，内部等待函数每次最多点击一次，避免内外重试次数相乘。成功须连续两帧同时确认目标从商店消失且同名手牌增加；单纯消失不清空防重复点击记录。
- 棋盘仅在备阶段、商店关闭后读取；锚点缺失或商店无法关闭均视为未知，不清空上阵记录、不判为空位。金鱼按 12、6、11、5 的系统站位顺序打开详情确认。
- 更新式神详情模板及金鱼搜索区域，增加 `c_stage_snake.png`。意外详情页关闭接入棋局截图流程；金鱼主动读取通过上下文豁免，异常也会恢复。现有红叉、网络恢复及其他任务的公共逻辑保持原样。
- 荒川内置阵容键由 `haiguo` 改为 `huangchuan`；读取旧配置时兼容转换，保留已保存的海国自定义阵容。编辑器删除引用检查同步兼容新旧配置，不改写实例配置文件。
- Frame 布局指纹忽略默认的 `badgeGrayscale: false`，头像索引只同步对应指纹，保留头像及本项目的标注格式。
- 本次参考提交另有契灵协同收尾及公共协作完成协议改动，没有棋局调用依赖，未移植。
- 棋局 97 项测试通过，包含新增的购买确认、真实 Frame 点击区域、累计三次点击、详情页豁免、棋盘未知状态与阵容迁移回归检查；尚未进行模拟器完整对局验证。

## 范围和结论

- 移植范围为 `tasks/Chess` 的新版本代码、规则、模板、`config/template.json` 的棋局配置项及对应测试；中文翻译仅涉及 `hyakki_draft_enabled`。
- 检查棋局直接引用、字符串生成的阶段标志、Frame 相对区域及索引、动态扫描的头像/符咒/御魂目录，并向外追踪共用棋局退出、导航入口、公共奖励处理、未知页面恢复和邀请处理。来源的网络恢复规则另列为公共框架能力。
- 共核对 440 张棋局 PNG，均存在且可解码，含 426 张任务图片和 14 张共用模板副本；64 个手牌身份、63 个商店身份、19 个纹章/复制术身份、200 张符咒图、20 种普通手牌御魂及 18 种百鬼投掷御魂有实际文件。
- 共核对 59 条外部共用规则的公共定义：38 条完全一致，7 条仅目录迁移且图片及识别参数相同，13 条图片或识别参数不同，1 条缺失。下文保留全部公共定义的对比；这 14 项差异已经在棋局内部适配。
- “存在差异”表示公共定义与来源版本不同，不能据此认定当前全局规则在实机上失效。棋局适配使用独立副本，公共定义继续供其他任务使用。

## 完整棋局流程

| 阶段 | 本任务的处理和专用资源 | 共用识别或流程 |
| --- | --- | --- |
| 启动恢复 | 局内标志、六道三选一、异常大厅、取消等待；必要时主动退出遗留对局 | `GameUi` 页面识别、`ChessBattleNavigationMixin`、退出确认 |
| 进入大厅 | 庭院→町中→娱乐→百鬼棋局；娱乐跳过动画 | 庭院/町中/娱乐/棋局页面检查及跳转按钮 |
| 开始匹配 | 开始、取消等待、六道选择、匹配超时重试及局内确认 | 共用页面恢复和未知页关闭 |
| 读取回目 | 两套 OCR 布局、备/战/待；金色百鬼/大蛇/逢魔标志 | OCR 引擎、截图及图像服务 |
| 备阶段 | 扫描买卡→升级/刷新→部署→黄金复制术/纹章/御魂；符咒选择优先中断 | Frame 读取和图像服务；新版点击上限由棋局内部兼容 |
| 战阶段 | 清理非体系手牌→买卡/经济循环→等待；刷新/升级受剩余 15 秒保护 | 截图与公共邀请处理 |
| 百鬼阶段 | 黄色昵称框定位本人→确认锁消失→等待约六秒→匹配御魂→再次截图复核→补偿移动后投掷，每回合最多两次 | OCR 检测框；本阶段图标均位于 `Chess/resource/hyakki_soul` |
| 大蛇/逢魔回合 | 激活金色阶段标志出现过后，使用首领专用棋盘 Frame 判定站位和落点 | 图像服务 |
| 符咒选择 | 图标/索引优先；三选项均不明时重新截图一次后兜底 | 截图与图像服务 |
| 结束和下一局 | 局内标志连续消失确认→奖励/分享→排名 OCR→返回大厅或再来一局 | `I_UI_REWARD`、全局棋局排名及返回按钮 |
| 保段位/满币结束 | 保段位退出两局；遵守局数/时长；满币后安排下周任务 | 共用退出确认、当前项目 cron 调度接口 |

## 棋局内部资源结果

| 资源组 | PNG 数量 | 核对结果 |
| --- | ---: | --- |
| `c` | 31 | 界面识别、百鬼锁与三个特殊回合标志可读取；点击及 OCR 规则已配套 |
| `resource/card` | 68 | 64 个手牌身份及定位标志；索引和 Frame 布局指纹通过 |
| `resource/store` | 64 | 63 个商店身份及定位标志；索引和 Frame 布局指纹通过 |
| `resource/fetter` | 21 | 19 个纹章/复制术身份及定位标志，含黄金复制术 |
| `resource/badge` | 200 | 符咒文件索引无缺项 |
| `resource/board` | 4 | 三种棋盘勾玉及新增表情锚点模板可读取；普通/首领 Frame 配套 |
| `resource/soul` | 20 | 普通手牌御魂模板可读取 |
| `resource/hyakki_soul` | 18 | 百鬼投掷模板可读取；仍缺下述两种 |
| `shared_ui` | 14 | 退出、奖励、庭院、红叉、协作、跳过及网络识别副本，文件指纹与来源一致 |

### 来源本身缺少的投掷模板

`resource/hyakki_soul/manifest.json` 明确声明缺少 `kuanggu`（狂骨）和 `dizangxiang`（地藏像）。因此百鬼投掷阶段不能按图标识别这两种目标；模板无法凭现有文件补出，需采集该阶段的实际截图后裁剪。普通手牌目录中这两种御魂的模板存在，但画面样式不同，不能直接冒充投掷模板。

当前荒川阵容新增狂骨偏好，该目标属于上述已知缺失项，百鬼投掷时无法通过图标识别；普通手牌仍可识别并装备。其他已知优先御魂均有投掷模板。没有优先目标时的随机兜底也只会从已经识别出的目标中选择。

### 正常差异及非运行时路径

- 寻森小鹿男（`hiromori_shikaotoko`）只有手牌头像。作者已在 `shikigami_catalog.py` 的 `NON_SHOP_SHIKIGAMI` 明确将其排除于商店身份，故 64/63 的数量差不是资源遗漏。
- 四套阵容中使用的所有手牌和商店身份均在索引内；索引声明的头像、纹章及符咒文件均能读取。
- 投掷模板清单内的来源截图路径用于记录采集出处，运行时按当前目录中的 `sou_*.png` 加载，不读取作者机器上的原始截图路径。
- 来源已停用的棋局旧退出、旧排名、旧符咒刷新和商店金币模板已随任务一起清理；现有退出/排名处理使用公共 `GameUi` 资源。

## 全局差异及棋局适配

以下是公共定义的差异记录；上述各项已在棋局使用独立来源模板，并保留现有模板回退。

| 共用规则 | 差异及对棋局的影响 |
| --- | --- |
| `GameUiAssets.I_CLOSE_RED` | 公共定义仍缺少来源的全局浮窗红叉；棋局使用 `I_SHARED_CLOSE_RED` 副本，浮窗自动关闭已接入完整截图流程，不会误用 `GeneralBuffAssets` 的同名加成弹窗规则。 |
| `GeneralBattleAssets.I_EXIT_ENSURE` | 退出确认的图片、裁剪位置、搜索范围及阈值不同；涉及启动恢复、主动退出和保段位。来源阈值 0.8，当前 0.9。 |
| `GlobalGameAssets.I_UI_REWARD` | 通用奖励模板和搜索范围不同；来源搜索范围更大，影响棋局奖励/分享/排名衔接时的识别覆盖。 |
| `GameUiAssets.I_CHECK_MAIN` | 庭院模板和搜索范围不同；来源还将图片移到 `page_checks`。不能按“只是改目录”忽略这项。 |
| `GlobalGameAssets.I_UI_CONFIRM` | 公共确认按钮的图片及裁剪不同，可能在未知页恢复中使用；来源文件名 `ui_confirm.png`，当前 `ui_ui_confirm.png`。 |
| `GlobalGameAssets.I_G_ACCEPT / I_G_REJECT` | 协作接受/拒绝模板图片不同；棋局截图仍调用公共邀请处理。 |
| `GlobalGameAssets.I_G_JADE / I_G_CAT_FOOD / I_G_DOG_FOOD` | 模板相同，来源扩大了搜索区域；影响仅勾协/勾粮协模式的判定范围。 |
| `GameUiAssets.I_ACTIVITY_SKIP` | 模板图片不同；属于未知页关闭兜底。棋局将当前列表中的活动跳过规则映射到来源副本，识别不到时仍尝试当前规则；公共列表不变。 |
| `GlobalGameAssets.I_NETWORK_ABNORMAL / I_NETWORK_ERROR` | 图片和裁剪参数不同；棋局使用来源副本和当前规则复核，接入等待、断线重连及既有异常重启机制；其他任务的截图策略不变。 |

### 全局差异参数

坐标均为 `(x, y, width, height)`；“裁剪”是 `roi_front`，“搜索”是 `roi_back`。以下“当前”指保留的公共定义；棋局独立副本采用“来源”参数。

#### GeneralBattleAssets.I_EXIT_ENSURE（图片及参数不同）

- 当前：`tasks/Component/GeneralBattle/gb/gb_exit_ensure.png`；裁剪 `[664, 408, 180, 64]`；搜索 `[640, 380, 230, 110]`；阈值 `0.9`。
- 来源：`tasks/Component/GeneralBattle/gb/gb_exit_ensure.png`；裁剪 `[699, 414, 107, 46]`；搜索 `[662, 364, 250, 121]`；阈值 `0.8`。

#### GameUiAssets.I_ACTIVITY_SKIP（图片不同）

- 当前：`tasks/GameUi/page/page_activity_skip.png`；裁剪 `[1159, 37, 51, 22]`；搜索 `[1141, 27, 86, 43]`；阈值 `0.8`。
- 来源：`tasks/GameUi/page/page_activity_skip.png`；裁剪 `[1159, 37, 51, 22]`；搜索 `[1141, 27, 86, 43]`；阈值 `0.8`。

#### GameUiAssets.I_CHECK_MAIN（图片及参数不同）

- 当前：`tasks/GameUi/page/page_check_main.png`；裁剪 `[807, 108, 76, 45]`；搜索 `[49, 98, 1033, 80]`；阈值 `0.95`。
- 来源：`tasks/GameUi/page_checks/page_check_main.png`；裁剪 `[807, 108, 76, 45]`；搜索 `[47, 88, 1046, 102]`；阈值 `0.95`。

#### GameUiAssets.I_CLOSE_RED（缺失）

- 当前：该类未定义此规则。
- 来源：`tasks/GameUi/page/page_close_red.png`；裁剪 `[1169, 60, 33, 25]`；搜索 `[1077, 19, 151, 144]`；阈值 `0.8`。

#### GlobalGameAssets.I_G_ACCEPT（图片不同）

- 当前：`tasks/GlobalGame/gg/gg_g_accept.png`；裁剪 `[830, 407, 56, 46]`；搜索 `[798, 369, 117, 110]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_g_accept.png`；裁剪 `[830, 407, 56, 46]`；搜索 `[798, 369, 117, 110]`；阈值 `0.8`。

#### GlobalGameAssets.I_G_CAT_FOOD（参数不同）

- 当前：`tasks/GlobalGame/gg/gg_g_cat_food.png`；裁剪 `[565, 463, 59, 65]`；搜索 `[565, 463, 59, 65]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_g_cat_food.png`；裁剪 `[565, 463, 59, 65]`；搜索 `[543, 421, 205, 176]`；阈值 `0.8`。

#### GlobalGameAssets.I_G_DOG_FOOD（参数不同）

- 当前：`tasks/GlobalGame/gg/gg_g_dog_food.png`；裁剪 `[565, 464, 60, 63]`；搜索 `[565, 464, 60, 63]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_g_dog_food.png`；裁剪 `[565, 464, 60, 63]`；搜索 `[543, 421, 205, 176]`；阈值 `0.8`。

#### GlobalGameAssets.I_G_JADE（参数不同）

- 当前：`tasks/GlobalGame/gg/gg_g_jade.png`；裁剪 `[661, 466, 43, 46]`；搜索 `[661, 466, 43, 46]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_g_jade.png`；裁剪 `[661, 466, 43, 46]`；搜索 `[543, 421, 205, 176]`；阈值 `0.8`。

#### GlobalGameAssets.I_G_REJECT（图片不同）

- 当前：`tasks/GlobalGame/gg/gg_g_reject.png`；裁剪 `[832, 508, 53, 51]`；搜索 `[808, 480, 108, 101]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_g_reject.png`；裁剪 `[832, 508, 53, 51]`；搜索 `[808, 480, 108, 101]`；阈值 `0.8`。

#### GlobalGameAssets.I_NETWORK_ABNORMAL（图片及参数不同）

- 当前：`tasks/GlobalGame/gg/gg_network_abnormal.png`；裁剪 `[583, 330, 221, 67]`；搜索 `[583, 330, 221, 67]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_network_abnormal.png`；裁剪 `[588, 335, 211, 57]`；搜索 `[583, 330, 221, 67]`；阈值 `0.8`。

#### GlobalGameAssets.I_NETWORK_ERROR（图片及参数不同）

- 当前：`tasks/GlobalGame/gg/gg_network_error.png`；裁剪 `[431, 253, 416, 208]`；搜索 `[431, 253, 416, 208]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_network_error.png`；裁剪 `[436, 258, 406, 198]`；搜索 `[431, 253, 416, 208]`；阈值 `0.8`。

#### GlobalGameAssets.I_UI_CONFIRM（图片及参数不同）

- 当前：`tasks/GlobalGame/ui/ui_ui_confirm.png`；裁剪 `[664, 408, 180, 64]`；搜索 `[547, 368, 322, 122]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/ui/ui_confirm.png`；裁剪 `[667, 417, 169, 47]`；搜索 `[547, 368, 322, 122]`；阈值 `0.8`。

#### GlobalGameAssets.I_UI_REWARD（图片及参数不同）

- 当前：`tasks/GlobalGame/ui/ui_ui_reward.png`；裁剪 `[518, 210, 240, 65]`；搜索 `[464, 142, 350, 145]`；阈值 `0.73`。
- 来源：`tasks/GlobalGame/ui/ui_ui_reward.png`；裁剪 `[521, 212, 237, 66]`；搜索 `[361, 47, 556, 286]`；阈值 `0.73`。

#### GlobalGameAssets.I_CLIENT_CLEAR（图片及参数不同）

- 当前：`tasks/GlobalGame/gg/gg_client_clear.png`；裁剪 `[578, 369, 151, 72]`；搜索 `[578, 369, 151, 72]`；阈值 `0.8`。
- 来源：`tasks/GlobalGame/gg/gg_client_clear.png`；裁剪 `[599, 383, 85, 42]`；搜索 `[594, 378, 95, 52]`；阈值 `0.8`。
- 棋局重连服务采用来源副本，识别不到时尝试当前规则；登录标志 `RestartAssets.I_LOGIN_8` 的图片和识别参数与来源一致，可直接复用。

## 全部 59 条共用规则

“目录调整，内容相同”已比较实际解码像素及识别参数；不会仅因来源路径不同而误报缺图。来源列用于定位作者的文件，当前列说明本项目实际文件。

### `tasks.Component.GeneralBattle.assets.GeneralBattleAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `C_RANDOM_BOTTOM` | 一致 | 无图片 | 无图片 | 登录/庭院/町中/娱乐/棋局导航 |
| `C_RANDOM_LEFT` | 一致 | 无图片 | 无图片 | 棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `C_RANDOM_RIGHT` | 一致 | 无图片 | 无图片 | 登录/庭院/町中/娱乐/棋局导航 |
| `C_RANDOM_TOP` | 一致 | 无图片 | 无图片 | 登录/庭院/町中/娱乐/棋局导航 |
| `I_EXIT_ENSURE` | 图片及参数不同 | `tasks/Component/GeneralBattle/gb/gb_exit_ensure.png` | `tasks/Component/GeneralBattle/gb/gb_exit_ensure.png` | 棋局退出/结算 |
| `I_GB_SKIN_CONFIRM` | 一致 | `tasks/Component/GeneralBattle/gb/gb_gb_skin_confirm.png` | `tasks/Component/GeneralBattle/gb/gb_gb_skin_confirm.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_OVER_GHOST` | 一致 | `tasks/Component/GeneralBattle/gb/gb_over_ghost.png` | `tasks/Component/GeneralBattle/gb/gb_over_ghost.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward.png` | `tasks/Component/GeneralBattle/gb/gb_reward.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_EXP_SOUL_4` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_exp_soul_4.png` | `tasks/Component/GeneralBattle/gb/gb_reward_exp_soul_4.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_GOLD` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_gold.png` | `tasks/Component/GeneralBattle/gb/gb_reward_gold.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_GOLD_SNAKE_SKIN` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_gold_snake_skin.png` | `tasks/Component/GeneralBattle/gb/gb_reward_gold_snake_skin.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_PARTICULARS` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_particulars.png` | `tasks/Component/GeneralBattle/gb/gb_reward_particulars.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_PARTICULARS_ORCHI` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_particulars_orchi.png` | `tasks/Component/GeneralBattle/gb/gb_reward_particulars_orchi.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_PURPLE_SNAKE_SKIN` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_purple_snake_skin.png` | `tasks/Component/GeneralBattle/gb/gb_reward_purple_snake_skin.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_SOUL_5` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_soul_5.png` | `tasks/Component/GeneralBattle/gb/gb_reward_soul_5.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_SOUL_6` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_soul_6.png` | `tasks/Component/GeneralBattle/gb/gb_reward_soul_6.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_REWARD_STATISTICS` | 一致 | `tasks/Component/GeneralBattle/gb/gb_reward_statistics.png` | `tasks/Component/GeneralBattle/gb/gb_reward_statistics.png` | 登录/庭院/町中/娱乐/棋局导航 |

### `tasks.Component.SwitchAccount.assets.SwitchAccountAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_CHECK_LOGIN_FORM` | 一致 | `tasks/Component/SwitchAccount/res/check_login_form.png` | `tasks/Component/SwitchAccount/res/check_login_form.png` | 登录/庭院/町中/娱乐/棋局导航 |

### `tasks.Exploration.assets.ExplorationAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_E_EXIT_CONFIRM` | 一致 | `tasks/Exploration/res/res_e_exit_confirm.png` | `tasks/Exploration/res/res_e_exit_confirm.png` | 公共导航恢复/未知页关闭 |

### `tasks.GameUi.assets.GameUiAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_ACTIVITY_SKIP` | 图片不同 | `tasks/GameUi/page/page_activity_skip.png` | `tasks/GameUi/page/page_activity_skip.png` | 公共导航恢复/未知页关闭 |
| `I_AD_CLOSE_RED` | 一致 | `tasks/GameUi/additional/additional_ad_close_red.png` | `tasks/GameUi/additional/additional_ad_close_red.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_BACK_BROWN` | 一致 | `tasks/GameUi/page/page_back_brown.png` | `tasks/GameUi/page/page_back_brown.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_BACK_DAILY` | 一致 | `tasks/GameUi/page/page_back_daily.png` | `tasks/GameUi/page/page_back_daily.png` | 公共导航恢复/未知页关闭 |
| `I_CHECK_CHESS` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_chess.png` | `tasks/GameUi/page_checks/page_check_chess.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_CHESS_BATTLE` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_chess_battle.png` | `tasks/GameUi/page_checks/page_check_chess_battle.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_CHESS_RANK` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_chess_rank.png` | `tasks/GameUi/page_checks/page_check_chess_rank.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_ENTERTAINMENT` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_entertainment.png` | `tasks/GameUi/page_checks/page_check_entertainment.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_LINEUP_HELPER` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_lineup_helper.png` | `tasks/GameUi/page_checks/page_check_lineup_helper.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_MAIN` | 图片及参数不同 | `tasks/GameUi/page/page_check_main.png` | `tasks/GameUi/page_checks/page_check_main.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_MAIN_SET` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_main_set.png` | `tasks/GameUi/page_checks/page_check_main_set.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_TOWN` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_town.png` | `tasks/GameUi/page_checks/page_check_town.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHESS_EXIT` | 一致 | `tasks/GameUi/page/page_chess_exit.png` | `tasks/GameUi/page/page_chess_exit.png` | 棋局退出/结算 |
| `I_CHESS_EXIT_TO_LOBBY` | 一致 | `tasks/GameUi/page/page_chess_exit_to_lobby.png` | `tasks/GameUi/page/page_chess_exit_to_lobby.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHESS_EXIT_TO_LOBBY_2` | 一致 | `tasks/GameUi/page/page_chess_exit_to_lobby_2.png` | `tasks/GameUi/page/page_chess_exit_to_lobby_2.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHESS_RANK_GOTO_LOBBY` | 一致 | `tasks/GameUi/page/page_chess_rank_goto_lobby.png` | `tasks/GameUi/page/page_chess_rank_goto_lobby.png` | 棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CLOSE_RED` | 缺失 | 缺失 | `tasks/GameUi/page/page_close_red.png` | 棋局直接调用 |
| `I_ENTERTAINMENT_GOTO_CHESS` | 一致 | `tasks/GameUi/page/page_entertainment_goto_chess.png` | `tasks/GameUi/page/page_entertainment_goto_chess.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_MAIN_GOTO_TOWN` | 一致 | `tasks/GameUi/page/page_main_goto_town.png` | `tasks/GameUi/page/page_main_goto_town.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_TOWN_GOTO_ENTERTAINMENT` | 一致 | `tasks/GameUi/page/page_town_goto_entertainment.png` | `tasks/GameUi/page/page_town_goto_entertainment.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_TOWN_GOTO_MAIN` | 一致 | `tasks/GameUi/page/page_town_goto_main.png` | `tasks/GameUi/page/page_town_goto_main.png` | 登录/庭院/町中/娱乐/棋局导航 |

### `tasks.GlobalGame.assets.GlobalGameAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_CHAT_CLOSE_BUTTON` | 一致 | `tasks/GlobalGame/gg/gg_chat_close_button.png` | `tasks/GlobalGame/gg/gg_chat_close_button.png` | 公共导航恢复/未知页关闭 |
| `I_CLIENT_CLEAR` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_client_clear.png` | `tasks/GlobalGame/gg/gg_client_clear.png` | 棋局网络重连/登录 |
| `I_G_ACCEPT` | 图片不同 | `tasks/GlobalGame/gg/gg_g_accept.png` | `tasks/GlobalGame/gg/gg_g_accept.png` | 公共邀请处理 |
| `I_G_CAT_FOOD` | 参数不同 | `tasks/GlobalGame/gg/gg_g_cat_food.png` | `tasks/GlobalGame/gg/gg_g_cat_food.png` | 公共邀请处理 |
| `I_G_DOG_FOOD` | 参数不同 | `tasks/GlobalGame/gg/gg_g_dog_food.png` | `tasks/GlobalGame/gg/gg_g_dog_food.png` | 公共邀请处理 |
| `I_G_IGNORE` | 一致 | `tasks/GlobalGame/gg/gg_g_ignore.png` | `tasks/GlobalGame/gg/gg_g_ignore.png` | 公共邀请处理 |
| `I_G_JADE` | 参数不同 | `tasks/GlobalGame/gg/gg_g_jade.png` | `tasks/GlobalGame/gg/gg_g_jade.png` | 公共邀请处理 |
| `I_G_REJECT` | 图片不同 | `tasks/GlobalGame/gg/gg_g_reject.png` | `tasks/GlobalGame/gg/gg_g_reject.png` | 公共邀请处理 |
| `I_NETWORK_ABNORMAL` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_network_abnormal.png` | `tasks/GlobalGame/gg/gg_network_abnormal.png` | 来源全局网络恢复（本次未移植） |
| `I_NETWORK_ERROR` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_network_error.png` | `tasks/GlobalGame/gg/gg_network_error.png` | 来源全局网络恢复（本次未移植） |
| `I_UI_BACK_BLUE` | 一致 | `tasks/GlobalGame/ui/ui_ui_back_blue.png` | `tasks/GlobalGame/ui/ui_ui_back_blue.png` | 公共导航恢复/未知页关闭 |
| `I_UI_BACK_RED` | 一致 | `tasks/GlobalGame/ui/ui_ui_back_red.png` | `tasks/GlobalGame/ui/ui_ui_back_red.png` | 登录/庭院/町中/娱乐/棋局导航、公共导航恢复/未知页关闭 |
| `I_UI_BACK_YELLOW` | 一致 | `tasks/GlobalGame/ui/ui_ui_back_yellow.png` | `tasks/GlobalGame/ui/ui_ui_back_yellow.png` | 登录/庭院/町中/娱乐/棋局导航、公共导航恢复/未知页关闭 |
| `I_UI_CONFIRM` | 图片及参数不同 | `tasks/GlobalGame/ui/ui_ui_confirm.png` | `tasks/GlobalGame/ui/ui_confirm.png` | 公共导航恢复/未知页关闭 |
| `I_UI_CONFIRM_SAMLL` | 一致 | `tasks/GlobalGame/ui/ui_ui_confirm_samll.png` | `tasks/GlobalGame/ui/ui_ui_confirm_samll.png` | 公共导航恢复/未知页关闭 |
| `I_UI_REWARD` | 图片及参数不同 | `tasks/GlobalGame/ui/ui_ui_reward.png` | `tasks/GlobalGame/ui/ui_ui_reward.png` | 棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |

### `tasks.Restart.assets.RestartAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_CANCEL_BATTLE` | 一致 | `tasks/Restart/login/login_cancel_battle.png` | `tasks/Restart/login/login_cancel_battle.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_LOGIN_8` | 一致 | `tasks/Restart/login/login_login_8.png` | `tasks/Restart/login/login_login_8.png` | 棋局网络重连/登录 |

### `tasks.SixRealms.assets.SixRealmsAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_EXIT_SIXREALMS` | 一致 | `tasks/SixRealms/moon_sea/ms/ms_exit_sixrealms.png` | `tasks/SixRealms/moon_sea/ms/ms_exit_sixrealms.png` | 公共导航恢复/未知页关闭 |

## 历史适配及验证记录（2026-10-23）

- 新版购买传入 `max_clicks=3`，当前公共 `BaseTask` 没有该参数。已在棋局类中实现相同行为；不带上限的调用仍交给原公共方法。避免修改所有任务共享的接口。
- 满币结束使用当前项目的 `set_next_run_next_monday(task='Chess')` 接口，保留当前 cron 调度约定。
- 浮窗红叉使用棋局独立的 `I_SHARED_CLOSE_RED`；其余 13 项差异也在棋局内部适配，公共定义保持原样。
- 完整流程适配后的 507 项测试通过；本次新增 17 项容量、下阵、升星、投掷配置和超时保护测试后，全项目共 524 项全部通过。已有配置迁移、Frame、购买、御魂、符咒及公共导航/结算测试继续通过。
- 完整流程适配时静态核对 636 处可解析的棋局方法调用，参数签名无不兼容；本次项目结构检查及 `git diff --check` 继续通过。
- 以上为代码、静态资源及合成画面的验证；尚未在模拟器完成一整局新版本实测。实际画面的识别效果及一整局操作仍需在目标模拟器验证。

## 2026-10-26 同步记录（abb5d928）

- 同步 `7cc93181..abb5d928` 中全部棋局改动：普通/首领 Frame、每次下阵重试前容量检查、JSON 阵容、编辑器、金鱼主动识别与移动、专属纹章保留和装备槽预留。保留本项目的满手牌腾位、公共识别隔离和网络恢复。
- 编辑器包括 `module/server/chesslineup_router.py`、`module/server/web/chesslineup` 全部静态文件，及当前配置模型中仅对 `Chess` 生效的动态阵容选项；同步模板的新 `custom_lineup` 字段及两项中文翻译。
- 原始手牌/商店 Frame 仅新增显式 `badgeGrayscale=false` 元数据，裁剪区域与模板未变；重新计算配套 `card_index.json` 布局指纹，保持运行时一致性校验。纹章布局也与索引逐项核对。
- 参考库把 `haiguo` 内置阵容显示名改为“荒川”，但旧海国配置的迁移指向未提供的 `custom:haiguo`。适配为已有自定义版本优先，否则使用随仓库提供的 `builtin:haiguo`；明确选择内置荒川时保持内置标识。
- 不导入无棋局调用依赖的组队协同、逢魔之时、斗技或鼬乐币商店修改。现有全局调度及其他任务代码保持原版本。
- 同步前全项目 528 项测试通过；新增 19 项测试后，共 547 项通过。验证编辑器所有目录卡图均返回成功、保存/删除/转换/应用、旧配置迁移、局内快照、普通/首领定位、锚点缺失不判为空、金鱼换位和纹章槽预留。
