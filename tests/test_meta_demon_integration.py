"""Exercise the MetaDemon adapters with the real page graph and cooperation store."""
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import numpy as np

from module.cooperation import Cooperation
from module.exception import TaskEnd
from tasks.Exploration import page as exploration_pages
from tasks.Exploration.base import BaseExploration
from tasks.Exploration.config import Exploration, UserStatus
from tasks.GameUi.registry import PageRegistry
from tasks.GameUi.session import NavigatorSession
from tasks.MetaDemon import page as pages
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.assistance import AssistanceLink
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import MetaDemon
from tasks.MetaDemonTicket.config import MetaDemonTicket
from tasks.MetaDemonTicket.ticket_farming import (
    ExplorationTicketTask, RealmRaidThresholdReached, TicketsFull,
)
from tasks.RealmRaid.config import RealmRaid


class MetaDemonIntegrationTest(unittest.TestCase):
    def test_breakthrough_counter_reads_both_map_layouts_and_the_chapter(self):
        runner = object.__new__(BaseExploration)
        runner.device = SimpleNamespace(image=object())
        runner.O_REALM_RAID_NUMBER = Mock()
        runner.O_REALM_RAID_NUMBER1 = Mock()
        runner.O_REALM_RAID_NUMBER_EVENT = Mock()
        for page, old_map, old_chapter, activity, expected in (
            (exploration_pages.page_exploration, '7/30', '', '', 7),
            (exploration_pages.page_mainline, '33', '', '25/30', 25),
            (exploration_pages.page_exp_entrance, '18', '3/30', '', 3),
            (exploration_pages.page_exp_entrance, '33', '50/50', '29/30', 29),
            (exploration_pages.page_gameplay, '33', '', '50/50', None),
        ):
            with self.subTest(page=page, old_map=old_map, activity=activity):
                runner.O_REALM_RAID_NUMBER.ocr_single.return_value = old_map
                runner.O_REALM_RAID_NUMBER1.ocr_single.return_value = old_chapter
                runner.O_REALM_RAID_NUMBER_EVENT.ocr_single.return_value = activity
                self.assertEqual(runner.read_realm_raid_tickets(page), expected)

    def test_ticket_exploration_checks_the_inherited_threshold_with_scrolls_disabled(self):
        runner = object.__new__(ExplorationTicketTask)
        runner.config = SimpleNamespace(realm_raid=RealmRaid(scheduler={'enable': True}))
        runner.read_realm_raid_tickets = Mock(side_effect=[24, 25, 15])
        settings = Exploration(scrolls={'scrolls_threshold': 25})
        page = exploration_pages.page_mainline
        runner.activate_realm_raid(settings.scrolls, settings.exploration_config, page)
        with self.assertRaises(RealmRaidThresholdReached):
            runner.activate_realm_raid(settings.scrolls, settings.exploration_config, page)
        settings.scrolls.scrolls_threshold = 10
        runner.config.realm_raid.raid_config.number_base = 20
        runner.activate_realm_raid(settings.scrolls, settings.exploration_config, page)
        runner.config.realm_raid.scheduler.enable = False
        runner.activate_realm_raid(settings.scrolls, settings.exploration_config, page)
        self.assertEqual(runner.read_realm_raid_tickets.call_args_list, [call(page)] * 3)

    def test_normal_scrolls_schedules_its_original_tasks(self):
        runner = object.__new__(BaseExploration)
        runner.read_realm_raid_tickets = Mock(return_value=25)
        runner.set_next_run = Mock()
        runner.goto_page = Mock()
        settings = Exploration(scrolls={'scrolls_enable': True, 'scrolls_threshold': 25})
        with self.assertRaises(TaskEnd):
            runner.activate_realm_raid(settings.scrolls, settings.exploration_config, exploration_pages.page_gameplay)
        self.assertEqual([call.kwargs['task'] for call in runner.set_next_run.call_args_list],
                         ['Exploration', 'RealmRaid', 'MemoryScrolls'])

    def test_exploration_tickets_use_the_registered_chapter_pages(self):
        for role in (UserStatus.ALONE, UserStatus.LEADER):
            with self.subTest(role=role):
                runner = ExplorationTicketTask.__new__(ExplorationTicketTask)
                runner.config = SimpleNamespace(meta_demon_ticket=MetaDemonTicket(), exploration=Exploration())
                runner.user_status = role
                runner.wait_start_time = datetime.now()
                runner.current_count = 0
                runner.collect_treasure_box = Mock()
                runner.check_and_invite = Mock(return_value=False)
                runner.ensure_difficulty = Mock()
                runner.goto_page = Mock()
                runner.appear = Mock(return_value=False)

                handlers = runner.exp_page_handle_dict
                handlers[exploration_pages.page_mainline]()
                expected = [call(exploration_pages.page_exp_entrance)]
                if role is UserStatus.ALONE:
                    handlers[exploration_pages.page_exp_entrance]()
                    expected.append(call(exploration_pages.page_exp_main))
                self.assertEqual(runner.goto_page.call_args_list, expected)

    def test_exploration_map_full_counter_stops_before_reopening_chapter(self):
        runner = ExplorationTicketTask.__new__(ExplorationTicketTask)
        runner.device = SimpleNamespace(image=object())
        runner.user_status = UserStatus.ALONE
        runner.appear = Mock(return_value=True)
        runner.goto_page = Mock()
        runner.collect_treasure_box = Mock()
        with patch.object(MetaDemonAssets.O_METADEMON_PASS_EXP, 'ocr_digit_counter',
                          side_effect=[(49, 1, 50), (50, 0, 50)]):
            runner.run_on_exp()
            with self.assertRaises(TicketsFull):
                runner.run_on_exp()
        runner.goto_page.assert_called_once_with(exploration_pages.page_exp_entrance)

    def test_activity_backup_route_is_resolved_in_the_task_session(self):
        PageRegistry.load_all_pages()
        session = NavigatorSession(task_category='meta_demon')
        session.bootstrap(PageRegistry.all())
        pages.configure_activity_navigation(session)
        activity = session.resolve_page(pages.page_activity)
        fallback = MetaDemonAssets.I_MD_CHECK_MAIN_PAGE_BACKUP
        task = SimpleNamespace(appear=Mock(side_effect=lambda rule: rule is fallback), screenshot=Mock(),
                               appear_then_click=Mock(side_effect=lambda rule, **_: rule is fallback))
        self.assertTrue(activity.recognizer.evaluate(task))
        edge = next(edge for edge in activity.transitions if edge.key == 'page_activity->page_meta_demon_boss')
        self.assertTrue(edge.action(task))
        task.appear_then_click.assert_called_with(fallback, interval=0.8)
        self.assertFalse(pages.page_activity.recognizer.evaluate(task))

    def test_frame_panel_scales_ocr_and_clicks_to_the_matched_rectangle(self):
        task = BossBattle.__new__(BossBattle)
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        frame = SimpleNamespace(roi_ranges=[None] * 3, matched_ranges=[(520, 260, 444, 291)])
        layout = task._build_quick_loadout_layout(frame)
        self.assertEqual(tuple(layout.group_ocr.roi), (526, 265, 84, 274))
        self.assertEqual(layout.column(task.PRESET_EQUIP_X), 906)

    def make_pair(self, first, second, task):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'config').mkdir()
        for name, config in (('first', first), ('second', second)):
            (root / 'config' / f'{name}.json').write_text(json.dumps({task: config.model_dump(mode='json')},
                                                                   ensure_ascii=False), encoding='utf-8')
        return Cooperation('first', root), Cooperation('second', root)

    def test_ticket_peer_wake_room_confirmation_and_completion(self):
        first = MetaDemonTicket(scheduler={'enable': True}, general_config={'user_status': 'leader'},
                                invite_config={'cooperation_script': 'second'})
        second = MetaDemonTicket(scheduler={'enable': True}, general_config={'user_status': 'member'})
        leader, member = self.make_pair(first, second, 'meta_demon_ticket')
        leader.publish('MetaDemonTicket')
        member.publish('')
        config = SimpleNamespace(model=SimpleNamespace(meta_demon_ticket=second), reload=Mock(), task_call=Mock())
        self.assertTrue(leader.prepare(None, 'MetaDemonTicket', 'second', defer=False))
        self.assertEqual(member.wake_next(config), 'MetaDemonTicket')
        config.task_call.assert_called_once_with('MetaDemonTicket', force_call=False)
        member.publish('MetaDemonTicket')
        token = leader.request_room_check('MetaDemonTicket', 'second')
        self.assertIsNone(leader.room_check_result('MetaDemonTicket', 'second', token))
        self.assertEqual(member.pending_room_check('MetaDemonTicket', 'first'), token)
        member.answer_room_check('MetaDemonTicket', 'first', token, True)
        self.assertTrue(leader.room_check_result('MetaDemonTicket', 'second', token))
        since = leader.begin_completion_phase('MetaDemonTicket', 'second')
        member.notify_task_completion('MetaDemonTicket', 'first', 'tickets_full')
        self.assertEqual(leader.peer_task_completion('MetaDemonTicket', 'second', since), 'tickets_full')

    def test_assistance_acknowledgement_uses_the_current_boss_session(self):
        first = MetaDemon(scheduler={'enable': True}, meta_demon_config={'mode': ['鬼王协助']},
                          assistance_config={'role': '上供', 'cooperation_script': 'second'})
        second = MetaDemon(scheduler={'enable': True}, meta_demon_config={'mode': ['鬼王协助']},
                           assistance_config={'role': '协助'})
        offer, assist = self.make_pair(first, second, 'meta_demon')
        offer.publish('MetaDemon')
        assist.publish('MetaDemon')

        def link(runtime, conf):
            return AssistanceLink(SimpleNamespace(conf=conf, config=SimpleNamespace(cooperation_runtime=runtime)))

        sender, receiver = link(offer, first), link(assist, second)
        self.assertTrue(sender.wait_for_peer())
        sender.publish('fixture-portrait')
        target = receiver.target()
        self.assertEqual(target[2], 'fixture-portrait')
        receiver.confirm(target, settled=True)
        self.assertTrue(sender.peer_settled())
        sender.publish('new-boss-portrait')
        self.assertFalse(sender.confirmed())
        self.assertEqual(receiver.target()[2], 'new-boss-portrait')
        sender.publish(completed=True)
        self.assertIsNone(receiver.target())
        self.assertTrue(receiver.peer_completed())
        sender.publish('interrupted-portrait')
        self.assertFalse(receiver.peer_completed())
        offer.publish('')
        self.assertIsNone(receiver.target())
        offer.publish('MetaDemon')
        self.assertIsNone(receiver.target())
