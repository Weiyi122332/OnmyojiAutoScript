"""Verify the main-page summon path and its star preview."""
from copy import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.exception import TaskEnd
from tasks.MetaDemon import page as pages
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import BossType
from tasks.MetaDemon.ticket_stars import recognize_summon_preview


class SummonChecks(unittest.TestCase):
    def make_task(self, frames):
        task = object.__new__(BossBattle)
        task.State = BossBattle.State()
        task.State.synthesis_done = True
        task.cur_boss_type = None
        task._current_boss_attempts = 2
        task.check_fatigue = Mock(return_value=True)
        state = {'index': -1, 'time': 0}
        controls = {
            task.I_MD_FIRE: 'fire', task.I_MD_SETTLING: 'settling',
            task.I_MD_SUMMON_BOSS: 'summon', task.I_MD_SWITCH_TICKET: 'queue',
            task.I_MD_GET_BOSS: 'panel', task.I_MD_TICKET_EMPTY: 'empty',
            task.I_MD_CLOSE_POPUP: 'close',
        }
        clicks = []

        def frame():
            return frames[min(state['index'], len(frames) - 1)]

        def screenshot():
            state['index'] += 1
            state['time'] += 1

        def appear(rule):
            return frame().get(controls[rule], False)

        def click(rule, **kwargs):
            if not appear(rule):
                return False
            clicks.append((state['index'], rule))
            return True

        task.screenshot = screenshot
        task.appear = appear
        task.appear_then_click = click
        task.next_summon_star = lambda: frame().get('preview')
        time_patch = patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: state['time'])
        return task, clicks, time_patch

    def test_six_stars_use_the_main_button_and_reset_the_attempt_count(self):
        task, clicks, clock = self.make_task([
            {'preview': BossType.SIX_STARS, 'summon': True, 'queue': True},
            {'fire': True},
        ])
        with clock:
            self.assertTrue(task.summon_boss())
        self.assertEqual(task.cur_boss_type, BossType.SIX_STARS)
        self.assertEqual(task._current_boss_attempts, 0)
        self.assertEqual(clicks, [(0, task.I_MD_SUMMON_BOSS)])

    def test_queue_changes_during_confirmation_without_a_second_summon(self):
        first = {'preview': BossType.FIVE_STARS, 'summon': True}
        later = {'preview': BossType.SIX_STARS, 'summon': True}
        task, clicks, clock = self.make_task([first, *[later] * 4, {'fire': True}])
        with clock:
            self.assertTrue(task.summon_boss())
        self.assertEqual(task.cur_boss_type, BossType.FIVE_STARS)
        self.assertEqual(clicks, [(0, task.I_MD_SUMMON_BOSS)])

    def test_home_button_retries_if_same_preview_remains(self):
        same = {'preview': BossType.THREE_STARS, 'summon': True}
        task, clicks, clock = self.make_task([*[same] * 4, {'fire': True}])
        with clock:
            self.assertTrue(task.summon_boss())
        self.assertEqual(clicks, [(0, task.I_MD_SUMMON_BOSS), (3, task.I_MD_SUMMON_BOSS)])

    def test_unknown_existing_boss_cannot_start_a_battle(self):
        task, clicks, clock = self.make_task([{'fire': True}])
        with clock:
            self.assertFalse(task.summon_boss())
        self.assertFalse(task.start_battle())
        self.assertFalse(task.State.done)
        self.assertEqual(clicks, [])

    def test_preview_missing_checks_empty_marker_without_summoning(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                task, clicks, clock = self.make_task([
                    {'queue': True}, {'panel': True, 'empty': empty, 'close': True},
                ])
                with clock:
                    self.assertFalse(task.summon_boss())
                self.assertEqual(task.State.done, empty)
                self.assertEqual([control for _, control in clicks],
                                 [task.I_MD_SWITCH_TICKET, task.I_MD_CLOSE_POPUP])

    def test_home_preview_requires_ordered_illuminated_slots(self):
        area = (1114, 496, 144, 38)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for index in range(6):
            x = 1063 + 8 * index
            frame[530:538, x + 1:x + 6] = (255, 154, 24)
        self.assertEqual(recognize_summon_preview(frame, area), 6)
        frame[530:538, 1080:1112] = (180, 179, 176)
        self.assertEqual(recognize_summon_preview(frame, area), 2)
        self.assertEqual(recognize_summon_preview(frame // 4, area), 2)
        frame[530:538, 1096:1101] = (255, 154, 24)
        self.assertIsNone(recognize_summon_preview(frame, area))

    def test_completed_queue_notifies_once_without_an_attempt_limit(self):
        for attempts, expect_push in ((0, False), (51, True)):
            with self.subTest(attempts=attempts):
                task = object.__new__(BossBattle)
                task.State = BossBattle.State()
                task.total_count = 0
                task.config = SimpleNamespace(notifier=Mock(enable=True))
                task.before_run = Mock()
                task.goto_page = Mock()
                task.screenshot = Mock()
                task.get_current_page = Mock(return_value=pages.page_meta_demon_boss)
                task.set_next_run = Mock()

                def prepare():
                    if task.total_count == attempts:
                        task.State.done = True
                        return False
                    return True

                def start():
                    task.total_count += 1
                    return True

                task.check_and_prepare_battle = Mock(side_effect=prepare)
                task.start_battle = Mock(side_effect=start)
                with self.assertRaises(TaskEnd):
                    task.run()
                self.assertEqual(task.total_count, attempts)
                task.set_next_run.assert_called_once_with(task='MetaDemon', success=True)
                if expect_push:
                    task.config.notifier.push.assert_called_once_with(
                        title='超鬼王挑战完成', content='已打完召唤队列中的鬼王',
                    )
                else:
                    task.config.notifier.push.assert_not_called()

    def test_synthesis_still_verifies_the_card_star_count(self):
        ticket = copy(MetaDemonAssets.I_MD_SYNTHESIS_TWO_STAR)
        card = np.array(Image.open(ticket.file).convert('RGB'))
        x, y, width, height = ticket.roi_front
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[y:y + height, x:x + width] = card
        task = object.__new__(BossBattle)
        task.device = SimpleNamespace(image=frame, image_frame_id='offline')
        task.appear = Mock(return_value=True)
        ticket.match_all_any = Mock(return_value=[])
        self.assertTrue(task.ticket_matches_star(ticket, BossType.TWO_STARS, synthesis=True))
        self.assertFalse(task.ticket_matches_star(ticket, BossType.ONE_STAR, synthesis=True))
