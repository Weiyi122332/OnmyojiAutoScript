"""Seven daily windows must apply to first runs, settings and UI rescheduling."""
import ast
import asyncio
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

from module.config.config_model import ConfigModel
from module.config.utils import convert_to_underscore
from module.exception import TaskEnd
from tasks.FrogBoss.config import FrogBossConfig, Strategy
from tasks.FrogBoss.frog_bet import RunReport
from tasks.FrogBoss.frog_schedule import CHINA_TIME, beijing_now, next_bet_time
from tasks.FrogBoss.script_task import ScriptTask


EARLY = datetime(2026, 9, 30, 10, 52)
ADVANCE = time(0, 10)


class ScheduleTests(unittest.TestCase):
    def test_seven_rounds_and_next_day(self):
        now = EARLY
        expected = [EARLY.replace(hour=h, minute=50) for h in (11, 13, 15, 17, 19, 21, 23)]
        for target in expected:
            self.assertEqual(next_bet_time(now, ADVANCE), target)
            now = next_bet_time(target, ADVANCE, skip_current=True)
        self.assertEqual(now, expected[0] + timedelta(days=1))

    def test_first_run_off_hours_late_start_and_boundaries(self):
        for hour, minute, expected in [(0, 0, (11, 50)), (9, 59, (11, 50)),
                                      (10, 0, (11, 50)), (11, 49, (11, 50)),
                                      (11, 50, (11, 50)), (11, 55, (11, 55)),
                                      (12, 0, (13, 50)), (22, 0, (23, 50))]:
            with self.subTest(now=(hour, minute)):
                now = EARLY.replace(hour=hour, minute=minute)
                self.assertEqual(next_bet_time(now, ADVANCE), now.replace(hour=expected[0], minute=expected[1]))
        self.assertEqual(next_bet_time(EARLY.replace(hour=23, minute=59), ADVANCE, True),
                         EARLY.replace(hour=11, minute=50) + timedelta(days=1))

    def test_advance_changes_due_time_and_aware_times_use_beijing(self):
        self.assertEqual(next_bet_time(EARLY, time(0, 15)), EARLY.replace(hour=11, minute=45))
        self.assertEqual(next_bet_time(EARLY, time(0, 10, 30)), EARLY.replace(hour=11, minute=49, second=30))
        self.assertEqual(next_bet_time(EARLY, time(2)), EARLY)
        utc_now = EARLY.replace(tzinfo=CHINA_TIME).astimezone(timezone.utc)
        target = next_bet_time(utc_now, ADVANCE)
        self.assertEqual(target, EARLY.replace(hour=11, minute=50, tzinfo=CHINA_TIME))

    def test_invalid_advance_is_rejected_before_saving(self):
        for advance in [time(0), time(2, 1), time(23)]:
            with self.subTest(advance=advance), self.assertRaises(ValidationError):
                FrogBossConfig(before_end_frog=advance)


class TaskWindowTests(unittest.TestCase):
    def setUp(self):
        self.task = ScriptTask.__new__(ScriptTask)
        self.scheduler = SimpleNamespace(next_run=None)
        self.notifier = SimpleNamespace(enable=True, push=Mock(return_value=True))
        self.task.config = SimpleNamespace(config_name='oas_test', notifier=self.notifier,
            model=SimpleNamespace(frog_boss=SimpleNamespace(scheduler=self.scheduler,
                frog_boss_config=SimpleNamespace(before_end_frog=ADVANCE, strategy_frog=Strategy.Rss))))
        self.task.set_next_run = Mock(side_effect=lambda **kw: setattr(self.scheduler, 'next_run', kw['target']))
        self.task.enter_frog_boss = Mock(side_effect=AssertionError('entered game before the betting window'))
        self.task.screenshot = Mock(side_effect=AssertionError('read betting page before the betting window'))
        self.task.goto_page = Mock()
        self.task.run_report = RunReport('frog_rss', EARLY.replace(hour=10, minute=0))

    def test_first_run_defers_without_entering_or_betting_and_reports(self):
        with patch('tasks.FrogBoss.script_task.beijing_now', return_value=EARLY), self.assertRaises(TaskEnd):
            self.task.run()
        self.task.enter_frog_boss.assert_not_called()
        self.task.set_next_run.assert_called_once_with(task='FrogBoss', target=EARLY.replace(hour=11, minute=50))
        self.notifier.push.assert_called_once()
        self.assertIn('等待下注时间', self.notifier.push.call_args.kwargs['content'])

    def test_do_bet_cannot_bypass_window_after_navigation(self):
        with patch('tasks.FrogBoss.script_task.beijing_now', return_value=EARLY), self.assertRaises(TaskEnd):
            self.task.do_bet()
        self.task.screenshot.assert_not_called()

    def test_completed_round_and_midnight_retry(self):
        self.task.run_report.round_at = EARLY.replace(hour=22, minute=0)
        with patch('tasks.FrogBoss.script_task.beijing_now', return_value=EARLY.replace(hour=23, minute=55)):
            self.task.next_run()
        self.assertEqual(self.scheduler.next_run, EARLY.replace(hour=11, minute=50) + timedelta(days=1))
        self.task.set_next_run.reset_mock()
        with patch('tasks.FrogBoss.script_task.beijing_now', return_value=EARLY.replace(hour=23, minute=59, second=30)), \
                self.assertRaises(TaskEnd):
            self.task.retry_bet('下注窗口已关闭')
        self.assertEqual(self.scheduler.next_run, EARLY.replace(hour=11, minute=50) + timedelta(days=1))

    def test_task_finishing_after_round_boundary_does_not_skip_new_round(self):
        self.task.run_report.round_at = EARLY.replace(hour=18, minute=0)
        with patch('tasks.FrogBoss.script_task.beijing_now', return_value=EARLY.replace(hour=20, minute=1)):
            self.task.next_run()
        self.assertEqual(self.scheduler.next_run, EARLY.replace(hour=21, minute=50))


