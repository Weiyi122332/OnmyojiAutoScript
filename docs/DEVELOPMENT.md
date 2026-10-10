# OAS 开发与排障手册

> 按 2026-09-28 工作区源码整理。适用于本仓库 `OnmyojiAutoScript`；同一工作区的 `OASX` 是配套 Flutter 客户端。实际行为以当前代码为准，尤其是活动任务和未提交的本地改动。

## 1. 从哪里开始

OAS 的主要运行链路是：

```text
OASX / HTTP、WebSocket 客户端
             │
             ▼
server.py → FastAPI (module/server/app.py)
             │
             ▼
MainManager → 每个配置实例一个 ScriptProcess（spawn 子进程）
             │
             ▼
script.py: Script.loop() → Config 调度 → tasks/<Task>/script_task.py: ScriptTask.run()
             │                            │
             ▼                            ▼
Device（截图、点击、ADB）       GameUi / 通用战斗 / 资源规则 / OCR
             │                            │
             └──────────────┬─────────────┘
                            ▼
                 图片 RPC、OCR RPC 服务
```

推荐阅读顺序：`server.py` → `module/server/app.py` → `module/server/main_manager.py` → `module/server/script_process.py` → `script.py` → `module/config/config.py` → `tasks/base_task.py` → 一个目标任务的 `script_task.py`。涉及页面时再读 [`tasks/GameUi/USAGE.md`](../tasks/GameUi/USAGE.md)；涉及战斗时读 [`tasks/Component/GeneralBattle/README.md`](../tasks/Component/GeneralBattle/README.md)。

### 目录速查

| 位置 | 职责 |
| --- | --- |
| `server.py`、`module/server/` | HTTP、WebSocket、脚本进程、日志、统计、标注工具和更新入口 |
| `script.py`、`module/script/` | 调度主循环、任务准备、模拟器和游戏生命周期、失败恢复 |
| `module/config/`、`config/` | Pydantic 配置模型、任务菜单、调度、实例 JSON、部署配置 |
| `tasks/` | 具体业务任务；目录与注册约定见 [`tasks/README.md`](../tasks/README.md)。`tasks/Component/` 是复用组件，`tasks/GameUi/` 是页面导航 |
| `module/device/` | 设备连接、截图、输入、应用控制与模拟器适配 |
| `module/atom/`、`module/image/`、`module/ocr/` | 图片、点击、滑动、OCR 等规则对象及其 RPC 运行时 |
| `assets/i18n/`、`module/server/i18n.py` | 前后端交换的任务名、参数名、帮助文本翻译 |
| `dev_tools/` | 从规则 JSON 生成 `assets.py` 等开发脚本 |
| `tests/` | 无设备依赖的回归测试和项目结构检查测试 |
| `deploy/`、`requirements*.txt` | 安装器、默认部署配置、依赖清单 |
| `bin/`、`fluentui/` | 运行附带的设备文件与桌面界面资源 |
| `module/gui/`、`gui.py` | 仓库内的 PySide/QML 界面；与 OASX 是两套界面 |
| `log/` | 运行日志、错误现场和诊断包；属于运行数据 |

## 2. 环境与启动

- 后端以 Python 3.10 和 Windows 为项目 README 标注的主要环境；依赖由 `requirements-in.txt` 声明，`requirements.txt` 是锁定后的安装清单。OCR、ADB、模拟器及 Windows 专用依赖使完整运行需要匹配的本机环境。
- 从**仓库根目录**执行命令。大量代码用 `Path.cwd()` 查找 `config/`、`tasks/`、`log/`；换一个工作目录启动会读错文件。
- `config/deploy.yaml` 是本地部署配置，默认值见 `deploy/template` 和 `deploy/config.py`。默认 Web 服务端口为 **22267**，OCR 为 **22268**，图片服务为 **22269**；可在部署配置或 `server.py --port` 中修改。OASX 的 API 内置回退地址是 `http://127.0.0.1:22288`，联调时必须在 OASX 设置中填实际后端地址，或把两边端口对齐。
- `config/template.json` 是新实例模板；运行实例是 `config/<实例名>.json`。实例文件被 `.gitignore` 排除。不要把真实账号、Token、完整日志或错误截图提交到仓库。

