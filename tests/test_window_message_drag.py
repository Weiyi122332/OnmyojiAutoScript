"""Emulator window-message gestures preserve holding and release on failures."""
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

from module.device.env import IS_WINDOWS

if IS_WINDOWS:
    from module.device.method import windows_impl as backend
else:
    backend = None


@unittest.skipUnless(IS_WINDOWS, 'Window-message transport requires Windows')
class WindowMessageDragTest(unittest.TestCase):
    def device(self, family):
        return SimpleNamespace(emulator_family=family, control_handle_list=[1001, 1002, 1003, 1004])

    def drag(self, device):
        backend.Window.press_and_drag_window_message(
            device, (100, 200), (300, 400), [([150, 250], .02), ([300, 400], .03)],
            hold_duration=.15, release_duration=.06)

    def test_each_emulator_uses_its_control_handle_with_continuous_button_and_waits(self):
        for family, hwnd in ((backend.EmulatorFamily.FAMILY_MUMU, 1002),
                             (backend.EmulatorFamily.FAMILY_NOX, 1004),
                             (backend.EmulatorFamily.FAMILY_LD, 1001)):
            with self.subTest(family=family):
                with patch.object(backend, 'PostMessage') as post, \
                        patch.object(backend, 'SendMessage') as send, \
                        patch.object(backend.time, 'sleep') as sleep:
                    self.drag(self.device(family))
                pressed = [item for item in post.call_args_list
                           if item.args[1] in (backend.WM_LBUTTONDOWN, backend.WM_LBUTTONUP)
                           or item.args[2] == backend.MK_LBUTTON]
                self.assertEqual(pressed, [
                    call(hwnd, backend.WM_LBUTTONDOWN, backend.MK_LBUTTON, backend.MAKELONG(100, 200)),
                    call(hwnd, backend.WM_MOUSEMOVE, backend.MK_LBUTTON, backend.MAKELONG(150, 250)),
                    call(hwnd, backend.WM_MOUSEMOVE, backend.MK_LBUTTON, backend.MAKELONG(300, 400)),
                    call(hwnd, backend.WM_LBUTTONUP, 0, backend.MAKELONG(300, 400)),
                ])
                self.assertEqual(sleep.call_args_list, [call(.15), call(.02), call(.03), call(.06)])
                send.assert_any_call(hwnd, backend.WM_NCHITTEST, 0, backend.MAKELONG(100, 200))

    def test_uncertain_move_releases_once_without_replaying_button_down(self):
        def fail_move(hwnd, message, state, point):
            if message == backend.WM_MOUSEMOVE and state == backend.MK_LBUTTON:
                raise OSError('uncertain mouse move')
        with patch.object(backend, 'PostMessage', side_effect=fail_move) as post, \
                patch.object(backend, 'SendMessage'), patch.object(backend.time, 'sleep'):
            with self.assertRaisesRegex(OSError, 'uncertain mouse move'):
                self.drag(self.device(backend.EmulatorFamily.FAMILY_MUMU))
        actions = [item.args[1] for item in post.call_args_list]
        self.assertEqual(actions.count(backend.WM_LBUTTONDOWN), 1)
        self.assertEqual(actions.count(backend.WM_LBUTTONUP), 1)
        self.assertEqual(post.call_args_list[-1],
                         call(1002, backend.WM_LBUTTONUP, 0, backend.MAKELONG(150, 250)))

    def test_unsupported_emulator_does_not_send_mouse_events(self):
        with patch.object(backend, 'PostMessage') as post, patch.object(backend, 'SendMessage') as send:
            self.drag(self.device(backend.EmulatorFamily.FAMILY_BLUESTACKS))
        post.assert_not_called()
        send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
