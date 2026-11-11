"""Summon selection must try later stars and retry unrecognized frames."""
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
from tasks.MetaDemon.config import BossType, MetaDemon
from tasks.MetaDemon.ticket_stars import recognize_summon_preview


class TicketSelectionChecks(unittest.TestCase):
    def test_missing_one_star_selects_two_after_transient_miss(self):
        task = object.__new__(BossBattle)
        task.conf = MetaDemon(meta_demon_config={'fire_sequence': '1 2 3 4 5'})
        task.State = BossBattle.State()
        task.cur_boss_type = None
        task.current_count = 0
        task.device = SimpleNamespace(image=object())
        task.I_MD_TWO_STARS = copy(task.I_MD_TWO_STARS)
        task.I_MD_TWO_STARS.roi_front = (460, 314, 66, 67)
        task.O_MD_TICKET_COUNTS = SimpleNamespace(roi=(345, 384, 591, 36), detect_and_ocr=Mock(return_value=[
            SimpleNamespace(ocr_text='持有：1', box=np.array([[111, 0], [180, 0], [180, 30], [111, 30]])),
        ]))
        state = {'frame': 0, 'selected': False, 'summoned': False}
        task.screenshot = lambda: state.update(frame=state['frame'] + 1)
        task.I_MD_CHECK_SELECTED = SimpleNamespace(roi_front=(490, 312, 6, 6))
        def appear(rule):
            if rule is task.I_MD_FIRE:
                return state['summoned']
            if rule is task.I_MD_GET_BOSS:
                return True
            if rule is task.I_MD_CHECK_SELECTED:
                return state['selected']
            return False
        task.appear = appear
        task.ticket_matches_star = Mock(side_effect=lambda rule, star: state['frame'] >= 3 and star == BossType.TWO_STARS)
        task.click = lambda *args, **kwargs: state.update(selected=True)
        task.appear_then_click = lambda *args, **kwargs: state.update(summoned=True) or True
        ticks = iter(i * 0.2 for i in range(1000))
        with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: next(ticks)):
            self.assertTrue(task.check_and_switch_ticket())
        self.assertFalse(task.State.done)
        self.assertEqual(task.cur_boss_type, BossType.TWO_STARS)
        attempted = {call.args[1] for call in task.ticket_matches_star.call_args_list}
        self.assertTrue({BossType.ONE_STAR, BossType.TWO_STARS, BossType.FIVE_STARS} <= attempted)

    def test_unrecognized_panel_does_not_end_task(self):
        task = object.__new__(BossBattle)
        task.conf = MetaDemon()
        task.State = SimpleNamespace(done=False)
        task.screenshot = Mock()
        task.appear = lambda rule: rule is task.I_MD_GET_BOSS
        task.ticket_matches_star = Mock(return_value=False)
        ticks = iter(range(1000))
        with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: next(ticks)):
            self.assertFalse(task.check_and_switch_ticket())
        self.assertFalse(task.State.done)
        self.assertGreater(task.screenshot.call_count, 1)

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

    def test_completed_targets_notify_once_without_the_old_run_limit(self):
        for attempts, expect_push in ((0, False), (51, True)):
            with self.subTest(attempts=attempts):
                task = object.__new__(BossBattle)
                task.conf = MetaDemon(meta_demon_config={'fire_sequence': '4 2', 'limit_count': 1,
                                                        'limit_time': '00:00:01'})
                task.State = BossBattle.State()
                task.total_count = 0
                task.config = SimpleNamespace(notifier=Mock(enable=True))
                task.before_run = Mock()
                task.goto_page = Mock()
                task.screenshot = Mock()
                task.get_current_page = Mock(return_value=pages.page_meta_demon_boss)
                task.set_next_run = Mock()

                def prepare(sequence):
                    if task.total_count == attempts:
                        task.stop_at_six_star_preview(BossType.SIX_STARS, sequence)
                        return False
                    return True

                def start(sequence):
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
                        title='超鬼王挑战完成', content='已打完目标星级的鬼王（4 星、2 星）',
                    )
                else:
                    task.config.notifier.push.assert_not_called()

    def test_lower_template_threshold_still_requires_correct_star_count(self):
        ticket = copy(MetaDemonAssets.I_MD_TWO_STARS)
        card = np.array(Image.open(ticket.file).convert('RGB'))
        x, y, w, h = ticket.roi_front
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[y:y+h, x:x+w] = card
        task = object.__new__(BossBattle)
        task.device = SimpleNamespace(image=image, image_frame_id='offline')
        task.appear = Mock(return_value=True)
        self.assertTrue(task.ticket_matches_star(ticket, BossType.TWO_STARS))
        self.assertEqual(ticket.threshold, 0.8)
        ticket.match_all_any = Mock(return_value=[])
        task.appear = Mock(return_value=True)
        self.assertFalse(task.ticket_matches_star(ticket, BossType.ONE_STAR))


if __name__ == '__main__':
    unittest.main()
