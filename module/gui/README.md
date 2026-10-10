# 桌面界面资源

桌面界面直接读取 `module/gui/qml/app.qml` 及其 QML 源文件，不需要提交 QML 编译副本。图标等资源由 `res.qrc` 编译为 `res_rcc.py`，供 `fluent_app.py` 导入。修改图标资源后，在项目根目录执行：

```
where python
cd module/gui
pyside6-rcc -o res_rcc.py res.qrc
```

即可生成rcc文件。当然当你每修改一次qrc指向的资源文件时候就需要运行一次

```
可以这样导入
import module.gui.res_rcc
```

`res_rcc.py`、QML 源文件和 `FluentUI` 运行库属于界面依赖，应随项目保留。

所以可以使用

```
Qt.resolvedUrl("../../qml/Page/O_Settings.qml")
```







[在PyQt中使用qrc/rcc资源系统（PySide6-PyQt5） - 知乎 (zhihu.com)](https://zhuanlan.zhihu.com/p/590358586)
