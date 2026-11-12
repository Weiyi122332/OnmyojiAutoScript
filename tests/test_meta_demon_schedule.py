"""Fatigue recovery has its own persisted schedule, independent of cron."""
from copy import deepcopy
from datetime import datetime, timedelta, time
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import numpy as np
from PIL import Image

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

    def tea_popup(self, *, free):
        fixtures = Path(__file__).parent / 'fixtures' / 'meta_demon'
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with Image.open(fixtures / 'tea_popup_free.png') as image:
            frame[160:550, 310:975] = np.asarray(image.convert('RGB'))
        if not free:
            frame[455:535, 527:762] = 0
            with Image.open(fixtures / 'tea_purchase_button.png') as image:
                frame[467:525, 555:723] = np.asarray(image.convert('RGB'))
        return frame

    def make_popup_task(self, frames, *, auto_tea=False):
        task = self.make_task()
        task.conf.meta_demon_config.auto_tea = auto_tea
        task.cur_boss_type = BossType.FIVE_STARS
        task._active_preset = task.conf.high_star_preset
        task.total_count = task._current_boss_attempts = 0
        for name in ('I_MD_DRINK_TEA_FREE', 'I_MD_DRINK_TEA', 'I_MD_CLOSE_POPUP',
                     'I_MD_FIRE', 'I_MD_SETTLING'):
            setattr(task, name, deepcopy(getattr(task, name)))
        frames = iter(frames)
        task.screenshot = Mock(side_effect=lambda: setattr(task.device, 'image', next(frames)))
        task.appear = Mock(side_effect=lambda rule, **kw: rule.template_match(task.device.image))
        task.click = Mock(return_value=True)
        task.appear_then_click = Mock(side_effect=lambda rule, **kw: task.appear(rule) and task.click(rule, **kw))
        task.is_in_battle = Mock(return_value=False)
        task.run_general_battle = Mock()
        return task

    def test_free_and_paid_tea_buttons_remain_distinct(self):
        for free in (False, True):
            with self.subTest(free=free):
                frame = self.tea_popup(free=free)
                task = self.make_popup_task([frame])
                self.assertEqual(task.I_MD_DRINK_TEA_FREE.template_match(frame), free)
                self.assertEqual(task.I_MD_DRINK_TEA.template_match(frame), not free)
                self.assertTrue(task.I_MD_CLOSE_POPUP.template_match(frame))
                button = task.I_MD_DRINK_TEA_FREE if free else task.I_MD_DRINK_TEA
                x, y, width, height = button.roi_front
                self.assertTrue(542 <= x < x + width <= 738 and 463 <= y < y + height <= 531)

    def test_free_tea_is_automatic_and_paid_tea_requires_the_switch(self):
        challenge = np.zeros((720, 1280, 3), dtype=np.uint8)
        challenge[597:650, 1135:1234] = BossBattle.I_MD_FIRE.image
        for free, auto_tea in ((True, False), (True, True), (False, True)):
            with self.subTest(free=free, auto_tea=auto_tea):
                task = self.make_popup_task(
                    [self.tea_popup(free=free), challenge, challenge], auto_tea=auto_tea,
                )
                task.is_in_battle.side_effect = [False, False, True]
                self.assertTrue(task.start_battle())
                button = task.I_MD_DRINK_TEA_FREE if free else task.I_MD_DRINK_TEA
                self.assertEqual(task.click.call_args_list, [call(button), call(task.I_MD_FIRE, interval=0.8)])
                task.run_general_battle.assert_called_once()
                task.config.save.assert_not_called()
                self.assertEqual((task.total_count, task._current_boss_attempts), (1, 1))

    def test_paid_popup_closes_before_waiting_even_after_using_free_tea(self):
        for use_free_first in (False, True):
            with self.subTest(use_free_first=use_free_first):
                paid = self.tea_popup(free=False)
                frames = ([self.tea_popup(free=True)] if use_free_first else [])
                task = self.make_popup_task([*frames, paid, paid, np.zeros_like(paid)])
                events = Mock()
                events.attach_mock(task.click, 'click')
                events.attach_mock(task.goto_page, 'goto_page')
                with patch('tasks.MetaDemon.boss_battle.datetime', FixedDateTime):
                    with self.assertRaises(TaskEnd):
                        task.start_battle()
                expected = [call.click(task.I_MD_DRINK_TEA_FREE)] if use_free_first else []
                self.assertEqual(events.mock_calls, [
                    *expected, call.click(task.I_MD_CLOSE_POPUP, interval=0.6),
                    call.goto_page(pages.page_main),
                ])
                self.assertEqual(task.conf.scheduler.next_run, NOW + timedelta(hours=1, minutes=40))
                self.assertTrue(task.conf.scheduler.waiting_for_fatigue)
                task.run_general_battle.assert_not_called()

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
