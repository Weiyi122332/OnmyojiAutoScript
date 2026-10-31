from datetime import datetime
from pathlib import Path

from tasks.ResourceInventory.reader import WarehouseReader
from tasks.ResourceInventory.storage import BEIJING, result_directory, save_snapshot


def collect_resources(transport, ocr, config_name: str, root='log/resource_inventory') -> tuple[dict, Path]:
    directory = result_directory(config_name, root)
    relative = 'evidence/' + datetime.now(BEIJING).strftime('%Y-%m-%d/%H%M%S%f')
    snapshot = WarehouseReader(transport, ocr, directory / relative).read(config_name)
    snapshot['evidence'] = {key: f'{relative}/{filename}' for key, filename in snapshot['evidence'].items()}
    target = save_snapshot(snapshot, directory)
    return snapshot, target
