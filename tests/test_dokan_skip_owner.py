"""Owner-skip option must abandon and choose Battle Again before combat."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tasks.Component.GeneralBattle.general_battle import BattleAction
from tasks.Dokan.config import DokanConfig
from tasks.Dokan.script_task import ScriptTask


class OwnerSkipTest(unittest.TestCase):
    def test_option_is_off_by_default(self):
        self.assertFalse(DokanConfig().skip_owner_battle)

    @patch('tasks.Dokan.script_task.sleep', return_value=None)
    def test_abandon_then_choose_battle_again(self, _sleep):
        markers = {name: object() for name in (
            'I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN',
            'I_RYOU_DOKAN_TOPPA_RANK',
            'I_DOKAN_ABANDONED_TOPPA_TITLE',
            'I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED',
            'I_DOKAN_ABANDONED_TOPPA_ENSURE',
            'I_DOKAN_ABANDONED_TOPPA_RIGHT',
            'I_DOKAN_ABANDONED_TOPPA',
        )}
        steps = []
        state = {'value': 'owner'}

        def appear(target):
            visible = {
                'owner': markers['I_DOKAN_ABANDONED_TOPPA_RIGHT'],
                'confirm': markers['I_DOKAN_ABANDONED_TOPPA_ENSURE'],
                'vote': markers['I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN'],
            }
            return target is visible.get(state['value'])

        def click(target, **kwargs):
            if target is markers['I_DOKAN_ABANDONED_TOPPA_RIGHT']:
                state['value'] = 'confirm'
                steps.append('abandon')
            elif target is markers['I_DOKAN_ABANDONED_TOPPA_ENSURE']:
                state['value'] = 'vote'
                steps.append('confirm')
            elif target is markers['I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN']:
                state['value'] = 'done'
                steps.append('battle_again')
            else:
                raise AssertionError('clicked unexpected control')
            return True

        task = SimpleNamespace(
            **markers,
            C_DOKAN_TOPPA_RANK_CLOSE_AREA=object(),
            dokan_owner_battle=True,
            first_master_killed=True,
            screenshot=Mock(),
            appear=appear,
            appear_then_click=click,
            wait_until_disappear=Mock(),
            wait_for_next_dokan_selection=Mock(),
            can_battle_again=Mock(return_value=True),
            click=Mock(side_effect=AssertionError('rank close not expected')),
        )
        self.assertTrue(ScriptTask.skip_owner_and_battle_again(task))
        self.assertEqual(steps, ['abandon', 'confirm', 'battle_again'])
        task.wait_for_next_dokan_selection.assert_called_once()

    @patch('tasks.Dokan.script_task.sleep', return_value=None)
    def test_last_attempt_abandons_and_keeps_bounty(self, _sleep):
        markers = {name: object() for name in (
            'I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN',
            'I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY',
            'I_RYOU_DOKAN_TOPPA_RANK',
            'I_DOKAN_ABANDONED_TOPPA_TITLE',
            'I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED',
            'I_DOKAN_ABANDONED_TOPPA_ENSURE',
            'I_DOKAN_ABANDONED_TOPPA_RIGHT',
            'I_DOKAN_ABANDONED_TOPPA',
        )}
        state = {'value': 'owner'}
        clicked = []

        def appear(target):
            visible = {
                'owner': markers['I_DOKAN_ABANDONED_TOPPA_RIGHT'],
                'confirm': markers['I_DOKAN_ABANDONED_TOPPA_ENSURE'],
                'vote': markers['I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY'],
            }
            return target is visible.get(state['value'])

        def click(target, **kwargs):
            if target is markers['I_DOKAN_ABANDONED_TOPPA_RIGHT']:
                state['value'] = 'confirm'
                clicked.append('abandon')
            elif target is markers['I_DOKAN_ABANDONED_TOPPA_ENSURE']:
                state['value'] = 'vote'
                clicked.append('confirm')
            elif target is markers['I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY']:
                state['value'] = 'done'
                clicked.append('keep_bounty')
            else:
                raise AssertionError('clicked unexpected control')
            return True

        task = SimpleNamespace(
            **markers,
            C_DOKAN_TOPPA_RANK_CLOSE_AREA=object(),
            dokan_owner_battle=True,
            screenshot=Mock(),
            appear=appear,
            appear_then_click=click,
            wait_until_disappear=Mock(),
            wait_for_next_dokan_selection=Mock(),
            can_battle_again=Mock(return_value=False),
        )
        self.assertTrue(ScriptTask.skip_owner_and_battle_again(task))
        self.assertEqual(clicked, ['abandon', 'confirm', 'keep_bounty'])
        self.assertFalse(task.dokan_owner_battle)
        task.wait_for_next_dokan_selection.assert_not_called()

    def test_owner_stage_skips_start_challenge(self):
        names = (
            'I_RYOU_DOKAN_GATHERING', 'I_RYOU_DOKAN_MASTER_BATTLE',
            'I_RYOU_DOKAN_START_CHALLENGE', 'I_RYOU_DOKAN_CD',
            'I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED',
            'I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY',
            'I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN',
            'I_RYOU_DOKAN_TODAY_ATTACK_COUNT',
            'I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE', 'I_DOKAN_BOSS_WAITING',
        )
        markers = {name: object() for name in names}
        task = SimpleNamespace(
            **markers,
            conf=SimpleNamespace(dokan_config=SimpleNamespace(skip_owner_battle=True)),
            device=SimpleNamespace(stuck_record_clear=Mock()),
            dokan_owner_battle=False,
            prepare_appear_cache=Mock(),
            skip_owner_and_battle_again=Mock(return_value=False),
            click_until_in_battle=Mock(side_effect=AssertionError('started owner battle')),
        )
        task.appear = lambda target: target in (
            task.I_RYOU_DOKAN_MASTER_BATTLE, task.I_RYOU_DOKAN_START_CHALLENGE
        )
        ScriptTask.run_on_dokan(task)
        task.skip_owner_and_battle_again.assert_called_once()
        task.click_until_in_battle.assert_not_called()

    def test_mid_battle_owner_is_exited(self):
        first = object()
        second = object()
        task = SimpleNamespace(
            I_RYOU_DOKAN_BATTLE_MASTER_FIRST=first,
            I_RYOU_DOKAN_BATTLE_MASTER_SECOND=second,
            conf=SimpleNamespace(dokan_config=SimpleNamespace(skip_owner_battle=True)),
            dokan_owner_battle=False,
            appear=lambda target: target is first,
        )
        self.assertEqual(ScriptTask._handle_in_battle(task, None, None), BattleAction.QUICK_EXIT)
        self.assertTrue(task.dokan_owner_battle)


if __name__ == '__main__':
    unittest.main()
