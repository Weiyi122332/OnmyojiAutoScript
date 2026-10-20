"""首领额外奖励模式与手动次数的互斥、耗尽及识别失败回归。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.config.config_model import ConfigModel
from module.exception import GamePageUnknownError
from tasks.ActivityShikigami.base_act import ActivityResourceNotEnough
from tasks.ActivityShikigami.config import ActivityShikigami, GeneralConfig
from tasks.ActivityShikigami.script_task import ScriptTask
import tasks.ActivityShikigami.page as pages


class BossRewardsTest(unittest.TestCase):
    def make_task(self, *, full=True, limit=0, count=0):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = ActivityShikigami(general_config=GeneralConfig(
            task_sequence=['首领'], boss_full_rewards=full, boss_limit=limit,
        ))
        task.action_count = {'boss': count, 'ap': 0}
        task.climb_consumable_count = {'boss': -1}
        task.climb_pending_consumption = {'boss': 0}
        task.climb_ocr_correction_rounds = {'boss': 0}
        task.device = SimpleNamespace(image=None)
        task.screenshot = Mock()
        task.time_limit_reached = Mock(return_value=False)
        task.O_REMAIN_BOSS = Mock()
        task.O_REMAIN_BOSS.ocr_digit_counter.return_value = (0, 100, 100)
        return task

    def test_default_keeps_manual_count_and_full_mode_enables_zero_limit(self):
        self.assertFalse(GeneralConfig().boss_full_rewards)
        self.assertEqual(GeneralConfig(boss_limit=0).task_sequence_v, [])
        conf = GeneralConfig(boss_limit=0, boss_full_rewards=True)
        self.assertEqual(conf.task_sequence_v, ['首领'])
        self.assertEqual(conf.climb_sequence_v, ['boss'])
        self.assertEqual(GeneralConfig(
            task_sequence=[], boss_full_rewards=True,
        ).task_sequence_v, [])

    def test_checkbox_is_exposed_as_a_boolean_and_can_be_saved(self):
        model = ConfigModel()
        fields = model.script_task('ActivityShikigami')['general_config']
        field = next(item for item in fields if item['name'] == 'boss_full_rewards')
        self.assertEqual(field['type'], 'boolean')
        with patch.object(ConfigModel, 'save'):
            self.assertTrue(model.script_set_arg(
                'ActivityShikigami', 'GeneralConfig', 'BossFullRewards', True,
            ))
        self.assertTrue(model.activity_shikigami.general_config.boss_full_rewards)

    def test_full_mode_ignores_zero_or_reached_manual_limit(self):
        for limit, count in ((0, 0), (1, 1), (2, 8)):
            with self.subTest(limit=limit, count=count):
                self.assertTrue(self.make_task(limit=limit, count=count).prepare_next_action('boss'))

    def test_full_mode_still_obeys_activity_time_limit(self):
        task = self.make_task()
        task.time_limit_reached.return_value = True
        self.assertFalse(task.prepare_next_action('boss'))

    def test_manual_mode_stops_at_configured_count(self):
        for limit, count, expected in ((0, 0, False), (2, 1, True), (2, 2, False)):
            with self.subTest(limit=limit, count=count):
                task = self.make_task(full=False, limit=limit, count=count)
                self.assertEqual(task.prepare_next_action('boss'), expected)

    def test_boss_checkbox_does_not_enable_other_modes(self):
        task = self.make_task()
        self.assertFalse(task.prepare_next_action('ap'))

    def test_manual_mode_does_not_treat_bonus_rewards_as_entry_tickets(self):
        task = self.make_task(full=False, limit=3)
        task.O_REMAIN_BOSS.ocr_digit_counter.return_value = (100, 0, 100)
        self.assertTrue(task._climb_resource_available('boss'))
        task.O_REMAIN_BOSS.ocr_digit_counter.assert_not_called()

    def test_full_mode_uses_remaining_rewards_instead_of_total(self):
        task = self.make_task()
        task.O_REMAIN_BOSS.ocr_digit_counter.return_value = (97, 3, 100)
        self.assertTrue(task._climb_resource_available('boss'))
        self.assertEqual(task.climb_consumable_count['boss'], 3)

    def test_full_rewards_skip_before_soul_switch_or_battle(self):
        task = self.make_task()
        task.O_REMAIN_BOSS.ocr_digit_counter.return_value = (100, 0, 100)
        task.switch_soul_for = Mock()
        task._enter_climb_battle = Mock()
        task.run_general_battle = Mock()
        with self.assertRaises(ActivityResourceNotEnough):
            task._run_climb_action('boss', pages.page_climb_boss)
        task.switch_soul_for.assert_not_called()
        task._enter_climb_battle.assert_not_called()
        task.run_general_battle.assert_not_called()
        self.assertEqual(task.action_count['boss'], 0)

    def test_100_of_100_stops_even_if_cached_count_disagrees(self):
        task = self.make_task()
        task.climb_consumable_count['boss'] = 80
        task.climb_pending_consumption['boss'] = 1
        task.O_REMAIN_BOSS.ocr_digit_counter.return_value = (100, 0, 100)
        self.assertFalse(task._climb_resource_available('boss'))
        self.assertEqual(task.climb_consumable_count['boss'], 0)
        self.assertEqual(task.climb_pending_consumption['boss'], 0)

    def test_unreadable_counter_retries_and_does_not_claim_completion(self):
        task = self.make_task()
        task.O_REMAIN_BOSS.ocr_digit_counter.return_value = (0, 0, 0)
        with patch('tasks.ActivityShikigami.activities.normal.time.sleep'):
            with self.assertRaises(GamePageUnknownError):
                task._climb_resource_available('boss')
        self.assertEqual(task.O_REMAIN_BOSS.ocr_digit_counter.call_count, 3)
        self.assertEqual(task.climb_consumable_count['boss'], -1)

    def test_invalid_counter_can_recover_with_a_new_screenshot(self):
        task = self.make_task()
        task.O_REMAIN_BOSS.ocr_digit_counter.side_effect = [
            (101, -1, 100), (99, 1, 100),
        ]
        with patch('tasks.ActivityShikigami.activities.normal.time.sleep'):
            self.assertTrue(task._climb_resource_available('boss'))
        self.assertEqual(task.climb_consumable_count['boss'], 1)


if __name__ == '__main__':
    unittest.main()
