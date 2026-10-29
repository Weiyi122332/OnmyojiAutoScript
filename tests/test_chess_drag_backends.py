"""Chess gestures release the finger and never replay an uncertain transport send."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.device.method.scrcpy.core import ScrcpyCore
from module.device.method.scrcpy.control import ControlSender
from tasks.Chess.runtime import press_and_drag as drag


class ChessDragBackendsTest(unittest.TestCase):
    def test_scrcpy_shared_lock_can_reenter_for_real_control_packets(self):
        lock = ScrcpyCore._scrcpy_control_socket_lock
        with lock:
            acquired = lock.acquire(blocking=False)
            self.assertTrue(acquired, 'Chess holds the socket lock while ControlSender acquires it again')
            if acquired:
                lock.release()
        device = SimpleNamespace(_scrcpy_control_socket_lock=lock, _scrcpy_resolution=(1280, 720),
                                 _scrcpy_control_socket=Mock(), scrcpy_ensure_running=Mock(), sleep=Mock())
        device._scrcpy_control = ControlSender(device)
        drag._press_and_drag_scrcpy(device, (500, 600), (90, 650), .04, (0, 0, 0, 0), .30, .05)
        actions = [call.args[0][1] for call in device._scrcpy_control_socket.send.call_args_list]
        self.assertEqual((actions[0], actions[-1]), (0, 1))
        self.assertTrue(all(action == 2 for action in actions[1:-1]))

    def test_uiautomator_and_scrcpy_release_after_a_move_error(self):
        for backend in ('uiautomator2', 'scrcpy'):
            with self.subTest(backend=backend):
                touch = Mock()
                device = SimpleNamespace(sleep=Mock(), scrcpy_ensure_running=Mock(),
                                         _scrcpy_control_socket_lock=threading.RLock())
                if backend == 'uiautomator2':
                    device.u2 = SimpleNamespace(touch=touch)
                    touch.move.side_effect = OSError('uncertain MOVE')
                    method = drag._press_and_drag_uiautomator2
                else:
                    device._scrcpy_control = touch
                    def send(x, y, action):
                        if action == 2:
                            raise OSError('uncertain MOVE')
                    touch.touch.side_effect = send
                    method = drag._press_and_drag_scrcpy
                with self.assertRaises(OSError):
                    method(device, (500, 600), (90, 650), .04, (0, 0, 0, 0), .30, .05)
                if backend == 'uiautomator2':
                    touch.down.assert_called_once()
                    touch.move.assert_called_once()
                    touch.up.assert_called_once()
                else:
                    self.assertEqual([call.args[2] for call in touch.touch.call_args_list], [0, 2, 1])

    def test_failed_minitouch_send_discards_moves_and_sends_only_a_release(self):
        builder = Mock()
        for name in ('down', 'move', 'wait', 'commit', 'up'):
            getattr(builder, name).return_value = builder
        device = SimpleNamespace(minitouch_builder=builder,
                                 minitouch_send=Mock(side_effect=[OSError('uncertain send'), None]))
        with self.assertRaises(OSError):
            drag._press_and_drag_minitouch(device, (500, 600), (90, 650), .04, (0, 0, 0, 0), .30, .05)
        self.assertEqual(device.minitouch_send.call_count, 2)
        builder.down.assert_called_once()
        self.assertEqual(builder.up.call_count, 2)
        self.assertEqual([call[0] for call in builder.mock_calls[-5:]], ['clear', 'up', 'commit', 'clear', 'clear'])

    def test_retry_profile_uses_a_longer_hold_and_drag_without_extra_gestures(self):
        device = SimpleNamespace(config=SimpleNamespace(script=SimpleNamespace(device=SimpleNamespace(control_method='scrcpy'))),
                                 handle_control_check=Mock(), _invalidate_image_batch_cache=Mock(),
                                 _format_action_duration=lambda value: '')
        with patch.object(drag, '_press_and_drag_scrcpy') as send:
            drag.Press_and_Drag(device, (500, 600), (90, 650))
            drag.Press_and_Drag(device, (500, 600), (90, 650), retry=True)
        fast, retry = [call.kwargs for call in send.call_args_list]
        self.assertLess(fast['hold_duration'], .06)
        self.assertGreaterEqual(retry['hold_duration'], .12)
        self.assertLess(fast['swipe_duration'], retry['swipe_duration'])


if __name__ == '__main__':
    unittest.main()