最小本地流程（已有可用 Python、依赖和模拟器时）：

```powershell
cd D:\OAS\OnmyojiAutoScript
python -m pip install -r requirements.txt
Copy-Item config/template.json config/dev.json
python server.py --host 127.0.0.1 --port 22267
```

然后在 OASX 中把服务地址设为 `http://127.0.0.1:22267`，编辑 `dev` 实例的设备参数并启用至少一个任务。也可用 OASX 的“新增配置”从模板创建实例。`script.py` 的 `__main__` 写死了 `oas1`，仅适合该实例确实存在时直接调试；常规调试走服务端。运行真实任务会控制模拟器，先确认目标实例和设备。

可用 `Invoke-RestMethod http://127.0.0.1:22267/test` 检查 API；它应返回字符串 `success`。`/home/test` 是另一条返回 `{"message":"test"}` 的路由。FastAPI 的 `/docs` 可查看当前实际注册的 HTTP 接口。

## 3. 配置、调度和任务执行

### 配置来源

`module/config/config_model.py:ConfigModel` 汇总所有任务字段，构造时读取 `config/<实例名>.json`。具体任务配置在 `tasks/<Task>/config.py`，通常继承 `tasks/Component/config_base.py:ConfigBase`，并包含 `tasks/Component/config_scheduler.py:Scheduler`。`Scheduler` 包含 `enable`、`next_run`、`priority`、成功/失败间隔、随机浮动和 `cron`。修改参数通过 `ConfigModel.script_set_arg()` 验证并写回 JSON；外部文件变化由 `module/config/config_watcher.py` 检测。

`module/config/config.py:Config` 持有 `ConfigModel`，负责保存配置、生成待运行和等待队列、更新下次运行时间。到期任务的排序由 `module/config/scheduler.py:TaskScheduler` 执行，规则来自 `script.optimization.schedule_rule`；`Filter` 的固定优先顺序在 `module/config/config_manual.py`。`cron` 非空时由 `module/config/cron.py` 计算下次时间；更改 `cron` 或启用任务时会尝试立即对齐 `next_run`。

任务菜单由 `module/config/config_menu.py:ConfigMenu` 手工维护，供 OASX 的 `/script_menu` 使用。`config/template.json` 提供新实例的初始字段。`module/config/argument/*.yaml` 和 `args.json` 保留了 Alas 时代的参数资料；新增当前 OAS 任务时，应先维护 Pydantic 模型、菜单和模板，不能只改这些旧文件。

### 一次任务的完整路径

1. `server.py` 初始化图片和 OCR 服务，并运行 `module/server/app.py:fastapi_app`。
2. `MainManager` 为每个实例建立 `ScriptProcess`；启动命令来自 WebSocket 的 `start` 消息，也可由部署配置 `Run` 自动启动。
3. `ScriptProcess` 用 `multiprocessing.get_context("spawn")` 建新进程，通过队列传状态、通过 Pipe 传日志；服务端再广播给 WebSocket 客户端。
4. `Script.loop()` 让 `Config.get_next()` 选任务，`ScriptRuntimeController` 根据空闲策略准备模拟器/游戏，随后通过 `module/task_loader.py` 定位并动态加载 `tasks/<大驼峰任务名>/script_task.py` 中的 `ScriptTask(config, device).run()`。任务路径从源码位置解析，不依赖当前工作目录；配置、日志和部分资源路径仍依赖仓库根目录启动。
5. 任务通常继承 `GameUi` 和所需复用组件，通过 `self.config.<task>` 读参数，通过 `self.device` 截图/操作，通过 `self.goto_page()` 导航。结束时调用 `self.set_next_run(task=..., success=True/False)`，再以 `TaskEnd` 告知调度器正常收尾。不要仅靠 `run()` 返回：`Script.run()` 正常返回值是 `False`，会被计入失败。
6. 调度器根据新 `next_run` 继续运行。`TaskEnd`、设备/页面异常、`ScriptError` 等由 `Script._handle_task_exception()` 区分处理；部分可恢复错误会触发 `Restart`，错误次数超过限制则停止脚本并按配置通知。

