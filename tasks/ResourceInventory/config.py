from datetime import datetime, timedelta

from pydantic import Field, model_validator

from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


def next_inventory_run(now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    target = now.replace(hour=23, minute=0, second=0, microsecond=0)
    return target + timedelta(days=1) if target <= now else target


class ResourceInventory(ConfigBase):
    scheduler: Scheduler = Field(default_factory=lambda: Scheduler(
        enable=True, priority=1, cron='0 23 * * *', next_run=next_inventory_run(),
    ))

    @model_validator(mode='before')
    @classmethod
    def schedule_template(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get('scheduler'), dict):
            return data
        scheduler = dict(data['scheduler'])
        # The committed template uses the repository's static date sentinel.
        if scheduler.get('next_run') == '2023-01-01 00:00:00':
            scheduler['next_run'] = next_inventory_run()
        return {**data, 'scheduler': scheduler}
