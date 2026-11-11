"""Exercise batch sessions and the account and screenshot paths that support them."""

from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from pydantic import ValidationError

from module.config.config import Config
from module.config.config_model import ConfigModel
from module.cooperation import Cooperation, META_DEMON_BATCH
from module.exception import GameStuckError, TaskEnd
from module.image.runtime import ImageRuntime
from script import Script
from tasks.Component.SwitchAccount.login_account import LoginAccount
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.assistance import AssistanceLink, GhostAssistant, run_offering
from tasks.MetaDemon.batch_assistance import OfferingBatch
from tasks.MetaDemon.config import MetaDemon, MetaDemonAssistanceConfig
from tasks.TaskGroup.group_runner import TaskGroupRunner
from tasks.base_task import BaseTask


def boss(role, peer, accounts=''):
    return MetaDemon(meta_demon_config={'mode': ['鬼王协助']}, assistance_config={
        'batch_cooperation': True, 'cooperation_script': peer, 'role': role,
        'friend_names': '测试好友', 'batch_accounts': accounts,
    })


class BatchAssistanceTest(unittest.TestCase):
    def pair(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        offering, assistant = Cooperation('offering', directory.name), Cooperation('assistant', directory.name)
        offering.publish('TaskGroup1')
        assistant.publish('MetaDemon')
        return offering, assistant

    @staticmethod
    def link(runtime, config, session=None):
        task = SimpleNamespace(conf=config, config=SimpleNamespace(cooperation_runtime=runtime))
        return AssistanceLink(task, batch_session=session)

    def test_assistant_follows_one_group_and_separate_boss_rounds(self):
        offering, assistant = self.pair()
        config = boss('上供', 'assistant')
        assistant_link = self.link(assistant, boss('协助', 'offering'))
        with OfferingBatch(SimpleNamespace(cooperation_runtime=offering), 'TaskGroup1', config.assistance_config) as batch:
            self.assertTrue(assistant_link.wait_for_peer())
            first = self.link(offering, config, batch.session)
            self.assertTrue(first.wait_for_peer())
            first.publish('first-portrait')
            target = assistant_link.target()
            self.assertEqual(target[2], 'first-portrait')
            assistant_link.confirm(target, settled=True)
            self.assertTrue(first.peer_settled())
            first.publish()
            self.assertIsNone(assistant_link.target())
            self.assertEqual(assistant_link.batch.offering_status(), 'active')

            second = self.link(offering, config, batch.session)
            second.publish('second-portrait')
            self.assertFalse(second.confirmed())
            self.assertEqual(assistant_link.target()[2], 'second-portrait')
            self.assertIsNone(assistant.peer_battle_state(AssistanceLink.CHANNEL, 'offering'))
            batch.complete = True

        offering.publish('')
        self.assertEqual(assistant_link.batch.offering_status(), 'complete')
        assistant_link.batch.close()
        self.assertFalse(second.peer_in_task())

    def test_group_switches_accounts_in_order_and_publishes_result(self):
        for switch_ok in (True, False):
            with self.subTest(second_account_login=switch_ok):
                offering, assistant = self.pair()
                model = ConfigModel(meta_demon=boss('上供', 'assistant', 'one|区服甲\ntwo|区服乙').model_dump(),
                                    task_group_1={'group_config': {'tasks': ['Pets', 'MetaDemon', 'DailyTrifles']}})
                runner = TaskGroupRunner.__new__(TaskGroupRunner)
                runner.command = 'TaskGroup1'
                runner.config = SimpleNamespace(model=model, cooperation_runtime=offering)
                runner.device = Mock()
                runner._set_start_index = Mock()
                runner.set_next_run = Mock()
                events = []
                sessions = []

                def switch_account(config, device, account):
                    def switch(*, saved_roles):
                        self.assertTrue(saved_roles)
                        events.append(account.account)
                        return account.account != 'two' or switch_ok
                    return SimpleNamespace(switchAccount=switch)

                def task_module(task, module_name):
                    def run(**kwargs):
                        events.append(task)
                        if task == 'MetaDemon':
                            state = assistant.peer_battle_state(META_DEMON_BATCH, 'offering')
                            self.assertEqual(state['payload']['status'], 'active')
                            self.assertTrue(kwargs['grouped_assistance'])
                            self.assertEqual(kwargs['batch_session'], state['session'])
                            sessions.append(state['session'])
                        return True
                    return SimpleNamespace(ScriptTask=lambda **_: SimpleNamespace(run=run))

                with patch('tasks.TaskGroup.group_runner.load_task_script', side_effect=task_module), \
                        patch('tasks.Component.SwitchAccount.switch_account.SwitchAccount', side_effect=switch_account):
                    with self.assertRaises(TaskEnd):
                        runner.run()
                expected = ['Pets', 'one', 'MetaDemon', 'two']
                self.assertEqual(events, expected + (['MetaDemon', 'DailyTrifles'] if switch_ok else []))
                self.assertEqual(len(set(sessions)), 1)
                state = assistant.peer_battle_state(META_DEMON_BATCH, 'offering')
                self.assertEqual(state['payload']['status'], 'complete' if switch_ok else 'failed')
                runner._set_start_index.assert_called_once_with(1 if switch_ok else 2)
                runner.set_next_run.assert_called_once_with(task='TaskGroup1', success=switch_ok, finish=True)

    def test_scheduler_can_start_a_group_when_standalone_boss_is_disabled(self):
        model = ConfigModel(meta_demon=boss('上供', 'assistant').model_dump(),
                            task_group_1={'group_config': {'tasks': ['MetaDemon']}})
        script = Script.__new__(Script)
        script.config_name = 'offering'
        script.config = Mock(spec=Config, model=model, meta_demon=model.meta_demon,
                             meta_demon_ticket=model.meta_demon_ticket)
        with patch('script.Cooperation') as factory:
            self.assertIsNone(script._meta_cooperation_runtime())
            self.assertIs(script._meta_cooperation_runtime('TaskGroup1'), factory.return_value)
            factory.assert_called_once_with('offering')
            factory.return_value.start.assert_called_once()

    def test_restarted_runner_cannot_reuse_an_active_batch(self):
        offering, assistant = self.pair()
        offering.publish_battle_state(META_DEMON_BATCH, 'assistant', 'stale', {'status': 'active', 'group': 'TaskGroup1'})
        restarted = Cooperation('offering', offering.root)
        restarted.start()
        self.addCleanup(restarted.close)
        restarted.publish('TaskGroup1')
        self.assertIsNone(assistant.peer_battle_state(META_DEMON_BATCH, 'offering'))

    def test_assistant_waits_until_batch_completion(self):
        worker = GhostAssistant.__new__(GhostAssistant)
        worker.task = Mock()
        worker.task.conf = boss('协助', 'offering')
        worker.task.State.done = False
        worker.link = Mock()
        worker.link.batch.offering_status.side_effect = ['active', 'active', 'complete']
        worker.link.target.return_value = None
        with patch('tasks.MetaDemon.assistance.time.sleep'):
            self.assertTrue(worker.run())
        worker.link.batch.offering_status.assert_called()

    def test_ended_account_with_unsettled_boss_fails_the_batch(self):
        with patch('tasks.MetaDemon.assistance.GhostOffering') as factory:
            factory.return_value.can_continue.return_value = False
            factory.return_value.shared_generation = 1
            self.assertFalse(run_offering(Mock(), SimpleNamespace(batch=object())))

    def test_batch_fields_use_existing_client_controls_and_validate_accounts(self):
        config = ConfigModel(meta_demon=boss('上供', 'assistant', 'test|区服|角色|苹果').model_dump())
        fields = {row['name']: row for row in config.script_task('MetaDemon')['assistance_config']}
        self.assertEqual(fields['batch_cooperation']['type'], 'boolean')
        self.assertEqual(fields['batch_accounts']['type'], 'multi_line')
        account, = MetaDemonAssistanceConfig.parse_accounts(fields['batch_accounts']['value'])
        self.assertEqual(account.character, '角色')
        self.assertFalse(account.apple_or_android)
        with self.assertRaises(ValidationError):
            MetaDemonAssistanceConfig(batch_accounts='account-only')
        self.assertFalse(MetaDemon().assistance_config.batch_cooperation)


class BatchDependencyTest(unittest.TestCase):
    def test_saved_role_uses_exact_ocr_and_refuses_duplicates(self):
        login = LoginAccount.__new__(LoginAccount)
        login.device = Mock()
        login.screenshot = Mock()
        login._open_saved_roles = Mock(return_value=True)
        login._confirm_saved_role = Mock(return_value=True)
        login._saved_role_panel = Mock(return_value=(None, False))
        box = [[12, 18], [72, 18], [72, 40], [12, 40]]
        row = SimpleNamespace(ocr_text='目标区服', box=box)
        ocr = Mock(roi=(418, 131, 648, 488))
        ocr.detect_and_ocr.return_value = [SimpleNamespace(ocr_text='相似区服'), row]
        login.O_SA_SELECT_SVR_CHARACTER_LIST = ocr
        account = AccountInfo(account='test', svr='目标区服')
        self.assertTrue(login.select_saved_role(account))
        self.assertEqual(tuple(login._confirm_saved_role.call_args.args[0].roi_front), (430, 149, 60, 22))
        login._confirm_saved_role.reset_mock()
        ocr.detect_and_ocr.return_value = [row, row]
        self.assertFalse(login.select_saved_role(account))
        login._confirm_saved_role.assert_not_called()

    def test_global_screenshot_claims_the_actual_reward_template_and_refreshes(self):
        task = BaseTask.__new__(BaseTask)
        rule = MetaDemonAssets.I_MD_GET_YESTERDAY_REWARD
        empty = np.zeros((720, 1280, 3), dtype=np.uint8)
        popup = empty.copy()
        x, y, w, h = rule.roi_front
        popup[y:y + h, x:x + w] = rule.image
        task.device = SimpleNamespace(image=popup, screenshot=Mock(), click_record_clear=Mock(), sleep=Mock())
        task._burst = Mock(return_value=False)
        runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(runtime.shutdown)
        task.appear = lambda target: runtime._match_rule_payload(task.device.image, target.to_service_payload())['matched']
        task.click = Mock(side_effect=lambda target: setattr(task.device, 'image', empty))
        self.assertIs(task.screenshot(), empty)
        task.click.assert_called_once_with(rule)
        task.device.click_record_clear.assert_called_once()
        self.assertEqual(task.device.screenshot.call_count, 2)

    def test_global_screenshot_limits_stuck_reward_attempts(self):
        task = BaseTask.__new__(BaseTask)
        task.device = Mock()
        task._burst = Mock(return_value=False)
        task.appear = Mock(return_value=True)
        task.click = Mock()
        with self.assertRaises(GameStuckError):
            task.screenshot()
        self.assertEqual(task.click.call_count, 6)
