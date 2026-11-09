"""Summon selection must try later stars and retry unrecognized frames."""
from copy import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import BossType, MetaDemon


class TicketSelectionChecks(unittest.TestCase):
    def test_missing_one_star_selects_two_after_transient_miss(self):
        task = object.__new__(BossBattle)
        task.conf = MetaDemon(meta_demon_config={'fire_sequence': '1 2 3 4 5'})
        task.State = SimpleNamespace(done=False)
        task.cur_boss_type = None
        task.current_count = 0
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
