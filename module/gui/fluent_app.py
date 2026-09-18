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


# 任务组相关界面文字的中文（.qm 里还没有这些新字符串，这里直接兜底）
_TASK_GROUP_ZH = {
    'Task Group': '任务组',
    'TaskGroup1': '任务组 1',
    'TaskGroup2': '任务组 2',
    'TaskGroup3': '任务组 3',
    'TaskGroup4': '任务组 4',
    'TaskGroup5': '任务组 5',
    'Task 1': '第 1 个任务',
    'Task 2': '第 2 个任务',
    'Task 3': '第 3 个任务',
    'Task 4': '第 4 个任务',
    'Task 5': '第 5 个任务',
    'Task 6': '第 6 个任务',
    'Task 7': '第 7 个任务',
    'Task 8': '第 8 个任务',
    'Task 9': '第 9 个任务',
    'Task 10': '第 10 个任务',
    'task_group_name_help': '给这个任务组起个名字，方便自己认（例如「日常」「御魂」「活动」）。',
    'task_group_slot_help': '按顺序从上往下执行：第 1 个任务、第 2 个任务……不需要的任务留「不设置」即可。',
}


class TaskGroupTranslator(QTranslator):
    """
    把菜单里的 TaskGroup1..5 显示成任务组的自定义名称。

    QML 里的菜单项是 qsTr(任务名)，所以这里接管这几个任务名的翻译，
    名称来自各配置实例里「任务组名称」设置。
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
            return _TASK_GROUP_ZH.get(source_text, '')
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
        self.task_group_translator = TaskGroupTranslator()
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
