"""Run-now changes must wake the existing scheduler, including during idle setup."""
from datetime import datetime, time, timedelta
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.config.config import Config
from module.config.config_model import ConfigModel
from module.config.config_watcher import ConfigWatcher
from module.config.utils import read_file, write_file
from module.script.runtime_controller import ScriptRuntimeController
from script import Script


class ImmediateRunTests(unittest.TestCase):
    def start_patch(self, *args, **kwargs):
        patcher = patch(*args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'immediate_run.json'
        self.now = datetime.now().replace(microsecond=0)
        self.version = int(self.now.timestamp()) * 1_000_000_000 + 100_000_000
        model = ConfigModel()
        for task in model.__dict__.values():
            scheduler = getattr(task, 'scheduler', None)
            if scheduler is not None:
                scheduler.enable = False
        ticket = model.meta_demon_ticket.scheduler
        ticket.enable = True
        ticket.cron = '0 0 * * *'
        ticket.next_run = self.now + timedelta(days=1)
        boss = model.meta_demon.scheduler
        boss.enable = boss.waiting_for_fatigue = True
        boss.next_run = self.now + timedelta(minutes=40)
        self.fatigue_time = boss.next_run
        self.path.write_text(model.model_dump_json(), encoding='utf-8')
        self.set_version(self.version)
        # Use real serialization and reloads, entirely within a temporary config.
        self.start_patch('module.config.config_watcher.filepath_config', return_value=str(self.path))
        reader = patch.object(ConfigModel, 'read_json', side_effect=lambda _: read_file(str(self.path)))
        writer = patch.object(ConfigModel, 'write_json',
                              side_effect=lambda _, data: write_file(str(self.path), data))
        for patcher in (reader, writer):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.task = Script.__new__(Script)
        self.task.config_name = 'immediate_run_test'
        self.task.config = Config(self.task.config_name)
        self.task.state_queue = None
        self.task.dokan_qq_monitor = None
        self.task._emulator_down = False
        self.task._antiban_wake_time = Mock(return_value=None)
        self.task._handle_continuous_task_rest = Mock(return_value=False)
        self.task._reset_continuous_task_rest()
        self.task.device = SimpleNamespace(
            app_is_running=Mock(return_value=True), app_stop=Mock(),
            emulator_stop=Mock(), release_during_wait=Mock(),
        )
        self.task.run = Mock(return_value=True)
        self.task.runtime = ScriptRuntimeController(self.task)
        self.sleep = self.start_patch('script.time.sleep', side_effect=AssertionError(
            'Scheduler kept waiting on the old plan instead of selecting the run-now task',
        ))

    def set_version(self, version):
        os.utime(self.path, ns=(version, version))

    def run_now(self):
        model = ConfigModel(config_name=self.task.config_name)
        self.assertTrue(model.script_set_arg('MetaDemonTicket', 'scheduler', 'next_run',
                                            self.now - timedelta(days=1)))
        self.version += 100_000_000
        self.set_version(self.version)

    def assert_ticket_selected(self):
        self.assertEqual(self.task.get_next_task(), 'MetaDemonTicket')
        self.assertEqual(self.task.config.meta_demon_ticket.scheduler.cron, '0 0 * * *')
        self.assertEqual(self.task.config.meta_demon.scheduler.next_run, self.fatigue_time)
        self.assertTrue(self.task.config.meta_demon.scheduler.waiting_for_fatigue)

    def test_run_now_saved_before_selection_replaces_cached_plan(self):
        self.run_now()
        self.assert_ticket_selected()
        self.task.run.assert_not_called()
        self.sleep.assert_not_called()

    def test_run_now_while_returning_to_courtyard_is_not_lost(self):
        def return_to_courtyard(command):
            self.assertEqual(command, 'GotoMain')
            self.run_now()
            return True

        self.task.run.side_effect = return_to_courtyard
        self.assert_ticket_selected()
        self.task.run.assert_called_once_with('GotoMain')
        self.sleep.assert_not_called()

    def test_run_now_while_closing_game_is_not_lost(self):
        model = ConfigModel(config_name=self.task.config_name)
        model.script.optimization.when_task_queue_empty = 'close_game'
        model.script.optimization.close_game_limit_time = time(0)
        model.save()
        self.task.config.reload()
        self.task.device.app_stop.side_effect = self.run_now
        self.assert_ticket_selected()
        self.task.device.app_stop.assert_called_once()
        self.sleep.assert_not_called()

    def test_run_now_while_closing_emulator_is_not_lost(self):
        model = ConfigModel(config_name=self.task.config_name)
        model.script.optimization.when_task_queue_empty = 'close_emulator_or_goto_main'
        model.script.optimization.close_emulator_limit_time = time(minute=1)
        model.save()
        self.task.config.reload()
        self.task.device.emulator_stop.side_effect = self.run_now
        self.assert_ticket_selected()
        self.task.device.emulator_stop.assert_called_once()
        self.sleep.assert_not_called()

    def test_run_now_during_config_reload_is_detected_before_waiting(self):
        reload_config = Config.reload
        changed = False

        def reload_then_change(config):
            nonlocal changed
            reload_config(config)
            if not changed:
                changed = True
                self.run_now()

        with patch.object(Config, 'reload', reload_then_change):
            self.assert_ticket_selected()
        self.assertTrue(changed)
        self.sleep.assert_not_called()

    def test_run_now_during_idle_sleep_wakes_on_the_next_poll(self):
        def change_while_sleeping(seconds):
            self.assertEqual(self.sleep.call_count, 1, 'Run-now change was missed on the next poll')
            self.run_now()

        self.sleep.side_effect = change_while_sleeping
        self.assert_ticket_selected()
        self.sleep.assert_called_once_with(5)

    def test_unchanged_config_allows_wait_deadline_to_finish(self):
        self.task.config.start_watching()
        self.assertTrue(self.task.wait_until(self.now - timedelta(seconds=2)))
        self.sleep.assert_not_called()

    def test_watcher_detects_same_second_and_older_file_replacements(self):
        watcher = ConfigWatcher()
        for difference in (100, 100_000_000, -1_000_000_000):
            with self.subTest(difference=difference):
                self.set_version(self.version)
                watcher.start_watching()
                self.assertFalse(watcher.should_reload())
                self.set_version(self.version + difference)
                self.assertTrue(watcher.should_reload())


if __name__ == '__main__':
    unittest.main()