任务标识有两种写法：目录、菜单和执行命令用 `LBS`、`DailyTrifles` 这样的大驼峰名；JSON/Pydantic 字段用 `lbs`、`daily_trifles` 下划线名。`ConfigModel.type()` 和 `convert_to_underscore()` 在两者间转换。改名时必须一起检查历史配置迁移和客户端展示。

## 4. 页面、规则、设备

### 页面导航

`tasks/GameUi/page_definition.py` 定义 `Page` 和有向 `Transition`，`tasks/GameUi/registry.py` 扫描并导入各任务的 `page.py`。每个任务的 `GameUi` 会创建自己的 `NavigatorSession`；实际识别和导航在 `tasks/GameUi/navigator.py`。静态页面可用 `Page(识别规则)` 并通过 `page_a.connect(page_b, 点击规则, key=...)` 连边；动态页面应按 [`GameUi 使用说明`](../tasks/GameUi/USAGE.md) 使用 `register=False` 放到当前 session，避免污染全局注册表。稳定的页面特征、明确的双向路径和唯一的边 key 有助于定位卡页问题。

### 资源规则

规则源文件一般是任务目录下的 `res/`、`store/` 等子目录中的 `image.json`、`ocr.json`、`click.json` 及相应图片。`dev_tools/assets_extract.py` 扫描这些 JSON，生成同任务的 `assets.py`；生成文件头部注明不要手改。生成命令从仓库根目录运行：

```powershell
python dev_tools/assets_extract.py
```

该脚本会遍历所有任务和 `Component` 子目录，并可能重写多个 `assets.py`；提交前检查 `git diff`，确认只留下需要的资源变化。新增规则可先通过 `/tool/annotator` 标注，相关接口在 `module/server/tool_router.py`，规则 schema 在 `module/server/annotator_rule_schema.py`。

`module/atom/` 提供 `RuleImage`、`RuleOcr`、`RuleClick` 等对象。`tasks/base_task.py` 把常用的 `screenshot()`、`appear()`、`appear_then_click()`、次数/时间限制和下次运行设置封装给任务。截图/点击最终落到 `module/device/`；图片匹配和 OCR 可经独立 RPC 服务执行。低配模式和资源预热在脚本进程创建时读取配置，改完这些参数需要重启对应实例才能全面生效。

### 通用组件

新任务应优先复用 `tasks/Component/` 中的 `GeneralBattle`、`GeneralRoom`、`GeneralInvite`、`SwitchSoul` 等。`GeneralBattle` 是按准备、战斗、结算、奖励阶段推进的状态机，可在任务中覆写阶段钩子或提供退出识别器；详细约定见[组件文档](../tasks/Component/GeneralBattle/README.md)。

## 5. 新增功能时怎么改

### 新增一个任务

以 `tasks/LBS/` 为可参考的当前结构，但不要照搬其活动业务逻辑：

