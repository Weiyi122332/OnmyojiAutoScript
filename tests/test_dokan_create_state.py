"""Dojo selection requires an existing dojo or confirmed successful creation."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tasks.Dokan.script_task import DokanNotStartedError, ScriptTask


class DokanCreationTest(unittest.TestCase):
    def make_task(self, disabled=False, unknown=False, confirmation=False):
        enabled = copy.copy(ScriptTask.I_RYOU_DOKAN_CREATE_DOKAN)
        enabled.roi_front = list(enabled.roi_front)
        grey = copy.copy(ScriptTask.I_RYOU_DOKAN_HAVE_DOKAN)
        grey.roi_front = list(grey.roi_front)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        if not unknown:
            template = grey.image if disabled else enabled.image
            x, y, w, h = enabled.roi_front
            image[y:y + h, x:x + w] = template
        confirm = object()
        selection = object()
        task = SimpleNamespace(
            I_RYOU_DOKAN_CREATE_DOKAN=enabled,
            I_RYOU_DOKAN_HAVE_DOKAN=grey,
            I_RYOU_DOKAN_CREATE_DOKAN_ENSURE=confirm,
            I_RYOU_DOKAN_FINDING_DOKAN=selection,
            I_RYOU_DOKAN_FOUND_DOKAN=object(),
            I_RYOU_DOKAN_CENTER_TOP=object(),
            device=SimpleNamespace(image=image),
            screenshot=Mock(),
            click=Mock(),
            wait_until_appear=Mock(return_value=True),
            creat_dokan=Mock(return_value=True),
            config=SimpleNamespace(dokan=SimpleNamespace(
                dokan_config=SimpleNamespace(
                    try_start_dokan=True, skip_owner_battle=True,
                    find_dokan_score=4.6,
                ),
                attack_count_config=SimpleNamespace(daily_attack_count=2),
            )),
            found_dokan_cnt=0,
            second_dokan_ready=False,
            update_remain_attack_count=Mock(return_value=2),
            find_dokan=Mock(return_value=True),
        )

        def appear(item):
            if item is selection:
                return True
            if item is confirm:
                return confirmation
            return item.template_match(task.device.image)

        task.appear = appear
        task.ensure_dokan_created = lambda: ScriptTask.ensure_dokan_created(task)
        return task

    def test_grey_button_skips_creation_even_when_enabled_template_matches(self):
        task = self.make_task(disabled=True)
        # Real resources have the same outline and pass both 0.8 thresholds.
        self.assertTrue(task.appear(task.I_RYOU_DOKAN_CREATE_DOKAN))
        self.assertTrue(task.ensure_dokan_created())
        task.click.assert_not_called()
        task.wait_until_appear.assert_not_called()
        task.creat_dokan.assert_not_called()
        task.screenshot.assert_called_once()

    def test_enabled_button_creates_instead_of_matching_grey_outline(self):
        task = self.make_task()
        self.assertTrue(task.appear(task.I_RYOU_DOKAN_HAVE_DOKAN))
        self.assertTrue(task.ensure_dokan_created())
        task.click.assert_called_once_with(task.I_RYOU_DOKAN_CREATE_DOKAN)
        task.wait_until_appear.assert_called_once_with(
            task.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE, True, 3)
        task.creat_dokan.assert_called_once()

    def test_grey_button_tolerates_screenshot_compression(self):
        task = self.make_task(disabled=True)
        ok, encoded = cv2.imencode('.jpg', task.device.image,
                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
        self.assertTrue(ok)
        task.device.image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        self.assertTrue(task.ensure_dokan_created())
        task.click.assert_not_called()

    def test_dimmed_coloured_button_still_requires_creation(self):
        task = self.make_task()
        task.device.image = (task.device.image * 0.65).astype(np.uint8)
        self.assertTrue(task.ensure_dokan_created())
        task.creat_dokan.assert_called_once()

    def test_existing_confirmation_is_completed(self):
        task = self.make_task(unknown=True, confirmation=True)
        self.assertTrue(task.ensure_dokan_created())
        task.click.assert_not_called()
        task.creat_dokan.assert_called_once()

    def test_two_unanswered_clicks_do_not_imply_creation(self):
        task = self.make_task()
        task.wait_until_appear.return_value = False
        self.assertFalse(task.ensure_dokan_created())
        self.assertEqual(task.click.call_count, 2)
        task.creat_dokan.assert_not_called()

    def test_unrecognized_state_stops_selection(self):
        task = self.make_task(unknown=True)
        with patch('tasks.Dokan.script_task.sleep'), self.assertRaises(DokanNotStartedError):
            ScriptTask.run_on_dokan_map(task)
        task.click.assert_not_called()
        task.find_dokan.assert_not_called()

    def test_failed_creation_stops_selection(self):
        task = self.make_task()
        task.creat_dokan.return_value = False
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.run_on_dokan_map(task)
        task.find_dokan.assert_not_called()

    def test_selection_starts_after_successful_creation(self):
        task = self.make_task()
        actions = []
        task.click.side_effect = lambda item: actions.append('click')
        task.creat_dokan.side_effect = lambda: actions.append('create') or True
        task.find_dokan.side_effect = lambda score: actions.append('select') or True
        ScriptTask.run_on_dokan_map(task)
        self.assertEqual(actions, ['click', 'create', 'select'])

    def test_grey_button_enters_selection_directly(self):
        task = self.make_task(disabled=True)
        ScriptTask.run_on_dokan_map(task)
        task.click.assert_not_called()
        task.creat_dokan.assert_not_called()
        task.find_dokan.assert_called_once_with(4.6)


if __name__ == '__main__':
    unittest.main()
