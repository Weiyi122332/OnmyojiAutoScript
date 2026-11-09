"""Exercise the MetaDemon adapters with the real page graph and cooperation store."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from module.cooperation import Cooperation
from tasks.GameUi.registry import PageRegistry
from tasks.GameUi.session import NavigatorSession
from tasks.MetaDemon import page as pages
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.assistance import AssistanceLink
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import MetaDemon
from tasks.MetaDemonTicket.config import MetaDemonTicket


class MetaDemonIntegrationTest(unittest.TestCase):
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
            return AssistanceLink(SimpleNamespace(conf=conf, config=SimpleNamespace(cooperation_runtime=runtime),
                                                   limit_time=timedelta(minutes=1), start_time=datetime.now()))

        sender, receiver = link(offer, first), link(assist, second)
        self.assertTrue(sender.wait_for_peer())
        sender.publish('fixture-portrait')
        target = receiver.target()
        self.assertEqual(target[2], 'fixture-portrait')
        receiver.confirm(target, settled=True)
        self.assertTrue(sender.peer_settled())
        sender.publish('new-boss-portrait')
        self.assertFalse(sender.confirmed())
