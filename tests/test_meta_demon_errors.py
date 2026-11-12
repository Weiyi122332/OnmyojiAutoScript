"""MetaDemon failures must stop on the failed screen instead of returning home."""
from types import SimpleNamespace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from module.exception import (
    GameBugError, GameNotRunningError, GamePageUnknownError, GameStuckError,
    GameTooManyClickError, MetaDemonError, RequestHumanTakeover, ScriptError, TaskEnd,
)
from script import Script
from tasks.Component.QuickLoadout.config import QuickLoadoutConfig, QuickLoadoutMode
from tasks.MetaDemon import page as pages
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import BossType, MetaDemon


class MetaDemonFailureTests(unittest.TestCase):
    def make_task(self):
        task = BossBattle.__new__(BossBattle)
        task.State = BossBattle.State()
        task.conf = MetaDemon()
        task.before_run = Mock()
        task.goto_page = Mock()
        task.screenshot = Mock()
        task.get_current_page = Mock(return_value=pages.page_meta_demon_boss)
        task.check_and_prepare_battle = Mock(return_value=True)
        task.start_battle = Mock(return_value=True)
        task.appear = Mock(return_value=False)
        task.set_next_run = Mock()
        task.finish_task = Mock()
        task.push_targets_finished = Mock()
        return task

    def test_failed_preparation_or_start_never_finishes_or_reschedules(self):
        for stage, message in (('check_and_prepare_battle', '战斗准备失败'),
                               ('start_battle', '未能进入战斗')):
            with self.subTest(stage=stage):
                task = self.make_task()
                getattr(task, stage).return_value = False
                with self.assertRaisesRegex(ScriptError, message):
                    task.run()
                task.goto_page.assert_called_once_with(pages.page_meta_demon_boss)
                task.finish_task.assert_not_called()
                task.set_next_run.assert_not_called()
                task.push_targets_finished.assert_not_called()

    def test_settling_after_prepare_is_not_a_failure(self):
        task = self.make_task()
        task.start_battle.return_value = False
        task.appear.return_value = True

        def prepare():
            if task.start_battle.called:
                task.State.done = True
                return False
            return True

        task.check_and_prepare_battle.side_effect = prepare
        task.run()
        task.start_battle.assert_called_once()
        task.set_next_run.assert_called_once_with(task='MetaDemon', success=True)
        task.finish_task.assert_called_once()

    def test_navigation_error_retains_task_identity_when_run_in_a_group(self):
        task = self.make_task()
        error = GameStuckError('navigation timed out')
        task.goto_page.side_effect = error
        with self.assertRaisesRegex(MetaDemonError, 'navigation timed out') as caught:
            task.run()
        self.assertIs(caught.exception.__cause__, error)
        task.set_next_run.assert_not_called()
        task.finish_task.assert_not_called()

    def test_unreadable_name_does_not_choose_a_generic_preset(self):
        task = self.make_task()
        task.cur_boss_type = BossType.FIVE_STARS
        task._read_quick_loadout_stage_name = Mock(return_value='   ')
        task.run_quick_loadout = Mock()
        with self.assertRaisesRegex(ScriptError, '鬼王名称'):
            task.prepare_boss_preset()
        task.run_quick_loadout.assert_not_called()
        self.assertIsNone(task._active_preset)

    def test_missing_fire_button_does_not_navigate_away(self):
        task = self.make_task()
        task.ui_click = Mock()
        with self.assertRaisesRegex(ScriptError, '未找到挑战按钮'):
            task.check_and_switch_powerful()
        task.goto_page.assert_not_called()
        task.ui_click.assert_not_called()

    def test_failed_quick_loadout_preserves_panel_and_clears_cache(self):
        stages = (
            ('_open_quick_loadout', False, '无法打开'),
            ('_select_group', False, '分组'),
            ('_select_preset_row', None, '阵容'),
            ('_deploy_quick_loadout', False, '出战成功'),
        )
        for stage, result, message in stages:
            with self.subTest(stage=stage):
                task = self.make_task()
                task._last_quick_loadout = ('previous',)
                task._open_quick_loadout = Mock(return_value=True)
                task._build_quick_loadout_layout = Mock()
                task._select_group = Mock(return_value=True)
                task._select_preset_row = Mock(return_value=250)
                task._deploy_quick_loadout = Mock(return_value=True)
                task._dismiss_quick_loadout = Mock()
                getattr(task, stage).return_value = result
                config = QuickLoadoutConfig(enable=True, mode=QuickLoadoutMode.OCR,
                                            group_name='队伍租借', preset_name='普攻')
                with self.assertRaisesRegex(ScriptError, message):
                    task.run_quick_loadout(config, frame=task.F_QUICK_LOADOUT_FRAME)
                task._dismiss_quick_loadout.assert_not_called()
                task.goto_page.assert_not_called()
                self.assertIsNone(task._last_quick_loadout)

    def test_ocr_exception_does_not_close_the_preset_panel(self):
        task = self.make_task()
        task._open_quick_loadout = Mock(return_value=True)
        task._build_quick_loadout_layout = Mock()
        task._select_group = Mock(return_value=True)
        task._select_preset_row = Mock(side_effect=RuntimeError('OCR unavailable'))
        task._dismiss_quick_loadout = Mock()
        config = QuickLoadoutConfig(enable=True, mode=QuickLoadoutMode.NUMBER,
                                    group_number=5, preset_number=1)
        with self.assertRaisesRegex(RuntimeError, 'OCR unavailable'):
            task.run_quick_loadout(config, frame=task.F_QUICK_LOADOUT_FRAME)
        task._dismiss_quick_loadout.assert_not_called()

    def test_deploy_timeout_preserves_the_open_panel(self):
        task = self.make_task()
        task.device = SimpleNamespace(click=Mock())
        task.click = Mock()
        task._quick_loadout_panel_visible = Mock(return_value=True)
        task._quick_loadout_fight = Mock()
        task._dismiss_quick_loadout = Mock()
        layout = task._quick_loadout_layout_at((496, 224, 553, 387))
        with patch('tasks.MetaDemon.quick_loadout.Timer') as timer, \
                patch('tasks.MetaDemon.quick_loadout.sleep'):
            timer.return_value.start.return_value.reached.side_effect = [False, True]
            with self.assertRaisesRegex(ScriptError, '出战超时'):
                task._deploy_quick_loadout(layout, task.F_QUICK_LOADOUT_FRAME, 249, equip_soul=True)
        task._dismiss_quick_loadout.assert_not_called()

    def test_repeated_synthesis_verification_failure_is_an_error(self):
        task = self.make_task()
        task.device = SimpleNamespace(image=object())
        task.ticket_matches_star = Mock(return_value=True)
        task.click = Mock(return_value=True)
        task.appear_then_click = Mock()
        task.O_SYNTHESIS_LEVEL = Mock()
        task.O_SYNTHESIS_LEVEL.ocr.return_value = ''
        with patch('tasks.MetaDemon.boss_battle.time.sleep'):
            with self.assertRaisesRegex(ScriptError, '连续三次无法确认目标合成星级'):
                task.do_synthesis(task.I_MD_SYNTHESIS_ONE_STAR, 3, BossType.ONE_STAR)
        self.assertEqual(task.click.call_count, 3)
        task.appear_then_click.assert_not_called()

    def test_synthesis_retry_limit_accepts_reward_but_rejects_missing_result(self):
        for reward in (False, True):
            with self.subTest(reward=reward):
                task = self.make_task()
                task.device = SimpleNamespace(image=object())
                task.ticket_matches_star = Mock(return_value=True)
                task.O_SYNTHESIS_LEVEL = Mock()
                task.O_SYNTHESIS_LEVEL.ocr.return_value = '合成二星裂变之眼'
                task.appear_then_click = Mock(return_value=True)
                task.click = Mock(return_value=True)
                # The reward arrives at the retry limit; the next frame has no materials.
                task.appear.side_effect = lambda rule, **kw: (
                    rule is task.I_UI_REWARD and reward
                    and task.appear_then_click.call_count == 2
                    and task.click.call_count == 2
                )
                task.ticket_matches_star.side_effect = lambda *a, **kw: task.click.call_count < 3
                with patch('tasks.MetaDemon.boss_battle.time.sleep'), \
                        patch('tasks.MetaDemon.boss_battle.random.randint', return_value=2):
                    if reward:
                        task.do_synthesis(task.I_MD_SYNTHESIS_ONE_STAR, 3, BossType.ONE_STAR)
                    else:
                        with self.assertRaisesRegex(ScriptError, '无法确认合成结果'):
                            task.do_synthesis(task.I_MD_SYNTHESIS_ONE_STAR, 3, BossType.ONE_STAR)
                self.assertEqual(task.appear_then_click.call_count, 2)


