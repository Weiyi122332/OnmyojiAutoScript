"""Quick preset selections vary their landing point without leaving the target row."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.atom.click import RuleClick
from module.exception import ScriptError
from tasks.Component.QuickLoadout.config import QuickLoadoutConfig, QuickLoadoutMode
from tasks.MetaDemon.boss_battle import BossBattle


class MetaDemonRandomClickTests(unittest.TestCase):
    def setUp(self):
        random_state = np.random.get_state()
        self.addCleanup(np.random.set_state, random_state)
        np.random.seed(20261112)
        RuleClick.reset_task_points()
        self.addCleanup(RuleClick.reset_task_points)
        sleeper = patch('tasks.MetaDemon.quick_loadout.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def make_task(self, panel=(496, 224, 553, 387), screen_size=(1280, 720)):
        task = BossBattle.__new__(BossBattle)
        task.device = SimpleNamespace(click=Mock())
        task.screenshot = Mock()
        task.swipe = Mock()
        task.appear = Mock(return_value=False)
        layout = task._quick_loadout_layout_at(panel, reference_size=task.PANEL_SIZE, screen_size=screen_size)
        return task, layout

    def points(self, task, control):
        return [(call.kwargs['x'], call.kwargs['y']) for call in task.device.click.call_args_list
                if call.kwargs['control_name'] == control]

    def assert_varied_in_area(self, points, area):
        self.assertGreater(len(set(points)), 1, 'Selection still uses a fixed coordinate')
        left, top, width, height = area
        for x, y in points:
            self.assertTrue(left <= x < left + width and top <= y < top + height,
                            f'{(x, y)} leaves target area {area}')

    def test_personal_group_numbers_skip_rental_and_stay_on_the_same_row(self):
        # Row centers from the verified 1280x720 layout; the final group is clipped.
        centers = [255, 306, 357, 408, 458, 509, 560, 594]
        for rental_visible in (False, True):
            for number in range(1, 8):
                with self.subTest(rental=rental_visible, number=number):
                    task, layout = self.make_task()
                    task.appear.return_value = rental_visible
                    config = QuickLoadoutConfig(mode=QuickLoadoutMode.NUMBER, group_number=number)
                    for _ in range(20):
                        self.assertTrue(task._select_group(layout, config))
                    points = self.points(task, 'QUICK_LOADOUT_GROUP')
                    center = centers[number - 1 + int(rental_visible)]
                    self.assertEqual(len(points), 20)
                    self.assert_varied_in_area(points, (502, center - 12, 108, 24))
                    self.assert_varied_in_area(points, layout.group_ocr.roi)
                    if rental_visible and number == 7:
                        self.assert_varied_in_area(points, (502, 588, 108, 15))
                    task.swipe.assert_not_called()

    def test_named_and_rental_groups_also_use_random_points(self):
        for group, preset, row_y in [('自定义分组', '任意队伍', 458),
                                    ('队伍租借', '群体', 255),
                                    ('队伍租借', '单体', 255),
                                    ('队伍租借', '普攻', 255)]:
            with self.subTest(group=group, preset=preset):
                task, layout = self.make_task()
                task.appear.return_value = True
                task._find_name_y = Mock(return_value=(row_y, 1.0))
                config = QuickLoadoutConfig(mode=QuickLoadoutMode.OCR, group_name=group, preset_name=preset)
                for _ in range(20):
                    self.assertTrue(task._select_group(layout, config))
                points = self.points(task, 'QUICK_LOADOUT_GROUP')
                self.assertEqual(len(points), 20)
                self.assert_varied_in_area(points, (502, row_y - 12, 108, 24))

    def test_deploy_selects_preset_in_a_random_area_before_clicking_fight(self):
        for row_y in (249, 345, 441, 537):
            with self.subTest(row=row_y):
                task, layout = self.make_task()
                task._quick_loadout_panel_visible = Mock(side_effect=[True, False] * 20)
                task._quick_loadout_fight = Mock(return_value=RuleClick(
                    roi_front=(762, 557, 108, 36), roi_back=(762, 557, 108, 36),
                    name='PRESET_FIGHT', profile='High',
                ))
                for _ in range(20):
                    self.assertTrue(task._deploy_quick_loadout(
                        layout, task.F_QUICK_LOADOUT_FRAME, row_y, equip_soul=True,
                    ))
                calls = task.device.click.call_args_list
                self.assertEqual([call.kwargs['control_name'] for call in calls],
                                 ['QUICK_LOADOUT_PRESET', 'PRESET_FIGHT'] * 20)
                points = self.points(task, 'QUICK_LOADOUT_PRESET')
                self.assert_varied_in_area(points, (760, row_y - 12, 80, 24))
                self.assert_varied_in_area(points, layout.preset_ocr.roi)

    def test_scaled_and_clipped_rows_stay_inside_the_visible_list(self):
        for panel, screen in (((248, 112, 277, 194), (640, 360)),
                              ((50, 60, 1110, 776), (1500, 1000))):
            for group in (False, True):
                task, layout = self.make_task(panel, screen)
                bounds = layout.group_ocr.roi if group else layout.preset_ocr.roi
                for row_y in (bounds[1], bounds[1] + bounds[3] - 1):
                    with self.subTest(panel=panel, group=group, row=row_y):
                        task.device.click.reset_mock()
                        for _ in range(20):
                            task._click_loadout_row(layout, row_y, group=group)
                        points = self.points(task, 'QUICK_LOADOUT_GROUP' if group else 'QUICK_LOADOUT_PRESET')
                        self.assert_varied_in_area(points, bounds)
                        self.assert_varied_in_area(points, layout.panel)

    def test_offscreen_target_is_an_error_without_a_click(self):
        for group in (False, True):
            with self.subTest(group=group):
                task, layout = self.make_task()
                with self.assertRaisesRegex(ScriptError, '不在可见范围内'):
                    task._click_loadout_row(layout, 100, group=group)
                task.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
