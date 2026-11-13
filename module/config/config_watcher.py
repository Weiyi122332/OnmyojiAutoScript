# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import os
from datetime import datetime

from module.config.utils import filepath_config
from module.logger import logger

class ConfigWatcher:
    """
    监视特定配置文件修改的功能。
    它跟踪了初始纳秒修改时间,(start_mtime)
    并提供了方法来检查文件是否被修改(should_reload)
    和获取当前修改时间(get_mtime)。
    """
    config_name = 'script'
    start_mtime: int | None = None

    def start_watching(self) -> None:
        self.start_mtime = self.get_mtime()

    def get_mtime(self) -> int:
        """
        File modification time in nanoseconds, including edits within one second.
        """
        return os.stat(filepath_config(self.config_name)).st_mtime_ns

    def should_reload(self) -> bool:
        """
        Returns:
            bool: Whether the file has been modified and configs should reload
        """
        mtime = self.get_mtime()
        if mtime != self.start_mtime:
            logger.info(f'Config "{self.config_name}" changed at {datetime.fromtimestamp(mtime / 1_000_000_000)}')
            return True
        else:
            return False

