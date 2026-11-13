"""Ticket pair completion and configuration fallback regression checks."""
from datetime import datetime, timedelta
from threading import Lock
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import TaskEnd
from tasks.Exploration.config import Exploration
from tasks.MetaDemonTicket.config import MetaDemonTicket, TicketMode
from tasks.MetaDemonTicket.ticket_farming import (
    RealmRaidThresholdReached, TicketRewardMixin, TicketsFull, TicketPartnerFinished,
    run_ticket_farming, ticket_farming_config,
)


class ScreenshotBase:
    def screenshot(self):
        return 'frame'


class Probe(TicketRewardMixin, ScreenshotBase):
    pass


class TicketPairChecks(unittest.TestCase):
    def test_room_confirmation_reaches_challenge_without_second_request(self):
        from tasks.MetaDemonTicket.ticket_farming import AwakeTicketTask
        from tasks.Component.GeneralInvite.general_invite import RoomType
        from tasks.Component.GeneralInvite.config_invite import InviteConfig
        runner = object.__new__(AwakeTicketTask)
        runtime = Mock(peers={'MetaDemonTicket': 'other'})
        runtime.request_room_check.return_value = 'check-token'
        runtime.room_check_result.return_value = True
        runner.config = SimpleNamespace(cooperation_runtime=runtime)
        runner._ticket_peer = 'other'
        runner.room_type = RoomType.NORMAL_3
        runner.appear = Mock(return_value=False)
        runner.screenshot = Mock()
        runner.is_in_room = Mock(side_effect=[True, False])
        runner.appear_then_click = Mock(return_value=True)
        invite = InviteConfig(friend_list='friend')
        self.assertTrue(runner.room_check_can_fire(invite))
        runtime.request_room_check.assert_not_called()
        self.assertFalse(runner.click_fire())
        runner.appear_then_click.assert_not_called()
        self.assertTrue(runner.room_check_can_fire(invite))
        runner.click_fire()
        runner.appear_then_click.assert_called_once_with(runner.I_FIRE, interval=1)
        runtime.request_room_check.assert_called_once()

    def probe(self, local_full, peer_status):
        runtime = Mock()
        runtime.peer_task_completion.return_value = peer_status
        runtime.pending_room_check.return_value = None
        task = Probe()
        task.config = SimpleNamespace(cooperation_runtime=runtime)
        task._ticket_peer = 'other'
        task._ticket_phase_started = 1
        task._ticket_farming_complete = False
        task._battle_context = None
        task._ticket_full = local_full
        return task

    def test_one_full_never_completes_pair(self):
        for own, other in [(True, None), (False, 'tickets_full'), (False, None)]:
            self.assertEqual(self.probe(own, other).screenshot(), 'frame')

    def test_both_full_complete_pair(self):
        with self.assertRaises(TicketsFull):
            self.probe(True, 'tickets_full').screenshot()

    def test_local_full_notifies_and_keeps_playing(self):
        task = self.probe(False, None)
        with patch('tasks.MetaDemonTicket.ticket_farming.metademon_tickets_full', return_value=True):
            task.check_ticket_reward()
        self.assertTrue(task._ticket_full)
        task.config.cooperation_runtime.notify_task_completion.assert_called_once_with('MetaDemonTicket', 'other', 'tickets_full')
        self.assertEqual(task.screenshot(), 'frame')

    def test_partner_failure_is_not_pair_success(self):
        with self.assertRaises(TicketPartnerFinished):
            self.probe(True, 'ticket_finished').screenshot()

    def owner(self, matches):
        meta = MetaDemonTicket(general_config={'user_status': 'member'}, invite_config={'cooperation_script': 'other'})
        runtime = Mock(peers={})
        runtime.matches_meta_demon_tickets.return_value = matches
        runtime.prepare.return_value = True
        owner = SimpleNamespace(config=SimpleNamespace(meta_demon_ticket=meta, cooperation_runtime=runtime), device=Mock())
        return owner

    def test_mismatch_does_not_fall_back_to_local_full(self):
        owner = self.owner(False)
        with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming') as precheck:
            self.assertFalse(run_ticket_farming(owner, TicketMode.AWAKE))
            precheck.assert_not_called()

    def test_already_full_member_still_joins_until_both_full(self):
        owner = self.owner(True)
        runner = Mock()
        runner._config = ticket_farming_config(owner.config.meta_demon_ticket, TicketMode.AWAKE)
        runner.run_member.side_effect = TicketsFull
        with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=True), patch('tasks.MetaDemonTicket.ticket_farming.AwakeTicketTask', return_value=runner):
            self.assertTrue(run_ticket_farming(owner, TicketMode.AWAKE))
        runner.run_member.assert_called_once()
        self.assertEqual(runner._ticket_peer, 'other')
        self.assertTrue(runner._ticket_full)

    def test_realm_raid_handoff_cleans_up_and_defers_ticket_farming(self):
        for delay in (timedelta(0), timedelta(minutes=30)):
            with self.subTest(delay=delay):
                events = Mock()
                owner = self.owner(True)
                owner.config.reload = events.reload
                owner.config.task_call = events.task_call
                owner.config.save = events.save
                owner.config.lock_config = Lock()
                events.task_call.return_value = True
                runner = Mock()
                runner._config = Exploration(scrolls={'scrolls_cd': delay})
                runner.finish_exploration = events.finish_exploration
                runner.exec_exp_page.side_effect = RealmRaidThresholdReached
                now = datetime(2026, 11, 11, 12, 0)
                with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=False), \
                        patch('tasks.MetaDemonTicket.ticket_farming.ExplorationTicketTask', return_value=runner), \
                        patch('tasks.MetaDemonTicket.ticket_farming.datetime') as clock:
                    clock.now.return_value = now
                    with self.assertRaises(TaskEnd):
                        run_ticket_farming(owner, TicketMode.EXPLORATION)
                self.assertEqual(events.mock_calls, [
                    call.finish_exploration(),
                    call.reload(),
                    call.task_call('RealmRaid', force_call=False),
                    call.save(),
                ])
                self.assertEqual(owner.config.meta_demon_ticket.scheduler.next_run,
                                 now + max(delay, timedelta(seconds=1)))
                self.assertTrue(owner.config.meta_demon_ticket.scheduler.waiting_for_realm_raid)
                owner.config.cooperation_runtime.notify_task_completion.assert_called_once_with(
                    'MetaDemonTicket', 'other', 'ticket_finished',
                )


if __name__ == '__main__':
    unittest.main()
