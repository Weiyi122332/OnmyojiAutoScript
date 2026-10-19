"""Reaching celeb rank satisfies the ordinary Duel score goal."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.exception import TaskEnd
from tasks.Duel.config import Duel
from tasks.Duel.script_task import ScriptTask


class DuelWeeklyGoalTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 12, 40)
        for target, kwargs in (
            ('logger', {}), ('datetime', {}), ('date', {'wraps': date}),
        ):
            patcher = patch('tasks.Duel.script_task.' + target, **kwargs)
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            if target == 'datetime':
                mocked.now.return_value = self.now
            elif target == 'date':
                mocked.today.return_value = self.now.date()

    def make_task(self, *, celeb=True, celeb_battle=False, stars=0):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = Duel()
        task.conf.duel_config.target_score = 3000
        task.conf.duel_celeb_config.celeb_battle = celeb_battle
        task.conf.duel_celeb_config.celeb_star = 8
        task.config = SimpleNamespace(duel=task.conf, reload=Mock(), save=Mock())
        task.start_time = self.now
        task.limit_time = timedelta(minutes=30)
        task.is_celeb = celeb
        task.current_celeb_star = stars
        task.current_score = 0
        task._weekly_goal_reached = False
        task.appear = Mock(return_value=False)
        task.update_duel_status = Mock()
        return task

    def test_celeb_rank_meets_ordinary_goal_without_a_star_requirement(self):
        for stars, target in ((0, 8), (7, 8), (8, 8), (0, 0)):
            with self.subTest(stars=stars, star_target=target):
                task = self.make_task(stars=stars)
                task.conf.duel_celeb_config.celeb_star = target
                self.assertFalse(task.can_start_duel())
                self.assertTrue(task._weekly_goal_reached)

    def test_enabled_celeb_battles_keep_their_star_goal(self):
        for stars, can_start in ((7, True), (8, False)):
            with self.subTest(stars=stars):
                task = self.make_task(celeb_battle=True, stars=stars)
                self.assertEqual(task.can_start_duel(), can_start)
                self.assertEqual(task._weekly_goal_reached, not can_start)

    def test_ordinary_rank_still_requires_the_target_score(self):
        for score, can_start in ((2999, True), (3000, False)):
            with self.subTest(score=score):
                task = self.make_task(celeb=False)
                task.current_score = score
                self.assertEqual(task.can_start_duel(), can_start)
                self.assertEqual(task._weekly_goal_reached, not can_start)

    def test_run_saves_the_date_and_schedules_without_starting_a_battle(self):
        for weekly_skip in (True, False):
            with self.subTest(weekly_skip=weekly_skip):
                task = self.make_task(stars=0)
                task.conf.duel_config.skip_when_weekly_goal_reached = weekly_skip
                saved_dates = []
                task.config.save.side_effect = lambda: saved_dates.append(
                    task.config.duel.duel_config.weekly_goal_reached_on)
                task.prepare_duel = Mock()
                task.screenshot = Mock()
                task.dismiss_duel_main_useless_message = Mock(return_value=False)
                task.check_and_get_reward = Mock()
                task.duel_main = Mock(return_value=True)
                task.goto_page = Mock()
                task.start_duel = Mock(side_effect=AssertionError('celeb battle is disabled'))
                task.set_next_run_next_monday = Mock()
                task.set_next_run = Mock()

                with self.assertRaises(TaskEnd):
                    task.run()

                self.assertEqual(saved_dates, ['2026-10-18'])
                self.assertEqual(task.config.duel.duel_config.weekly_goal_reached_on,
                                 '2026-10-18')
                task.start_duel.assert_not_called()
                if weekly_skip:
                    task.set_next_run_next_monday.assert_called_once_with(task='Duel')
                    task.set_next_run.assert_not_called()
                else:
                    task.set_next_run.assert_called_once_with(task='Duel', success=True, finish=True)
                    task.set_next_run_next_monday.assert_not_called()


if __name__ == '__main__':
    unittest.main()
