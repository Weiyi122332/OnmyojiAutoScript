import unittest
from copy import deepcopy
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, call, patch

import numpy as np
from PIL import Image

from module.exception import GameStuckError, TaskEnd
from tasks.DemonEncounter.assets import DemonEncounterAssets
from tasks.DemonEncounter.config import DemonEncounter
from tasks.DemonEncounter.script_task import ScriptTask
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.page import page_demon_encounter, page_main, page_shikigami_records, page_town
from tasks.GameUi.registry import PageRegistry
from tasks.GameUi.session import NavigatorSession


class DemonEncounterNavigationTest(unittest.TestCase):
    def setUp(self):
        self.task = ScriptTask.__new__(ScriptTask)

    def test_search_button_is_recognized_after_leaving_full_boss(self):
        fixture = Path(__file__).parent / 'fixtures' / 'demon_encounter' / 'full_boss_return_button.png'
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with Image.open(fixture) as image:
            frame[620:720, 875:975] = np.asarray(image.convert('RGB'))
        button = deepcopy(DemonEncounterAssets.I_DE_BOSS_BEST)

        self.assertTrue(button.template_match(frame))
        x, y, width, height = button.roi_front
        self.assertGreaterEqual(x, 900)
        self.assertGreaterEqual(y, 643)
        self.assertLessEqual(x + width, 945)
        self.assertLessEqual(y + height, 694)

    def test_town_lantern_and_back_link_the_current_map_directly(self):
        PageRegistry.load_all_pages()
        self.task.navigator = NavigatorSession(task_category='demon_encounter')
        self.task.navigator.bootstrap(PageRegistry.all())
        town = self.task.navigator.resolve_page(page_town)
        encounter = self.task.navigator.resolve_page(page_demon_encounter)
        self.task.appear = Mock(side_effect=lambda rule: rule is GameUiAssets.I_CHECK_DEMON_ENCOUNTER)

        self.assertTrue(self.task.match_page_once(encounter))
        self.assertEqual([edge.key for edge in self.task._build_path(town, encounter)],
                         ['page_town->page_demon_encounter'])
        self.assertEqual([edge.key for edge in self.task._build_path(encounter, town)],
                         ['page_demon_encounter->page_town'])

    def test_direct_entry_preserves_task_order(self):
        events = Mock()
        self.task.config = SimpleNamespace(demon_encounter=DemonEncounter(demon_soul_config={'enable': True}))
        self.task.check_time = events.check_time
        self.task.checkout_soul = events.checkout_soul
        self.task.goto_page = events.goto_page
        self.task._check_challenge_count = events.check_count
        self.task.execute_lantern = events.execute_lantern
        self.task.execute_boss = events.execute_boss
        self.task.set_next_run = events.set_next_run
        events.check_time.return_value = True
        events.check_count.return_value = True

        with self.assertRaises(TaskEnd):
            self.task.run()

        self.assertEqual(events.mock_calls, [
            call.check_time(),
            call.goto_page(page_shikigami_records),
            call.checkout_soul(),
            call.goto_page(page_demon_encounter),
            call.check_count(),
            call.execute_lantern(),
            call.execute_boss(),
            call.goto_page(page_main),
            call.set_next_run(task='DemonEncounter', success=True, finish=False),
        ])

    def test_failed_boss_search_reenters_the_map_from_town(self):
        self.task.device = Mock()
        self.task.screenshot = Mock()
        self.task.appear = Mock(return_value=False)
        self.task.appear_then_click = Mock(return_value=True)
        self.task.click = Mock()
        self.task._check_challenge_count = Mock(return_value=True)
        self.task.goto_page = Mock()

        with patch.object(ScriptTask, 'best_demon_enable', new_callable=PropertyMock, return_value=True), \
                patch('tasks.DemonEncounter.script_task.time') as clock:
            clock.monotonic.side_effect = count(step=6)
            with self.assertRaisesRegex(GameStuckError, 'Cannot enter best boss after 3 re-enter rounds'):
                self.task.execute_boss()

        self.assertEqual(self.task.goto_page.call_args_list, [
            call(page_town),
            call(page_demon_encounter),
        ] * 3)
        self.assertEqual(self.task._check_challenge_count.call_count, 3)
