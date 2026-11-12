"""Fatigue recovery has its own persisted schedule, independent of cron."""
from datetime import datetime, timedelta, time
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.config.config import Config
from module.config.config_model import ConfigModel
from module.exception import TaskEnd
from tasks.MetaDemon import page as pages
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import BossType


NOW = datetime(2026, 11, 12, 12, 40, 30)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 12, 12, 40, 30)


class MetaDemonScheduleTests(unittest.TestCase):
    def make_task(self, cron='0 5 * * *'):
        task = BossBattle.__new__(BossBattle)
        config = Config.__new__(Config)
        config.model = ConfigModel()
        config.lock_config = Lock()
        config.reload = Mock()
        config.save = Mock()
        task.config = config
        task.conf = config.meta_demon
        task.conf.scheduler.cron = cron
        task.conf.scheduler.float_time = time(0, 15)
        task.conf.scheduler.wait_interval = timedelta(hours=1, minutes=40)
        task.start_time = NOW - timedelta(hours=1)
        task.goto_page = Mock()
        task.device = SimpleNamespace(image=object())
        return task

    def test_both_fatigue_paths_use_wait_interval_instead_of_cron(self):
        for source in ('counter', 'tea_popup'):
            for cron in ('0 5 * * *', '* * * * *', ''):
                with self.subTest(source=source, cron=cron):
                    task = self.make_task(cron)
                    task.O_MD_FATIGUE = Mock()
                    task.O_MD_FATIGUE.ocr_digit_counter.return_value = (101, -1, 100)
                    task.cur_boss_type = BossType.FIVE_STARS
                    task._active_preset = task.conf.high_star_preset
                    task.screenshot = Mock()
                    task.is_in_battle = Mock(return_value=False)
                    task.appear = Mock(side_effect=lambda rule, **kw: rule is task.I_MD_DRINK_TEA)
                    task.ui_click_until_disappear = Mock()
                    with patch('tasks.MetaDemon.boss_battle.datetime', FixedDateTime):
                        with self.assertRaises(TaskEnd):
                            if source == 'counter':
                                task.check_fatigue()
                            else:
                                task.start_battle()
                    scheduler = task.conf.scheduler
                    self.assertEqual(scheduler.next_run, NOW + timedelta(hours=1, minutes=40))
                    self.assertTrue(scheduler.waiting_for_fatigue)
                    self.assertEqual(scheduler.cron, cron)
                    task.config.reload.assert_called_once()
                    task.config.save.assert_called_once()
                    task.goto_page.assert_called_once_with(pages.page_main)

    def test_saved_wait_survives_reload_cron_edits_and_reenabling(self):
        task = self.make_task()
        with patch('tasks.MetaDemon.boss_battle.datetime', FixedDateTime):
            with self.assertRaises(TaskEnd):
                task.wait_for_fatigue()
        # Match the JSON round trip performed when the backend restarts.
        restored = ConfigModel.model_validate_json(task.config.model.model_dump_json())
        expected = NOW + timedelta(hours=1, minutes=40)
        self.assertTrue(restored.meta_demon.scheduler.waiting_for_fatigue)
        with patch.object(ConfigModel, 'save'):
            self.assertTrue(restored.script_set_arg('MetaDemon', 'scheduler', 'cron', '0 23 * * *'))
            self.assertTrue(restored.script_set_arg('MetaDemon', 'scheduler', 'enable', True))
        self.assertEqual(restored.meta_demon.scheduler.next_run, expected)
        self.assertEqual(restored.meta_demon.scheduler.cron, '0 23 * * *')

    def test_resuming_consumes_wait_and_completed_queue_uses_cron_again(self):
        task = self.make_task()
        task.conf.scheduler.waiting_for_fatigue = True
        task.conf.scheduler.next_run = NOW
        task.navigator = Mock()
        with patch('tasks.MetaDemon.boss_battle.ipages.configure_activity_navigation'):
            task.before_run()
        self.assertFalse(task.conf.scheduler.waiting_for_fatigue)
        task.config.save.assert_called_once()
        task.conf.scheduler.float_time = time(0)
        with patch('module.config.config.datetime', FixedDateTime):
            task.set_next_run('MetaDemon', success=True)
        self.assertEqual(task.conf.scheduler.next_run, datetime(2026, 11, 13, 5))

    def test_wait_flag_is_hidden_from_settings(self):
        task = self.make_task()
        payload = task.config.model.script_task('MetaDemon')
        self.assertNotIn('waiting_for_fatigue', [row['name'] for row in payload['scheduler']])


if __name__ == '__main__':
    unittest.main()
