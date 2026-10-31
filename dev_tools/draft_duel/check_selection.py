"""选人状态机离线检查，不连接设备。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tasks.DraftDuel.script_task import ScriptTask
from tasks.DraftDuel.strategy import normalize_name, choose_pick


class SelectionTests(unittest.TestCase):
    def test_observed_mumu1_candidate_typo_resolves_to_catalog_entry(self):
        names = [normalize_name(n) for n in ['紧那罗', '天刀姬·绯夜猎', '樱花妖']]
        self.assertEqual(names, ['紧那罗', '妖刀姬·绯夜猎刃', '樱花妖'])
        self.assertIn(choose_pick(names, team=['季', '追月神']).name, names)

    def test_round_number(self):
        for text, expected in [('请选择第1名角色', 1), ('请选择第五名角色', 5),
                               ('请选择第1名式神', 1), ('请选择第 3 名式神', 3),
                               ('请选择第五名式神', 5),
                               ('请选择第 3 名角色', 3), ('等待队友', None)]:
            self.assertEqual(ScriptTask._parse_select_number(text), expected)

    def test_fifth_name_is_recorded_when_last_click_switches_to_rank(self):
        owner = object.__new__(ScriptTask)
        owner.device = Mock()
        frame = [-1]
        states = [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 'rank']
        names = ['莹草', '鬼童丸', '茨木童子', '椒图', '辉夜姬']
        owner.screenshot = Mock(side_effect=lambda: frame.__setitem__(0, frame[0] + 1))
        def appear(rule):
            state = states[frame[0]]
            if rule is owner.I_POST_DRAFT_RANK:
                return state == 'rank'
            if rule is owner.I_POST_DRAFT_SELECT:
                return state != 'rank'
            return any(rule is getattr(owner, f'I_SELECT_NONE_{i}')
                       and state == i and frame[0] == (i - 1) * 3 for i in range(1, 6))
        owner.appear = Mock(side_effect=appear)
        owner.O_SELECT_NUMBER = Mock()
        owner.O_SELECT_NUMBER.ocr.side_effect = lambda _: f'请选择第{states[frame[0]]}名角色'
        for i in (1, 2, 3):
            rule = Mock()
            rule.ocr.side_effect = lambda _: names[states[frame[0]] - 1]
            setattr(owner, f'O_SHIKIGAMI_NAME_{i}', rule)
        owner.appear_then_click = Mock(return_value=True)
        with patch('tasks.DraftDuel.runtime.selection.time.sleep'), patch(
                'tasks.DraftDuel.runtime.selection.choose_pick',
                side_effect=[SimpleNamespace(name=n, score=40) for n in names]):
            self.assertTrue(owner._select_shikigami())
        self.assertEqual(owner.draft_selected, names)
        self.assertEqual(owner.appear_then_click.call_count, 5)

    def test_confirm_wait_and_next_round(self):
        owner = object.__new__(ScriptTask)
        owner.device = Mock()
        frame = [-1]
        states = [1, 1, 1, 1, 2, 2, 2, 'rank']
        owner.screenshot = Mock(side_effect=lambda: frame.__setitem__(0, frame[0] + 1))
        def appear(rule):
            state = states[frame[0]]
            if rule is owner.I_POST_DRAFT_RANK:
                return state == 'rank'
            if rule is owner.I_POST_DRAFT_SELECT:
                return state != 'rank'
            if rule is owner.I_SELECT_NONE_1:
                return frame[0] == 0
            if rule is owner.I_SELECT_NONE_2:
                return frame[0] == 4
            return False
        owner.appear = Mock(side_effect=appear)
        owner.O_SELECT_NUMBER = Mock()
        owner.O_SELECT_NUMBER.ocr.side_effect = lambda _: f'请选择第{states[frame[0]]}名角色'
        for i, name in enumerate(('莹草', '鬼童丸', '茨木童子'), 1):
            setattr(owner, f'O_SHIKIGAMI_NAME_{i}', Mock(ocr=Mock(return_value=name)))
        owner.appear_then_click = Mock(return_value=True)
        with patch('tasks.DraftDuel.runtime.selection.time.sleep'), patch(
                'tasks.DraftDuel.runtime.selection.choose_pick',
                side_effect=[SimpleNamespace(name='莹草', score=40),
                             SimpleNamespace(name='鬼童丸', score=40)]) as choose:
            self.assertTrue(owner._select_shikigami())
        self.assertEqual(owner.draft_selected, ['莹草', '鬼童丸'])
        self.assertEqual(owner.appear_then_click.call_count, 2)
        self.assertEqual(choose.call_count, 2)


if __name__ == '__main__':
    unittest.main()
