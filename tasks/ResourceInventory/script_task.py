from pathlib import Path

from module.exception import TaskEnd
from module.logger import logger
from module.ocr.rpc import get_ocr_client
from module.server.setting import State
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.ResourceInventory.adb import AdbInventoryTransport
from tasks.ResourceInventory.recognition import RESOURCE_LABELS
from tasks.ResourceInventory.service import collect_resources


class ScriptTask(GameUi):
    def run(self):
        self.goto_page(page_main)
        transport = AdbInventoryTransport(
            Path(State.deploy_config.AdbExecutable).resolve(), self.device.serial,
        )
        snapshot, target = collect_resources(transport, get_ocr_client(), self.config.config_name)
        for name, item in snapshot['resources'].items():
            if item['quantity'] is None:
                logger.warning(f"资源识别 {RESOURCE_LABELS[name]}：未识别（{item['error']}）")
            else:
                suffix = '' if item['exact'] else '（界面缩写）'
                logger.info(f"资源识别 {RESOURCE_LABELS[name]}：{item['display']}{suffix}")
        logger.info(f'资源识别结果：{target}')
        self.set_next_run(task='ResourceInventory', success=snapshot['status'] == 'complete')
        raise TaskEnd('ResourceInventory')
