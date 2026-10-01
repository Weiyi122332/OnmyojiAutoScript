"""Delay each dojo reward capture by one second, then save the latest frame."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Dokan.script_task import ScriptTask


class DokanRewardCaptureWaitTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.frame = 0
        self.task = ScriptTask.__new__(ScriptTask)
        self.task.device = SimpleNamespace(image=np.zeros((2, 2, 3), dtype=np.uint8), image_frame_id='frame-0')
        self.task.screenshot = Mock(side_effect=self.screenshot)
        self.reward_visible = True
        self.details_visible = False
        self.task.appear = Mock(side_effect=self.appear)
        patches = (
            patch('module.base.timer.time.time', side_effect=lambda: self.now),
            patch('tasks.Dokan.script_task.sleep', side_effect=self.advance_time),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def advance_time(self, seconds):
        self.now += seconds

    def screenshot(self):
        self.frame += 1
        self.task.device.image = np.full((2, 2, 3), self.frame, dtype=np.uint8)
        self.task.device.image_frame_id = f'frame-{self.frame}'

    def appear(self, target):
        if target is self.task.I_RYOU_DOKAN_BATTLE_OVER:
            return self.reward_visible
        if target is self.task.I_REWARD_PARTICULARS:
            return self.details_visible
        return False

    def test_wait_is_exactly_one_second_and_refreshes_the_frame(self):
        self.assertTrue(self.task._wait_for_dokan_reward_ready())
        self.assertEqual(self.now - 1000, 1.0)
        self.assertEqual(self.frame, 1)
        self.assertEqual(self.task.device.image_frame_id, f'frame-{self.frame}')

    def test_reward_disappearance_cancels_capture(self):
        self.reward_visible = False
        self.assertFalse(self.task._wait_for_dokan_reward_ready())
        self.assertEqual(self.now - 1000, 1.0)

    def test_details_overlay_interrupts_wait_for_a_clean_reward_image(self):
        self.details_visible = True
        self.assertFalse(self.task._wait_for_dokan_reward_ready())

    def test_latest_frame_is_saved_after_wait_and_before_close(self):
        saved = []
        events = []
        self.task._save_reward_image = Mock(side_effect=lambda _: (
            saved.append(self.task.device.image.copy()), events.append('save')))
        context = SimpleNamespace(battle_key='dokan_member', continuous_count=1)
        with patch.object(GeneralBattle, '_handle_reward', side_effect=lambda *_: events.append('close')):
            self.task._handle_reward(context, None)
        self.assertEqual(events, ['save', 'close'])
        self.assertEqual(self.now - 1000, 1.0)
        self.assertTrue(np.array_equal(saved[0], self.task.device.image))
        self.assertEqual(int(saved[0][0, 0, 0]), 1)

    def test_second_reward_starts_its_own_one_second_wait(self):
        saved_at = []
        self.task._save_reward_image = Mock(side_effect=lambda _: saved_at.append(self.now))
        context = SimpleNamespace(battle_key='dokan_member', continuous_count=1)
        with patch.object(GeneralBattle, '_handle_reward'):
            self.task._handle_reward(context, None)
            second_start = self.now
            context.continuous_count = 2
            self.task._handle_reward(context, None)
        self.assertEqual(len(saved_at), 2)
        self.assertEqual(saved_at[1] - second_start, 1.0)
        self.assertEqual(self.frame, 2)


if __name__ == '__main__':
    unittest.main()
