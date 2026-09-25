# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import sys
import os

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtCore import Qt, QObject, QTranslator, QLocale, Slot
from pathlib import Path

from module.gui.utils import get_work_path
from module.gui.Bridge import bridge
from module.logger import logger

# import module.gui.qml_rcc
import module.gui.res_rcc

class FluentApp():
    app = None
    engine = None
    translator = None
    dpi = None

    def __init__(self):
        super().__init__()
        # 适配高分辨率、声明、设置Logo、设置软件名字
        # 后面的这三条失效了 使用 QGuiApplication.setHighDpiScaleFactorRoundingPolicy
        # https://blog.weimo.info/archives/602/
        # QGuiApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        # QGuiApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
        # QGuiApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        os.putenv("QT_QUICK_CONTROLS_STYLE", "Basic")

        FluentApp.app = QGuiApplication(sys.argv)
        QGuiApplication.setWindowIcon(QIcon(os.fspath(Path(__file__).resolve().parent / "res/icon.ico")))
        QGuiApplication.setApplicationName("oas")
        QGuiApplication.setOrganizationName("oas")

        FluentApp.engine = QQmlApplicationEngine()
        FluentApp.engine.addImportPath(os.fspath(Path(__file__).resolve().parent))

        FluentApp.translator = Translator(engine=FluentApp.engine, app=FluentApp.app)
        FluentApp.dpi = DpiScale()
        self.set_context_property(context=FluentApp.translator, name='translator')
        self.set_context_property(context=FluentApp.dpi, name='dpi')

    @classmethod
    def run(cls):
        FluentApp.engine.load(os.fspath(Path(get_work_path() / 'module' / 'gui' / 'qml' / 'app.qml')))
        if not FluentApp.engine.rootObjects():
            sys.exit(-1)
        sys.exit(FluentApp.app.exec())

    @classmethod
    def set_context_property(cls, context, name: str) -> None:
        """
        设置上下文
        :param name:
        :param context:
        :return:
        """
        FluentApp.engine.rootContext().setContextProperty(name, context)



    def qml_register_type(self, Class, qml_class: str) -> None:
        """
        注册qml类型
        :param Class:
        :param qml_class:
        :return:
        """
        qmlRegisterType(Class, "Oas", 1, 0, qml_class)


# 新增界面文字的中文兜底（module/config/i18n/zh_CN.qm 里还没有这些字符串）
_FALLBACK_ZH = {
    'Task Group': '任务组',
    'TaskGroup1': '任务组 1',
    'TaskGroup2': '任务组 2',
    'TaskGroup3': '任务组 3',
    'TaskGroup4': '任务组 4',
    'TaskGroup5': '任务组 5',
    'task_group_name_help': '给这个任务组起个名字，方便自己认（例如「日常」「御魂」「活动」）。',
    'Tasks': '任务列表',
    'task_group_tasks_help': '一行一个任务，按从上往下的顺序执行（OASX 里这个列表可以点「新增任务」添加、拖动改顺序）。',
    'Start Index': '从第几项开始运行',
    'task_group_start_index_help': '默认 1，整组从头跑。跑到第 N 项出错停下时，这里会被自动改成 N，下次就从第 N 项接着跑；整组跑完会自动改回 1。也可以自己手动填。',
    # 定时规则（crontab）
    'Cron': '定时规则',
    'cron_help': 'crontab 表达式：分 时 日 月 周。留空表示按「成功/失败间隔」的原逻辑运行；填了就只在表达式命中的时刻启动任务（仍会叠加随机浮动）。例：0 5 * * *（每天 5:00）、30 20 * * 1（每周一 20:30）、*/30 9-23 * * *（9 点到 23 点之间每 30 分钟）。支持 * , - / 和英文缩写（sun..sat、jan..dec），星期日可写 0 或 7，也支持 @daily、@weekly 这类简写。',
    'Float Time': '随机浮动时间',
    'float_time_help': '随机浮动：最终运行时间 = 算出来的时间 + 0~此设置的随机秒数。留空或 00:00:00 表示不浮动；对 crontab 规则同样生效（例如设 00:10:00，5:00 的任务会在 5:00~5:10 之间随机启动）。',
}


class FallbackTranslator(QTranslator):
    """
    兜底翻译：.qm 里还没有的字符串（任务组、定时规则等）。

    QML 里的菜单项是 qsTr(任务名)，所以这里接管这几个任务名的翻译，
    名称来自各配置实例里「任务组名称」设置；其余用 _FALLBACK_ZH。
    """

    def translate(self, context, source_text, disambiguation=None, n=-1):
        try:
            from module.config.task_group_names import collect_group_names
            name = collect_group_names().get(source_text)
        except Exception as e:
            logger.error(f'load task group names failed: {e}')
            name = None
        if name:
            return name
        if getattr(self, 'language', '简体中文') == '简体中文':
            return _FALLBACK_ZH.get(source_text, '')
        return ''

    def set_language(self, language: str) -> None:
        self.language = language


class Translator(QObject):

    def __init__(self, engine, app) -> None:
        super(Translator, self).__init__()
        self._engine = engine
        self._app = app
        self.path_en_US = str((Path.cwd() / "module" / "config" / "i18n" / "en_US.qm").resolve())
        self.path_zh_CN = str((Path.cwd() / "module" / "config" / "i18n" / "zh_CN.qm").resolve())

        self.translator = QTranslator()
        # 任务组自定义名称：装在 .qm 之后，Qt 会用后装的
        self.task_group_translator = FallbackTranslator()
        QGuiApplication.installTranslator(self.task_group_translator)

    @Slot(str)
    def set_language(self, language: str) -> None:
        """
        设置语言
        :param language:
        :return:
        """
        if language == "简体中文":
            self.task_group_translator.set_language(language)
            if not self.translator.load(self.path_zh_CN):
                logger.error("load language 简体中文 failed!")
            QGuiApplication.installTranslator(self.translator)
            QGuiApplication.installTranslator(self.task_group_translator)
            self._engine.retranslate()
            return

        if language == "English":
            self.task_group_translator.set_language(language)
            if not self.translator.load(self.path_en_US):
                logger.error("load language English failed!")
            QGuiApplication.installTranslator(self.translator)
            QGuiApplication.installTranslator(self.task_group_translator)
            self._engine.retranslate()
            return

class DpiScale(QObject):
    def __init__(self) -> None:
        super().__init__()

    @Slot(str)
    def set_dpi_scale(self, strategy: str) -> None:
        """
        设置dpi缩放
        :param strategy:
        :return:
        """
        match strategy:
            case "default": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)  # 不缩放
            case "round": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)  # 设备像素比0.5及以上的，进行缩放
            case "floor": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Floor)  # 始终不缩放
            case "ceil": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Ceil)  # 始终缩放
            case "round_prefer_floor": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)  # 设备像素比0.75及以上的，进行缩放
            case _: QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
