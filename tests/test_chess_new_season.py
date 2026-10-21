"""New-season Chess resources and their integration with the current runtime."""

from copy import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.atom.frame import Click, Image, RuleFrame
from module.image.runtime import ImageRuntime
from tasks.base_task import BaseTask
from tasks.Chess.assets import ChessAssets
from tasks.Chess.config import Chess, ChessConfig
from tasks.Chess.script_task import ScriptTask
from tasks.Chess.strategy.lineup import LINEUP_REGISTRY
from tasks.GameUi.chess_battle import ChessBattleNavigationMixin
from tasks.GameUi.default_pages import page_chess_battle, page_chess_result
from tasks.GlobalGame.assets import GlobalGameAssets


class ChessSeasonConfigTest(unittest.TestCase):
    def test_only_new_season_lineups_are_offered(self):
        self.assertEqual(set(LINEUP_REGISTRY), {'qijiaoshan', 'haiguo'})
        self.assertEqual(ChessConfig().lineup_bond.value, '七角山')

    def test_old_season_instances_keep_constraints_and_cron(self):
        for name in ('流火', '冥府', '大江山', '狐妖', '荒川',
                     'liuhuo', 'mingfu', 'dajiangshan', 'huyao', 'arakawa'):
            with self.subTest(lineup=name):
                config = Chess(scheduler={'cron': '0 6 * * *'}, chess_config={
                    'lineup_bond': name, 'run_count': 3, 'rank_protection': True,
                })
                self.assertEqual(config.chess_config.lineup_bond.value, '七角山')
                self.assertEqual(config.chess_config.run_count, 3)
                self.assertTrue(config.chess_config.rank_protection)
                self.assertEqual(config.scheduler.cron, '0 6 * * *')

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
        self.assertFalse(task._buy_shop_slot(1, ChessAssets.C_SHIKIGAMI_1, 'hakurou'))
        task.click.assert_not_called()

    def test_purchase_confirmation_ignores_a_single_disappearing_frame(self):
        task = BaseTask.__new__(BaseTask)
        task.screenshot = Mock()
        task.click = Mock(return_value=True)
        visible = Mock(side_effect=[True, False, True, False, False])
        self.assertTrue(task.ui_click_until_disappear(
            ChessAssets.C_SHIKIGAMI_1, click_target=ChessAssets.C_SHIKIGAMI_1,
            visible=visible, interval=0, timeout=1, confirm_frames=2,
        ))
        self.assertEqual(task.screenshot.call_count, 5)
        self.assertEqual(task.click.call_count, 2)


if __name__ == '__main__':
    unittest.main()
