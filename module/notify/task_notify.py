"""按任务设置选择推送渠道，不修改全局通知器。"""

from module.notify.notify import Notifier
from tasks.Component.config_notify import TaskNotifyConfig


def resolve_task_notifier(config, settings: TaskNotifyConfig | None) -> Notifier:
    if settings is None:
        return config.notifier
    if not settings.task_notify_enable:
        return Notifier('', enable=False)
    channel = settings.task_notify_config.strip()
    if not channel:
        return config.notifier
    notifier = Notifier(channel, enable=True)
    notifier.config_name = config.config_name.upper()
    # 无效的独立配置停用推送，避免回退到其他收件人。
    if not hasattr(notifier, 'notifier') or not hasattr(notifier, 'required'):
        notifier.enable = False
    return notifier
