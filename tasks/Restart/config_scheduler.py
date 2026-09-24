# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum
from datetime import datetime, time
from pydantic import BaseModel, ValidationError, validator, Field
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import Time

from module.logger import logger

class RestartScheduler(Scheduler):
    enable: bool = Field(default=True, description='enable_help')
    priority: int = Field(default=0, description='priority_help')
