"""New-season Chess resources and their integration with the current runtime."""

from copy import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.atom.frame import Click, Image, RuleFrame
from module.atom.click import RuleClick
from module.image.runtime import ImageRuntime
from tasks.base_task import BaseTask
from tasks.Chess.assets import ChessAssets
from tasks.Chess.config import Chess, ChessConfig
from tasks.Chess.runtime.hyakki_draft import HyakkiTurn, throw_point
from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ScriptTask
from tasks.Chess.strategy.lineup import LINEUP_REGISTRY
from tasks.Chess.strategy.shikigami_catalog import NON_SHOP_SHIKIGAMI
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.chess_battle import ChessBattleNavigationMixin
from tasks.GameUi.default_pages import page_chess_battle, page_chess_result
from tasks.GlobalGame.assets import GlobalGameAssets

SHOP_CLICK = RuleClick((100, 100, 20, 20), (100, 100, 20, 20), name='test_shop_slot')


class ChessSeasonConfigTest(unittest.TestCase):
    def test_only_new_season_lineups_are_offered(self):
        self.assertEqual(set(LINEUP_REGISTRY), {'pinganjing', 'qijiaoshan', 'huangchuan', 'minghuo'})
        self.assertEqual(ChessConfig().lineup_bond.value, '七角山')

    def test_old_season_instances_keep_constraints_and_cron(self):
        for name in ('流火', '冥府', '大江山', '狐妖',
                     'liuhuo', 'mingfu', 'dajiangshan', 'huyao', 'arakawa'):
            with self.subTest(lineup=name):
                config = Chess(scheduler={'cron': '0 6 * * *'}, chess_config={
                    'lineup_bond': name, 'run_count': 3, 'rank_protection': True,
                })
                self.assertEqual(config.chess_config.lineup_bond.value, '七角山')
                self.assertEqual(config.chess_config.run_count, 3)
                self.assertTrue(config.chess_config.rank_protection)
                self.assertEqual(config.scheduler.cron, '0 6 * * *')

    def test_hyakki_option_defaults_on_and_can_be_disabled(self):
        self.assertTrue(ChessConfig().hyakki_draft_enabled)
        self.assertFalse(ChessConfig(hyakki_draft_enabled=False).hyakki_draft_enabled)

    def test_new_resource_indexes_and_all_portraits_are_loadable(self):
        reader = ScriptTask.__new__(ScriptTask)
        for kind in ('card', 'store'):
            entries = reader.frame_card_library['cards'][kind]
            portraits = reader.frame_portraits[kind]
            self.assertEqual(set(entries), set(portraits))
            self.assertTrue(all(image.size for image in portraits.values()))
            for lineup in LINEUP_REGISTRY.values():
                self.assertTrue(set(lineup['strategy']['shikigami']) <= set(entries))
        self.assertEqual(set(reader.frame_emblem_library['entries']),
                         set(reader.frame_emblem_portraits))
        for badges in reader.frame_badges.values():
            self.assertTrue(all(image.size for image in badges))

    def test_non_shop_identity_and_preferred_soul_resources_are_accounted_for(self):
        reader = ScriptTask.__new__(ScriptTask)
        cards = reader.frame_card_library['cards']
        self.assertEqual(set(cards['card']) - set(cards['store']), NON_SHOP_SHIKIGAMI)
        preferred = {
            soul
            for lineup in LINEUP_REGISTRY.values()
            for shikigami in lineup['strategy']['shikigami'].values()
            for soul in shikigami.get('preferred_souls', ())
        }
        manifest = json.loads((Path(__file__).resolve().parents[1]
                               / 'tasks/Chess/resource/hyakki_soul/manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(preferred - set(reader.hyakki_soul_fronts) <= set(manifest['missing']))

    def test_every_local_png_decodes(self):
        root = Path(__file__).resolve().parents[1] / 'tasks/Chess'
        images = list(root.rglob('*.png'))
        self.assertTrue(images)
        for file in images:
            with self.subTest(file=file.relative_to(root)):
                image = cv2.imdecode(np.fromfile(file, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                self.assertIsNotNone(image)


class ChessFrameIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(self.runtime.shutdown)

    def test_alternate_badge_rebases_ranges_and_preview_never_clicks(self):
        with TemporaryDirectory() as directory:
            rng = np.random.default_rng(734)
            badges = [rng.integers(0, 256, (6, 7, 3), dtype=np.uint8) for _ in range(2)]
            files = []
            for index, badge in enumerate(badges):
                file = Path(directory) / f'badge_{index}.png'
                file.write_bytes(cv2.imencode('.png', cv2.cvtColor(badge, cv2.COLOR_RGB2BGR))[1].tobytes())
                files.append(str(file))
            image = np.zeros((100, 120, 3), dtype=np.uint8)
            image[35:41, 40:47] = badges[1]
            frame = RuleFrame(
                roi_badge=(10, 10, 7, 6), roi_back=(0, 0, 120, 100),
                roi_range=[(18, 18, 10, 8), (25, 12, 6, 6)],
                badgefile=files, threshold=0.99, range=[Image(), Click()],
            )
            task = SimpleNamespace(device=SimpleNamespace(image=image), click=Mock())
            task.appear = lambda rule, **_: rule._apply_match_result(
                self.runtime._match_rule_payload(image, rule.to_service_payload()))

            result = BaseTask.runframe(task, frame)
            self.assertTrue(result)
            self.assertEqual(frame.badge_index, 1)
            np.testing.assert_array_equal(result[0], image[43:51, 48:58])
            self.assertEqual(result[1], (55, 37, 6, 6))
            task.click.assert_not_called()

            BaseTask.runframe(task, frame, None, True)
            task.click.assert_called_once()

    def test_frame_badges_and_gray_mode_have_distinct_cache_keys(self):
        frame = copy(ChessAssets.F_HAND_CARD)
        changed = copy(frame)
        changed.files = ['different_badge.png'] * len(frame.files)
        self.assertNotEqual(frame.match_cache_key(), changed.match_cache_key())
        changed = copy(frame)
        changed.badge_grayscale = True
        self.assertNotEqual(frame.match_cache_key(), changed.match_cache_key())

    def test_frame_scan_uses_new_season_portrait_and_never_sends_input(self):
        task = ScriptTask.__new__(ScriptTask)
        frame = ChessAssets.F_HAND_CARD
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        badge = task.frame_badges['card'][0]
        bx, by, _, _ = frame.badge_references[0]
        image[by:by+badge.shape[0], bx:bx+badge.shape[1]] = badge
        portrait = task.frame_portraits['card']['hakurou']
        x, y, _, _ = frame.roi_ranges[-2]
        image[y:y+portrait.shape[0], x:x+portrait.shape[1]] = cv2.cvtColor(portrait, cv2.COLOR_GRAY2RGB)
        task.device = SimpleNamespace(image=image, image_frame_id='test-card')
        task.click = Mock()
        task.appear = lambda rule, **_: rule._apply_match_result(
            self.runtime._match_rule_payload(image, rule.to_service_payload()))
        with patch('module.atom.ocr.RuleOcr.ocr', return_value=''):
            cards = task._frame_card_scan('card')
        self.assertEqual([card['name'] for card in cards], ['hakurou'])
        task.click.assert_not_called()


class ChessFlowIntegrationTest(unittest.TestCase):
    def test_missing_global_red_cross_uses_the_chess_copy(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear_then_click = Mock(return_value=True)
        with patch.object(BaseTask, '_burst', return_value=False), \
                patch.object(GameUiAssets, 'I_CLOSE_RED', None, create=True):
            self.assertTrue(task._burst())
        task.appear_then_click.assert_called_once_with(task._chess_close_red, interval=0.8)
        self.assertNotEqual(task._chess_close_red.file, task.I_CLOSE_RED.file)

    def test_red_cross_keeps_using_the_chess_copy_if_global_rule_is_added(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear_then_click = Mock(return_value=True)
        global_rule = object()
        with patch.object(BaseTask, '_burst', return_value=False), \
                patch.object(GameUiAssets, 'I_CLOSE_RED', global_rule, create=True):
            self.assertTrue(task._burst())
        task.appear_then_click.assert_called_once_with(task._chess_close_red, interval=0.8)

    def test_sixrealms_page_is_recognized_without_taking_over_generic_rewards(self):
        scene = SimpleNamespace(appear=lambda rule: rule is ChessAssets.I_SELECT_SIXREALMS)
        self.assertTrue(page_chess_battle.recognizer.evaluate(scene))
        reward = SimpleNamespace(appear=lambda rule: rule is GlobalGameAssets.I_UI_REWARD)
        self.assertFalse(page_chess_result.recognizer.evaluate(reward))

    def test_selects_one_field_then_waits_for_the_page_to_disappear(self):
        task = ChessBattleNavigationMixin()
        scene = {'visible': True}
        task.appear = lambda _: scene['visible']
        task.screenshot = Mock(side_effect=lambda: scene.update(visible=False))
        task.click = Mock()
        task.device = SimpleNamespace(click_record_remove=Mock(), stuck_record_clear=Mock())
        with patch('tasks.GameUi.chess_battle.time.sleep'), \
                patch('tasks.GameUi.chess_battle.random.choice', return_value=ChessAssets.C_SIXREALMS_1):
            self.assertTrue(task.select_chess_sixrealms_if_visible())
        task.click.assert_called_once_with(ChessAssets.C_SIXREALMS_1)

    def test_purchase_missing_before_the_first_click_is_not_success(self):
        task = ScriptTask.__new__(ScriptTask)
        task._recognize_shop_slot = Mock(return_value=None)
        task.click = Mock()
        self.assertFalse(task._buy_shop_slot(1, SHOP_CLICK, 'hakurou'))
        task.click.assert_not_called()

    def test_purchase_confirmation_ignores_a_single_disappearing_frame(self):
        task = BaseTask.__new__(BaseTask)
        task.screenshot = Mock()
        task.click = Mock(return_value=True)
        visible = Mock(side_effect=[True, False, True, False, False])
        self.assertTrue(task.ui_click_until_disappear(
            SHOP_CLICK, click_target=SHOP_CLICK,
            visible=visible, interval=0, timeout=1, confirm_frames=2,
        ))
        self.assertEqual(task.screenshot.call_count, 5)
        self.assertEqual(task.click.call_count, 2)

    def test_purchase_stops_after_three_clicks_when_target_remains(self):
        task = ScriptTask.__new__(ScriptTask)
        task.screenshot = Mock()
        task.click = Mock(return_value=True)
        self.assertFalse(task.ui_click_until_disappear(
            SHOP_CLICK, click_target=SHOP_CLICK,
            visible=lambda: True, interval=0, timeout=1, confirm_frames=2, max_clicks=3,
        ))
        self.assertEqual(task.click.call_count, 3)

    def test_purchase_can_confirm_after_the_third_click(self):
        task = ScriptTask.__new__(ScriptTask)
        task.screenshot = Mock()
        task.click = Mock(return_value=True)
        self.assertTrue(task.ui_click_until_disappear(
            SHOP_CLICK, click_target=SHOP_CLICK,
            visible=Mock(side_effect=[True, True, True, False, False]),
            interval=0, timeout=1, confirm_frames=2, max_clicks=3,
        ))
        self.assertEqual(task.click.call_count, 3)

    def _shop_task(self, purchase_succeeds):
        task = ScriptTask.__new__(ScriptTask)
        task._recognize_shop_slot = Mock(return_value={'source': 'image', 'score': 1.0})
        task._is_purchase_allowed = Mock(return_value=True)
        task._can_afford_shop_shikigami = Mock(return_value=True)
        task._hand_capacity_count = Mock(return_value=0)
        task._lineup_hand_card_match_count = Mock(return_value=0)
        task._confirm_shop_purchase = Mock(return_value=purchase_succeeds)
        badge = object()
        task._shop_purchase_badge = Mock(return_value=badge)
        task.appear = Mock(side_effect=lambda rule: rule is badge)
        task._economy_action_allowed = Mock(return_value=True)
        task._is_shop_open = Mock(return_value=True)
        task.click = Mock(return_value=True)
        task.ui_click_until_disappear = Mock(return_value=purchase_succeeds)
        task.device = SimpleNamespace(click_record_remove=Mock())
        return task

    def test_confirmed_purchase_clears_the_slots_click_history(self):
        task = self._shop_task(True)
        self.assertTrue(task._buy_shop_slot(1, SHOP_CLICK, 'hakurou'))
        self.assertEqual(task.device.click_record_remove.call_count, 2)
        task.click.assert_called_once_with(SHOP_CLICK)

    def test_blocked_purchase_cancels_after_two_cleanup_retries(self):
        task = self._shop_task(False)
        task._free_one_hand_slot_for_purchase = Mock(side_effect=[
            {'type': 'other'}, {'type': 'lineup'},
        ])
        task._hand_capacity_count.side_effect = [9, 10, 9, 10, 9]
        self.assertFalse(task._buy_shop_slot(1, SHOP_CLICK, 'hakurou'))
        self.assertEqual(task.click.call_count, 3)
        self.assertEqual(task._free_one_hand_slot_for_purchase.call_count, 2)
        self.assertEqual(task.device.click_record_remove.call_count, 3)


class ChessSpecialRoundTest(unittest.TestCase):
    def test_hyakki_wait_restarts_after_ambiguous_lock_and_limits_throws(self):
        turn = HyakkiTurn((1, 2), wait_seconds=6)
        self.assertFalse(turn.ready(.9, 0))
        self.assertFalse(turn.ready(.1, 1))
        self.assertFalse(turn.ready(.1, 6))
        self.assertFalse(turn.ready(None, 7))
        self.assertFalse(turn.ready(.1, 8))
        self.assertTrue(turn.ready(.1, 14))
        self.assertFalse(turn.ready(.9, 15))
        self.assertIsNone(turn.unlocked_at)
        turn.throws = 2
        self.assertFalse(turn.ready(.1, 30))

    def test_nonpreferred_hyakki_targets_wait_for_all_player_locks(self):
        task = ScriptTask.__new__(ScriptTask)
        task._hyakki_all_locks_gone = Mock(return_value=False)
        task._hyakki_skip = Mock()
        preferred = {'name': 'zheng', 'center': (200, 200)}
        other = {'name': 'po_shi', 'center': (300, 200)}
        self.assertEqual(task._hyakki_target_pool([preferred, other], {'zheng'}), [preferred])
        self.assertEqual(task._hyakki_target_pool([other], {'zheng'}), [])
        task._hyakki_all_locks_gone.return_value = True
        self.assertEqual(task._hyakki_target_pool([other], {'zheng'}), [other])

    def test_moving_hyakki_target_cannot_produce_an_out_of_bounds_click(self):
        previous = {'center': (200, 200)}
        latest = {'center': (180, 200)}
        self.assertEqual(throw_point(previous, latest, .5, .1, (0, 138, 1024, 462)),
                         (174, 350))
        self.assertIsNone(throw_point(previous, {'center': (180, 590)}, .5, .1,
                                     (0, 138, 1024, 462)))

    def test_gold_stage_marker_is_active_but_gray_preview_is_not(self):
        task = ScriptTask.__new__(ScriptTask)
        rule = ChessAssets.I_STAGE_HYAKKI
        x, y, w, h = rule.roi_back
        template = rule.image
        th, tw = template.shape[:2]
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[y:y+th, x:x+tw] = template
        task.device = SimpleNamespace(image=image)
        self.assertTrue(task._stage_marker_visible(rule))
        image[y:y+th, x:x+tw] = cv2.cvtColor(
            cv2.cvtColor(template, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
        self.assertFalse(task._stage_marker_visible(rule))

    def test_golden_copy_uses_verified_one_cost_cards_and_actual_positions(self):
        task = ScriptTask.__new__(ScriptTask)
        task.select_lineup_strategy('qijiaoshan')
        task.chess_state = ChessGameState()
        task._board_actual_positions = {'hakurou': 9}
        self.assertEqual(task._golden_copy_targets({'hakurou', 'keisei_chihime'}),
                         [('hakurou', 9)])
        self.assertEqual(task._golden_copy_targets(set()), [])


if __name__ == '__main__':
    unittest.main()
