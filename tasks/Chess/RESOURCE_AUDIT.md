# 百鬼棋局资源与全局依赖核对

核对日期：2026-10-30。来源目录：`D:/OnmyojiAutoScript-xylolit-mu`，版本 `4d9ef784`；目标项目：`D:/OAS/OnmyojiAutoScript`。

## 私有远端复核

2026-10-30 已使用参考仓库现有的 `config/git_ssh.key`，通过 SSH 443 端口成功拉取 `git@github.com:xylolit-mu/OnmyojiAutoScript-private.git`。仅以私有远端为本轮及后续同步来源。

私有远端 `dev` 最新为 `4d9ef7843cc36ba0f83ba0ef2e04054193ec3953`（2026-10-29 23:04 +08:00），本地参考分支与其完全一致，快进更新检查返回已是最新。默认 `master` 为较旧的 `00c083e8`（2026-10-03），不作为新版棋局来源；没有将本地参考库回退到该旧分支。

## 历史公开快照核对

以下仅保留此前的核对记录，不作为本轮同步来源。2026-10-23 曾核对作者公开仓库的 `self` 分支 `47a3a3bc6173e6560ab8cc3658d3e55bc2c80287`（2026-10-22）。按 Git blob 比较，该公开快照的全部 456 个棋局文件与本地来源的 `a5b8f7aa` 基线一致，59 条共用规则涉及的 62 个图片及规则类文件也一致。