class MetaDemonExceptionHandlingTests(unittest.TestCase):
    def make_script(self):
        script = Script.__new__(Script)
        script.config_name = 'test'
        script.config = SimpleNamespace(notifier=Mock(), task_call=Mock())
        script.device = Mock(package='game.package')
        script.save_error_log = Mock()
        script.exception_handler = Mock()
        script._request_error_restart = Mock()
        script._capture_task_runtime_outcome = Mock()
        return script

    def test_all_task_failures_save_evidence_and_stop_without_recovery(self):
        for error in (ScriptError, GameStuckError, GameTooManyClickError, GameBugError,
                      GamePageUnknownError, GameNotRunningError, RequestHumanTakeover, RuntimeError):
            with self.subTest(error=error), patch('script.logger'):
                script = self.make_script()
                with self.assertRaises(SystemExit) as caught:
                    script._handle_task_exception(error('识别失败'), 'MetaDemon')
                self.assertEqual(caught.exception.code, 1)
                script.save_error_log.assert_called_once()
                script.config.notifier.push.assert_called_once()
                self.assertIn('识别失败', script.config.notifier.push.call_args.kwargs['content'])
                script.exception_handler.assert_not_called()
                script._request_error_restart.assert_not_called()
                script.config.task_call.assert_not_called()
                script.device.sleep.assert_not_called()
                script._capture_task_runtime_outcome.assert_not_called()

    def test_normal_completion_and_fatigue_wait_remain_successful(self):
        script = self.make_script()
        self.assertTrue(script._handle_task_exception(TaskEnd(), 'MetaDemon'))
        script._capture_task_runtime_outcome.assert_called_once_with('MetaDemon')
        script.save_error_log.assert_not_called()
        script.config.notifier.push.assert_not_called()

    def test_nested_meta_demon_failure_does_not_restart_the_task_group(self):
        script = self.make_script()
        with patch('script.logger'), self.assertRaises(SystemExit):
            script._handle_task_exception(MetaDemonError('navigation timed out'), 'TaskGroup1')
        script.save_error_log.assert_called_once()
        script._request_error_restart.assert_not_called()
        script.config.notifier.push.assert_called_once()

    def test_reporting_failure_still_stops_the_script(self):
        for broken in ('save_error_log', 'notify'):
            with self.subTest(broken=broken), patch('script.logger'):
                script = self.make_script()
                if broken == 'save_error_log':
                    script.save_error_log.side_effect = OSError('disk unavailable')
                else:
                    script.config.notifier.push.side_effect = RuntimeError('notify unavailable')
                with self.assertRaises(SystemExit) as caught:
                    script._handle_task_exception(ScriptError('识别失败'), 'MetaDemon')
                self.assertEqual(caught.exception.code, 1)
                script.config.notifier.push.assert_called_once()
                script._request_error_restart.assert_not_called()

    def test_error_archive_keeps_the_cause_without_a_section_separator(self):
        script = self.make_script()
        script.config.script = SimpleNamespace(error=SimpleNamespace(save_error=True))
        script.device.screenshot_deque = []
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'log').mkdir()
            source = root / 'log' / 'source.txt'
            source.write_text('开始超鬼王\nOCR 识别失败\n脚本已停止\n保存报错现场\n', encoding='utf-8')
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch('script.logger', Mock(log_file=str(source))):
                    Script.save_error_log(script)
            finally:
                os.chdir(previous)
            archived = list((root / 'log' / 'error').glob('*/log.txt'))
            self.assertEqual(len(archived), 1)
            self.assertIn('OCR 识别失败', archived[0].read_text(encoding='utf-8'))

    def test_other_tasks_keep_existing_recovery(self):
        script = self.make_script()
        with patch('script.logger'), patch('script.I18n.trans_zh_cn', return_value='御魂'):
            self.assertFalse(script._handle_task_exception(GameStuckError('stuck'), 'Orochi'))
        script._request_error_restart.assert_called_once_with('Orochi')
        script.device.sleep.assert_called_once_with(10)


if __name__ == '__main__':
    unittest.main()
