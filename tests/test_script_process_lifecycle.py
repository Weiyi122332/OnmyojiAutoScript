"""Repeated start requests must never leave two workers controlling one device."""
import asyncio
from threading import RLock
import unittest
from unittest.mock import AsyncMock, Mock, patch

from module.server.script_process import ScriptProcess, ScriptState


class ScriptProcessLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(self):
        manager = ScriptProcess.__new__(ScriptProcess)
        manager.config_name = 'test'
        manager.state = ScriptState.INACTIVE
        manager._process = None
        manager._process_lock = RLock()
        manager._latest_schedule = None
        manager.state_queue = Mock()
        manager.log_pipe_in = Mock()
        manager.broadcast_state = AsyncMock()
        return manager

    def make_child(self):
        child = Mock()
        child.is_alive.return_value = False
        child.start.side_effect = lambda: setattr(child.is_alive, 'return_value', True)
        child.terminate.side_effect = lambda: setattr(child.is_alive, 'return_value', False)
        child.kill.side_effect = lambda: setattr(child.is_alive, 'return_value', False)
        return child

    async def test_duplicate_start_preserves_the_worker_and_running_schedule(self):
        manager = self.make_manager()
        child = self.make_child()
        schedule = {'running': {'name': 'MetaDemon'}}
        with patch('module.server.script_process._SCRIPT_PROCESS_CONTEXT.Process', return_value=child) as factory:
            await manager.start()
            manager._latest_schedule = schedule
            await manager.start()
        factory.assert_called_once()
        child.start.assert_called_once()
        child.terminate.assert_not_called()
        self.assertIs(manager._process, child)
        self.assertIs(manager._latest_schedule, schedule)
        self.assertEqual(manager.state, ScriptState.RUNNING)

    async def test_concurrent_starts_before_broadcast_finishes_create_one_worker(self):
        manager = self.make_manager()
        child = self.make_child()
        broadcasting = asyncio.Event()
        release = asyncio.Event()

        async def broadcast(payload):
            broadcasting.set()
            await release.wait()

        manager.broadcast_state = AsyncMock(side_effect=broadcast)
        with patch('module.server.script_process._SCRIPT_PROCESS_CONTEXT.Process', return_value=child) as factory:
            first = asyncio.create_task(manager.start())
            await broadcasting.wait()
            second = asyncio.create_task(manager.start())
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)
        factory.assert_called_once()
        child.start.assert_called_once()
        self.assertIs(manager._process, child)

    async def test_stop_waits_for_exit_before_another_start(self):
        manager = self.make_manager()
        first, second = self.make_child(), self.make_child()
        order = Mock()
        order.attach_mock(first.terminate, 'terminate')
        order.attach_mock(first.join, 'join')
        order.attach_mock(second.start, 'start')
        with patch('module.server.script_process._SCRIPT_PROCESS_CONTEXT.Process', side_effect=[first, second]):
            await manager.start()
            await manager.stop()
            self.assertIsNone(manager._process)
            self.assertEqual(manager.state, ScriptState.INACTIVE)
            await manager.start()
        self.assertEqual([event[0] for event in order.mock_calls], ['terminate', 'join', 'start'])
        self.assertFalse(first.is_alive())
        self.assertIs(manager._process, second)

    async def test_stop_uses_kill_if_terminate_has_not_finished(self):
        manager = self.make_manager()
        child = self.make_child()
        child.start()
        child.terminate.side_effect = None
        manager._process = child
        await manager.stop()
        child.kill.assert_called_once()
        self.assertEqual(child.join.call_count, 2)
        self.assertIsNone(manager._process)

    async def test_dead_worker_is_reaped_before_a_new_worker_starts(self):
        manager = self.make_manager()
        old, new = self.make_child(), self.make_child()
        manager._process = old
        with patch('module.server.script_process._SCRIPT_PROCESS_CONTEXT.Process', return_value=new):
            await manager.start()
        old.join.assert_called_once_with(timeout=0)
        self.assertIs(manager._process, new)


if __name__ == '__main__':
    unittest.main()
