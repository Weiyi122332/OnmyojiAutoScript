"""Reuse identical checks within one screenshot while keeping clicks and ROI edits fresh."""

import copy
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.atom.image import RuleImage
from module.device.device import Device
from tasks.base_task import BaseTask


class ImageRecognitionCacheTest(unittest.TestCase):
    def setUp(self):
        self.device = Device.__new__(Device)
        self.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.device.image_frame_id = 'frame-1'
        self.device.reset_image_batch_cache('frame-1')
        self.task = BaseTask.__new__(BaseTask)
        self.task.device = self.device
        self.task.interval_timer = {}
        self.rule = RuleImage(
            roi_front=(0, 0, 30, 40), roi_back=(0, 0, 200, 100),
            threshold=0.8, method='Template matching', file='test-template.png',
        )
        self.result = {'matched': True, 'score': 0.95, 'roi_front': [10, 20, 30, 40]}
        self.client = Mock()
        self.client.match_rule.return_value = self.result
        self.client.match_many.return_value = [self.result]
        for name in ('module.atom.image.get_image_client', 'tasks.base_task.get_image_client'):
            patcher = patch(name, return_value=self.client)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_repeated_checks_and_click_copies_share_result_and_coordinates(self):
        self.assertTrue(self.task.appear(self.rule))
        click_copy = copy.copy(self.rule)
        click_copy.profile = 'High'
        click_copy.roi_front = [99, 99, 30, 40]

        self.assertTrue(self.task.appear(self.rule))
        self.assertTrue(self.task.appear(click_copy))

        self.client.match_rule.assert_called_once()
        self.assertEqual(click_copy.roi_front, [10, 20, 30, 40])

    def test_misses_are_also_reused(self):
        self.client.match_rule.return_value = {'matched': False, 'score': 0.2, 'roi_front': None}
        self.assertFalse(self.task.appear(self.rule))
        self.assertFalse(self.task.appear(self.rule))
        self.client.match_rule.assert_called_once()

    def test_new_screenshot_and_control_invalidation_require_new_matches(self):
        self.task.appear(self.rule)
        self.device._invalidate_image_batch_cache()
        self.task.appear(self.rule)
        self.device.image_frame_id = 'frame-2'
        self.device.reset_image_batch_cache('frame-2')
        self.task.appear(self.rule)
        self.assertEqual(self.client.match_rule.call_count, 3)

    def test_modified_recognition_parameters_do_not_reuse_old_result(self):
        changes = (
            ('roi_back', [1, 2, 180, 90]),
            ('threshold', 0.9),
            ('file', 'different-template.png'),
            ('method', 'Multi-scale template matching'),
            ('scale_range', (0.8, 1.1)),
            ('scale_step', 0.05),
        )
        for attribute, value in changes:
            with self.subTest(parameter=attribute):
                rule = copy.copy(self.rule)
                self.device.reset_image_batch_cache('frame-1')
                self.client.match_rule.reset_mock()
                self.task.appear(rule)
                setattr(rule, attribute, value)
                self.task.appear(rule)
                self.assertEqual(self.client.match_rule.call_count, 2)

    def test_sift_front_geometry_is_part_of_recognition_parameters(self):
        self.rule.method = 'Sift Flann'
        self.task.appear(self.rule)
        self.rule.roi_front = [10, 20, 50, 60]
        self.task.appear(self.rule)
        self.assertEqual(self.client.match_rule.call_count, 2)

    def test_explicit_threshold_does_not_pollute_default_result(self):
        self.task.appear(self.rule)
        self.client.match_rule.return_value = {'matched': False, 'score': 0.95, 'roi_front': None}
        self.assertFalse(self.task.appear(self.rule, threshold=0.99))
        self.assertTrue(self.task.appear(self.rule))
        self.assertEqual(self.client.match_rule.call_count, 2)
        self.assertEqual(self.client.match_rule.call_args.kwargs['threshold'], 0.99)

    def test_prefetch_deduplicates_identical_rules_and_populates_single_check_cache(self):
        equivalent = copy.copy(self.rule)
        self.task.prepare_appear_cache([self.rule, equivalent])
        self.assertTrue(self.task.appear(self.rule))
        self.assertTrue(self.task.appear(equivalent))
        self.client.match_rule.assert_not_called()
        self.assertEqual(len(self.client.match_many.call_args.kwargs['rules_data']), 1)

    def test_unregistered_images_are_not_cached(self):
        self.device.image_frame_id = None
        self.device.reset_image_batch_cache()
        self.task.appear(self.rule)
        self.task.appear(self.rule)
        self.assertEqual(self.client.match_rule.call_count, 2)


if __name__ == '__main__':
    unittest.main()
