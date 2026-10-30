"""Dojo scheduling uses the shared scheduler without a separate run time."""

from datetime import datetime, timedelta
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.config.config import Config
from module.config.cron import try_parse_cron
from tasks.Dokan.config import Dokan
from tasks.Dokan.script_task import ScriptTask


class DokanScheduleTest(unittest.TestCase):
    def make_task(self, remaining=0, cron=''):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = Dokan.model_validate({
            'dokan_config': {'dokan_run_time': '23:59:00', 'monday_to_thursday': False},
            'scheduler': {'success_interval': '00 03:17:00',
                          'failure_interval': '00 00:03:00', 'cron': cron},
            'attack_count_config': {'remain_attack_count': remaining},
        })
        config = Config.__new__(Config)
        config.model = SimpleNamespace(dokan=task.conf)
        config.reload = Mock()
        config.save = Mock()
        config.lock_config = Lock()
        task.config = config
        task.start_time = datetime.now() - timedelta(hours=2)
        return task

    def test_completed_skipped_and_incomplete_runs_use_configured_intervals(self):
        for options, remaining, success in (
            ({}, 2, False),
            ({'is_dokan_activated': True}, 1, False),
            ({'is_dokan_activated': True}, 0, True),
            ({'skip_today': True}, 2, True),
        ):
            with self.subTest(options=options, remaining=remaining):
                task = self.make_task(remaining=remaining)
                scheduler = task.conf.scheduler
                interval = scheduler.success_interval if success else scheduler.failure_interval
                before = datetime.now().replace(microsecond=0)
                with patch('module.config.config.logger'):
                    task.next_run(**options)
                after = datetime.now().replace(microsecond=0)
                self.assertLessEqual(before + interval, scheduler.next_run)
                self.assertLessEqual(scheduler.next_run, after + interval)
                task.config.save.assert_called_once()

    def test_cron_sets_the_next_time_for_success_and_failure(self):
        cron = '*/13 * * * *'
        expression = try_parse_cron(cron)
        for activated in (True, False):
            with self.subTest(activated=activated):
                task = self.make_task(cron=cron)
                before = datetime.now().replace(microsecond=0)
                with patch('module.config.config.logger'):
                    task.next_run(is_dokan_activated=activated)
                after = datetime.now().replace(microsecond=0)
                self.assertLessEqual(expression.next_after(before), task.conf.scheduler.next_run)
                self.assertLessEqual(task.conf.scheduler.next_run, expression.next_after(after))

    def test_weekend_restriction_delays_until_next_monday(self):
        task = self.make_task()
        task.conf.dokan_config.monday_to_thursday = True
        task.set_next_run_next_monday = Mock()
        task.set_next_run = Mock()
        with patch('tasks.Dokan.script_task.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 24, 21)
            task.next_run(skip_today=True)
        task.set_next_run_next_monday.assert_called_once_with(task='Dokan')
        task.set_next_run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
