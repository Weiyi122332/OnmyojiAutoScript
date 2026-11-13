"""Realm raid handoffs resume ticket farming without waiting for the daily cron."""
from datetime import datetime, time, timedelta
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.config.config import Config
from module.config.config_model import ConfigModel
from module.exception import TaskEnd
from tasks.Exploration import page as exploration_pages
from tasks.MetaDemonTicket.config import MetaDemonTicket, TicketMode
from tasks.MetaDemonTicket.script_task import ScriptTask
from tasks.MetaDemonTicket.ticket_farming import ExplorationTicketTask, TicketsFull


NOW = datetime(2026, 11, 13, 0, 32, 7)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 13, 0, 32, 7)


class TicketScheduleTests(unittest.TestCase):
    def start_patch(self, *args, **kwargs):
        patcher = patch(*args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        self.task = ScriptTask.__new__(ScriptTask)
        config = Config.__new__(Config)
        config.model = ConfigModel()
        config.lock_config = Lock()
        config.reload = Mock()
        config.save = Mock()
        self.task.config = config
        self.task.device = SimpleNamespace(image=object())
        self.task.start_time = NOW - timedelta(minutes=28)
        self.task.goto_page = Mock()
        ticket = config.meta_demon_ticket
        ticket.general_config.mode = TicketMode.EXPLORATION
        ticket.scheduler.enable = True
        ticket.scheduler.cron = '0 0 * * *'
        ticket.scheduler.float_time = time(minute=5)
        config.realm_raid.scheduler.enable = True
        config.realm_raid.scheduler.cron = '0 0 29 2 *'
        config.realm_raid.scheduler.next_run = datetime(2028, 2, 29)
        config.exploration.scrolls.scrolls_threshold = 25
        config.exploration.scrolls.scrolls_cd = timedelta(0)

        self.runner = ExplorationTicketTask.__new__(ExplorationTicketTask)
        self.runner.config = config
        self.runner.device = self.task.device
        self.runner.install_ticket_reward_hook = Mock()
        self.runner.pre_process = Mock()
        self.runner.finish_exploration = Mock()
        self.runner.read_realm_raid_tickets = Mock(return_value=26)
        self.runner.exec_exp_page = Mock(side_effect=self.reach_threshold)
        for target, replacement in (
            ('tasks.MetaDemonTicket.ticket_farming.datetime', FixedDateTime),
            ('module.config.config.datetime', FixedDateTime),
            ('module.config.config_model.datetime', FixedDateTime),
        ):
            self.start_patch(target, replacement)
        self.start_patch('tasks.MetaDemonTicket.ticket_farming.ExplorationTicketTask',
                         return_value=self.runner)
        self.precheck = self.start_patch(
            'tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=False,
        )
        self.jitter = self.start_patch('module.config.config.random_float_seconds', return_value=152)

    def reach_threshold(self):
        config = self.runner._config
        self.runner.activate_realm_raid(config.scrolls, config.exploration_config,
                                        exploration_pages.page_mainline)

    def run_task(self):
        with self.assertRaises(TaskEnd):
            self.task.run()

    def test_handoff_uses_exploration_cooldown_without_cron_or_jitter(self):
        config = self.task.config
        for cron, delay in (('0 0 * * *', timedelta(0)),
                            ('0 0 * * *', timedelta(minutes=30)),
                            ('* * * * *', timedelta(minutes=30)),
                            ('', timedelta(minutes=30))):
            with self.subTest(cron=cron, delay=delay):
                config.meta_demon_ticket.scheduler.cron = cron
                config.exploration.scrolls.scrolls_cd = delay
                self.runner.__dict__.pop('_config', None)
                self.run_task()
                scheduler = config.meta_demon_ticket.scheduler
                self.assertEqual(scheduler.next_run, NOW + max(delay, timedelta(seconds=1)))
                self.assertTrue(scheduler.waiting_for_realm_raid)
                self.assertEqual(scheduler.cron, cron)
                self.assertEqual(config.realm_raid.scheduler.next_run, NOW)
                self.assertEqual(config.realm_raid.scheduler.cron, '0 0 29 2 *')
        self.assertEqual(self.runner.finish_exploration.call_count, 4)
        self.task.goto_page.assert_not_called()
        self.jitter.assert_not_called()

    def test_saved_continuation_survives_reload_cron_edits_and_reenabling(self):
        self.run_task()
        restored = ConfigModel.model_validate_json(self.task.config.model.model_dump_json())
        expected = NOW + timedelta(seconds=1)
        self.assertTrue(restored.meta_demon_ticket.scheduler.waiting_for_realm_raid)
        with patch.object(ConfigModel, 'save'):
            for cron in ('0 23 * * *', ''):
                self.assertTrue(restored.script_set_arg('MetaDemonTicket', 'scheduler', 'cron', cron))
                self.assertTrue(restored.script_set_arg('MetaDemonTicket', 'scheduler', 'enable', False))
                self.assertTrue(restored.script_set_arg('MetaDemonTicket', 'scheduler', 'enable', True))
                self.assertEqual(restored.meta_demon_ticket.scheduler.next_run, expected)
                self.assertEqual(restored.meta_demon_ticket.scheduler.cron, cron)

    def test_resumed_run_clears_continuation_and_normal_completion_uses_cron(self):
        for outcome in ('full_before_farming', 'full_reward', 'time_limit'):
            with self.subTest(outcome=outcome):
                self.precheck.return_value = False
                self.runner.exec_exp_page.side_effect = self.reach_threshold
                self.run_task()
                # Restart the backend before the pending run starts.
                config = self.task.config
                config.model = ConfigModel.model_validate_json(config.model.model_dump_json())
                scheduler = config.meta_demon_ticket.scheduler

                def finish():
                    self.assertFalse(scheduler.waiting_for_realm_raid)
                    if outcome == 'full_reward':
                        raise TicketsFull

                self.runner.exec_exp_page.side_effect = finish
                self.precheck.return_value = outcome == 'full_before_farming'
                self.run_task()
                self.assertFalse(scheduler.waiting_for_realm_raid)
                self.assertEqual(scheduler.next_run, datetime(2026, 11, 14, 0, 2, 32))
                self.assertEqual(scheduler.cron, '0 0 * * *')

    def test_disabling_realm_raid_during_cleanup_does_not_create_a_continuation(self):
        config = self.task.config
        self.runner.finish_exploration.side_effect = lambda: setattr(config.realm_raid.scheduler, 'enable', False)
        self.run_task()
        self.assertFalse(config.meta_demon_ticket.scheduler.waiting_for_realm_raid)
        self.assertEqual(config.meta_demon_ticket.scheduler.next_run, datetime(2026, 11, 14, 0, 2, 32))
        self.assertEqual(config.realm_raid.scheduler.next_run, datetime(2028, 2, 29))

    def test_old_settings_default_to_no_continuation_and_hide_runtime_state(self):
        ticket = MetaDemonTicket(scheduler={'cron': '0 0 * * *'})
        self.assertFalse(ticket.scheduler.waiting_for_realm_raid)
        payload = self.task.config.model.script_task('MetaDemonTicket')
        self.assertNotIn('waiting_for_realm_raid', [row['name'] for row in payload['scheduler']])


if __name__ == '__main__':
    unittest.main()
