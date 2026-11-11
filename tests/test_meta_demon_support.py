"""Shared role selection and MetaDemon points collection."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from module.exception import GameStuckError
from module.image.runtime import ImageRuntime
from tasks.Component.SwitchAccount.login_account import LoginAccount
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.base_task import BaseTask


class MetaDemonSupportTest(unittest.TestCase):
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
