"""公共按住拖动的离线检查，不连接设备或启动游戏。"""

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from module.device.control import Control
from module.device.device import Device
from module.device.method.scrcpy import const
from tasks.Chess.runtime.hand_operations import ChessHandOperationsMixin


class PressAndDragChecks(unittest.TestCase):
    def device(self, method):
        device = Mock()
        device.config.script.device.control_method = method
        device._scrcpy_control_socket_lock = nullcontext()
        device._format_action_duration.return_value = '[offline] '
        builder = device.minitouch_builder
        for name in ('down', 'move', 'up', 'commit', 'wait'):
            getattr(builder, name).return_value = builder
        return device

    def drag(self, device, **kwargs):
        return Control.press_and_drag(
            device, (100, 100), (400, 300), point_random=(0, 0, 0, 0),
            name='shared_drag', **kwargs,
        )

    def test_available_on_every_device(self):
        self.assertIs(Device.press_and_drag, Control.press_and_drag)

    def test_complete_gesture_on_each_touch_transport(self):
        for method in ('minitouch', 'uiautomator2', 'scrcpy'):
            with self.subTest(method=method):
                device = self.device(method)
                self.drag(device)
                device.handle_control_check.assert_called_once_with('shared_drag')
                device._invalidate_image_batch_cache.assert_called_once()
                device.swipe_adb.assert_not_called()
                if method == 'minitouch':
                    builder = device.minitouch_builder
                    builder.down.assert_called_once_with(100, 100)
                    self.assertEqual(builder.move.call_args_list[-1], call(400, 300))
                    builder.up.assert_called_once_with()
                    device.minitouch_send.assert_called_once()
                elif method == 'uiautomator2':
                    touch = device.u2.touch
                    self.assertEqual(touch.mock_calls[0], call.down(100, 100))
                    self.assertEqual(touch.mock_calls[-1], call.up(400, 300))
                    self.assertGreater(touch.move.call_count, 1)
                else:
                    events = device._scrcpy_control.touch.call_args_list
                    self.assertEqual(events[0], call(100, 100, const.ACTION_DOWN))
                    self.assertEqual(events[-1], call(400, 300, const.ACTION_UP))
                    self.assertTrue(all(c.args[-1] == const.ACTION_MOVE for c in events[1:-1]))

    def test_transport_failure_releases_without_replaying_drag(self):
        for method in ('minitouch', 'uiautomator2', 'scrcpy'):
            with self.subTest(method=method):
                device = self.device(method)
                if method == 'minitouch':
                    device.minitouch_send.side_effect = [RuntimeError('offline failure'), None]
                elif method == 'uiautomator2':
                    device.u2.touch.move.side_effect = RuntimeError('offline failure')
                else:
                    def fail_move(*args):
                        if args[-1] == const.ACTION_MOVE:
                            raise RuntimeError('offline failure')
                    device._scrcpy_control.touch.side_effect = fail_move
                with self.assertRaisesRegex(RuntimeError, 'offline failure'):
                    self.drag(device)
                if method == 'minitouch':
                    device.minitouch_builder.down.assert_called_once()
                    self.assertEqual(device.minitouch_send.call_count, 2)
                    self.assertEqual(device.minitouch_builder.up.call_count, 2)
                elif method == 'uiautomator2':
                    device.u2.touch.down.assert_called_once()
                    device.u2.touch.up.assert_called_once()
                else:
                    events = device._scrcpy_control.touch.call_args_list
                    self.assertEqual(sum(c.args[-1] == const.ACTION_DOWN for c in events), 1)
                    self.assertEqual(events[-1].args[-1], const.ACTION_UP)

    def test_control_rejection_does_not_start_gesture(self):
        device = self.device('minitouch')
        device.handle_control_check.side_effect = RuntimeError('control rejected')
        with self.assertRaisesRegex(RuntimeError, 'control rejected'):
            self.drag(device)
        device.minitouch_builder.down.assert_not_called()
        device.minitouch_send.assert_not_called()

    def test_adb_fallback_retains_custom_timing(self):
        device = self.device('ADB')
        self.drag(device, hold_duration=0.6, swipe_duration=0.8)
        device.swipe_adb.assert_called_once()
        args, kwargs = device.swipe_adb.call_args
        self.assertEqual(args, ([100, 100], [400, 300]))
        self.assertGreaterEqual(kwargs['duration'], 0.6 + 0.8 * 0.92)
        self.assertLessEqual(kwargs['duration'], 0.6 + 0.8 * 1.08)

    def test_chess_retries_only_after_business_confirmation_is_missing(self):
        owner = SimpleNamespace(
            device=Mock(), chess_state=SimpleNamespace(drag_pending=set()),
        )
        kwargs = dict(p1=(100, 100), p2=(400, 300), name='chess_deploy')
        ChessHandOperationsMixin._drag_chess(owner, **kwargs)
        ChessHandOperationsMixin._drag_chess(owner, **kwargs)
        self.assertEqual(owner.device.press_and_drag.call_args_list, [
            call(**kwargs, retry=False), call(**kwargs, retry=True),
        ])
        ChessHandOperationsMixin._confirm_chess_drag(owner, 'chess_deploy')
        self.assertEqual(owner.chess_state.drag_pending, set())
        owner.device.click_record_remove.assert_called_once_with('chess_deploy')


if __name__ == '__main__':
    unittest.main()
