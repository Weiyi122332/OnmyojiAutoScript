import json
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
import re

from module.config.atomicwrites import atomic_write


BEIJING = timezone(timedelta(hours=8))


def result_directory(config_name: str, root: Path | str = 'log/resource_inventory') -> Path:
    if not config_name or config_name in ('.', '..') or re.search(r'[\\/:*?"<>|]', config_name):
        raise ValueError('Invalid resource inventory config name')
    return Path(root) / config_name


def save_snapshot(snapshot: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    captured = datetime.fromisoformat(snapshot['captured_at'])
    if captured.tzinfo is None:
        raise ValueError('Resource snapshots require a timezone-aware timestamp')
    day = captured.astimezone(BEIJING).date().isoformat()
    snapshot = {**snapshot, 'date': day}
    target = directory / 'latest.json'
    with atomic_write(str(target), overwrite=True, encoding='utf-8') as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    daily = directory / 'days' / f'{day}.json'
    daily.parent.mkdir(parents=True, exist_ok=True)
    previous = read_snapshot(daily)
    # Keep the day's successful scan if a later scan only returned partial data.
    if snapshot['status'] == 'complete' or previous is None or previous.get('status') != 'complete':
        with atomic_write(str(daily), overwrite=True, encoding='utf-8') as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    with (directory / 'history.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(snapshot, ensure_ascii=False) + '\n')
    return target


def read_snapshot(path: Path) -> dict | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid resource snapshot')
    return value


def available_dates(directory: Path) -> list[str]:
    dates = []
    for path in (directory / 'days').glob('*.json'):
        try:
            if date.fromisoformat(path.stem).isoformat() == path.stem:
                dates.append(path.stem)
        except ValueError:
            continue
    return sorted(dates, reverse=True)