class SettingsTests(unittest.TestCase):
    def test_enabling_and_changing_advance_recalculate_pending_time(self):
        model = ConfigModel()
        model.frog_boss.frog_boss_config.before_end_frog = ADVANCE
        with patch.object(ConfigModel, 'save'), patch('tasks.FrogBoss.frog_schedule.beijing_now', return_value=EARLY):
            self.assertTrue(model.script_set_arg('FrogBoss', 'scheduler', 'enable', True))
            self.assertEqual(model.frog_boss.scheduler.next_run, EARLY.replace(hour=11, minute=50))
            self.assertTrue(model.script_set_arg('FrogBoss', 'frog_boss_config', 'before_end_frog', time(0, 20)))
            self.assertEqual(model.frog_boss.scheduler.next_run, EARLY.replace(hour=11, minute=40))
            self.assertFalse(model.script_set_arg('FrogBoss', 'frog_boss_config', 'before_end_frog', time(0)))
            self.assertEqual(model.frog_boss.frog_boss_config.before_end_frog, time(0, 20))

    def test_cron_and_unrelated_task_settings_are_preserved(self):
        model = ConfigModel()
        scheduled = EARLY + timedelta(days=1)
        model.frog_boss.scheduler.cron = '50 11-23/2 * * *'
        model.frog_boss.scheduler.next_run = scheduled
        model.orochi.scheduler.next_run = scheduled
        with patch.object(ConfigModel, 'save'):
            self.assertTrue(model.script_set_arg('FrogBoss', 'frog_boss_config', 'before_end_frog', ADVANCE))
            self.assertEqual(model.frog_boss.scheduler.next_run, scheduled)
            self.assertTrue(model.script_set_arg('Orochi', 'scheduler', 'enable', True))
            self.assertEqual(model.orochi.scheduler.next_run, scheduled)


class RescheduleApiTests(unittest.TestCase):
    def setUp(self):
        # Load only this endpoint so the manager's background server never starts.
        path = Path(__file__).resolve().parents[2] / 'module/server/script_router.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                        and node.name == 'sync_next_run')
        function.decorator_list = []
        self.config = SimpleNamespace(model=SimpleNamespace(frog_boss=SimpleNamespace(
            frog_boss_config=SimpleNamespace(before_end_frog=ADVANCE))), task_delay=Mock(),
            get_next=Mock(), get_schedule_data=Mock(return_value={}))
        self.process = SimpleNamespace(broadcast_state=AsyncMock())
        manager = SimpleNamespace(script_process={'oas_test': self.process},
                                  config_cache=Mock(return_value=self.config))
        namespace = {'mm': manager, 'datetime': datetime, 'convert_to_underscore': convert_to_underscore,
                     'next_bet_time': next_bet_time, 'beijing_now': lambda: EARLY}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        self.endpoint = namespace['sync_next_run']

    def test_empty_target_recalculates_round_instead_of_daily_interval(self):
        self.assertTrue(asyncio.run(self.endpoint('oas_test', 'FrogBoss', '')))
        self.config.task_delay.assert_called_once_with(task='FrogBoss', target=EARLY.replace(hour=11, minute=50))
        self.process.broadcast_state.assert_awaited_once()

    def test_explicit_target_and_unrelated_task_keep_existing_behavior(self):
        for task, target_text, target in [('FrogBoss', '2026-09-30 13:50:00', EARLY.replace(hour=13, minute=50)),
                                         ('Orochi', '', None)]:
            with self.subTest(task=task):
                self.config.task_delay.reset_mock()
                self.assertTrue(asyncio.run(self.endpoint('oas_test', task, target_text)))
                self.config.task_delay.assert_called_once_with(task=task, success=True, target=target)


if __name__ == '__main__':
    unittest.main()
