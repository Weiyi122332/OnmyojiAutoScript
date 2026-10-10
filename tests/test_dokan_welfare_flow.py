"""Welfare-only dojos keep member battles and safely skip every owner entry."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config_model import ConfigModel
from tasks.Component.GeneralBattle.general_battle import BattleAction, GeneralBattle
from tasks.Dokan.config import Dokan, DokanBattleConfig
from tasks.Dokan.script_task import ScriptTask


class WelfareDokanFlowTest(unittest.TestCase):
    def test_old_disabled_mode_flags_do_not_restore_removed_ui_or_discard_remaining_settings(self):
        task = Dokan.model_validate({
            'dokan_config': {
                'only_welfare_guild': False, 'skip_owner_battle': False, 'try_start_dokan': False,
                'find_dokan_score': 4.6, 'min_bounty': 9999, 'random_delay': True,
                'dokan_auto_cheering_while_cd': True, 'min_people_num': 140,
                'find_dokan_refresh_count': 5, 'monday_to_thursday': False,
            },
            'dokan_owner_battle_conf': {}, 'dokan_owner_switch_soul': {},
            'attack_count_config': {
                'attack_dokan_master': 'ATTACK_TWO_TWO', 'daily_attack_count': 2,
                'attack_date': '2026-10-08', 'remain_attack_count': 1,
            },
        })
        model = ConfigModel(dokan=task)
        page = model.script_task('Dokan')
        self.assertEqual(set(page), {
            'scheduler', 'dokan_config', 'notification_config', 'dokan_member_battle_conf',
            'dokan_member_switch_soul', 'qq_message_config',
        })
        self.assertEqual({field['name'] for field in page['dokan_config']}, {
            'dokan_run_time', 'dokan_attack_priority', 'monday_to_thursday',
            'push_reward_images', 'min_people_num', 'find_dokan_refresh_count',
        })
        self.assertEqual(task.dokan_config.min_people_num, 140)
        self.assertEqual(task.dokan_config.find_dokan_refresh_count, 5)
        self.assertEqual(task.attack_count_config.remain_attack_count, 1)
        self.assertEqual(task.attack_count_config.attack_date, '2026-10-08')
        self.assertNotIn('daily_attack_count', task.attack_count_config.model_dump())

    def test_owner_prepare_never_clicks_ready_for_either_owner_team(self):
        for marker in ('I_RYOU_DOKAN_BATTLE_MASTER_FIRST', 'I_RYOU_DOKAN_BATTLE_MASTER_SECOND'):
            with self.subTest(marker=marker):
                task = ScriptTask.__new__(ScriptTask)
                task.dokan_owner_battle = False
                task.appear = Mock(side_effect=lambda target: target is getattr(task, marker))
                with patch.object(GeneralBattle, '_handle_prepare') as prepare:
                    self.assertEqual(task._handle_prepare(None, None), BattleAction.QUICK_EXIT)
                prepare.assert_not_called()

    def test_member_prepare_and_battle_continue_using_the_existing_battle_handler(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(return_value=False)
        task.dokan_owner_battle = False
        with patch.object(GeneralBattle, '_handle_prepare', return_value=BattleAction.CONTINUE) as prepare, \
                patch.object(GeneralBattle, '_handle_in_battle', return_value=BattleAction.CONTINUE) as battle:
            self.assertEqual(task._handle_prepare(None, None), BattleAction.CONTINUE)
            self.assertEqual(task._handle_in_battle(None, None), BattleAction.CONTINUE)
        prepare.assert_called_once()
        battle.assert_called_once()

    def test_recovering_inside_owner_battle_uses_quick_exit_without_changing_member_configuration(self):
        task = ScriptTask.__new__(ScriptTask)
        config = DokanBattleConfig()
        task.conf = SimpleNamespace(dokan_member_battle_conf=config)
        task.appear = Mock(side_effect=lambda target: target is task.I_RYOU_DOKAN_BATTLE_MASTER_FIRST)
        task.run_general_battle = Mock()
        task.run_on_battle()
        sent_config = task.run_general_battle.call_args.args[0]
        self.assertTrue(sent_config.quick_exit)
        self.assertFalse(config.quick_exit)
        self.assertTrue(task.dokan_owner_battle)

    def test_member_soul_is_switched_once_across_two_dojos(self):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(dokan=Dokan())
        task.config.dokan.dokan_member_switch_soul.enable = True
        task.switch_member_soul_done = False
        task.goto_page = Mock()
        task.run_switch_soul = Mock()
        task.switch_soul_in_dokan()
        task.switch_soul_in_dokan()
        task.run_switch_soul.assert_called_once()
        self.assertTrue(task.switch_member_soul_done)

    def test_settlement_vote_without_owner_state_uses_the_same_retry_flow(self):
        task = ScriptTask.__new__(ScriptTask)
        task.dokan_owner_battle = False
        task.device = SimpleNamespace(stuck_record_clear=Mock())
        task.prepare_appear_cache = Mock()
        task.appear = Mock(side_effect=lambda target: target is task.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN)
        task.skip_owner_and_battle_again = Mock()
        task.run_on_dokan()
        task.skip_owner_and_battle_again.assert_called_once()

    def test_member_soul_by_name_is_kept_and_switched_once(self):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(dokan=Dokan())
        souls = task.config.dokan.dokan_member_switch_soul
        souls.enable_switch_by_name = True
        souls.group_name, souls.team_name = '道馆', '馆员'
        task.switch_member_soul_done = False
        task.goto_page = Mock()
        task.run_switch_soul_by_name = Mock()
        task.switch_soul_in_dokan()
        task.switch_soul_in_dokan()
        task.run_switch_soul_by_name.assert_called_once_with('道馆', '馆员')


if __name__ == '__main__':
    unittest.main()