- [全局浮窗红叉](https://github.com/xylolit-mu/OnmyojiAutoScript/blob/47a3a3bc6173e6560ab8cc3658d3e55bc2c80287/tasks/GameUi/page/page_close_red.png)确实存在于公开库；完整流程移植时已作为棋局专用副本加入。
- [百鬼投掷资源清单](https://github.com/xylolit-mu/OnmyojiAutoScript/blob/47a3a3bc6173e6560ab8cc3658d3e55bc2c80287/tasks/Chess/resource/hyakki_soul/manifest.json)仍明确缺少狂骨和地藏像。公开库已有的同名图片位于普通手牌御魂目录，不能直接作为投掷阶段模板。
- 额外检查 `mine`、`pr`、`test` 三个分支：没有找到这两种百鬼投掷专用模板。`test` 的旧版普通御魂目录也有同名图片，仍属于不同用途。

## 完整流程移植结果

本次按“保留现有脚本功能”的要求，维护 16 项棋局专用公共识别副本于 `tasks/Chess/shared_ui`，由 `runtime/shared_ui.py` 在棋局实例内部使用。公共规则定义、公共页面图、其他任务和调度器没有修改。

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

## 2026-10-30 同步记录（私有远端 dev / 4d9ef784）

- 合并 `bc532746..4d9ef784` 的全部棋局增量：`cache.py`、`economy.py`、`frame_cards.py` 和 `script_task.py`。本次变更的 10 个参考方法与来源 AST 一致；830 处可静态核对的棋局方法调用参数兼容。
- 备阶段经济保留 12 秒保护；战阶段购买和升级按预算继续，刷新入口及每次实际点击前都检查最后 5 秒限制，并扣除倒计时缓存年龄。刷新额度仍按实际点击消耗。
- 商店动画期间，完整五槽身份连续两帧稳定且至少三个槽位改变，可作为刷新确认。超时未确认时仅补扫当前商店购买一次，随后阻止本轮继续刷新，避免重复消耗金币。
- 卡牌先匹配头像，多候选时再读取羁绊，商店仍有歧义才读取名称；羁绊优先于冲突名称，不对头像或点击范围执行 OCR。
- 同步普通确认按钮的图片、裁剪 `[692, 419, 124, 39]`、`High` profile 及来源 SHA-256，并重新生成棋局 `assets.py`。仍通过棋局专用副本使用；16 项副本的图片与规则均与来源一致。来源另增的六道备用确认仅用于独立六道任务，没有棋局调用依赖。
- 完整复核参考版的金鱼详情检查、主次羁绊纹章保留、装备槽预留和每回合备阶段棋盘核对调用链。阵容编辑器路由、静态服务、卡面、配置读写钩子、中文文案和用户数据忽略规则均已配套存在；旧海国迁移、满手牌下阵前腾位、周调度及网络恢复继续采用本项目的兼容适配。
- 公共 Frame 的 19 个规则方法、3 个结果方法、资源生成器、`BaseTask.runframe`、图像服务匹配入口及 5 个标注后台方法均与参考实现一致（标注默认 profile 保留当前项目约定）。全部 428 张来源棋局图片一致，含副本的 444 张 PNG 均可读取；头像、纹章、符咒索引和 Frame 布局指纹通过。
- 棋局 138 项、当前开发工作区全套 615 项测试通过，新增覆盖选择性 OCR、分阶段截止、缓存年龄、点击前复核、动画刷新确认和超时补扫；未进行模拟器完整对局验证。来源仍缺狂骨、地藏像两种百鬼投掷专用模板。

## 2026-10-29 同步记录（bc532746）

- 合并 `5502dc1f`、`7dc61fe2`、`bc532746` 的全部棋局改动。94 个新增或修改的方法均已检查；除两处下阵方法保留当前项目的满手牌腾位检查外，变更方法与参考库一致。818 处可静态核对的方法调用参数兼容。
- Frame 规则和定位图从 `resource` 移至 `c`，新增普通、野怪、百鬼三套详情 Frame；配套移植公共 Frame 的 Digit OCR、整数条件校验及数字读取。八套 Frame 的图片、头像索引和布局指纹均可读取。
- 补齐此前缺少的 Frame 标注组件：前端编辑/多范围面板、配置模型、后台类型检测、保存/重载、裁剪和只读预览。Digit 条件与运行时一致，原有其他规则的默认 profile 保持 `Default`。
- 拖拽使用快速/重试两档，并在业务确认后清除 pending；minitouch 批量发送手势，uiautomator2/scrcpy 不自动重放不确定动作，异常时尽力松手。完整移植 scrcpy `RLock` 依赖，实测控制发送器可以在手势锁内再次加锁，避免死锁。
- 购买改为点击前确认金币定位标志、点击后检查该位置标志消失，累计最多三次。手牌未满时不因购买失败出售手牌；售卖统一做回合/阶段及两帧数量复核，失败目标每回合最多两次，无法装配的御魂优先于阵容卡出售。
- 同一截图复用等级、金币、手牌容量等读取；升级后商店像素未变时复用身份结果，统一使用设备 combat 截图间隔并在退出时恢复。经济动作保留 12 秒截止，棋盘动作保留最后 2 秒保护。
- 首次百鬼确认本人昵称后每回合关店读取生命；保留金从普通 50、低于 60 生命时 40 调整到低于 20 生命时 0，并停止升级。未到最终阶数的普通刷新额度为每回合 `max(0, 阶数-5)`，实际点击即计数。
- 金鱼移动后复核目标详情，失败不改写站位；确认非金鱼的位置当局跳过。备阶段阵容检查仅复用有效且有人的关店截图，每回合一次。
- 六道自动选择新增默认开启的配置开关；关闭时等待页面结束。町中入口恢复按参考逻辑放入棋局专用 mixin，不替换当前公共导航。同步协作勾玉、猫粮、狗粮的图片和区域。
- 棋局 126 项、当前开发工作区全套 603 项测试通过；其中覆盖 Frame 标注保存/重载/预览、三种拖拽后端及异常松手、购买和售卖确认、生命阈值/刷新额度、金鱼及导航恢复。未进行模拟器完整对局验证。
- 参考提交中的结界挂卡轮换、式神委派奖励、活动任务和悬赏任务修改没有棋局依赖，不在本次移植范围。原库仍缺狂骨和地藏像两种百鬼投掷模板。

## 2026-10-28 同步记录（e78d4cc0 / f2b70c87）

- 完整合并 `e78d4cc0` 的三处阶段保护：每次系统卡下阵前检查备阶段，拖拽确认期间允许阶段结束立即中断，返回上阵流程后再次检查阶段。战斗开始不确认下阵成功、不继续拖卡、不清空原有上阵登记。
- 连同参考快照 `f2b70c87` 的共用协作接受、拒绝、忽略图片与坐标一起移植；补齐原本未映射的忽略按钮，并沿截图→公共邀请处理→实际命中坐标点击验证全部五种邀请策略。
- 全流程复核还发现庭院卷轴按钮图片有差异，增加棋局专用模板并验证庭院导航。公共识别和其他任务保留当前实现，棋局优先来源模板、当前模板回退。
- RuleFrame 的 19 个方法、FrameResult 的 3 个方法、FrameExtractor、BaseTask.runframe 和图像服务 Frame 匹配入口逐项与参考库一致，无框架缺项；706 处可静态核对的棋局 self 调用签名兼容。
- 核对全部 426 张来源棋局图片和 16 张公共副本，以及头像、纹章、符咒索引与布局指纹；当前 442 张图片均可解码。原库仍缺少狂骨、地藏像两张百鬼投掷专用模板，未用普通手牌图片替代。
- 新增 7 项阶段切换、真实邀请识别及导航回归测试；棋局 104 项、当前开发工作区全套 581 项测试通过。相关改动仅涉及棋局及其回归测试；本次参考快照中的悬赏任务新功能不属于棋局移植范围。

## 范围和结论

- 移植范围为 `tasks/Chess` 的新版本代码、规则、模板、`config/template.json` 的棋局配置项及对应测试；中文翻译仅涉及 `hyakki_draft_enabled`。
- 检查棋局直接引用、字符串生成的阶段标志、Frame 相对区域及索引、动态扫描的头像/符咒/御魂目录，并向外追踪共用棋局退出、导航入口、公共奖励处理、未知页面恢复和邀请处理。来源的网络恢复规则另列为公共框架能力。
- 共核对 444 张棋局 PNG，均存在且可解码，含与来源逐张一致的 428 张任务图片和 16 张共用模板副本；64 个手牌身份、63 个商店身份、19 个纹章/复制术身份、200 张符咒图、20 种普通手牌御魂及 18 种百鬼投掷御魂有实际文件。
- 合并来源与当前项目的调用链，核对 61 项公共定义：39 项完全一致，7 项仅目录迁移，12 项图片或参数不同，1 项仅在来源存在，另 2 项仅在当前项目存在。12 项差异与来源红叉均在 16 项棋局副本范围内；当前活动跳过映射到来源跳过模板，一键返回保留当前项目实现。
- “存在差异”表示公共定义与来源版本不同，不能据此认定当前全局规则在实机上失效。棋局适配使用独立副本，公共定义继续供其他任务使用。

## 完整棋局流程

| 阶段 | 本任务的处理和专用资源 | 共用识别或流程 |
| --- | --- | --- |
| 启动恢复 | 局内标志、六道三选一、异常大厅、取消等待；必要时主动退出遗留对局 | `GameUi` 页面识别、`ChessBattleNavigationMixin`、退出确认 |
| 进入大厅 | 庭院→町中→娱乐→百鬼棋局；娱乐跳过动画 | 庭院/町中/娱乐/棋局页面检查及跳转按钮 |
| 开始匹配 | 开始、取消等待、六道选择、匹配超时重试及局内确认 | 共用页面恢复和未知页关闭 |
| 读取回目 | 普通、野怪、百鬼三套详情 Frame 一次读取回合、阶段和倒计时；关店后读取本人生命 | Digit/Single OCR、Frame、逐帧缓存及图像服务 |
| 备阶段 | 扫描买卡→升级/刷新→部署→黄金复制术/纹章/御魂；符咒选择优先中断 | Frame 读取和图像服务；新版点击上限由棋局内部兼容 |
| 战阶段 | 清理非体系手牌→按预算买卡/升级/刷新→等待；刷新在最后 5 秒停止 | 截图与公共邀请处理 |
| 百鬼阶段 | 黄色昵称框定位本人→确认锁消失→等待约六秒→匹配御魂→再次截图复核→补偿移动后投掷，每回合最多两次 | OCR 检测框；本阶段图标均位于 `Chess/resource/hyakki_soul` |
| 大蛇/逢魔回合 | 激活金色阶段标志出现过后，使用首领专用棋盘 Frame 判定站位和落点 | 图像服务 |
| 符咒选择 | 图标/索引优先；三选项均不明时重新截图一次后兜底 | 截图与图像服务 |
| 结束和下一局 | 局内标志连续消失确认→奖励/分享→排名 OCR→返回大厅或再来一局 | `I_UI_REWARD`、全局棋局排名及返回按钮 |
| 保段位/满币结束 | 保段位退出两局；遵守局数/时长；满币后安排下周任务 | 共用退出确认、当前项目 cron 调度接口 |

## 棋局内部资源结果

| 资源组 | PNG 数量 | 核对结果 |
| --- | ---: | --- |
| `c` | 39 | 八套 Frame、界面识别、手牌/商店/纹章/棋盘定位标志可读取；Digit 和 Single OCR 配套 |
| `resource/card` | 65 | 64 个手牌身份；定位标志已移至 c/card，索引和布局指纹通过 |
| `resource/store` | 63 | 商店头像齐全；定位标志已移至 c/store，索引和布局指纹通过 |
| `resource/fetter` | 20 | 19 个纹章/复制术身份，含黄金复制术；定位标志移至 c/fetter |
| `resource/badge` | 200 | 符咒文件索引无缺项 |
| `resource/board` | 3 | 三种棋盘勾玉可读取；表情锚点移至 c/board，普通/首领 Frame 配套 |
| `resource/soul` | 20 | 普通手牌御魂模板可读取 |
| `resource/hyakki_soul` | 18 | 百鬼投掷模板可读取；仍缺下述两种 |
| `shared_ui` | 16 | 退出、奖励、庭院、红叉、协作、跳过及网络识别副本，文件指纹与来源一致 |

### 来源本身缺少的投掷模板

`resource/hyakki_soul/manifest.json` 明确声明缺少 `kuanggu`（狂骨）和 `dizangxiang`（地藏像）。因此百鬼投掷阶段不能按图标识别这两种目标；模板无法凭现有文件补出，需采集该阶段的实际截图后裁剪。普通手牌目录中这两种御魂的模板存在，但画面样式不同，不能直接冒充投掷模板。

当前荒川阵容新增狂骨偏好，该目标属于上述已知缺失项，百鬼投掷时无法通过图标识别；普通手牌仍可识别并装备。其他已知优先御魂均有投掷模板。没有优先目标时的随机兜底也只会从已经识别出的目标中选择。

### 正常差异及非运行时路径

- 寻森小鹿男（`hiromori_shikaotoko`）只有手牌头像。作者已在 `shikigami_catalog.py` 的 `NON_SHOP_SHIKIGAMI` 明确将其排除于商店身份，故 64/63 的数量差不是资源遗漏。
- 四套阵容中使用的所有手牌和商店身份均在索引内；索引声明的头像、纹章及符咒文件均能读取。
- 投掷模板清单内的来源截图路径用于记录采集出处，运行时按当前目录中的 `sou_*.png` 加载，不读取作者机器上的原始截图路径。
- 来源已停用的棋局旧退出、旧排名、旧符咒刷新和商店金币模板已随任务一起清理；现有退出/排名处理使用公共 `GameUi` 资源。

## 全局差异及棋局适配

棋局保留 16 项来源副本，覆盖当前 12 项公共定义差异及公共红叉缺项。已与当前公共定义一致的副本仍保留，所有副本与参考快照的图片和区域一致。

识别先尝试来源模板，再回退当前模板；点击使用同帧实际命中的坐标。以下“当前”指本项目公共定义。

### `GeneralBattleAssets.I_EXIT_ENSURE`

- 当前：`tasks/Component/GeneralBattle/gb/gb_exit_ensure.png`；裁剪 `[664, 408, 180, 64]`；搜索 `[640, 380, 230, 110]`。
- 来源：`tasks/Component/GeneralBattle/gb/gb_exit_ensure.png`；裁剪 `[699, 414, 107, 46]`；搜索 `[662, 364, 250, 121]`；阈值 `0.8`。

### `GameUiAssets.I_ACTIVITY_SKIP`

- 当前：`tasks/GameUi/page/page_activity_skip.png`；裁剪 `[1159, 37, 51, 22]`；搜索 `[1141, 27, 86, 43]`。
- 来源：`tasks/GameUi/page/page_activity_skip.png`；裁剪 `[1159, 37, 51, 22]`；搜索 `[1141, 27, 86, 43]`；阈值 `0.8`。

### `GameUiAssets.I_CHECK_MAIN`

- 当前：`tasks/GameUi/page/page_check_main.png`；裁剪 `[807, 108, 76, 45]`；搜索 `[49, 98, 1033, 80]`。
- 来源：`tasks/GameUi/page_checks/page_check_main.png`；裁剪 `[807, 108, 76, 45]`；搜索 `[47, 88, 1046, 102]`；阈值 `0.95`。

### `GameUiAssets.I_CLOSE_RED`

- 当前：无此规则；棋局通过专用副本处理。
- 来源：`tasks/GameUi/page/page_close_red.png`；裁剪 `[1169, 60, 33, 25]`；搜索 `[1077, 19, 151, 144]`；阈值 `0.8`。

### `GlobalGameAssets.I_G_ACCEPT`

- 当前：`tasks/GlobalGame/gg/gg_g_accept.png`；裁剪 `[846, 476, 56, 46]`；搜索 `[814, 430, 117, 110]`。
- 来源：`tasks/GlobalGame/gg/gg_g_accept.png`；裁剪 `[846, 476, 56, 46]`；搜索 `[814, 430, 117, 110]`；阈值 `0.8`。

### `GlobalGameAssets.I_G_CAT_FOOD`

- 当前：`tasks/GlobalGame/gg/gg_g_cat_food.png`；裁剪 `[565, 463, 59, 65]`；搜索 `[543, 421, 205, 176]`。
- 来源：`tasks/GlobalGame/gg/gg_g_cat_food.png`；裁剪 `[666, 499, 59, 65]`；搜索 `[543, 421, 205, 176]`；阈值 `0.8`。

### `GlobalGameAssets.I_G_DOG_FOOD`

- 当前：`tasks/GlobalGame/gg/gg_g_dog_food.png`；裁剪 `[565, 464, 60, 63]`；搜索 `[543, 421, 205, 176]`。
- 来源：`tasks/GlobalGame/gg/gg_g_dog_food.png`；裁剪 `[575, 510, 63, 54]`；搜索 `[543, 421, 205, 176]`；阈值 `0.8`。

### `GlobalGameAssets.I_G_JADE`

- 当前：`tasks/GlobalGame/gg/gg_g_jade.png`；裁剪 `[661, 466, 43, 46]`；搜索 `[543, 421, 205, 176]`。
- 来源：`tasks/GlobalGame/gg/gg_g_jade.png`；裁剪 `[676, 512, 43, 46]`；搜索 `[650, 489, 94, 100]`；阈值 `0.8`。

### `GlobalGameAssets.I_G_REJECT`

- 当前：`tasks/GlobalGame/gg/gg_g_reject.png`；裁剪 `[846, 562, 53, 51]`；搜索 `[819, 536, 108, 101]`。
- 来源：`tasks/GlobalGame/gg/gg_g_reject.png`；裁剪 `[846, 562, 53, 51]`；搜索 `[819, 536, 108, 101]`；阈值 `0.8`。

### `GlobalGameAssets.I_NETWORK_ABNORMAL`

- 当前：`tasks/GlobalGame/gg/gg_network_abnormal.png`；裁剪 `[583, 330, 221, 67]`；搜索 `[583, 330, 221, 67]`。
- 来源：`tasks/GlobalGame/gg/gg_network_abnormal.png`；裁剪 `[588, 335, 211, 57]`；搜索 `[583, 330, 221, 67]`；阈值 `0.8`。

### `GlobalGameAssets.I_NETWORK_ERROR`

- 当前：`tasks/GlobalGame/gg/gg_network_error.png`；裁剪 `[431, 253, 416, 208]`；搜索 `[431, 253, 416, 208]`。
- 来源：`tasks/GlobalGame/gg/gg_network_error.png`；裁剪 `[436, 258, 406, 198]`；搜索 `[431, 253, 416, 208]`；阈值 `0.8`。

### `GlobalGameAssets.I_UI_CONFIRM`

- 当前：`tasks/GlobalGame/ui/ui_ui_confirm.png`；裁剪 `[664, 408, 180, 64]`；搜索 `[547, 368, 322, 122]`。
- 来源：`tasks/GlobalGame/ui/ui_confirm.png`；裁剪 `[692, 419, 124, 39]`；搜索 `[547, 368, 322, 122]`；阈值 `0.8`；profile `High`。

### `GlobalGameAssets.I_UI_REWARD`

- 当前：`tasks/GlobalGame/ui/ui_ui_reward.png`；裁剪 `[518, 210, 240, 65]`；搜索 `[464, 142, 350, 145]`。
- 来源：`tasks/GlobalGame/ui/ui_ui_reward.png`；裁剪 `[521, 212, 237, 66]`；搜索 `[361, 47, 556, 286]`；阈值 `0.73`。

### `GlobalGameAssets.I_CLIENT_CLEAR`

- 当前：`tasks/GlobalGame/gg/gg_client_clear.png`；裁剪 `[578, 369, 151, 72]`；搜索 `[578, 369, 151, 72]`。
- 来源：`tasks/GlobalGame/gg/gg_client_clear.png`；裁剪 `[599, 383, 85, 42]`；搜索 `[594, 378, 95, 52]`；阈值 `0.8`。

### `GlobalGameAssets.I_G_IGNORE`

- 当前：`tasks/GlobalGame/gg/gg_g_ignore.png`；裁剪 `[792, 86, 21, 21]`；搜索 `[777, 65, 48, 48]`。
- 来源：`tasks/GlobalGame/gg/gg_g_ignore.png`；裁剪 `[792, 86, 21, 21]`；搜索 `[777, 65, 48, 48]`；阈值 `0.8`。

### `GameUiAssets.I_MAIN_SCROLL_CLOSE`

- 当前：`tasks/GameUi/page/page_main_scroll_close.png`；裁剪 `[1181, 634, 28, 39]`；搜索 `[1162, 595, 77, 112]`。
- 来源：`tasks/GameUi/page/page_main_scroll_close.png`；裁剪 `[1181, 634, 28, 39]`；搜索 `[1162, 595, 77, 112]`；阈值 `0.8`。

## 全部 61 项共用规则

以下为来源和当前调用链的合并清单。公共定义保留原样；差异项由棋局专用副本适配。


### `tasks.ActivityShikigami.assets.ActivityShikigamiAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_SKIP_BUTTON` | 来源无此项，棋局映射来源跳过模板 | `tasks/ActivityShikigami/as/page/as_skip_button.png` | 无此规则 | 公共导航恢复/未知页关闭 |

### `tasks.Component.GeneralBattle.assets.GeneralBattleAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `C_RANDOM_BOTTOM` | 一致 | 无图片 | 无图片 | 登录/庭院/町中/娱乐/棋局导航 |
| `C_RANDOM_LEFT` | 一致 | 无图片 | 无图片 | 棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `C_RANDOM_RIGHT` | 一致 | 无图片 | 无图片 | 登录/庭院/町中/娱乐/棋局导航 |
| `C_RANDOM_TOP` | 一致 | 无图片 | 无图片 | 登录/庭院/町中/娱乐/棋局导航 |
| `I_EXIT_ENSURE` | 图片及参数不同 | `tasks/Component/GeneralBattle/gb/gb_exit_ensure.png` | `tasks/Component/GeneralBattle/gb/gb_exit_ensure.png` | 棋局直接调用、棋局退出/结算 |
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
| `I_ACTIVITY_SKIP` | 图片不同 | `tasks/GameUi/page/page_activity_skip.png` | `tasks/GameUi/page/page_activity_skip.png` | 公共导航恢复/未知页关闭、棋局直接调用 |
| `I_AD_CLOSE_RED` | 一致 | `tasks/GameUi/additional/additional_ad_close_red.png` | `tasks/GameUi/additional/additional_ad_close_red.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_BACK_BROWN` | 一致 | `tasks/GameUi/page/page_back_brown.png` | `tasks/GameUi/page/page_back_brown.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_BACK_DAILY` | 一致 | `tasks/GameUi/page/page_back_daily.png` | `tasks/GameUi/page/page_back_daily.png` | 公共导航恢复/未知页关闭 |
| `I_CHECK_CHESS` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_chess.png` | `tasks/GameUi/page_checks/page_check_chess.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_CHESS_BATTLE` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_chess_battle.png` | `tasks/GameUi/page_checks/page_check_chess_battle.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_CHESS_RANK` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_chess_rank.png` | `tasks/GameUi/page_checks/page_check_chess_rank.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_ENTERTAINMENT` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_entertainment.png` | `tasks/GameUi/page_checks/page_check_entertainment.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_LINEUP_HELPER` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_lineup_helper.png` | `tasks/GameUi/page_checks/page_check_lineup_helper.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_MAIN` | 图片及参数不同 | `tasks/GameUi/page/page_check_main.png` | `tasks/GameUi/page_checks/page_check_main.png` | 棋局直接调用、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_MAIN_SET` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_main_set.png` | `tasks/GameUi/page_checks/page_check_main_set.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHECK_TOWN` | 目录调整，内容相同 | `tasks/GameUi/page/page_check_town.png` | `tasks/GameUi/page_checks/page_check_town.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_CHESS_EXIT` | 一致 | `tasks/GameUi/page/page_chess_exit.png` | `tasks/GameUi/page/page_chess_exit.png` | 棋局退出/结算 |
| `I_CHESS_EXIT_TO_LOBBY` | 一致 | `tasks/GameUi/page/page_chess_exit_to_lobby.png` | `tasks/GameUi/page/page_chess_exit_to_lobby.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHESS_EXIT_TO_LOBBY_2` | 一致 | `tasks/GameUi/page/page_chess_exit_to_lobby_2.png` | `tasks/GameUi/page/page_chess_exit_to_lobby_2.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CHESS_RANK_GOTO_LOBBY` | 一致 | `tasks/GameUi/page/page_chess_rank_goto_lobby.png` | `tasks/GameUi/page/page_chess_rank_goto_lobby.png` | 棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |
| `I_CLOSE_RED` | 公共定义缺失，棋局使用来源副本 | 无此规则 | `tasks/GameUi/page/page_close_red.png` | 棋局直接调用 |
| `I_ENTERTAINMENT_GOTO_CHESS` | 一致 | `tasks/GameUi/page/page_entertainment_goto_chess.png` | `tasks/GameUi/page/page_entertainment_goto_chess.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_MAIN_GOTO_TOWN` | 一致 | `tasks/GameUi/page/page_main_goto_town.png` | `tasks/GameUi/page/page_main_goto_town.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_MAIN_SCROLL_CLOSE` | 图片不同 | `tasks/GameUi/page/page_main_scroll_close.png` | `tasks/GameUi/page/page_main_scroll_close.png` | 公共导航恢复/未知页关闭、棋局直接调用 |
| `I_RETURN_MAIN` | 仅当前项目，保留当前实现 | `tasks/GameUi/page/page_return_main.png` | 无此规则 | 公共导航恢复/未知页关闭 |
| `I_TOWN_GOTO_ENTERTAINMENT` | 一致 | `tasks/GameUi/page/page_town_goto_entertainment.png` | `tasks/GameUi/page/page_town_goto_entertainment.png` | 登录/庭院/町中/娱乐/棋局导航 |
| `I_TOWN_GOTO_MAIN` | 一致 | `tasks/GameUi/page/page_town_goto_main.png` | `tasks/GameUi/page/page_town_goto_main.png` | 登录/庭院/町中/娱乐/棋局导航 |

### `tasks.GlobalGame.assets.GlobalGameAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_CHAT_CLOSE_BUTTON` | 一致 | `tasks/GlobalGame/gg/gg_chat_close_button.png` | `tasks/GlobalGame/gg/gg_chat_close_button.png` | 公共导航恢复/未知页关闭 |
| `I_CLIENT_CLEAR` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_client_clear.png` | `tasks/GlobalGame/gg/gg_client_clear.png` | 棋局直接调用 |
| `I_G_ACCEPT` | 一致 | `tasks/GlobalGame/gg/gg_g_accept.png` | `tasks/GlobalGame/gg/gg_g_accept.png` | 公共邀请处理、棋局直接调用 |
| `I_G_CAT_FOOD` | 参数不同 | `tasks/GlobalGame/gg/gg_g_cat_food.png` | `tasks/GlobalGame/gg/gg_g_cat_food.png` | 公共邀请处理、棋局直接调用 |
| `I_G_DOG_FOOD` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_g_dog_food.png` | `tasks/GlobalGame/gg/gg_g_dog_food.png` | 公共邀请处理、棋局直接调用 |
| `I_G_IGNORE` | 一致 | `tasks/GlobalGame/gg/gg_g_ignore.png` | `tasks/GlobalGame/gg/gg_g_ignore.png` | 公共邀请处理、棋局直接调用 |
| `I_G_JADE` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_g_jade.png` | `tasks/GlobalGame/gg/gg_g_jade.png` | 公共邀请处理、棋局直接调用 |
| `I_G_REJECT` | 一致 | `tasks/GlobalGame/gg/gg_g_reject.png` | `tasks/GlobalGame/gg/gg_g_reject.png` | 公共邀请处理、棋局直接调用 |
| `I_NETWORK_ABNORMAL` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_network_abnormal.png` | `tasks/GlobalGame/gg/gg_network_abnormal.png` | 棋局网络恢复、棋局直接调用 |
| `I_NETWORK_ERROR` | 图片及参数不同 | `tasks/GlobalGame/gg/gg_network_error.png` | `tasks/GlobalGame/gg/gg_network_error.png` | 棋局网络恢复、棋局直接调用 |
| `I_UI_BACK_BLUE` | 一致 | `tasks/GlobalGame/ui/ui_ui_back_blue.png` | `tasks/GlobalGame/ui/ui_ui_back_blue.png` | 公共导航恢复/未知页关闭 |
| `I_UI_BACK_RED` | 一致 | `tasks/GlobalGame/ui/ui_ui_back_red.png` | `tasks/GlobalGame/ui/ui_ui_back_red.png` | 公共导航恢复/未知页关闭、登录/庭院/町中/娱乐/棋局导航 |
| `I_UI_BACK_YELLOW` | 一致 | `tasks/GlobalGame/ui/ui_ui_back_yellow.png` | `tasks/GlobalGame/ui/ui_ui_back_yellow.png` | 公共导航恢复/未知页关闭、登录/庭院/町中/娱乐/棋局导航 |
| `I_UI_CONFIRM` | 图片及参数不同 | `tasks/GlobalGame/ui/ui_ui_confirm.png` | `tasks/GlobalGame/ui/ui_confirm.png` | 公共导航恢复/未知页关闭、棋局直接调用 |
| `I_UI_CONFIRM_SAMLL` | 一致 | `tasks/GlobalGame/ui/ui_ui_confirm_samll.png` | `tasks/GlobalGame/ui/ui_ui_confirm_samll.png` | 公共导航恢复/未知页关闭 |
| `I_UI_REWARD` | 图片及参数不同 | `tasks/GlobalGame/ui/ui_ui_reward.png` | `tasks/GlobalGame/ui/ui_ui_reward.png` | 棋局直接调用、棋局退出/结算、登录/庭院/町中/娱乐/棋局导航 |

### `tasks.Restart.assets.RestartAssets`

| 规则 | 对比 | 当前文件 | 来源文件 | 调用路径 |
| --- | --- | --- | --- | --- |
| `I_CANCEL_BATTLE` | 一致 | `tasks/Restart/login/login_cancel_battle.png` | `tasks/Restart/login/login_cancel_battle.png` | 登录/庭院/町中/娱乐/棋局导航 |

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
