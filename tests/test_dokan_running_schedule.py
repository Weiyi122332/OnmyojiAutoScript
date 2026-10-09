"""Dojo running state survives dashboard refreshes without touching the game."""

import asyncio
import copy
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from module.config.config import Config
from module.server.script_process import ScriptProcess, ScriptState
from script import Script


def process_fixture():
    process = ScriptProcess.__new__(ScriptProcess)
    process.state = ScriptState.RUNNING
    process._process = Mock()
    process._process.is_alive.return_value = True
    process._latest_schedule = {
        'running': {'name': 'Dokan', 'next_run': '2026-10-09 20:55:01'},
        'pending': [], 'waiting': [],
    }
    return process


class LiveDokanScheduleTests(unittest.TestCase):
    def test_reconnect_keeps_active_dojo_even_when_saved_plan_is_in_the_future(self):
        process = process_fixture()
        config = SimpleNamespace(task=None, scheduler_update_dt=datetime(2026, 10, 9, 21),
            pending_task=[], waiting_task=[
                SimpleNamespace(command='Dokan', next_run=datetime(2028, 2, 29)),
                SimpleNamespace(command='RyouToppa', next_run=datetime(2026, 10, 9, 22)),
            ])
        fresh = Config.get_schedule_data(config)
        before = copy.deepcopy(fresh)
        self.assertEqual(fresh['running'], {})

        result = process.schedule_with_live_dokan(fresh)

        self.assertEqual(result['running']['name'], 'Dokan')
        self.assertEqual([item['name'] for item in result['waiting']], ['RyouToppa'])
        self.assertEqual(fresh, before)

    def test_refresh_preserves_other_tasks_and_removes_duplicate_dojo_rows(self):
        process = process_fixture()
        fresh = {'running': {}, 'pending': [{'name': 'Dokan'}, {'name': 'Duel'}],
                 'waiting': [{'name': 'Dokan'}, {'name': 'RyouToppa'}]}
        result = process.schedule_with_live_dokan(fresh)
        self.assertEqual([item['name'] for item in result['pending']], ['Duel'])
        self.assertEqual([item['name'] for item in result['waiting']], ['RyouToppa'])

    def test_other_tasks_and_missing_live_schedule_keep_existing_behavior(self):
        process = process_fixture()
        fresh = {'running': {'name': 'RyouToppa'}, 'pending': [], 'waiting': []}
        for cached in (None, {'running': {}}, {'running': {'name': 'Duel'}}):
            process._latest_schedule = cached
            self.assertIs(process.schedule_with_live_dokan(fresh), fresh)

    def test_stopped_failed_or_dead_process_cannot_report_stale_dojo(self):
        process = process_fixture()
        fresh = {'running': {}, 'pending': [], 'waiting': []}
        for state in (ScriptState.INACTIVE, ScriptState.WARNING, ScriptState.UPDATING):
            process.state = state
            self.assertIs(process.schedule_with_live_dokan(fresh), fresh)
        process.state = ScriptState.RUNNING
        process._process.is_alive.return_value = False
        self.assertIs(process.schedule_with_live_dokan(fresh), fresh)
        process._process = None
        self.assertIs(process.schedule_with_live_dokan(fresh), fresh)

    def test_dojo_start_and_finish_publish_matching_dashboard_state(self):
        task = Script.__new__(Script)
        task.state_queue = Mock()
        fresh = {'running': {}, 'pending': [{'name': 'Duel'}], 'waiting': [{'name': 'Dokan'}]}
        task.__dict__['config'] = SimpleNamespace(get_schedule_data=lambda: copy.deepcopy(fresh))

        task._publish_dokan_schedule(running=True)
        started = task.state_queue.put.call_args.args[0]['schedule']
        self.assertEqual(started['running']['name'], 'Dokan')
        self.assertEqual(started['waiting'], [])

        task._publish_dokan_schedule(running=False)
        finished = task.state_queue.put.call_args.args[0]['schedule']
        self.assertEqual(finished['running'], {})
        process = process_fixture()
        process._latest_schedule = finished
        self.assertIs(process.schedule_with_live_dokan(fresh), fresh)


class LiveDokanProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_schedule_is_cached_before_broadcast_for_later_reconnects(self):
        process = process_fixture()
        payload = {'schedule': {'running': {'name': 'Dokan'}, 'pending': [], 'waiting': []}}
        process._latest_schedule = None
        process.state_queue = Mock()
        process.state_queue.empty.return_value = False
        process.state_queue.get_nowait.return_value = payload
        process.broadcast_state = AsyncMock(side_effect=asyncio.CancelledError)
        process.config_name = 'test'
        with patch('module.server.script_process.sleep', new=AsyncMock()):
            await process.coroutine_broadcast_state()
        self.assertEqual(process._latest_schedule, payload['schedule'])

    async def test_new_start_and_stop_clear_previous_dojo_schedule(self):
        process = process_fixture()
        process.config_name = 'test'
        process.state_queue = Mock()
        process.log_pipe_in = Mock()
        process.broadcast_state = AsyncMock()
        process._process = None
        child = Mock()
        with patch('module.server.script_process._SCRIPT_PROCESS_CONTEXT.Process', return_value=child):
            await process.start()
        self.assertIsNone(process._latest_schedule)
        child.start.assert_called_once()
        process._latest_schedule = {'running': {'name': 'Dokan'}}
        await process.stop()
        self.assertIsNone(process._latest_schedule)
        self.assertEqual(process.state, ScriptState.INACTIVE)
        child.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
