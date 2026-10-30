"""Regressions for reference 4d9ef784: selective OCR and refresh deadlines."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from tasks.Chess.runtime.cache import economy_action_allowed
from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ScriptTask
from tasks.Chess.strategy.shikigami_catalog import SHIKIGAMI_BONDS_BY_ROMAJI


class ChessSelectiveOcrTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.frame_card_library = {'cards': {'store': {
            'onikiri': {'name': '鬼切'}, 'hakurou': {'name': '白狼'},
        }}}
        return task

    def test_store_bonds_resolve_ambiguous_portraits_before_a_conflicting_name(self):
        task = self.task()
        text = ['白狼', *SHIKIGAMI_BONDS_BY_ROMAJI['onikiri']]
        name, score = task._frame_card_identity(
            'store', None, text, [(0.95, 'hakurou'), (0.94, 'onikiri')])
        self.assertEqual((name, score), ('onikiri', 0.94))

    def test_unique_portrait_and_no_candidates_skip_all_ocr(self):
        for candidates, expected in (([(0.95, 'onikiri')], 'onikiri'), ([], None)):
            with self.subTest(candidates=candidates):
                task = self.task()
                task._frame_card_candidates = Mock(return_value=candidates)
                local = SimpleNamespace(range_targets=Mock())
                name, _, _ = task._resolve_frame_card('store', local, np.zeros((2, 2)), None)
                self.assertEqual(name, expected)
                local.range_targets.assert_not_called()

    def test_store_reads_only_bond_ranges_when_they_resolve_the_card(self):
        task = self.task()
        task._frame_card_candidates = Mock(return_value=[(0.95, 'hakurou'), (0.94, 'onikiri')])
        bonds = SHIKIGAMI_BONDS_BY_ROMAJI['onikiri']
        targets = [SimpleNamespace(ocr=Mock(return_value=value)) for value in ('白狼', *bonds, '', '')]
        local = SimpleNamespace(range_targets=Mock(return_value=(None, targets)))
        name, _, text = task._resolve_frame_card('store', local, np.zeros((2, 2)), None)
        self.assertEqual(name, 'onikiri')
        self.assertEqual(text, ('', *bonds))
        targets[0].ocr.assert_not_called()
        for target in targets[1:4]:
            target.ocr.assert_called_once()
        for target in targets[4:]:
            target.ocr.assert_not_called()

    def test_store_name_is_read_only_after_bonds_remain_ambiguous(self):
        task = self.task()
        task._frame_card_candidates = Mock(return_value=[(0.95, 'hakurou'), (0.94, 'onikiri')])
        targets = [SimpleNamespace(ocr=Mock(return_value=value))
                   for value in ('鬼切', '', '', '', '', '')]
        local = SimpleNamespace(range_targets=Mock(return_value=(None, targets)))
        name, _, _ = task._resolve_frame_card('store', local, np.zeros((2, 2)), None)
        self.assertEqual(name, 'onikiri')
        for target in targets[:4]:
            target.ocr.assert_called_once()
        for target in targets[4:]:
            target.ocr.assert_not_called()

    def test_hand_ocr_never_reads_image_or_click_ranges(self):
        task = self.task()
        task._frame_card_candidates = Mock(return_value=[(0.95, 'hakurou'), (0.94, 'onikiri')])
        bonds = SHIKIGAMI_BONDS_BY_ROMAJI['onikiri']
        targets = [SimpleNamespace(ocr=Mock(return_value=value)) for value in (*bonds, '', '')]
        local = SimpleNamespace(range_targets=Mock(return_value=(None, targets)))
        name, _, _ = task._resolve_frame_card('card', local, np.zeros((2, 2)), None)
        self.assertEqual(name, 'onikiri')
        for target in targets[:3]:
            target.ocr.assert_called_once()
        for target in targets[3:]:
            target.ocr.assert_not_called()


class ChessRefreshDeadlineTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task._read_chess_mode = Mock(return_value='战')
        task._read_round_number = Mock(return_value=10)
        task._read_remaining_time = Mock(return_value=6)
        task._economy_guard_round = 10
        task.appear = Mock(return_value=False)
        task.click = Mock()
        return task

    def test_preparation_keeps_twelve_seconds_but_battle_allows_purchase_and_upgrade(self):
        task = self.task()
        for mode, seconds, allowed in (('备', 11, False), ('备', 12, True),
                                       ('战', 4, True), ('鬼', 30, False)):
            with self.subTest(mode=mode, seconds=seconds):
                task._read_chess_mode.return_value = mode
                task._read_remaining_time.return_value = seconds
                self.assertEqual(economy_action_allowed(task), allowed)
        task._read_chess_mode.return_value = '战'
        task._read_round_number.return_value = 11
        self.assertFalse(economy_action_allowed(task))

    def test_refresh_uses_five_seconds_and_accounts_for_cached_frame_age(self):
        task = self.task()
        for seconds, allowed in ((5, False), (6, True), (None, True)):
            with self.subTest(seconds=seconds):
                task._read_remaining_time.return_value = seconds
                self.assertEqual(task._battle_refresh_time_allowed(), allowed)
        task._read_remaining_time.return_value = 6
        task._detail_frame_cache = (None, None, 10)
        with patch('tasks.Chess.runtime.economy.time.monotonic', return_value=12):
            self.assertFalse(task._battle_refresh_time_allowed())

    def test_no_refresh_click_at_the_deadline_or_after_the_final_recheck(self):
        task = self.task()
        task._read_remaining_time.return_value = 5
        self.assertEqual(task._click_shop_refresh_and_confirm_slots(True), 'no_progress')
        task.click.assert_not_called()
        task._battle_refresh_time_allowed = Mock(side_effect=[True, False])
        task._shop_slots = Mock(return_value=[])
        task._shop_slot_refresh_snapshot = Mock(return_value={})
        task._read_level = Mock(return_value=6)
        task._read_shop_gold = Mock(return_value=60)
        task._can_execute_economy_operation = Mock(return_value=True)
        task._clear_economy_click_history = Mock()
        task._economy_action_allowed = Mock(return_value=True)
        self.assertEqual(task._click_shop_refresh_and_confirm_slots(True), 'no_progress')
        task.click.assert_not_called()

    def test_battle_loop_does_not_stop_at_the_old_twelve_second_cutoff(self):
        task = self.task()
        task._read_remaining_time.return_value = 8
        task.purchase_lineup_cards_once = Mock()
        task._economy_pending = True
        task._schedule_economy_cycle = Mock()
        task._run_economy_atomic_batch = Mock(return_value='complete')
        task._run_battle_economy_until_budget_limit()
        task.purchase_lineup_cards_once.assert_called_once()
        task._run_economy_atomic_batch.assert_called_once_with(battle_mode=True)


class ChessAnimatedRefreshTest(unittest.TestCase):
    def test_two_stable_identity_scans_confirm_refresh_despite_animated_pixels(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task._battle_refresh_time_allowed = Mock(return_value=True)
        task.appear = Mock(return_value=True)
        task._read_level = Mock(return_value=6)
        task._read_shop_gold = Mock(return_value=60)
        task._read_round_number = Mock(return_value=10)
        task._can_execute_economy_operation = Mock(return_value=True)
        task._clear_economy_click_history = Mock()
        task._economy_action_allowed = Mock(return_value=True)
        task.click = Mock()
        task.device = SimpleNamespace(click_record_remove=Mock())
        task._shop_slots = Mock(return_value=[(i, object()) for i in range(1, 6)])
        snapshots = [{i: {'name': 'old' + str(i), 'image': np.full((4, 4), value, dtype=np.uint8)}
                      for i in range(1, 6)} for value in (0, 20, 40)]
        task._shop_slot_refresh_snapshot = Mock(side_effect=snapshots)
        task._shop_refresh_changed_slots = Mock(return_value=([1, 2, 3], {i: 20 for i in range(1, 6)}))
        task._shop_page_identities = Mock(return_value=('new1', 'new2', 'new3', 'new4', 'new5'))
        clock = [0.0]
        task.screenshot = Mock(side_effect=lambda: clock.__setitem__(0, clock[0] + .1))
        with patch('tasks.Chess.runtime.economy.time.monotonic', side_effect=lambda: clock[0]):
            self.assertEqual(task._click_shop_refresh_and_confirm_slots(False), 'success')
        task.click.assert_called_once()
        self.assertEqual(task._shop_page_identities.call_count, 2)
        self.assertEqual(task.device.click_record_remove.call_count, 3)
        self.assertEqual(task.chess_state.economy_refresh_counts[10], 1)

    def test_shop_identities_follow_slot_positions_and_require_five_distinct_slots(self):
        task = ScriptTask.__new__(ScriptTask)
        cards = [{'name': 'card' + str(i), 'position': (i, 0), 'badge_score': .9}
                 for i in range(5)]
        cards.append({'name': 'bad_duplicate', 'position': (0, 0), 'badge_score': .8})
        task._frame_card_scan = Mock(return_value=cards)
        task._frame_shop_column = Mock(side_effect=lambda x: x)
        self.assertEqual(task._shop_page_identities(), ('card4', 'card3', 'card2', 'card1', 'card0'))
        task._frame_card_scan.return_value = cards[1:5]
        self.assertIsNone(task._shop_page_identities())

    def test_ambiguous_refresh_buys_visible_targets_once_without_spending_again(self):
        for allowed, shop_open in ((True, True), (False, True), (True, False)):
            with self.subTest(allowed=allowed, shop_open=shop_open):
                task = ScriptTask.__new__(ScriptTask)
                task.chess_state = ChessGameState()
                task._economy_pending = True
                task._is_purchase_allowed = Mock(return_value=True)
                task._read_level = Mock(return_value=6)
                task._read_shop_gold = Mock(return_value=60)
                task._next_economy_operation = Mock(return_value='refresh')
                task._can_execute_economy_operation = Mock(return_value=True)
                task._ensure_shop_open = Mock(return_value=True)
                task._click_shop_refresh_and_confirm_slots = Mock(return_value='no_progress')
                task._economy_action_allowed = Mock(return_value=allowed)
                task._is_shop_open = Mock(return_value=shop_open)
                task.purchase_lineup_cards_once = Mock()
                self.assertEqual(task._run_economy_atomic_batch(True), 'blocked')
                self.assertEqual(task.purchase_lineup_cards_once.call_count, int(allowed and shop_open))
                task._click_shop_refresh_and_confirm_slots.assert_called_once()


if __name__ == '__main__':
    unittest.main()
