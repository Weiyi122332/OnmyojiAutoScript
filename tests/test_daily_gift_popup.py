"""每日礼包关闭点击最多两次，仅在两次后仍显示弹窗时失败。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.exception import GameStuckError
from tasks.DailyTrifles.script_task import ScriptTask


class DailyGiftPopupTest(unittest.TestCase):
    def make_task(self, visible_frames):
        task = ScriptTask.__new__(ScriptTask)
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        task.screenshot = Mock()
        task.appear = Mock(side_effect=visible_frames)
        task.click = Mock()
        return task

    def close_popup(self, task):
        with patch('tasks.DailyTrifles.script_task.sleep'), \
                patch('tasks.DailyTrifles.script_task.logger'), \
                patch('tasks.DailyTrifles.script_task.random.choice', return_value='right'):
            task.close_gift_daily_popup()

    def test_absent_popup_is_not_clicked(self):
        task = self.make_task([False])
        self.close_popup(task)
        task.click.assert_not_called()

    def test_first_click_closes_popup_without_retry(self):
        task = self.make_task([True, False])
        self.close_popup(task)
        task.click.assert_called_once()

    def test_first_click_does_not_close_popup_but_retry_succeeds(self):
        task = self.make_task([True, True, False])
        self.close_popup(task)
        self.assertEqual(task.click.call_count, 2)

    def test_two_failed_clicks_raise_without_a_third_click(self):
        task = self.make_task([True, True, True])
        with self.assertRaisesRegex(GameStuckError, 'after 2 clicks'):
            self.close_popup(task)
        self.assertEqual(task.click.call_count, 2)


if __name__ == '__main__':
    unittest.main()
