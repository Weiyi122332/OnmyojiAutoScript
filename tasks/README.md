# 任务目录约定

`tasks/` 下的目录名是运行命令和用户配置的一部分。新增独立任务用大驼峰目录名，例如 `NewFeature`，对应配置字段用 `new_feature`。不要仅为整理文件而重命名现有任务目录；旧实例 JSON、任务组列表和资源路径都依赖这些名字。

| 位置 | 作用 |
| --- | --- |
| `tasks/<Task>/config.py` | 导出同名配置类；可调度任务声明 `scheduler: Scheduler` |
| `tasks/<Task>/script_task.py` | 导出 `ScriptTask` 类及 `run()`；调度器和任务组都从这里执行 |
| `tasks/<Task>/assets.py` | 从规则 JSON 生成的资源类；运行时会引用它，不要手改生成段 |
| `tasks/<Task>/page.py` | 可选的页面定义和跳转边 |
| `tasks/<Task>/res/` 等 | 规则 JSON、识别图片和任务自己的数据，跟随所属任务存放 |
| `tasks/Component/` | 多个任务复用的游戏流程；不要放独立调度入口 |
| `tasks/GameUi/` | 页面识别与导航基础设施 |

增加独立任务时，依次完成这些注册点：

1. 在 `module/config/config_model.py` 导入配置类，增加配置字段；在 `config/template.json` 增加对应默认值。
2. 在 `module/config/config_menu.py` 加入菜单，在 `module/config/config_manual.py` 加入调度顺序。
3. 在 `tasks/TaskGroup/config.py` 的 `GroupTaskChoice` 中加入任务，使任务组可以选它。
4. 在 `assets/i18n/zh-CN.json` 和 `assets/i18n/en-US.json` 加入界面文案。需要规则时，用 `dev_tools/assets_extract.py` 生成 `assets.py`。
5. 运行 `python dev_tools/check_structure.py`，再验证模型、接口和实际任务流程。详细步骤见 [开发与排障手册](../docs/DEVELOPMENT.md#5-新增功能时怎么改)。

普通任务和任务组统一通过 `module/task_loader.py` 找到脚本。`GotoMain` 是内部命令，不在菜单和实例模板中；`OrochiMoans` 仅保留旧配置模型，目前没有可执行脚本。结构检查器显式记录这两个例外，其他新任务必须遵守上面的注册约定。
