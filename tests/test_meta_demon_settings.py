"""MetaDemon quick presets, settings payload and ticket-runner mapping."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.config.config_model import ConfigModel
from module.server.i18n import Addition
from tasks.Component.QuickLoadout.config import QuickLoadoutConfig, QuickLoadoutMode
from tasks.MetaDemon.config import BossType, MetaDemon, MetaDemonRentalLineup, PRESET_GROUPS, SPECIAL_BOSS_PRESETS
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemonTicket.config import MetaDemonTicket, TicketMode
from tasks.MetaDemonTicket.ticket_farming import ticket_farming_config, ExplorationTicketTask, AwakeTicketTask
from tasks.EvoZone.config import EvoZone
from tasks.Exploration.config import AutoRotate, Exploration, ExplorationLevel, UpType, UserStatus


class MetaDemonSettingsChecks(unittest.TestCase):
    def test_exploration_label_migrates(self):
        conf = ConfigModel(meta_demon={'meta_demon_config': {'mode': ['鬼王战斗', '门票刷取：探索绘卷']},
                                      'scheduler': {'enable': True}})
        self.assertNotIn('mode', conf.meta_demon.meta_demon_config.model_dump())
        self.assertEqual(conf.meta_demon_ticket.general_config.mode, TicketMode.EXPLORATION)
        self.assertTrue(conf.meta_demon.scheduler.enable and conf.meta_demon_ticket.scheduler.enable)

    def test_removed_boss_settings_and_legacy_ticket_preset(self):
        conf = ConfigModel(meta_demon={
            'meta_demon_config': {'limit_time': '00:45:00', 'limit_count': 50},
            'preset_config': {'ticket_farming_enable': True, 'ticket_farming_group': 4, 'ticket_farming_team': 2},
            'low_star_battle_conf': {'preset_enable': True},
            'high_star_battle_conf': {'green_enable': True},
            'switch_soul_config': {'low_star_enable': True},
        })
        battle = conf.meta_demon.model_dump()
        self.assertFalse({'low_star_battle_conf', 'high_star_battle_conf', 'switch_soul_config'} & battle.keys())
        self.assertFalse({'limit_time', 'limit_count'} & battle['meta_demon_config'].keys())
        ticket = conf.meta_demon_ticket.general_battle_config
        self.assertEqual((ticket.preset_group, ticket.preset_team), (4, 2))

    def test_existing_quick_loadout_target_migrates(self):
        conf = MetaDemon(
            general_config={'high_star_quick_loadout_enable': True},
            switch_soul_config={'high_star_group_team_name': '默认分组,超鬼王'},
            meta_demon_config={'high_star_powerful_enable': True, 'powerful_count': 2},
        )
        self.assertEqual(conf.high_star_preset.model_dump(), {
            'powerful_count': 2, 'switch_soul': True,
            'group_name': '默认分组', 'preset_name': '超鬼王', 'preset_numbers': '',
            'rental_lineup': MetaDemonRentalLineup.NONE,
        })
        self.assertEqual(conf.high_star_preset, conf.tsukuyomi_preset)
        self.assertEqual(conf.low_star_preset.preset_name, '')
        self.assertEqual(MetaDemon.model_validate(conf.model_dump()), conf)

    def test_legacy_assistance_does_not_turn_into_solo_battles(self):
        conf = ConfigModel(
            meta_demon={'scheduler': {'enable': True}, 'meta_demon_config': {'mode': ['鬼王协助']}},
            task_group_1={'group_config': {'tasks': ['Pets', 'MetaDemon', 'DailyTrifles'], 'start_index': 3}},
        )
        self.assertFalse(conf.meta_demon.scheduler.enable)
        self.assertEqual(conf.task_group_1.group_config.task_list, ['Pets', 'DailyTrifles'])
        self.assertEqual(conf.task_group_1.group_config.start_index, 2)
        self.assertNotIn('assistance_config', conf.meta_demon.model_dump())

    def test_exploration_tickets_copy_normal_settings_with_ticket_limits_and_role(self):
        meta = MetaDemonTicket(
            general_config={'user_status': 'leader', 'limit_time': '00:45:00', 'awake_buff_enable': True},
            invite_config={'friend_list': '刷票好友'},
            switch_soul_config={'group_name': '觉醒'},
            general_battle_config={'preset_enable': True, 'preset_group': 3, 'preset_team': 2})
        normal = Exploration(
            exploration_config={'exploration_level': '第二十六章', 'auto_rotate': '是',
                                'up_type': UpType.COIN, 'buff_gold_50_click': True,
                                'collect_paper_reward': False, 'minions_cnt': 1, 'limit_time': '00:01:00'},
            switch_soul_config={'enable_switch_by_name': True, 'group_name': '普通探索', 'team_name': '金币'},
            general_battle_config={'preset_enable': True, 'preset_group': 7, 'lock_team_enable': True},
            scrolls={'scrolls_enable': True})
        before = normal.model_dump()
        exploration = ticket_farming_config(meta, TicketMode.EXPLORATION, normal)
        settings = exploration.exploration_config
        self.assertEqual(settings.exploration_level, ExplorationLevel.EXPLORATION_26)
        self.assertEqual(settings.auto_rotate, AutoRotate.yes)
        self.assertEqual(settings.up_type, UpType.COIN)
        self.assertTrue(settings.buff_gold_50_click)
        self.assertFalse(settings.collect_paper_reward)
        self.assertEqual(settings.user_status, UserStatus.LEADER)
        self.assertEqual(settings.limit_time, meta.general_config.limit_time)
        self.assertGreater(settings.minions_cnt, normal.exploration_config.minions_cnt)
        self.assertEqual(exploration.invite_config.friend_list, '刷票好友')
        self.assertEqual(exploration.switch_soul_config, normal.switch_soul_config)
        self.assertEqual(exploration.general_battle_config.preset_group, 7)
        self.assertFalse(exploration.general_battle_config.lock_team_enable)
        self.assertFalse(exploration.scrolls.scrolls_enable)
        self.assertEqual(normal.model_dump(), before)
        awake = ticket_farming_config(meta, TicketMode.AWAKE)
        self.assertTrue(awake.evo_zone_config.soul_buff_enable)
        self.assertEqual(awake.switch_soul_config.group_name, '觉醒')
        self.assertIs(awake.general_battle_config, meta.general_battle_config)

    def test_ticket_rotation_reuses_exploration_without_enabling_scrolls_mode(self):
        from tasks.Exploration.script_task import ScriptTask as ExplorationTask
        self.assertIs(ExplorationTicketTask.switch_rotate, ExplorationTask.switch_rotate)
        self.assertIs(ExplorationTicketTask.run_on_exp_settings, ExplorationTask.run_on_exp_settings)
        meta = MetaDemonTicket()
        for rotation in (AutoRotate.no, AutoRotate.yes):
            normal = Exploration(exploration_config={'auto_rotate': rotation}, scrolls={'scrolls_enable': True})
            exploration = ticket_farming_config(meta, TicketMode.EXPLORATION, normal)
            self.assertEqual(exploration.exploration_config.auto_rotate, rotation)
            self.assertFalse(exploration.scrolls.scrolls_enable)

    def test_settings_payload_has_flat_groups_and_defaults(self):
        payload = ConfigModel.script_task(SimpleNamespace(meta_demon=MetaDemon()), 'MetaDemon')
        self.assertEqual(set(payload), {'scheduler', 'meta_demon_config', 'settings_layout_config', *PRESET_GROUPS})
        selector = payload['settings_layout_config'][0]['ui_layout']['sections'][-1]
        self.assertTrue(selector['select_variant'])
        self.assertEqual([variant['groups'][0]['name'] for variant in selector['variants']], list(PRESET_GROUPS))
        for key in PRESET_GROUPS:
            fields = {field['name']: field for field in payload[key]}
            self.assertEqual(set(fields), {
                'powerful_count', 'rental_lineup', 'switch_soul', 'preset_numbers', 'group_name', 'preset_name',
            })
            expected_count = 0 if key == 'low_star_preset' else 1
            self.assertEqual(fields['powerful_count']['default'], expected_count)
            self.assertEqual(fields['powerful_count']['value'], expected_count)
            self.assertEqual(fields['rental_lineup']['enumEnum'], [mode.value for mode in MetaDemonRentalLineup])
            self.assertEqual(fields['switch_soul']['ui_visible_when'], {'rental_lineup': MetaDemonRentalLineup.NONE.value})
        for group in payload.values():
            self.assertIsInstance(group, list)
            for field in group:
                self.assertIn('default', field)
        ticket = ConfigModel.script_task(SimpleNamespace(meta_demon_ticket=MetaDemonTicket()), 'MetaDemonTicket')
        self.assertIn('invite_config', ticket)
        common = {field['name']: field for field in ticket['general_config']}
        self.assertNotIn('exploration_target', common)
        self.assertNotIn('exploration_rotate', common)

    def test_boss_and_ticket_settings_are_localized_in_simplified_chinese(self):
        config = ConfigModel()
        translations = Addition.load_additions()['zh-CN']
        self.assertEqual(translations['MetaDemonTicket'], '鬼王门票')
        chinese = r'[\u3400-\u9fff]'
        for task in ('MetaDemon', 'MetaDemonTicket'):
            self.assertRegex(translations[task], chinese)
            for group, rows in config.script_task(task).items():
                self.assertRegex(rows[0]['ui_group_title']['zh_CN'], chinese)
                self.assertRegex(translations.get(group, group), chinese)
                for row in rows:
                    name = row['name']
                    with self.subTest(task=task, group=group, field=name):
                        display = row['ui_text']['zh_CN']
                        self.assertRegex(display['title'], chinese)
                        self.assertRegex(translations.get(name, name), chinese)
                        if row.get('description'):
                            self.assertRegex(display['description'], chinese)
                        options = row.get('enumEnum', [])
                        self.assertEqual(list(display['options']), options)
                        for option in options:
                            if not str(option).isdecimal():
                                self.assertRegex(display['options'][option], chinese)
                                self.assertRegex(translations.get(option, option), chinese)

    def test_group_edits_are_saved_under_independent_backend_keys(self):
        config = ConfigModel()
        with patch.object(ConfigModel, 'save') as save:
            self.assertTrue(config.script_set_arg('MetaDemon', 'low_star_preset', 'powerful_count', 2))
            self.assertTrue(config.script_set_arg('MetaDemon', 'tsukuyomi_preset', 'group_name', '活动'))
            self.assertTrue(config.script_set_arg('MetaDemon', 'tsukuyomi_preset', 'preset_name', '月读队'))
            self.assertEqual(save.call_count, 3)
        groups = config.script_task('MetaDemon')
        self.assertEqual({row['name']: row['value'] for row in groups['low_star_preset']}['powerful_count'], 2)
        self.assertEqual(config.meta_demon.tsukuyomi_preset.preset_name, '月读队')
        self.assertEqual(config.meta_demon.high_star_preset.preset_name, '')

    def test_presets_match_stars_and_distinguish_the_six_boss_names(self):
        settings = MetaDemon()
        for boss, field in SPECIAL_BOSS_PRESETS.items():
            with self.subTest(boss=boss):
                self.assertIs(settings.preset_for(BossType.FOUR_STARS, boss), settings.low_star_preset)
                for star in (BossType.FIVE_STARS, BossType.SIX_STARS):
                    self.assertIs(settings.preset_for(star, boss), getattr(settings, field))
        self.assertIs(settings.preset_for(BossType.SIX_STARS, '鬼王酒吞'), settings.high_star_preset)

    def test_named_legacy_rules_migrate_to_independent_presets(self):
        settings = MetaDemon(
            quick_preset_config={'enable': True, 'skip_equip_soul': True,
                                 'preset_rules': '甲:月读;乙:ALL',
                                 'preset_groups': '甲,一组,特殊;乙,二组,通用'},
            high_star_preset={'powerful_count': 3, 'group_name': '已保存', 'preset_name': '新配置'},
        )
        self.assertEqual(settings.tsukuyomi_preset.preset_name, '特殊')
        self.assertFalse(settings.tsukuyomi_preset.switch_soul)
        self.assertEqual(settings.low_star_preset.preset_name, '通用')
        self.assertEqual(settings.kidomaru_preset.preset_name, '通用')
        self.assertEqual(settings.high_star_preset.preset_name, '新配置')
        self.assertEqual(settings.high_star_preset.powerful_count, 3)
        settings.kidomaru_preset.powerful_count = 2
        self.assertEqual(settings.shura_kidomaru_preset.powerful_count, 1)

    def test_default_powerful_count_preserves_saved_zero(self):
        settings = MetaDemon(high_star_preset={'powerful_count': 0}, tsukuyomi_preset={'switch_soul': True})
        self.assertEqual(settings.high_star_preset.powerful_count, 0)
        self.assertEqual(settings.tsukuyomi_preset.powerful_count, 1)
        legacy = MetaDemon(meta_demon_config={'high_star_powerful_enable': False})
        self.assertEqual(legacy.high_star_preset.powerful_count, 0)

    def test_rented_lineup_takes_precedence_over_personal_settings(self):
        for rental, name in ((MetaDemonRentalLineup.GROUP, '群体'),
                             (MetaDemonRentalLineup.SINGLE, '单体'),
                             (MetaDemonRentalLineup.NORMAL_ATTACK, '普攻')):
            with self.subTest(rental=rental):
                owner = BossBattle.__new__(BossBattle)
                owner.conf = MetaDemon(low_star_preset={
                    'rental_lineup': rental, 'switch_soul': True, 'preset_numbers': '1,1',
                })
                owner.cur_boss_type = BossType.ONE_STAR
                owner.run_quick_loadout = Mock(return_value=True)
                self.assertTrue(owner.prepare_boss_preset())
                config = owner.run_quick_loadout.call_args.args[0]
                self.assertEqual((config.group_name, config.preset_name), ('队伍租借', name))
                self.assertTrue(owner.run_quick_loadout.call_args.kwargs['skip_equip_soul'])

    def test_number_pair_selects_personal_preset(self):
        owner = BossBattle.__new__(BossBattle)
        owner.conf = MetaDemon(low_star_preset={'switch_soul': True, 'preset_numbers': ' 1 ， 2 '})
        owner.cur_boss_type = BossType.ONE_STAR
        owner.run_quick_loadout = Mock(return_value=True)
        self.assertEqual(owner.conf.low_star_preset.preset_numbers, '1,2')
        self.assertTrue(owner.prepare_boss_preset())
        config = owner.run_quick_loadout.call_args.args[0]
        self.assertEqual((config.mode, config.group_number, config.preset_number), (QuickLoadoutMode.NUMBER, 1, 2))
        self.assertFalse(owner.run_quick_loadout.call_args.kwargs['skip_equip_soul'])
        with self.assertRaises(ValueError):
            MetaDemon(low_star_preset={'preset_numbers': '1,0'})

    def test_first_personal_group_skips_rental_tab_without_swiping(self):
        owner = BossBattle.__new__(BossBattle)
        layout = owner._quick_loadout_layout_at((496, 224, 553, 387), reference_size=owner.PANEL_SIZE)
        owner.appear = Mock(return_value=True)
        owner.device = SimpleNamespace(click=Mock())
        owner.swipe = Mock()
        with patch('tasks.MetaDemon.quick_loadout.sleep'):
            self.assertTrue(owner._select_group(layout, QuickLoadoutConfig(mode=QuickLoadoutMode.NUMBER)))
        owner.appear.assert_called_once_with(owner.I_MD_RENTAL_TAB)
        owner.device.click.assert_called_once_with(557, 306, control_name='QUICK_LOADOUT_GROUP')
        owner.swipe.assert_not_called()

    def test_deploy_soul_prompt_respects_the_equip_option(self):
        for equip in (True, False):
            with self.subTest(equip=equip):
                owner = BossBattle.__new__(BossBattle)
                frame = owner.F_QUICK_LOADOUT_FRAME
                layout = owner._quick_loadout_layout_at((496, 224, 553, 387))
                owner.screenshot = Mock()
                owner.device = SimpleNamespace(click=Mock())
                owner._quick_loadout_panel_visible = Mock(side_effect=[True, False])
                owner._quick_loadout_fight = Mock()
                owner._dismiss_quick_loadout = Mock(return_value=True)
                owner.appear = Mock(side_effect=[True, False])
                owner.appear_then_click = Mock(return_value=True)
                owner.click = Mock(return_value=True)
                with patch('tasks.MetaDemon.quick_loadout.sleep'):
                    self.assertEqual(owner._deploy_quick_loadout(layout, frame, 249, equip_soul=equip), equip)
                if equip:
                    owner.appear_then_click.assert_called_once_with(owner.I_SOU_SWITCH_SURE, interval=0.8)
                else:
                    owner.appear_then_click.assert_not_called()
                    owner.click.assert_any_call(owner.C_MD_PRESET_SOUL_CANCEL, interval=0.8)

    def test_boss_prepares_souls_and_powerful_before_challenge(self):
        owner = object.__new__(BossBattle)
        owner.conf = MetaDemon(tsukuyomi_preset={
            'powerful_count': 2, 'switch_soul': True,
            'group_name': '鬼王', 'preset_name': '月读队',
        })
        owner.cur_boss_type = BossType.SIX_STARS
        owner._read_quick_loadout_stage_name = Mock(return_value=' 月 读 ')
        events = []
        owner.summon_boss = Mock(return_value=True)
        owner.check_fatigue = Mock(return_value=True)
        owner.run_quick_loadout = Mock(side_effect=lambda *args, **kwargs: events.append('equip') or True)
        owner.check_and_switch_powerful = Mock(side_effect=lambda: events.append(owner.enable_powerful_fire) or True)
        owner.screenshot = Mock()
        owner.appear = Mock(return_value=False)
        owner.appear_then_click = Mock(side_effect=lambda *args, **kwargs: events.append('fire') or True)
        owner.is_in_battle = Mock(side_effect=[False, True, True])
        owner.run_general_battle = Mock()
        self.assertFalse(owner.start_battle())
        self.assertTrue(owner.check_and_prepare_battle())
        self.assertTrue(owner.start_battle())
        self.assertEqual(events, ['equip', True, 'fire'])
        config = owner.run_quick_loadout.call_args.args[0]
        self.assertEqual((config.group_name, config.preset_name), ('鬼王', '月读队'))
        self.assertFalse(owner.run_quick_loadout.call_args.kwargs['skip_equip_soul'])
        self.assertTrue(owner.enable_powerful_fire)
        self.assertTrue(owner.start_battle())
        self.assertFalse(owner.enable_powerful_fire)

    def test_same_target_skips_switch_even_when_the_boss_group_changes(self):
        owner = object.__new__(BossBattle)
        preset = {'switch_soul': True, 'group_name': '活动', 'preset_name': '共用'}
        owner.conf = MetaDemon(tsukuyomi_preset=preset, shuten_doji_preset=preset,
                              oni_king_shuten_doji_preset={**preset, 'preset_name': '另一队'})
        owner.cur_boss_type = BossType.FIVE_STARS
        owner._read_quick_loadout_stage_name = Mock(side_effect=['月读', '酒吞童子', '鬼王酒吞童子'])
        owner._open_quick_loadout = Mock(return_value=True)
        owner._build_quick_loadout_layout = Mock()
        owner._select_group = Mock(return_value=True)
        owner._select_preset_row = Mock(return_value=120)
        owner._deploy_quick_loadout = Mock(return_value=True)
        for expected in (1, 1, 2):
            owner._active_preset = None
            self.assertTrue(owner.prepare_boss_preset())
            self.assertEqual(owner._deploy_quick_loadout.call_count, expected)
            self.assertTrue(owner._deploy_quick_loadout.call_args.kwargs['equip_soul'])

    def test_incomplete_preset_stops_before_any_game_input(self):
        owner = object.__new__(BossBattle)
        owner.conf = MetaDemon(low_star_preset={'switch_soul': True, 'group_name': '已填'})
        owner.cur_boss_type = BossType.TWO_STARS
        owner.run_quick_loadout = Mock()
        self.assertFalse(owner.prepare_boss_preset())
        self.assertFalse(owner.start_battle())
        owner.run_quick_loadout.assert_not_called()

    def test_ticket_entry_uses_mode_settings_without_copying_runtime(self):
        from module.config.config import Config
        from tasks.MetaDemonTicket.ticket_farming import run_ticket_farming, TicketsFull
        from tasks.EvoZone.config import Layer, UserStatus as AwakeStatus
        from tasks.Exploration.config import UserStatus as ExplorationStatus
        for mode, runner_class in ((TicketMode.AWAKE, AwakeTicketTask),
                                   (TicketMode.EXPLORATION, ExplorationTicketTask)):
            with self.subTest(mode=mode):
                original = object.__new__(Config)
                original.config_name = 'TICKET_CHECK'
                original.task = 'MetaDemon'
                original.model = ConfigModel()
                original.model.exploration.exploration_config.auto_rotate = AutoRotate.yes
                battle = original.model.meta_demon_ticket.general_battle_config
                battle.preset_enable, battle.preset_group, battle.preset_team = True, 3, 2
                original.model.exploration.scrolls.scrolls_enable = True
                exploration_battle = original.model.exploration.general_battle_config
                exploration_battle.preset_enable, exploration_battle.preset_group, exploration_battle.preset_team = True, 7, 4
                original.model.evo_zone.general_battle_config.preset_group = 6
                before = original.model.model_dump()
                device = object()
                runner = object.__new__(runner_class)
                runner.config = original
                runner.device = device
                runner.run_alone = Mock(side_effect=TicketsFull)
                runner.exec_exp_page = Mock(side_effect=TicketsFull)
                runner.pre_process = Mock()
                runner.finish_exploration = Mock()
                runner._register_custom_pages = Mock()
                runner.install_ticket_reward_hook = Mock()

                def build(config, actual_device):
                    self.assertIs(actual_device, device)
                    self.assertIs(config, original)
                    return runner

                with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=False), \
                     patch('tasks.MetaDemonTicket.ticket_farming.AwakeTicketTask', side_effect=build), \
                     patch('tasks.MetaDemonTicket.ticket_farming.ExplorationTicketTask', side_effect=build):
                    self.assertTrue(run_ticket_farming(SimpleNamespace(config=original, device=device), mode))
                runner.install_ticket_reward_hook.assert_called_once()
                self.assertTrue(runner._ticket_farming_complete)
                if mode == TicketMode.AWAKE:
                    self.assertIs(runner._config.general_battle_config, battle)
                    self.assertEqual(runner._config.evo_zone_config.layer, Layer.SEVEN)
                    self.assertEqual(runner._config.evo_zone_config.user_status, AwakeStatus.ALONE)
                    runner.run_alone.assert_called_once()
                    runner.exec_exp_page.assert_not_called()
                    runner.finish_exploration.assert_not_called()
                else:
                    self.assertEqual(runner._config.general_battle_config.preset_group, 7)
                    self.assertEqual(runner._config.general_battle_config.preset_team, 4)
                    self.assertEqual(runner._config.exploration_config.user_status, ExplorationStatus.ALONE)
                    self.assertEqual(runner._config.exploration_config.auto_rotate, AutoRotate.yes)
                    self.assertFalse(runner._config.scrolls.scrolls_enable)
                    runner.pre_process.assert_called_once()
                    runner.exec_exp_page.assert_called_once()
                    runner.finish_exploration.assert_called_once()
                    runner.run_alone.assert_not_called()
                self.assertEqual(original.model.model_dump(), before)

    def test_inherited_ticket_flows_use_the_configured_soul_and_battle_settings(self):
        from datetime import datetime, timedelta
        from tasks.EvoZone.config import Layer
        meta = MetaDemonTicket(switch_soul_config={'enable': True,
            'switch_group_team': '2,3'}, general_battle_config={
                'preset_enable': True, 'preset_group': 3, 'preset_team': 2})
        runtime = SimpleNamespace(meta_demon_ticket=meta)
        awake = object.__new__(AwakeTicketTask)
        awake.config = runtime
        awake.goto_page = Mock()
        awake.evozone_enter = Mock()
        awake.check_layer = Mock()
        awake.check_lock = Mock()
        awake.screenshot = Mock()
        awake.appear = Mock(side_effect=[True, False, True])
        awake.appear_then_click = Mock(return_value=True)
        awake.current_count, awake.limit_count = 0, 1
        awake.start_time, awake.limit_time = datetime.now(), timedelta(minutes=1)
        awake.run_general_battle = Mock(side_effect=lambda **kw: setattr(awake, 'current_count', 1))
        awake.run_alone()
        awake.check_layer.assert_called_once_with(Layer.SEVEN)
        self.assertIs(awake.run_general_battle.call_args.kwargs['config'], meta.general_battle_config)
        self.assertEqual(awake._config.switch_soul_config.switch_group_team, '2,3')
        exploration = object.__new__(ExplorationTicketTask)
        normal = Exploration(
            switch_soul_config={'enable_switch_by_name': True, 'group_name': '普通探索', 'team_name': '金币'},
            general_battle_config={'preset_enable': True, 'preset_group': 7, 'preset_team': 4})
        exploration.config = SimpleNamespace(meta_demon_ticket=meta, exploration=normal)
        exploration.C_SAFE_RANDOM_CLICK_AREA_EXP = Mock()
        exploration.goto_page = Mock()
        exploration.run_switch_soul_by_name = Mock()
        exploration.run_general_battle = Mock()
        exploration._match_end = Mock()
        exploration.pre_process()
        exploration.run_switch_soul_by_name.assert_called_once_with('普通探索', '金币')
        exploration.run_on_battle()
        self.assertEqual(exploration.run_general_battle.call_args.args[0], normal.general_battle_config)

    def test_normal_awake_config_keeps_original_task_settings(self):
        from tasks.EvoZone.script_task import ScriptTask as NormalAwakeTask
        config = EvoZone()
        task = object.__new__(NormalAwakeTask)
        task.config = SimpleNamespace(evo_zone=config)
        self.assertIs(task._config, config)

    def test_ticket_counter_uses_existing_resource_and_checks_capacity(self):
        from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
        from tasks.MetaDemonTicket.ticket_farming import metademon_tickets_full
        image = object()
        task = SimpleNamespace(device=SimpleNamespace(image=image),
            appear=Mock(side_effect=lambda target: target is GeneralBattleAssets.I_REWARD))
        for counter, full in (((1000, 0, 1000), True), ((1001, -1, 1000), True),
                              ((999, 1, 1000), False), ((0, 0, 0), False),
                              ((-1, 1001, 1000), False)):
            with self.subTest(counter=counter), patch.object(
                    GeneralBattleAssets.O_METADEMON_PASS, 'ocr_digit_counter', return_value=counter) as ocr:
                self.assertEqual(metademon_tickets_full(task), full)
                ocr.assert_called_once_with(image)

    def test_full_tickets_interrupt_both_reward_flows_and_cleanup_skips_ocr(self):
        from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
        from tasks.MetaDemonTicket.ticket_farming import TicketsFull
        for runner_class in (AwakeTicketTask, ExplorationTicketTask):
            runner = object.__new__(runner_class)
            runner.device = SimpleNamespace(image=object())
            runner.appear = Mock(return_value=True)
            with self.subTest(task=runner_class.__name__), patch.object(
                    GeneralBattleAssets.O_METADEMON_PASS, 'ocr_digit_counter', return_value=(1000, 0, 1000)) as ocr:
                with self.assertRaises(TicketsFull):
                    runner._handle_reward(None, None)
                self.assertEqual(ocr.call_count, 1)
                runner._ticket_farming_complete = True
                runner.check_ticket_reward()
                self.assertEqual(ocr.call_count, 1)

    def test_ticket_ocr_is_skipped_without_red_daruma_reward_image(self):
        from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
        for runner_class in (AwakeTicketTask, ExplorationTicketTask):
            runner = object.__new__(runner_class)
            runner.device = SimpleNamespace(image=object())
            runner.appear = Mock(return_value=False)
            with self.subTest(task=runner_class.__name__), patch.object(
                    GeneralBattleAssets.O_METADEMON_PASS, 'ocr_digit_counter') as ocr:
                runner.check_ticket_reward()
                runner.appear.assert_called_once_with(GeneralBattleAssets.I_REWARD)
                ocr.assert_not_called()

    def test_exploration_exhausted_targets_keep_exit_request_through_stale_frame(self):
        from tasks.Exploration.script_task import ScriptTask as NormalExplorationTask
        from tasks.Exploration.config import UserStatus
        from tasks.Exploration import page as pages
        for task_class in (NormalExplorationTask, ExplorationTicketTask):
            with self.subTest(task=task_class.__name__):
                task = object.__new__(task_class)
                task.pre_page = None
                task.user_status = UserStatus.ALONE
                task.need_exit = False
                task.fire_monster_type = ''
                task.collect_reward = Mock(return_value=False)
                task.ensure_exploration_team_locked = Mock(return_value=False)
                task.switch_rotate = Mock(return_value=False)
                task.get_fire_button = Mock(return_value=None)
                task.swipe = Mock(return_value=True)
                task.arrive_end = Mock(return_value=True)
                task.appear_then_click = Mock(return_value=True)
                task.screenshot = Mock()
                task.get_current_page = Mock(return_value=pages.page_exp_exit)
                task.run_on_exp_main()
                self.assertTrue(task.need_exit)
                task.get_fire_button.reset_mock()
                task.get_fire_button.return_value = object()
                task.run_on_exp_main()  # delayed scene frame after clicking back
                task.get_fire_button.assert_not_called()
                self.assertTrue(task.need_exit)
                task.run_on_exp_exit()
                self.assertIs(task.appear_then_click.call_args.args[0], task.I_E_EXIT_CONFIRM)

    def test_fire_does_not_cancel_requested_exit_but_accidental_popup_still_cancels(self):
        from tasks.Exploration.script_task import ScriptTask as NormalExplorationTask
        from tasks.Exploration import page as pages
        task = object.__new__(NormalExplorationTask)
        task.need_exit = True
        task.screenshot = Mock()
        task.get_current_page = Mock(return_value=pages.page_exp_exit)
        self.assertTrue(task.fire(object()))
        self.assertTrue(task.need_exit)
        task.need_exit = False
        task.appear_then_click = Mock(return_value=True)
        task.run_on_exp_exit()
        self.assertIs(task.appear_then_click.call_args.args[0], task.I_E_EXIT_CANCEL)

    def test_full_ticket_precheck_skips_both_farming_runners(self):
        from tasks.MetaDemon.assets import MetaDemonAssets
        from tasks.MetaDemonTicket.ticket_farming import run_ticket_farming
        from tasks.GameUi import page as pages
        for mode in (TicketMode.AWAKE, TicketMode.EXPLORATION):
            owner = SimpleNamespace(goto_page=Mock(), screenshot=Mock(), appear=Mock(return_value=True),
                                    device=SimpleNamespace(image=object()),
                                    config=SimpleNamespace(meta_demon_ticket=MetaDemonTicket()))
            with self.subTest(mode=mode), patch.object(MetaDemonAssets.O_METADEMON_PASS_EXP,
                    'ocr_digit_counter', return_value=(50, 0, 50)) as ocr, \
                 patch('tasks.MetaDemonTicket.ticket_farming.AwakeTicketTask') as awake, \
                 patch('tasks.MetaDemonTicket.ticket_farming.ExplorationTicketTask') as exploration:
                self.assertTrue(run_ticket_farming(owner, mode))
                owner.goto_page.assert_called_once_with(pages.page_exploration)
                ocr.assert_called_once_with(owner.device.image)
                awake.assert_not_called()
                exploration.assert_not_called()

    def test_ticket_precheck_retries_invalid_counter_and_rejects_wrong_page(self):
        from tasks.MetaDemon.assets import MetaDemonAssets
        from tasks.MetaDemonTicket.ticket_farming import tickets_full_before_farming
        owner = SimpleNamespace(goto_page=Mock(), screenshot=Mock(), appear=Mock(return_value=True),
                                device=SimpleNamespace(image=object()))
        with patch.object(MetaDemonAssets.O_METADEMON_PASS_EXP, 'ocr_digit_counter',
                          side_effect=[(0,0,0), (-1,51,50), (49,1,50)]) as ocr:
            self.assertFalse(tickets_full_before_farming(owner))
            self.assertEqual(ocr.call_count, 3)
        owner.appear.return_value = False
        with patch.object(MetaDemonAssets.O_METADEMON_PASS_EXP, 'ocr_digit_counter') as ocr:
            self.assertFalse(tickets_full_before_farming(owner))
            ocr.assert_not_called()

    def test_boss_entry_runs_the_battle_task(self):
        from tasks.MetaDemon.script_task import ScriptTask
        self.assertIs(ScriptTask.run, BossBattle.run)

    def test_awake_kirin_and_layer_choices_use_dedicated_ticket_settings(self):
        from tasks.EvoZone.config import KirinType, Layer
        default = ticket_farming_config(MetaDemonTicket(), TicketMode.AWAKE)
        self.assertEqual(default.evo_zone_config.kirin_type, KirinType.LIGHTNINGKIRIN)
        self.assertEqual(default.evo_zone_config.layer, Layer.SEVEN)
        for kirin in KirinType:
            for layer in Layer:
                conf = MetaDemonTicket(general_config={'awake_kirin_type': kirin, 'awake_layer': layer})
                awake = ticket_farming_config(conf, TicketMode.AWAKE)
                self.assertEqual(awake.evo_zone_config.kirin_type, kirin)
                self.assertEqual(awake.evo_zone_config.layer, layer)
        migrated = ConfigModel(meta_demon={'meta_demon_config': {'mode': ['门票刷取：觉醒七层']}, 'scheduler': {'enable': True}})
        self.assertEqual(migrated.meta_demon_ticket.general_config.mode, TicketMode.AWAKE)
        self.assertFalse(migrated.meta_demon.scheduler.enable)
        self.assertTrue(migrated.meta_demon_ticket.scheduler.enable)
        payload = ConfigModel.script_task(migrated, 'MetaDemonTicket')
        fields = {row['name']: row for row in payload['general_config']}
        self.assertEqual(fields['awake_kirin_type']['enumEnum'], [item.value for item in KirinType])
        self.assertEqual(fields['awake_layer']['enumEnum'], [item.value for item in Layer])
        self.assertEqual(fields['awake_layer']['default'], Layer.SEVEN.value)

    def test_disabled_souls_do_not_navigate(self):
        owner = object.__new__(BossBattle)
        owner.conf = MetaDemon()
        owner.cur_boss_type = BossType.ONE_STAR
        owner.goto_page = Mock()
        self.assertTrue(owner.prepare_boss_preset())
        owner.goto_page.assert_not_called()


if __name__ == '__main__':
    unittest.main()
