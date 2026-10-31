"""Run the warehouse reader directly without starting the scheduler."""

import argparse
import json
from pathlib import Path
import shutil

from module.ocr.rpc import get_ocr_client
from tasks.ResourceInventory.adb import AdbInventoryTransport
from tasks.ResourceInventory.service import collect_resources


def main() -> int:
    parser = argparse.ArgumentParser(description='通过后台 ADB 识别纳物库金币、体力、勾玉和普通蓝票')
    parser.add_argument('--serial', required=True, help='ADB serial of the target emulator')
    parser.add_argument('--adb', default=shutil.which('adb') or './toolkit/Lib/site-packages/adbutils/binaries/adb.exe')
    parser.add_argument('--ocr-address', default='127.0.0.1:22268')
    parser.add_argument('--config-name', default='manual')
    parser.add_argument('--output-dir', type=Path, default=Path('log/resource_inventory'))
    args = parser.parse_args()
    transport = AdbInventoryTransport(args.adb, args.serial)
    snapshot, target = collect_resources(
        transport, get_ocr_client(address=args.ocr_address), args.config_name, args.output_dir,
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f'Saved: {target}')
    return 0 if snapshot['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
