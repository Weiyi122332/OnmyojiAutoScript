"""返回庭院优先使用一键入口，识别失败或未到达时保留原导航。"""

import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.navigator import GameUi
from tasks.GameUi.page_definition import Page
from tasks.GameUi.session import NavigatorSession


class ReturnMainNavigationTest(unittest.TestCase):
    def setUp(self):
        self.main, self.source, self.other = [
            Page(lambda task: False, key=key, name=key, category='global', register=False)
            for key in ('page_main', 'page_source', 'page_other')
        ]
        self.task = GameUi.__new__(GameUi)
        self.task.navigator = NavigatorSession(task_category='global')
        self.task.navigator.bootstrap([self.main, self.source, self.other])
        self.task.appear = Mock(return_value=False)
        self.task.click = Mock()
        self.task._wait_for_destination = Mock(return_value=True)
        self.task._ensure_main_scroll_open = Mock(return_value=False)
        self.task._run_hooks = Mock()
        self.task.close_unknown_pages = Mock(return_value=True)
        self.task._build_path = Mock(side_effect=lambda source, destination: [
            SimpleNamespace(key='normal_return', destination=destination)
        ])

        def advance(transition):
            self.task.navigator.current_page = transition.destination
            return True

        self.task._execute_transition = Mock(side_effect=advance)
        patcher = patch('tasks.GameUi.navigator.logger')
        patcher.start()
        self.addCleanup(patcher.stop)

    def navigate(self, frames, destination=None, **kwargs):
        self.task._refresh_current_page = Mock(side_effect=frames)
        return self.task.goto_page(destination or self.main, **kwargs)

    def test_shortcut_takes_priority_over_normal_path(self):
        self.task.appear.return_value = True
        self.assertTrue(self.navigate([self.source]))
        self.task.click.assert_called_once_with(self.task.I_RETURN_MAIN)
        self.task._wait_for_destination.assert_called_once_with(
            self.task.navigator.resolve_page(self.main), timeout=6.0,
        )
        self.task._build_path.assert_not_called()
        self.task.close_unknown_pages.assert_not_called()
        self.assertEqual(self.task.navigator.current_page, self.main)
        self.task._run_hooks.assert_called_once_with(self.main.on_enter_success)

    def test_missing_shortcut_keeps_normal_path(self):
        self.assertTrue(self.navigate([self.source]))
        self.task.click.assert_not_called()
        self.task._execute_transition.assert_called_once()

    def test_failed_shortcut_rechecks_page_and_uses_normal_path_once(self):
        self.task.appear.return_value = True
        self.task._wait_for_destination.return_value = False
        self.assertTrue(self.navigate([self.source, self.other]))
        self.task.click.assert_called_once_with(self.task.I_RETURN_MAIN)
        self.task.appear.assert_called_once_with(self.task.I_RETURN_MAIN)
        self.task._build_path.assert_called_once_with(
            self.other, self.task.navigator.resolve_page(self.main),
        )
        self.task._execute_transition.assert_called_once()

    def test_failed_shortcut_clears_cached_source(self):
        self.task.navigator.current_page = self.source
        self.task.appear.return_value = True
        self.task._wait_for_destination.return_value = False
        self.assertFalse(self.task._try_return_to_main(self.main))
        self.assertIsNone(self.task.navigator.current_page)

    def test_unknown_page_can_return_without_using_generic_closers(self):
        self.task.appear.return_value = True
        self.assertTrue(self.navigate([None]))
        self.task.click.assert_called_once_with(self.task.I_RETURN_MAIN)
        self.task.close_unknown_pages.assert_not_called()

    def test_unknown_page_without_shortcut_uses_existing_recovery(self):
        self.assertTrue(self.navigate([None, self.main]))
        self.task.close_unknown_pages.assert_called_once()
        self.task.click.assert_not_called()

    def test_already_in_courtyard_does_not_click_shortcut(self):
        self.assertTrue(self.navigate([self.main]))
        self.task.appear.assert_not_called()
        self.task.click.assert_not_called()

    def test_other_destination_does_not_use_courtyard_shortcut(self):
        self.assertTrue(self.navigate([self.source], destination=self.other))
        self.task.appear.assert_not_called()
        self.task.click.assert_not_called()

    def test_accepted_page_is_preserved(self):
        self.assertTrue(self.navigate([self.other], accepted_pages=(self.other,)))
        self.task.appear.assert_not_called()
        self.task.click.assert_not_called()
        self.assertEqual(self.task.navigator.current_page, self.other)


class ReturnMainRecognitionTest(unittest.TestCase):
    fixtures = Path(__file__).parent / 'fixtures' / 'game_ui'

    def test_live_headers_recognize_shortcut_at_its_actual_position(self):
        for name in ('exploration', 'bondling'):
            with self.subTest(page=name):
                frame = np.asarray(Image.open(self.fixtures / f'return_main_{name}_header.png').convert('RGB'))
                rule = deepcopy(GameUiAssets.I_RETURN_MAIN)
                self.assertTrue(rule.template_match(frame))
                self.assertEqual(rule.roi_front, [93, 17, 42, 39])

    def test_regular_back_button_is_not_a_courtyard_shortcut(self):
        frame = np.asarray(Image.open(self.fixtures / 'return_main_back_only_header.png').convert('RGB'))
        self.assertFalse(deepcopy(GameUiAssets.I_RETURN_MAIN).template_match(frame))


if __name__ == '__main__':
    unittest.main()