1. 新建 `tasks/<Task>/config.py`：定义参数模型与顶层任务模型，包含 `scheduler`，字段用 `Field(default=..., description='..._help')`。需要页面时新建 `page.py`，需要资源时保存规则 JSON 和截图，再生成 `assets.py`。
2. 新建 `script_task.py`，导出名为 `ScriptTask` 的类并实现 `run()`。继承 `GameUi`、必要组件和本任务 `*Assets`。设定可观察的完成条件、超时条件与恢复路径；成功/失败时更新 `next_run`，正常结束抛 `TaskEnd`。
3. 在 `module/config/config_model.py` 导入并新增下划线字段，在 `module/config/config_menu.py` 放到合适菜单，在 `module/config/config_manual.py` 的 Filter 顺序中加入大驼峰任务名。还要把任务加到 `tasks/TaskGroup/config.py:GroupTaskChoice`，供任务组选择。
4. 在 `config/template.json` 放入该任务的默认配置。按当前实际模型检查字段拼写与序列化格式；不要让旧实例丢失其自有参数。
5. 在 `assets/i18n/zh-CN.json`、`assets/i18n/en-US.json` 补充任务、分组、选项和帮助文本。若还使用仓库内 Qt 界面，对应 `module/config/i18n/*.xml` 也要处理；OASX 自己的界面文案位于独立仓库 `lib/translation/`。
6. 先运行 `python dev_tools/check_structure.py` 检查所有注册点，再验证 `/script_menu` 包含任务、`/<实例>/<Task>/args` 可读、任务开关与下次运行可保存；最后在目标模拟器上跑通进入、执行、退出和异常恢复。

只增加任务内部的一个功能时，沿 `config.py` → `script_task.py` → 规则/页面 → 翻译 → 模板的顺序检查。若改动涉及通用导航、战斗、设备或调度，同时检查使用该组件的其他任务。

### 新增或修改后端接口

HTTP 路由分别在 `module/server/home_router.py`（`/home`）、`script_router.py`（根路径下的配置/任务路由）、`stats_router.py`（`/stats`）、`log_router.py`（`/logs`）、`tool_router.py`（`/tool`）；统一由 `module/server/app.py` 注册。配置导入、导出、名称校验与脱敏规则集中在 `module/server/config_manager.py`。修改请求字段或响应结构时，同步检查 OASX 的 `lib/api/api_client*.dart`、`lib/service/script_service*.dart` 和相关模型/控件。

WebSocket 地址是 `/ws/<实例名>`。连接后先发送 `state` 和 `schedule`；客户端可发 `get_state`、`get_schedule`、`start`、`stop`。服务端将状态/队列以 JSON、日志以文本广播。`/<实例>/state` 和 `/<实例>/log` 两条 SSE 当前仅返回示例内容，不能作为实际状态/日志接口。实时日志浏览与统计分别看 `/logs/.../stream` 和 `/stats/.../stream`。统计解析器会把任务组日志拆成实际执行的子任务，`TaskGroup1` 等组名不作为统计任务；同一任务独立运行与在组内运行会合并累计。任务时长在 `Scheduler: End task`、任务组子项完成日志或六道之门子任务的 `task ended` 日志处截止；缺少结束日志时才退回下一任务边界或日志末尾。

### 与 OASX 联动

OASX 是工作区中的独立 Flutter 仓库。`lib/main.dart` 初始化 GetStorage 和长生命周期服务，`lib/routes.dart` 定义 `/home`、`/settings`、`/server`；`lib/api/api_client*.dart` 封装 HTTP，`lib/service/websocket_service.dart` 和 `script_service*.dart` 管理连接与脚本状态。工作台在 `lib/modules/home/`，动态参数在 `lib/modules/args/`，日志在 `lib/modules/log/`，本地部署在 `lib/modules/server/`，应用设置在 `lib/modules/settings/`。前端状态、翻译分别由 GetX 服务与 `lib/translation/` 管理。

跨端排查可沿“后端路由 → `lib/api/` 对应请求 → `lib/service/` 状态更新 → 页面 Controller/Widget”的顺序走。若只改后端参数，先确认 OASX 动态表单是否已能根据 Pydantic schema 渲染；新增参数类型或页面行为才需要改 OASX。OASX `README.md` 列出环境与构建方法，测试位于 `test/`，发布工作流在 `.github/workflows/release.yml`。两仓库独立提交，不要覆盖客户端已有的本地改动。

