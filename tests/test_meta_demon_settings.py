"""MetaDemon quick presets, settings payload and ticket-runner mapping."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.config.config_model import ConfigModel
from module.server.i18n import Addition
from tasks.MetaDemon.config import BossType, MetaDemon, MetaDemonMode
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemonTicket.config import MetaDemonTicket, TicketMode
from tasks.MetaDemonTicket.ticket_farming import ticket_farming_config, ExplorationTicketTask, AwakeTicketTask
from tasks.EvoZone.config import EvoZone
from tasks.Exploration.config import AutoRotate, Exploration, ExplorationLevel, UpType, UserStatus


class MetaDemonSettingsChecks(unittest.TestCase):
    def test_exploration_label_migrates(self):
        conf = ConfigModel(meta_demon={'meta_demon_config': {'mode': ['鬼王战斗', '门票刷取：探索绘卷']},
                                      'scheduler': {'enable': True}})
        self.assertEqual(conf.meta_demon.meta_demon_config.mode, [MetaDemonMode.BOSS_BATTLE])
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
        )
        self.assertTrue(conf.quick_preset_config.enable)
        self.assertEqual(conf.quick_preset_config.named_presets(), {'ALL': ('默认分组', '超鬼王')})
        self.assertEqual(MetaDemon.model_validate(conf.model_dump()), conf)

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

    def test_ticket_rotation_reuses_exploration_and_disables_scrolls(self):
        from tasks.Exploration.script_task import ScriptTask as ExplorationTask
        self.assertIs(ExplorationTicketTask.switch_rotate, ExplorationTask.switch_rotate)
        self.assertIs(ExplorationTicketTask.run_on_exp_settings, ExplorationTask.run_on_exp_settings)
        meta = MetaDemonTicket()
        for rotation in (AutoRotate.no, AutoRotate.yes):
            normal = Exploration(exploration_config={'auto_rotate': rotation}, scrolls={'scrolls_enable': True})
            exploration = ticket_farming_config(meta, TicketMode.EXPLORATION, normal)
            self.assertEqual(exploration.exploration_config.auto_rotate, rotation)
            self.assertFalse(exploration.scrolls.scrolls_enable)
        # Even a stale enabled scrolls setting cannot perform ticket OCR or scheduling.
        owner = object.__new__(ExplorationTicketTask)
        owner.O_REALM_RAID_NUMBER1_META = Mock()
        owner.O_REALM_RAID_NUMBER_META = Mock()
        owner.set_next_run = Mock()
        from tasks.Exploration import page as pages
        exploration.scrolls.scrolls_enable = True
        for page in (pages.page_exploration, pages.page_exp_entrance, pages.page_exp_main):
            owner.activate_realm_raid(exploration.scrolls, exploration.exploration_config, page)
        owner.O_REALM_RAID_NUMBER1_META.ocr_digit_counter.assert_not_called()
        owner.O_REALM_RAID_NUMBER_META.ocr_digit_counter.assert_not_called()
        owner.set_next_run.assert_not_called()

    def test_settings_payload_has_flat_groups_and_defaults(self):
        payload = ConfigModel.script_task(SimpleNamespace(meta_demon=MetaDemon()), 'MetaDemon')
        self.assertEqual(set(payload), {'scheduler', 'meta_demon_config', 'quick_preset_config',
                                        'settings_layout_config', 'assistance_config'})
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

    def test_quick_loadout_is_the_only_soul_path(self):
        owner = object.__new__(BossBattle)
        owner.conf = MetaDemon(
            quick_preset_config={'enable': True, 'preset_groups': '预设组1,默认分组,超鬼王'},
            switch_soul_config={'low_star_enable': True, 'low_star_group_team': '2,3'},
        )
        owner._preset_boss_generation = None
        owner._boss_generation = 1
        owner.cur_boss_type = BossType.ONE_STAR
        owner.goto_page = Mock()
        owner.run_quick_loadout = Mock(return_value=True)
        owner._read_quick_loadout_stage_name = Mock()
        self.assertTrue(owner.check_and_switch_soul())
        self.assertTrue(owner.check_and_switch_soul())
        owner.run_quick_loadout.assert_called_once()
        config = owner.run_quick_loadout.call_args.args[0]
        self.assertEqual((config.group_name, config.preset_name), ('默认分组', '超鬼王'))
        self.assertIs(owner.run_quick_loadout.call_args.kwargs['frame'], owner.F_QUICK_LOADOUT_FRAME)
        owner.goto_page.assert_not_called()
        owner._read_quick_loadout_stage_name.assert_not_called()

    def test_custom_presets_apply_to_each_new_boss(self):
        owner = object.__new__(BossBattle)
        owner.conf = MetaDemon(general_config={'high_star_quick_loadout_enable': True},
            quick_preset_config={'high_star_custom_preset_enable': True,
                'high_star_custom_preset': '大天狗:("高星","天狗");ALL:("通用","其他")'})
        owner.cur_boss_type = BossType.FIVE_STARS
        owner._preset_boss_generation = None
        owner._boss_generation = 1
        owner._read_quick_loadout_stage_name = Mock(return_value='大天狗')
        owner.run_quick_loadout = Mock(return_value=True)
        owner.goto_page = Mock()
        self.assertTrue(owner.check_and_switch_soul())
        self.assertTrue(owner.check_and_switch_soul())
        owner.run_quick_loadout.assert_called_once()
        target = owner.run_quick_loadout.call_args.args[0]
        self.assertEqual((target.group_name, target.preset_name), ('高星', '天狗'))
        owner._boss_generation = 2
        owner.cur_boss_type = BossType.TWO_STARS
        owner._read_quick_loadout_stage_name.return_value = '酒吞童子'
        self.assertTrue(owner.check_and_switch_soul())
        self.assertEqual(owner.run_quick_loadout.call_count, 2)
        target = owner.run_quick_loadout.call_args.args[0]
        self.assertEqual((target.group_name, target.preset_name), ('通用', '其他'))
        owner.goto_page.assert_not_called()

    def test_numeric_custom_target_rejected_without_deploy(self):
        owner = object.__new__(BossBattle)
        owner.conf = MetaDemon(quick_preset_config={'enable': True, 'preset_rules': 'ALL: (7, 5)'})
        owner.cur_boss_type = BossType.SIX_STARS
        owner._preset_boss_generation = None
        owner._boss_generation = 1
        owner.run_quick_loadout = Mock()
        self.assertFalse(owner.check_and_switch_soul())
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
                runner.close_exploration_buffs = Mock()
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
                    runner.close_exploration_buffs.assert_not_called()
                else:
                    self.assertEqual(runner._config.general_battle_config.preset_group, 7)
                    self.assertEqual(runner._config.general_battle_config.preset_team, 4)
                    self.assertEqual(runner._config.exploration_config.user_status, ExplorationStatus.ALONE)
                    self.assertEqual(runner._config.exploration_config.auto_rotate, AutoRotate.yes)
                    self.assertFalse(runner._config.scrolls.scrolls_enable)
                    runner.pre_process.assert_called_once()
                    runner.exec_exp_page.assert_called_once()
                    runner.close_exploration_buffs.assert_called_once()
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

    def _summon_owner(self, frames, star=BossType.TWO_STARS):
        from copy import deepcopy
        owner = object.__new__(BossBattle)
        owner.conf = MetaDemon(meta_demon_config={'fire_sequence': '2 1'})
        owner.State = BossBattle.State()
        owner.cur_boss_type = None
        owner.current_count = 7
        owner._boss_generation = 0
        names = ('I_MD_FIRE', 'I_MD_GET_BOSS', 'I_MD_TICKET_EMPTY', 'I_MD_SWITCH_TICKET',
                 'I_MD_CLOSE_POPUP', 'I_MD_CHECK_SELECTED', 'I_MD_SUMMON_BOSS', 'I_MD_ONE_STAR', 'I_MD_TWO_STARS',
                 'I_MD_THREE_STARS', 'I_MD_FOUR_STARS', 'I_MD_FIVE_STARS', 'I_MD_SIX_STARS')
        for name in names:
            setattr(owner, name, deepcopy(getattr(owner, name)))
        target_ticket = {BossType.TWO_STARS: owner.I_MD_TWO_STARS,
                         BossType.FIVE_STARS: owner.I_MD_FIVE_STARS,
                         BossType.SIX_STARS: owner.I_MD_SIX_STARS}[star]
        state = {'index': -1, 'time': 0.0}
        clicks = []

        def current_frame():
            return frames[min(state['index'], len(frames) - 1)]

        def screenshot():
            state['index'] += 1
            state['time'] += 1

        def appear(rule, **kwargs):
            frame = current_frame()
            if rule is owner.I_MD_FIRE:
                return frame.get('fire', False)
            if rule is owner.I_MD_GET_BOSS:
                return frame.get('panel', False)
            if rule is owner.I_MD_SWITCH_TICKET:
                return not frame.get('panel', False) and not frame.get('fire', False)
            if rule is owner.I_MD_SUMMON_BOSS:
                return frame.get('preview') is not None
            if rule is target_ticket:
                return frame.get('panel', False)
            if rule is owner.I_MD_CHECK_SELECTED and frame.get('panel'):
                x = target_ticket.roi_front[0] if frame.get('selected') else 360
                rule.roi_front = (x, 280, 50, 22)
                return True
            return False

        def click(rule, **kwargs):
            if not appear(rule):
                return False
            clicks.append((state['index'], rule))
            return True

        owner.screenshot = Mock(side_effect=screenshot)
        owner.next_summon_star = Mock(side_effect=lambda: current_frame().get('preview'))
        owner.read_ticket_counts = Mock(side_effect=lambda _: current_frame().get('inventory', {star: 1}))
        owner.check_fatigue = Mock(return_value=True)
        owner.synthesis_boss_ticket = Mock()
        owner.appear = Mock(side_effect=appear)
        owner.click = Mock(side_effect=click)
        owner.appear_then_click = Mock(side_effect=click)
        return owner, state, clicks

    def test_summon_sequence_override_only_uses_six_without_changing_config(self):
        owner, state, clicks = self._summon_owner([
            {'panel': True, 'selected': True}, {'fire': True}], star=BossType.SIX_STARS)
        original = owner.conf.meta_demon_config.fire_sequence
        with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: state['time']):
            self.assertTrue(owner.check_and_switch_ticket(sequence=(BossType.SIX_STARS,)))
        self.assertEqual(owner.cur_boss_type, BossType.SIX_STARS)
        self.assertEqual(owner.conf.meta_demon_config.fire_sequence, original)

    def test_summon_recovers_closed_panel_and_confirms_two_star(self):
        owner, state, clicks = self._summon_owner([
            {'panel': True}, {}, {}, {'panel': True}, {'panel': True, 'selected': True},
            {}, {'fire': True}])
        with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: state['time']):
            self.assertTrue(owner.check_and_switch_ticket())
        self.assertTrue(any(rule is owner.I_MD_SWITCH_TICKET for _, rule in clicks))
        self.assertEqual([index for index, rule in clicks if rule is owner.I_MD_GET_BOSS], [4])
        self.assertEqual(owner.cur_boss_type, BossType.TWO_STARS)
        self.assertEqual(owner._boss_generation, 1)
        self.assertEqual(owner.current_count, 0)

    def test_summon_retries_unresponsive_confirmation_without_reselecting(self):
        owner, state, clicks = self._summon_owner([
            *[{'panel': True, 'selected': True}] * 4, {'fire': True}])
        with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: state['time']):
            self.assertTrue(owner.check_and_switch_ticket())
        self.assertEqual(sum(rule is owner.I_MD_GET_BOSS for _, rule in clicks), 2)
        self.assertFalse(any(rule is owner.I_MD_TWO_STARS for _, rule in clicks))

    def test_summon_rejects_wrong_selection_and_bounds_missing_panel_wait(self):
        for frames in ([{'panel': True}], [{}]):
            with self.subTest(frames=frames):
                owner, state, clicks = self._summon_owner(frames)
                with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: state['time']):
                    self.assertFalse(owner.check_and_switch_ticket())
                self.assertFalse(any(rule is owner.I_MD_GET_BOSS for _, rule in clicks))
                self.assertIsNone(owner.cur_boss_type)
                self.assertEqual(owner._boss_generation, 0)
                self.assertLessEqual(owner.screenshot.call_count, 25)

    def test_panel_can_use_configured_priority_over_the_home_queue(self):
        inventory = {BossType.TWO_STARS: 3, BossType.FIVE_STARS: 2}
        preview = BossType.TWO_STARS
        owner, state, clicks = self._summon_owner([
            {'panel': True, 'inventory': inventory, 'preview': preview},
            {'panel': True, 'inventory': inventory, 'preview': preview, 'selected': True},
            {'fire': True},
        ], star=BossType.FIVE_STARS)
        owner.conf.meta_demon_config.fire_sequence = '5 2'
        with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: state['time']):
            self.assertTrue(owner.check_and_switch_ticket(stop_at_six=True))
        self.assertEqual(owner.cur_boss_type, BossType.FIVE_STARS)
        self.assertEqual(clicks, [(0, owner.I_MD_FIVE_STARS), (1, owner.I_MD_GET_BOSS)])

    def test_exhaustion_requires_consistent_inventory_and_home_preview(self):
        inventory = {BossType.TWO_STARS: 2, BossType.FIVE_STARS: 0}
        for preview, finished in ((BossType.TWO_STARS, True), (BossType.FIVE_STARS, False)):
            with self.subTest(preview=preview):
                owner, state, clicks = self._summon_owner([
                    {'panel': True, 'inventory': inventory, 'preview': preview},
                ])
                owner.conf.meta_demon_config.fire_sequence = '5'
                with patch('tasks.MetaDemon.boss_battle.time.monotonic', side_effect=lambda: state['time']):
                    self.assertFalse(owner.check_and_switch_ticket(stop_at_six=True))
                self.assertEqual(owner.State.targets_finished, finished)
                self.assertGreaterEqual(owner.read_ticket_counts.call_count, 2)
                self.assertEqual(clicks, [])

    def test_six_star_home_preview_stops_without_summon_or_synthesis(self):
        for sequence, finished in (((BossType.TWO_STARS,), True), ((BossType.SIX_STARS,), False)):
            with self.subTest(sequence=sequence):
                owner, _, clicks = self._summon_owner([{'preview': BossType.SIX_STARS}])
                self.assertFalse(owner.check_and_prepare_battle(sequence))
                self.assertTrue(owner.State.done)
                self.assertEqual(owner.State.targets_finished, finished)
                self.assertEqual(clicks, [])
                owner.synthesis_boss_ticket.assert_not_called()

    def test_active_unverified_or_unconfigured_boss_cannot_start_a_battle(self):
        for boss in (None, BossType.FIVE_STARS):
            with self.subTest(boss=boss):
                owner, _, clicks = self._summon_owner([{'fire': True}])
                owner.cur_boss_type = boss
                self.assertFalse(owner.check_and_switch_ticket(stop_at_six=True))
                self.assertFalse(owner.start_battle((BossType.TWO_STARS,)))
                self.assertFalse(owner.State.targets_finished)
                self.assertEqual(clicks, [])

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

    def test_boss_dispatches_battle_or_assistance_without_ticket_runner(self):
        from tasks.MetaDemon.script_task import ScriptTask
        from tasks.MetaDemon.assets import MetaDemonAssets
        for next_mode in (MetaDemonMode.BOSS_BATTLE, MetaDemonMode.BOSS_ASSIST):
            owner = object.__new__(ScriptTask)
            owner.config = SimpleNamespace(meta_demon=MetaDemon(meta_demon_config={
                'mode': [next_mode]}))
            owner.device = SimpleNamespace(image=object())
            owner.goto_page, owner.screenshot = Mock(), Mock()
            owner.appear = Mock(return_value=True)
            with patch.object(MetaDemonAssets.O_METADEMON_PASS_EXP, 'ocr_digit_counter', return_value=(50,0,50)), \
                 patch('tasks.MetaDemon.boss_battle.BossBattle.run', return_value='battle') as battle, \
                 patch('tasks.MetaDemon.assistance.run_assistance', return_value='assistance') as assistance:
                self.assertEqual(owner.run(), 'battle' if next_mode == MetaDemonMode.BOSS_BATTLE else 'assistance')
                self.assertEqual(battle.call_count, int(next_mode == MetaDemonMode.BOSS_BATTLE))
                self.assertEqual(assistance.call_count, int(next_mode == MetaDemonMode.BOSS_ASSIST))

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
        self.assertTrue(owner.check_and_switch_soul())
        owner.goto_page.assert_not_called()


if __name__ == '__main__':
    unittest.main()
