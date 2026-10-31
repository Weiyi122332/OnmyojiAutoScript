"""Read-only access to resource snapshots; capture stays in the task scheduler."""

from datetime import date
import json

from fastapi import APIRouter, HTTPException, Query

from module.config.config_model import ConfigModel
from module.server.api_logger import ApiLoggingRoute
from module.server.config_manager import ConfigManager
from tasks.ResourceInventory.storage import available_dates, read_snapshot, result_directory


resource_app = APIRouter(prefix='/resources', tags=['resources'], route_class=ApiLoggingRoute)


@resource_app.get('/{script_name}')
def resource_snapshot(script_name: str, target_date: str | None = Query(None, alias='date')):
    try:
        script_name = ConfigManager.validate_config_name(script_name, allow_template=False)
        directory = result_directory(script_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ConfigManager.config_path(script_name).is_file():
        raise HTTPException(status_code=404, detail='Config does not exist')
    if target_date is not None:
        try:
            if date.fromisoformat(target_date).isoformat() != target_date:
                raise ValueError()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail='Expected date YYYY-MM-DD') from exc
    path = directory / 'days' / f'{target_date}.json' if target_date else directory / 'latest.json'
    try:
        snapshot = read_snapshot(path)
        dates = available_dates(directory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail='Resource snapshot could not be read') from exc
    scheduler = ConfigModel(config_name=script_name).resource_inventory.scheduler
    return {
        'script_name': script_name,
        'snapshot': snapshot,
        'dates': dates,
        'schedule': {
            'enabled': scheduler.enable,
            'cron': scheduler.cron,
            'next_run': scheduler.next_run.isoformat(sep=' '),
        },
    }
