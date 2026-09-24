# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import Field

from tasks.Component.config_base import ConfigBase, TimeDelta, DateTime, Time

class Scheduler(ConfigBase):
    enable: bool = Field(default=False, description='enable_help')
    next_run: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"), description='next_run_help')
    priority: int = Field(default=5, description='priority_help')

    success_interval: TimeDelta = Field(default=TimeDelta(days=1), description='success_interval_help')
    failure_interval: TimeDelta = Field(default=TimeDelta(days=1), description='failure_interval_help')
    # 随机浮动：最终运行时间 = 下面算出来的时间 + 0~float_time 的随机秒数（对 cron 规则同样生效）
    float_time: Time = Field(default=Time(hour=0, minute=0, second=0), description='float_time_help')
    # 定时规则（crontab）。留空时按「成功/失败间隔」运行
    cron: str = Field(default='', description='cron_help')


if __name__ == "__main__":
    dict_s = {
        "enable": False,
        "next_run": "2026-07-19T14:15:37",
        "priority": 5,
        "success_interval": "10 00:00:01",
        "failure_interval": "10 00:00:01",
        "float_time": "02:00:05",
        "cron": "0 5 * * *"
    }
    s = Scheduler(**dict_s)
    print(s.model_dump())

