# This Python file uses the following encoding: utf-8
# @author runhey
# 脚本进程
# github https://github.com/runhey
import multiprocessing
from asyncio import QueueEmpty, CancelledError, sleep
from enum import Enum

from module.logger import logger
from module.server.config_manager import ConfigManager
from module.server.script_websocket import ScriptWSManager

# 脚本进程必须使用全新解释器，避免继承主服务已连接的 ZeroRPC/ZeroMQ context。
# Pipe、Queue 和 Process 必须来自同一个 multiprocessing context。
_SCRIPT_PROCESS_CONTEXT = multiprocessing.get_context("spawn")


class ScriptState(int, Enum):
    INACTIVE = 0
    RUNNING = 1
    WARNING = 2
    UPDATING = 3


class ScriptProcess(ScriptWSManager):

    def __init__(self, config_name: str) -> None:
        super().__init__()
        if config_name not in ConfigManager.all_script_files():
            raise FileNotFoundError(f'{config_name}.json not found')
        self.config_name = config_name  # config_name
        self.log_pipe_out, self.log_pipe_in = _SCRIPT_PROCESS_CONTEXT.Pipe(False)
        self.state_queue = _SCRIPT_PROCESS_CONTEXT.Queue()
        self.state: ScriptState = ScriptState.INACTIVE
        self._process = None
        self._latest_schedule: dict | None = None

    def schedule_with_live_dokan(self, schedule: dict) -> dict:
        """Keep an active dojo visible when a client refreshes or reconnects."""
        if self.state != ScriptState.RUNNING or self._process is None or not self._process.is_alive():
            return schedule
        running = (self._latest_schedule or {}).get('running', {})
        if running.get('name') != 'Dokan':
            return schedule
        return {
            **schedule,
            'running': dict(running),
            'pending': [item for item in schedule.get('pending', []) if item['name'] != 'Dokan'],
            'waiting': [item for item in schedule.get('waiting', []) if item['name'] != 'Dokan'],
        }

    @staticmethod
    def _extract_log_dedup_key(log: str) -> str | None:
        text = str(log).strip()
        if not text:
            return None
        parts = str(log).split('|', 2)
        if len(parts) != 3:
            return None
        level, timestamp, message = [part.strip() for part in parts]
        if not level or not timestamp or not message:
            return None
        return message

    async def start(self):
        self._latest_schedule = None
        self.state = ScriptState.RUNNING
        await self.broadcast_state({"state": self.state})
        if self._process:
            logger.warning(f'Script {self.config_name} is initialized')
        if self._process and self._process.is_alive():
            logger.warning(f'Script {self.config_name} is already running and first stop it')
            self.stop()
        self._process = _SCRIPT_PROCESS_CONTEXT.Process(
            target=func,
            args=(self.config_name, self.state_queue, self.log_pipe_in,),
            name=self.config_name,
            daemon=True,
        )
        self._process.start()


    async def stop(self):
        self._latest_schedule = None
        self.state = ScriptState.INACTIVE
        await self.broadcast_state({"state": self.state})
        if self._process is None:
            logger.warning(f'Script {self.config_name} process is removed')
            return
        if not self._process.is_alive():
            logger.warning(f'Script {self.config_name} is not running')
            return
        self._process.terminate()
        self._process = None

    async def coroutine_broadcast_state(self):
        try:
            while 1:
                if self.state == ScriptState.INACTIVE:
                    await sleep(1)
                    continue
                await sleep(0.1)
                try:
                    if self.state_queue.empty():
                        await sleep(1)
                        continue
                    data = self.state_queue.get_nowait()
                    if not data:
                        await sleep(0.5)
                        continue
                    if 'state' in data and data['state'] == ScriptState.WARNING:
                        self.state = ScriptState.WARNING
                    if isinstance(data.get('schedule'), dict):
                        self._latest_schedule = data['schedule']
                    await self.broadcast_state(data)
                except QueueEmpty as e:
                    logger.warning(f'QueueEmpty: {e}')
                    await sleep(0.5)
                    continue
                except Exception as e:
                    logger.error(f'Error: {e}')
                    continue
        except CancelledError as e:
            logger.warning(f'{self.config_name} state coroutine is cancelled')
            return

    async def coroutine_broadcast_log(self):
        try:
            previous_log_key = None  # 缓存上一条正文日志，用于相邻重复去重
            while 1:
                if self.state == ScriptState.INACTIVE:
                    await sleep(1)
                    continue
                await sleep(0.05)
                try:
                    if not self.log_pipe_out.poll():
                        await sleep(0.3)
                        continue
                    log = self.log_pipe_out.recv()
                    if not str(log).strip():
                        continue
                    current_log_key = self._extract_log_dedup_key(log)
                    if current_log_key is not None:
                        if current_log_key == previous_log_key:
                            continue
                        previous_log_key = current_log_key
                    else:
                        previous_log_key = None
                    await self.broadcast_log(log)
                except EOFError as e:
                    await sleep(0.5)
                    logger.warning(f'EOFError: {e}')
                    continue
                except Exception as e:
                    logger.error(f'Log Error: {e}')
                    continue
        except CancelledError as e:
            logger.warning(f'{self.config_name} log coroutine is cancelled')
            return


def func(config: str, state_queue: multiprocessing.Queue, log_pipe_in) -> None:

    def start_log() -> None:
        try:
            from module.logger import set_file_logger, set_func_logger
            set_file_logger(name=config)
            set_func_logger(log_pipe_in.send)
        except Exception as e:
            logger.exception(f'Start log error')
            logger.error(f'Error: {e}')
            raise
    start_log()
    import time
    try:
        # while 1:
        #     time.sleep(1)
        #     logger.info(f'Script {config} is running')
        #     state_queue.put({"state": ScriptState.RUNNING})
        from script import Script
        script = Script(config_name=config)
        script.state_queue = state_queue
        script.loop()
    except SystemExit as e:
        logger.info(f'Script {config} process exit')
        logger.error(f'Error: {e}')
        state_queue.put({"state": ScriptState.WARNING})
        time.sleep(0.1)
        exit(-1)
    except Exception as e:
        logger.exception(f'Run script {config} error')
        logger.error(f'Error: {e}')
        raise


if __name__ == '__main__':
    p = ScriptProcess('oas1')
    p.start()
    from time import sleep
    sleep(10)
    logger.info(p._process.exitcode)
