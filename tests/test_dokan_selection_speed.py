"""Stable frames may be screened quickly; scrolling frames must never be used."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tasks.Dokan.script_task import ScriptTask


class DokanListStabilityTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.capture_duration = 0.0
        self.capture_times = []
        self.frames = []
        self.frame_index = 0
        self.task = ScriptTask.__new__(ScriptTask)
        self.task.I_RIGHTPAD_POINT_BOUNTY = copy.copy(ScriptTask.I_RIGHTPAD_POINT_BOUNTY)
        self.task.I_RIGHTPAD_POINT_BOUNTY.roi_front = list(self.task.I_RIGHTPAD_POINT_BOUNTY.roi_front)
        self.task.device = SimpleNamespace(image=None, image_frame_id=None)
        self.task.screenshot = Mock(side_effect=self.screenshot)
        self.client = SimpleNamespace(match_dynamic_template=Mock(side_effect=self.match_template))
        for target, kwargs in (
            ('module.atom.animate.get_image_client', {'return_value': self.client}),
            ('tasks.Dokan.script_task.time.monotonic', {'side_effect': lambda: self.now}),
            ('tasks.Dokan.script_task.sleep', {'side_effect': self.sleep}),
            ('tasks.Dokan.script_task.logger', {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        generator = np.random.default_rng(42)
        self.images = []
        x, y, w, h = self.task.I_RIGHTPAD_POINT_BOUNTY.roi_back
        for _ in range(3):
            image = np.zeros((720, 1280, 3), dtype=np.uint8)
            image[y:y + h, x:x + w] = generator.integers(0, 256, (h, w, 3), dtype=np.uint8)
            self.images.append(image)

    def screenshot(self):
        self.capture_times.append(self.now)
        self.now += self.capture_duration
        self.task.device.image = self.frames[min(self.frame_index, len(self.frames) - 1)]
        self.task.device.image_frame_id = f'frame-{self.frame_index}'
        self.frame_index += 1

    def sleep(self, seconds):
        self.now += seconds

    @staticmethod
    def match_template(template, image, roi_back, threshold, **kwargs):
        x, y, w, h = roi_back
        score = float(cv2.matchTemplate(image[y:y + h, x:x + w], template,
                                       cv2.TM_CCOEFF_NORMED)[0, 0])
        matched = score > threshold
        return {'matched': matched, 'score': score,
                'roi_front': list(roi_back) if matched else None}

    def test_static_list_becomes_ready_in_point_six_seconds(self):
        self.frames = [self.images[0]]
        self.assertTrue(self.task._wait_for_dokan_list_ready())
        self.assertAlmostEqual(self.now - 1000, 0.6)
        self.assertEqual(len(self.capture_times), 3)
        for previous, current in zip(self.capture_times, self.capture_times[1:]):
            self.assertAlmostEqual(current - previous, 0.3)

    def test_scroll_is_accepted_only_after_two_consecutive_stable_comparisons(self):
        self.frames = self.images + [self.images[-1], self.images[-1]]
        self.assertTrue(self.task._wait_for_dokan_list_ready())
        self.assertEqual(len(self.capture_times), 5)
        self.assertAlmostEqual(self.now - 1000, 1.2)
        self.assertIs(self.task.device.image, self.images[-1])

    def test_one_stable_comparison_between_movements_is_not_enough(self):
        self.frames = [self.images[0], self.images[0], self.images[1],
                       self.images[1], self.images[2]]
        self.assertFalse(self.task._wait_for_dokan_list_ready())
        self.assertAlmostEqual(self.now - 1000, 1.5)

    def test_capture_past_deadline_cannot_provide_a_ready_frame(self):
        self.frames = [self.images[0]]
        self.capture_duration = 2.0
        self.assertFalse(self.task._wait_for_dokan_list_ready())
        self.client.match_dynamic_template.assert_not_called()

    def test_capture_error_propagates_instead_of_using_a_stale_frame(self):
        self.task.screenshot.side_effect = RuntimeError('capture failed')
        with self.assertRaisesRegex(RuntimeError, 'capture failed'):
            self.task._wait_for_dokan_list_ready()


if __name__ == '__main__':
    unittest.main()
