"""移除式神活动玩法后的旧配置兼容与任务调度回归检查。"""

import unittest
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError

from module.config.config_model import ConfigModel
from module.exception import GamePageUnknownError, TaskEnd
from tasks.ActivityShikigami.config import ActivityShikigami, GeneralConfig
from tasks.ActivityShikigami.activities.fake_god import select_fakegod_target
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets as Assets
from tasks.ActivityShikigami.base_act import ActivityResourceNotEnough
from tasks.ActivityShikigami import page as pages
from tasks.ActivityShikigami.script_task import ScriptTask
from tasks.GameUi.session import NavigatorSession


class ActivityModesTest(unittest.TestCase):
    def test_saved_selection_keeps_remaining_modes_and_settings(self):
        conf = ActivityShikigami.model_validate({
            'general_config': {
                'task_sequence': ['探索', '爬塔', '大富翁', '伪神'],
                'throw_limit': 20, 'fakegod_limit': 4,
                'pass_limit': '10,2', 'ap_limit': 8,
            },
            'switch_soul_config': {
                'enable_switch_rich_man': True,
                'rich_man_group_team': 'invalid removed preset',
                'enable_switch_exp_encounter': True,
                'exp_encounter_group_team': 'invalid removed preset',
                'enable_switch_ap': True, 'ap_group_team': '2,3',
            },
            'rich_man_battle_conf': {'green_enable': True},
            'exp_encounter_battle_conf': {'green_enable': True},
            'ap_battle_conf': {'lock_team_enable': True},
        })
        self.assertEqual(conf.general_config.task_sequence_v, ['体力', '伪神/爬塔'])
        self.assertEqual(conf.general_config.ap_limit, 8)
        self.assertEqual(conf.switch_soul_config.ap_group_team, '2,3')
        self.assertTrue(conf.ap_battle_conf.lock_team_enable)
        conf.switch_soul_config.validate_switch_soul()
        saved = conf.model_dump(mode='json')
        self.assertNotIn('throw_limit', saved['general_config'])
        self.assertNotIn('pass_limit', saved['general_config'])
        self.assertNotIn('rich_man_battle_conf', saved)
        self.assertNotIn('exp_encounter_battle_conf', saved)

    def test_legacy_aliases_are_filtered_without_changing_retained_order(self):
        conf = GeneralConfig(
            task_sequence='EXP，rich_man;normal\nfake_god',
            ap_limit=5, fakegod_limit=2,
        )
        self.assertEqual(conf.task_sequence_v, ['体力', '伪神/爬塔'])

    def test_removed_only_selection_does_not_enable_other_modes(self):
        conf = GeneralConfig(
            task_sequence=['探索', '大富翁', 'pass'], ap_limit=5, fakegod_limit=2,
        )
        self.assertEqual(conf.task_sequence_v, [])

    def test_unknown_selection_still_reports_invalid_configuration(self):
        with self.assertRaises(ValidationError):
            GeneralConfig(task_sequence=['unknown activity'])

    def test_removed_legacy_task_cannot_enable_activity_scheduler(self):
        for task_name, field in (('RichMan', 'rich_man'), ('FlightChess', 'flight_chess')):
            with self.subTest(task=task_name):
                migrated = ConfigModel._migrate_renamed_tasks({
                    'running_task': task_name,
                    field: {'scheduler': {'enable': True}},
                })
                conf = ActivityShikigami.model_validate(migrated['activity_shikigami'])
                self.assertFalse(conf.scheduler.enable)
                self.assertEqual(migrated['running_task'], '')
                self.assertNotIn(field, migrated)

    def test_legacy_fakegod_still_preserves_schedule_and_battle_config(self):
        migrated = ConfigModel._migrate_renamed_tasks({
            'running_task': 'Fakegod',
            'fakegod': {
                'scheduler': {'enable': True},
                'general_climb': {'pass_limit': 7},
                'switch_soul_config': {
                    'enable_switch_pass': True, 'pass_group_team': '1,2',
                },
                'pass_battle_conf': {'green_enable': True},
            },
        })
        conf = ActivityShikigami.model_validate(migrated['activity_shikigami'])
        self.assertEqual(migrated['running_task'], 'ActivityShikigami')
        self.assertTrue(conf.scheduler.enable)
        self.assertEqual(conf.general_config.fakegod_limit, 7)
        self.assertEqual(conf.switch_soul_config.fakegod_group_team, '1,2')
        self.assertTrue(conf.fakegod_battle_conf.green_enable)

    def test_old_weekly_purchase_configuration_is_preserved(self):
        purchase = {'special_room': {'totem_pass': True}}
        migrated = ConfigModel._migrate_renamed_tasks({'rich_man': purchase})
        self.assertEqual(migrated['weekly_purchase'], purchase)

    def test_task_dispatches_only_retained_enabled_modes(self):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = ActivityShikigami(general_config=GeneralConfig(
            task_sequence=['探索', '爬塔', '大富翁', '伪神'],
            ap_limit=5, fakegod_limit=2,
        ))
        task.before_run = Mock()
        task.time_limit_reached = Mock(return_value=False)
        calls = Mock()
        task.run_fakegod = calls.fakegod
        task.run_climb = calls.climb
        task.finish_activity_task = calls.finish
        task.finish_activity_task.side_effect = TaskEnd
        with self.assertRaises(TaskEnd):
            task.run()
        self.assertEqual([item[0] for item in calls.mock_calls], ['climb', 'fakegod', 'finish'])
        task.run_climb.assert_called_once_with('ap')

    def test_ordered_activity_list_can_reorder_remove_and_clear(self):
        limits = {'ap_limit': 2, 'ap100_limit': 2, 'fakegod_limit': 2}
        conf = GeneralConfig(task_sequence=['百体', '伪神/爬塔', '体力'], **limits)
        self.assertEqual(conf.task_sequence_v, ['百体', '伪神/爬塔', '体力'])
        saved = conf.model_dump(mode='json')
        restored = GeneralConfig.model_validate(saved)
        self.assertEqual(restored.task_sequence_v, conf.task_sequence_v)
        saved['task_sequence'] = ['体力']
        deleted = GeneralConfig.model_validate(saved)
        self.assertEqual(deleted.task_sequence_v, ['体力'])
        self.assertEqual(deleted.ap100_limit, 2)
        self.assertEqual(deleted.fakegod_limit, 2)
        for value in ([], '', '[]'):
            with self.subTest(value=value):
                self.assertEqual(GeneralConfig(task_sequence=value, **limits).task_sequence_v, [])

    def test_ordered_list_deduplicates_aliases_without_sorting(self):
        conf = GeneralConfig(
            task_sequence='["刹那试炼", "伪神", "古迹演武", "百体", "首领"]',
            ap_limit=1, ap100_limit=1, boss_limit=0, fakegod_limit=1,
        )
        self.assertEqual(conf.model_dump(mode='json')['task_sequence'], ['百体', '伪神/爬塔', '体力', '首领'])
        self.assertEqual(conf.task_sequence_v, ['百体', '伪神/爬塔', '体力'])

    def test_retained_categories_dispatch_in_saved_order(self):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = ActivityShikigami(general_config=GeneralConfig(
            task_sequence=['首领', '百体', '伪神/爬塔', '体力'],
            ap_limit=1, ap100_limit=1, boss_limit=1, fakegod_limit=1,
        ))
        task.before_run = Mock()
        task.time_limit_reached = Mock(return_value=False)
        calls = Mock()
        task.run_fakegod = calls.fakegod
        task.run_climb = calls.climb
        task.finish_activity_task = calls.finish
        task.finish_activity_task.side_effect = TaskEnd
        with self.assertRaises(TaskEnd):
            task.run()
        self.assertEqual([(call[0], call.args) for call in calls.mock_calls], [
            ('climb', ('boss',)), ('climb', ('ap100',)), ('fakegod', ()),
            ('climb', ('ap',)), ('finish', ()),
        ])

    def test_api_uses_task_list_and_saves_edits_in_order(self):
        model = ConfigModel(activity_shikigami={'general_config': {'ap_limit': 1, 'ap100_limit': 1}})
        args = model.script_task('ActivityShikigami')['general_config']
        field = next(item for item in args if item['name'] == 'task_sequence')
        self.assertEqual(field['type'], 'task_list')
        self.assertEqual(field['maxItems'], 4)
        self.assertEqual(field['enumEnum'], ['体力', '百体', '首领', '伪神/爬塔'])
        with patch.object(ConfigModel, 'save'):
            for value in (['百体', '体力'], ['体力'], []):
                self.assertTrue(model.script_set_arg('ActivityShikigami', 'GeneralConfig', 'TaskSequence', value))
                stored = model.model_dump(mode='json')['activity_shikigami']['general_config']['task_sequence']
                self.assertEqual(stored, value)

    def test_current_activity_has_separate_direct_climb_routes(self):
        task = ScriptTask.__new__(ScriptTask)
        task.navigator = NavigatorSession(task_category=pages.page_act.category)
        task.navigator.bootstrap([
            pages.page_main, pages.page_act, pages.page_climb_ap,
            pages.page_climb_ap100, pages.page_fakegod_map, pages.page_fakegod_action,
        ])
        task.setup_climb_pages()
        task.setup_fakegod_pages()
        def route(source, destination):
            return task._build_path(
                task.navigator.resolve_page(source),
                task.navigator.resolve_page(destination),
            )
        for destination, entry in (
            (pages.page_climb_ap, Assets.I_TO_BATTLE_MAIN),
            (pages.page_climb_ap100, Assets.I_TO_BATTLE_AP100),
        ):
            with self.subTest(destination=destination.key):
                forward = route(pages.page_act, destination)
                self.assertEqual(len(forward), 1)
                self.assertEqual(forward[0].action, entry)
                self.assertEqual(len(route(destination, pages.page_act)), 1)
        forward = route(pages.page_act, pages.page_fakegod_action)
        self.assertEqual([edge.destination.key for edge in forward], [
            pages.page_fakegod_map.key, pages.page_fakegod_action.key,
        ])
        self.assertEqual(forward[-1].action, select_fakegod_target)
        backward = route(pages.page_fakegod_action, pages.page_act)
        self.assertEqual([edge.destination.key for edge in backward], [
            pages.page_fakegod_map.key, pages.page_act.key,
        ])

    def test_fakegod_map_shortcuts_reach_climb_without_selecting_a_battle_node(self):
        task = ScriptTask.__new__(ScriptTask)
        task.navigator = NavigatorSession(task_category=pages.page_act.category)
        task.navigator.bootstrap([
            pages.page_act, pages.page_climb_ap, pages.page_climb_ap100,
            pages.page_fakegod_map, pages.page_fakegod_action,
        ])
        # 体力/百体可以先于伪神执行，不依赖 setup_fakegod_pages()。
        task.setup_climb_pages()
        for destination, entry in (
            (pages.page_climb_ap, Assets.I_FG_MAP_TO_AP),
            (pages.page_climb_ap100, Assets.I_FG_MAP_TO_AP100),
        ):
            with self.subTest(destination=destination.key):
                source = task.navigator.resolve_page(pages.page_fakegod_map)
                target = task.navigator.resolve_page(destination)
                forward = task._build_path(source, target)
                self.assertEqual(len(forward), 1)
                self.assertEqual(forward[0].action, entry)
                backward = task._build_path(target, source)
                self.assertEqual(len(backward), 1)
                self.assertEqual(backward[0].action, task.I_UI_BACK_YELLOW)
                from_battle = task._build_path(
                    task.navigator.resolve_page(pages.page_fakegod_action), target,
                )
                self.assertEqual([edge.destination.key for edge in from_battle], [
                    pages.page_fakegod_map.key, destination.key,
                ])
                self.assertNotIn(select_fakegod_target, [edge.action for edge in from_battle])

    def test_removed_ticket_limits_do_not_disable_boss_and_current_modes(self):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = ActivityShikigami(general_config=GeneralConfig(
            pass_limit='20,10', boss_limit=5, ap_limit=3, ap100_limit=2,
        ))
        task.setup_climb_pages = Mock()
        task.time_limit_reached = Mock(return_value=False)
        task._run_climb_type = Mock()
        task.run_climb()
        self.assertEqual([call.args[0] for call in task._run_climb_type.call_args_list], ['ap', 'boss', 'ap100'])
        saved = task.conf.general_config.model_dump(mode='json')
        self.assertNotIn('pass_limit', saved)
        self.assertEqual(saved['boss_limit'], 5)

    def test_removed_configs_do_not_validate_or_reappear_when_saved(self):
        conf = ActivityShikigami.model_validate({
            'general_config': {
                'task_sequence': ['boss', 'pass', '百体', '体力', '伪神'],
                'pass_limit': 'obsolete invalid value', 'boss_limit': 6,
                'ap_limit': 7, 'ap100_limit': 3, 'fakegod_limit': 2,
            },
            'switch_soul_config': {
                'enable_switch_pass': True, 'pass_group_team': 'invalid',
                'enable_switch_boss_by_name': True, 'boss_group_team_name': '活动,首领',
                'enable_switch_ap100_by_name': True, 'ap100_group_team_name': '活动,百体',
            },
            'pass_battle_conf': {'preset_group': 'invalid'},
            'boss_battle_conf': {'battle_timeout': 120},
            'ap100_battle_conf': {'green_enable': True},
        })
        conf.switch_soul_config.validate_switch_soul()
        saved = conf.model_dump(mode='json')
        self.assertEqual(saved['general_config']['task_sequence'], ['首领', '百体', '体力', '伪神/爬塔'])
        self.assertEqual(conf.general_config.task_sequence_v, ['首领', '百体', '体力', '伪神/爬塔'])
        self.assertNotIn('pass_limit', saved['general_config'])
        self.assertNotIn('pass_battle_conf', saved)
        self.assertFalse(any('pass' in key for key in saved['switch_soul_config']))
        self.assertEqual(saved['general_config']['boss_limit'], 6)
        self.assertEqual(saved['switch_soul_config']['boss_group_team_name'], '活动,首领')
        self.assertEqual(saved['boss_battle_conf']['battle_timeout'], 120)
        self.assertEqual(saved['switch_soul_config']['ap100_group_team_name'], '活动,百体')
        self.assertTrue(saved['ap100_battle_conf']['green_enable'])
        self.assertEqual(ActivityShikigami.model_validate(saved).model_dump(mode='json'), saved)

    def test_legacy_climb_keeps_all_live_general_settings(self):
        general = {
            'ap_limit': 9, 'ap100_limit': 4, 'pass_limit': 'invalid', 'boss_limit': 11,
            'limit_time': '02:10:00', 'active_souls_clean': True, 'random_sleep': True,
            'use_penta_pass': True, 'climb_drink_break': True, 'climb_drink_interval': '30,45',
        }
        conf = ActivityShikigami.model_validate({'general_climb': general})
        saved = conf.model_dump(mode='json')
        self.assertNotIn('general_climb', saved)
        self.assertEqual(conf.general_config.task_sequence_v, ['体力', '首领', '百体'])
        for key, value in general.items():
            if key != 'pass_limit':
                self.assertEqual(saved['general_config'][key], value)

    def test_mixed_legacy_fakegod_fills_missing_settings_and_keeps_explicit_choices(self):
        conf = ActivityShikigami.model_validate({
            'general_config': {'task_sequence': [], 'ap_limit': 3, 'limit_time': '00:45:00'},
            '_legacy_fakegod': {
                'scheduler': {'enable': True},
                'general_climb': {'pass_limit': 8, 'limit_time': '02:00:00'},
            },
        })
        self.assertEqual(conf.general_config.fakegod_limit, 8)
        self.assertEqual(conf.general_config.limit_time_v.total_seconds(), 2700)
        self.assertEqual(conf.general_config.task_sequence_v, [])
        explicit = ActivityShikigami.model_validate({
            'general_config': {'fakegod_limit': 0},
            '_legacy_fakegod': {'general_climb': {'pass_limit': 8}},
        })
        self.assertEqual(explicit.general_config.fakegod_limit, 0)

    def test_template_and_api_expose_only_supported_configuration(self):
        root = Path(__file__).resolve().parents[1]
        template = json.loads((root / 'config/template.json').read_text(encoding='utf-8'))
        expected = ActivityShikigami().model_dump(mode='json')
        self.assertEqual(template['activity_shikigami'], expected)
        args = ConfigModel().script_task('ActivityShikigami')
        self.assertEqual(set(args), set(expected))
        self.assertEqual(
            {field['name'] for field in args['general_config']},
            set(expected['general_config']),
        )
        self.assertEqual(
            {field['name'] for field in args['switch_soul_config']},
            set(expected['switch_soul_config']),
        )
        self.assertIn('boss_battle_conf', args)
        self.assertIn('boss_limit', {field['name'] for field in args['general_config']})
        # 武道会也使用首领配置，保持共用字段完整。
        martial = ConfigModel().script_task('MartialArts')
        self.assertIn('boss_battle_conf', martial)
        self.assertIn('boss_limit', {field['name'] for field in martial['general_climb']})

    def test_boss_routes_are_added_only_when_boss_is_requested(self):
        task = ScriptTask.__new__(ScriptTask)
        task.navigator = NavigatorSession(task_category=pages.page_act.category)
        task.navigator.bootstrap([pages.page_act, pages.page_climb_ap, pages.page_climb_ap100])
        task.setup_climb_pages()
        self.assertNotIn(pages.page_climb_boss.key, task.navigator.pages)
        task.setup_climb_pages(include_boss=True)
        main = task.navigator.resolve_page(pages.page_act)
        boss = task.navigator.resolve_page(pages.page_climb_boss)
        forward = task._build_path(main, boss)
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0].action, Assets.I_TO_BATTLE_BOSS)
        backward = task._build_path(boss, main)
        self.assertEqual(len(backward), 1)
        self.assertEqual(backward[0].action, task.I_UI_BACK_YELLOW)

    def test_boss_uses_its_own_resources_preset_and_battle_config(self):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = ActivityShikigami.model_validate({
            'general_config': {'task_sequence': ['首领'], 'boss_limit': 7},
            'switch_soul_config': {'enable_switch_boss': True, 'boss_group_team': '2,3'},
            'boss_battle_conf': {'green_enable': True, 'lock_team_enable': True},
        })
        task.conf.switch_soul_config.validate_switch_soul()
        task.setup_climb_pages = Mock()
        task.time_limit_reached = Mock(return_value=False)
        with patch.object(task, '_run_climb_type') as run_branch:
            task.run_climb('boss')
            run_branch.assert_called_once_with('boss')
        task.setup_climb_pages.assert_called_once_with(include_boss=True)
        task.current_action_type = 'boss'
        task.action_count = {'boss': 0}
        task.climb_consumable_count = {'boss': -1, 'penta_pass': 0}
        task.climb_pending_consumption = {'boss': 0, 'penta_pass': 0}
        task.climb_ocr_correction_rounds = {'boss': 0}
        task.penta_pass_active = False
        task.screenshot = Mock()
        task.O_REMAIN_BOSS = Mock()
        task.O_REMAIN_BOSS.ocr_digit_counter.return_value = (0, 3, 10)
        task.device = Mock()
        self.assertTrue(task._climb_resource_available('boss'))
        self.assertEqual(task.climb_consumable_count['boss'], 3)
        self.assertEqual(task._climb_fire_rule('boss'), Assets.I_AS_BOSS_FIRE)
        self.assertEqual(task._exit_matcher(), Assets.I_AS_BOSS_FIRE)
        task.switch_soul_for = Mock()
        task._enter_climb_battle = Mock(return_value=True)
        task.run_general_battle = Mock()
        task._run_climb_action('boss', pages.page_climb_boss)
        task.switch_soul_for.assert_called_once_with(
            'boss', Assets.I_BATTLE_MAIN_TO_RECORDS,
            return_page=pages.page_climb_boss, exit_records=True,
        )
        task.run_general_battle.assert_called_once_with(
            task.conf.boss_battle_conf, battle_key='activity_boss',
        )
        self.assertEqual(task.action_count['boss'], 1)
        self.assertEqual(task.climb_pending_consumption['boss'], 1)
        self.assertEqual(task.climb_pending_consumption['penta_pass'], 0)

    def test_fakegod_returns_to_map_and_reselects_before_next_battle(self):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = ActivityShikigami(general_config=GeneralConfig(fakegod_limit=1))
        task.action_count = {'fakegod': 0}
        task.setup_fakegod_pages = Mock()
        task._goto_fakegod_action = Mock(return_value=True)
        task.screenshot = Mock()
        task.get_current_page = Mock(side_effect=[
            pages.page_fakegod_map, pages.page_fakegod_action, pages.page_fakegod_map,
        ])
        task.time_limit_reached = Mock(return_value=False)
        task.prepare_next_action = Mock(return_value=True)
        task._run_fakegod_action = Mock(side_effect=lambda _: task.record_action('fakegod'))
        task.run_fakegod()
        self.assertEqual(task.action_count['fakegod'], 1)
        self.assertEqual(task._goto_fakegod_action.call_count, 2)
        task.prepare_next_action.assert_called_once_with('fakegod')

    def test_fakegod_map_can_finish_general_battle(self):
        task = ScriptTask.__new__(ScriptTask)
        task.current_action_type = 'fakegod'
        for visible, expected in (
            (Assets.I_FG_AS_CHECK_MAIN_2, True),
            (Assets.I_FG_ACT_FIRE, True),
            (Assets.I_CLIMB_MODE_AP, False),
        ):
            with self.subTest(visible=visible.name):
                task.appear = lambda rule: rule == visible
                self.assertEqual(task._evaluate_exit_matcher(task._exit_matcher()), expected)

    def test_fakegod_marker_matches_current_enemy_portraits(self):
        import cv2
        import numpy as np

        fixture = Path(__file__).parent / 'fixtures/activity_shikigami/fakegod_map_targets.png'
        targets = cv2.cvtColor(
            cv2.imdecode(np.fromfile(fixture, dtype=np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2RGB,
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[200:520, 350:1000] = targets
        rule = deepcopy(Assets.I_FG_AS_TO_PASS)
        self.assertTrue(rule.multi_scale_template_match(frame))
        x, y, width, height = rule.roi_front
        self.assertTrue(350 <= x < 1000 and 200 <= y < 520)

    def test_fakegod_unrecognized_map_raises_navigation_error(self):
        task = Mock()
        task.appear.return_value = True
        task.appear_then_click.return_value = False
        with patch('tasks.ActivityShikigami.activities.fake_god.time.sleep'):
            with self.assertRaises(GamePageUnknownError):
                select_fakegod_target(task)
        task.click.assert_not_called()
        runtime = ScriptTask.__new__(ScriptTask)
        runtime.goto_page = Mock(side_effect=GamePageUnknownError)
        runtime._sync_fakegod_team_lock = Mock()
        with self.assertRaises(GamePageUnknownError):
            runtime._goto_fakegod_action(pages.page_fakegod_action)
        runtime._sync_fakegod_team_lock.assert_not_called()

    def test_fakegod_recognition_failure_does_not_run_ap_or_finish_successfully(self):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = ActivityShikigami.model_validate({
            'general_config': {
                'task_sequence': ['伪神/爬塔', '体力'], 'fakegod_limit': 300, 'ap_limit': 300,
            },
        })
        task.before_run = Mock()
        task.time_limit_reached = Mock(return_value=False)
        task.setup_fakegod_pages = Mock()
        task.goto_page = Mock(side_effect=GamePageUnknownError)
        task.run_climb = Mock()
        task.finish_activity_task = Mock()
        with self.assertRaises(GamePageUnknownError):
            task.run()
        task.run_climb.assert_not_called()
        task.finish_activity_task.assert_not_called()

    def test_fakegod_confirmed_resource_shortage_can_end_branch(self):
        runtime = ScriptTask.__new__(ScriptTask)
        runtime.goto_page = Mock(side_effect=ActivityResourceNotEnough)
        runtime._sync_fakegod_team_lock = Mock()
        self.assertFalse(runtime._goto_fakegod_action(pages.page_fakegod_action))
        runtime._sync_fakegod_team_lock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