## 6. 修 Bug 的定位路线

先记录实例名、任务名、配置、复现步骤和首次异常时间，再沿数据链定位：

| 现象 | 先看哪里 |
| --- | --- |
| OASX 连不上或启动按钮无效 | `config/deploy.yaml` 的 `WebuiHost/WebuiPort`、OASX 设置地址、`/test`、`log/*_api.txt`、`module/server/script_router.py` 的 WebSocket |
| 参数不显示、保存失败、实例无法导入 | `tasks/<Task>/config.py`、`ConfigModel`、`config/template.json`、`config_manager.py`、OASX `lib/modules/args/` |
| 任务不运行或顺序异常 | 实例 JSON 的 `scheduler`、`Config.get_next()`、`TaskScheduler`、`ConfigManual.SCHEDULER_PRIORITY`、cron/时区 |
| 卡在未知页面或误点 | 对应 `page.py`、规则 JSON 与原图、`GameUi` 导航日志、截图尺寸/坐标、页面优先级与退出边 |
| OCR/图片识别异常 | `/home/ocr_server_info`、`/home/image_server_info`、`module/ocr/rpc.py`、`module/image/rpc.py`、ROI/阈值和当前截图 |
| 设备断连、黑屏、输入无效 | `module/device/connection.py`、`screenshot.py`、`control.py`、模拟器适配与 ADB serial |
| 战斗/组队逻辑异常 | `tasks/Component/GeneralBattle/`、`GeneralRoom/`、`GeneralInvite/` 和具体任务的覆写钩子 |
| 日志或统计展示异常 | `module/server/log_service.py`、`log_router.py`、`log_stats.py`、`stats_router.py`，再看 OASX 日志/统计模型 |

日志在 `log/YYYY-MM-DD_<实例名>.txt`，API 日志在 `log/YYYY-MM-DD_api.txt`。启用错误现场保存时，`log/error/<实例名>_<毫秒时间戳>/` 含错误日志和最近截图。可从 `/home/export_diagnostic` 导出包含近期日志和脱敏配置摘要的 zip；分享前仍应人工检查内容。复现完成后查看第一次错误及其前后截图，确认是识别、导航、调度、设备还是接口问题，再改最靠近根因的模块。

## 7. 验证与提交前检查

本仓库没有统一的后端 `pytest`/`unittest` 测试套件或 CI 测试工作流；现有 `*_test.py` 多为设备/组件的独立调试脚本，不能当作全量回归。推荐按变更范围验证：

1. **静态检查**：运行 `python dev_tools/check_structure.py` 检查任务接线；对修改的 Python 文件运行 `python -m py_compile <文件...>`，检查 JSON 文件可解析；查看 `git diff --check`。结构检查器只读源码，不导入游戏依赖，可在没有模拟器的环境运行。
2. **模型与接口**：验证 `ConfigModel` 能读模板/测试实例，`/script_menu`、`/<实例>/<Task>/args` 和实际修改的接口返回预期数据。配置迁移或导入功能要同时测试旧配置与非法输入。
3. **资源与页面**：检查规则 JSON、图片路径、生成后的 `assets.py` 一致，并在目标截图上验证识别；页面跳转至少跑进入和退出两个方向。
4. **实机/模拟器**：只在目标设备上执行受影响的任务，确认成功、超时和典型错误路径会更新下次运行时间，不会无限点击或卡死。
5. **跨端改动**：在 OASX 仓库运行 `flutter test` 和 `flutter analyze`，再手动检查动态参数、状态推送及日志页面。该仓库 README 还有具体构建命令。

检查 `git status` 时区分新改动与工作区原有改动；不要用整仓资源生成或格式化覆盖正在开发的其他任务。文档和源码引用的相对路径均以本仓库根目录为基准。
