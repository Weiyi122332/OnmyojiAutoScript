"""任务独立推送设置；渠道留空时沿用全局配置。"""

from pydantic import BaseModel, Field

from tasks.Component.config_base import MultiLine


class TaskNotifyConfig(BaseModel):
    task_notify_enable: bool = Field(default=True, description='task_notify_enable_help')
    task_notify_config: MultiLine = Field(default='', description='task_notify_config_help')
