"""狐栖归处庭院事务入口及皮肤切换回退。"""

import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tasks.Component.Costume import costume_base
from tasks.Component.Costume.assets import CostumeAssets
from tasks.Component.Costume.config import MainType
from tasks.Component.Costume.costume_base import CostumeBase
from tasks.DailyTrifles.assets import DailyTriflesAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.page import page_main


class CourtyardAffairsCostumeTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(costume_base._default_main_assets, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.task = CostumeBase()
        self.task.I_CHECK_MAIN = deepcopy(GameUiAssets.I_CHECK_MAIN)
        self.task.I_ENTER_COURTYARD_AFFAIRS = deepcopy(
            DailyTriflesAssets.I_ENTER_COURTYARD_AFFAIRS)
        self.default_entry = deepcopy(self.task.I_ENTER_COURTYARD_AFFAIRS)
        self.task.device = SimpleNamespace(invalidate_image_batch_cache=Mock())

    def frame(self, shift=(0, 0)):
        rule = CostumeAssets.I_ENTER_COURTYARD_AFFAIRS_17
        fixture = Path(__file__).parent / 'fixtures' / 'courtyard_affairs' / 'main17_entry.png'
        crop = cv2.cvtColor(cv2.imdecode(np.fromfile(fixture, dtype=np.uint8),
                                       cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        x, y, w, h = rule.roi_back
        x, y = x + shift[0], y + shift[1]
        frame[y:y+h, x:x+w] = crop
        return frame

    def select_fox(self):
        self.task.check_costume_main([MainType.COSTUME_MAIN_17])
        return self.task.I_ENTER_COURTYARD_AFFAIRS

    def test_fox_entry_matches_at_actual_position(self):
        frame = self.frame()
        self.assertFalse(self.default_entry.template_match(frame))
        rule = self.select_fox()
        self.assertTrue(rule.template_match(frame))
        self.assertEqual(tuple(rule.roi_front), (478, 451, 25, 30))

    def test_entry_movement_inside_skin_search_area(self):
        rule = self.select_fox()
        self.assertTrue(rule.template_match(self.frame(shift=(20, -15))))
        self.assertEqual(tuple(rule.roi_front), (498, 436, 25, 30))

    def test_default_skin_restores_original_entry(self):
        self.select_fox()
        self.task.check_costume_main([MainType.COSTUME_MAIN])
        rule = self.task.I_ENTER_COURTYARD_AFFAIRS
        self.assertEqual(rule.file, self.default_entry.file)
        self.assertEqual(rule.roi_back, self.default_entry.roi_back)

    def test_other_skin_does_not_keep_fox_entry(self):
        self.select_fox()
        self.task.check_costume_main([MainType.COSTUME_MAIN_1])
        rule = self.task.I_ENTER_COURTYARD_AFFAIRS
        self.assertEqual(rule.file, self.default_entry.file)
        self.assertEqual(rule.roi_back, self.default_entry.roi_back)

    def test_random_detection_switches_to_fox_entry(self):
        self.task.check_costume_main([MainType.COSTUME_MAIN])
        self.task.check_costume_main([MainType.COSTUME_MAIN, MainType.COSTUME_MAIN_17])
        self.task.device.image = self.frame()
        self.task.device.image_frame_id = 'fox-frame'
        self.task.device.get_image_batch_cache = Mock(return_value={
            'matched': True, 'roi_front': [836, 148, 71, 48],
        })
        self.assertTrue(self.task.detect_random_main_costume())
        self.assertEqual(self.task.current_main_type, MainType.COSTUME_MAIN_17)
        self.assertTrue(self.task.I_ENTER_COURTYARD_AFFAIRS.template_match(self.frame()))
        self.task.device.invalidate_image_batch_cache.assert_called()

    def test_navigation_uses_the_same_updated_entry_rule(self):
        shared = DailyTriflesAssets.I_ENTER_COURTYARD_AFFAIRS
        original = CostumeBase._clone_rule_image(shared)
        self.addCleanup(self.task.replace_img, 'I_ENTER_COURTYARD_AFFAIRS', original)
        self.task.I_ENTER_COURTYARD_AFFAIRS = shared
        transition = next(t for t in page_main.transitions
                          if t.destination.key == 'page_courtyard_affairs')
        self.assertIs(transition.action, shared)
        self.select_fox()
        self.assertTrue(transition.action.template_match(self.frame()))
        self.assertEqual(tuple(transition.action.roi_front), (478, 451, 25, 30))


if __name__ == '__main__':
    unittest.main()
