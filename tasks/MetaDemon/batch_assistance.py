"""Keep an assistant attached to one offering task group across account switches."""

import time
from uuid import uuid4

from module.cooperation import META_DEMON_BATCH
from module.exception import ScriptError
from module.logger import logger
from tasks.MetaDemon.config import AssistanceRole, MetaDemon, MetaDemonMode
from tasks.TaskGroup.config import GROUP_CLASSES


BATCH_GROUPS = frozenset(group.__name__ for group in GROUP_CLASSES)


def batch_settings(model):
    boss = getattr(model, 'meta_demon', None)
    if (isinstance(boss, MetaDemon) and MetaDemonMode.BOSS_ASSIST in boss.meta_demon_config.mode
            and boss.assistance_config.batch_cooperation):
        return boss.assistance_config
    return None


class OfferingBatch:
    def __init__(self, config, group, settings):
        self.runtime = getattr(config, 'cooperation_runtime', None)
        self.group = group
        self.peer = settings.cooperation_script
        self.session = uuid4().hex
        self.complete = False
        if self.runtime is None or self.runtime.active_task != group:
            raise ScriptError('整批鬼王上供需要通过调度器启动任务组')
        if not self.peer or self.peer == self.runtime.name:
            raise ScriptError('整批鬼王协同需要填写另一实例的配置名')
        if not settings.friends:
            raise ScriptError('鬼王上供需要填写分享好友名字')

    def _publish(self, status):
        self.runtime.publish_battle_state(META_DEMON_BATCH, self.peer, self.session,
                                          {'status': status, 'group': self.group})

    def __enter__(self):
        self._publish('active')
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._publish('complete' if exc_type is None and self.complete else 'failed')


class BatchAssistance:
    def __init__(self, task, runtime, peer, session=None):
        self.runtime = runtime
        self.peer = peer
        self.offering = task.conf.assistance_config.role == AssistanceRole.OFFERING
        self.session = session if self.offering else None
        if not peer or peer == runtime.name:
            raise ScriptError('整批鬼王协同需要填写另一实例的配置名')
        if self.offering and (not self.session or runtime.active_task not in BATCH_GROUPS):
            raise ScriptError('整批鬼王上供必须在任务组中运行')

    def wait_for_peer(self):
        logger.info(f'等待整批鬼王协同：{self.peer}')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.offering:
                if self.assistant_ready():
                    return True
            else:
                state = self.runtime.peer_battle_state(META_DEMON_BATCH, self.peer)
                if state and self._offering_active(state['payload']):
                    self.session = state['session']
                    self._publish('ready')
                    return True
            time.sleep(0.5)
        logger.warning(f'整批鬼王协同等待超时：{self.peer}')
        return False

    def _publish(self, status):
        self.runtime.publish_battle_state(META_DEMON_BATCH, self.peer, self.session, {'status': status})

    def _peer_payload(self):
        state = self.runtime.peer_battle_state(META_DEMON_BATCH, self.peer)
        return state['payload'] if state and state['session'] == self.session else {}

    def _offering_active(self, payload):
        group = payload.get('group')
        return (payload.get('status') == 'active' and group in BATCH_GROUPS
                and self.runtime.runner_task(self.peer) == group)

    def assistant_ready(self):
        return (self._peer_payload().get('status') == 'ready'
                and self.runtime.runner_task(self.peer) in (BATCH_GROUPS | {'MetaDemon'}))

    def offering_status(self):
        payload = self._peer_payload()
        if self._offering_active(payload):
            return 'active'
        if payload.get('status') == 'active':
            # The group can publish its result while the runner is being checked.
            payload = self._peer_payload()
        return 'complete' if payload.get('status') == 'complete' else 'failed'

    def close(self):
        if not self.offering and self.session:
            self._publish('left')


def run_group_assistance(group, task_class, settings, batch):
    """Run each account as a fresh child task under the same offering session."""
    accounts = settings.parse_accounts(settings.batch_accounts) if batch else []
    session = batch.session if batch else None
    for index, account in enumerate(accounts or (None,), 1):
        if batch_settings(group.config.model) != settings:
            logger.warning('整批鬼王协同配置已变化，结束本轮任务组')
            return False
        if account is not None:
            from tasks.Component.SwitchAccount.switch_account import SwitchAccount
            logger.info(f'整批鬼王上供切换账号 {index}/{len(accounts)}')
            if not SwitchAccount(group.config, group.device, account).switchAccount(saved_roles=True):
                return False
        group.device.stuck_record_clear()
        group.device.click_record_clear()
        task = task_class(config=group.config, device=group.device)
        if not task.run(grouped_assistance=True, batch_session=session):
            return False
    return True
