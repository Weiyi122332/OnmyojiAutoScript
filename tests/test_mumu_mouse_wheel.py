"""Native MuMu input frames, discovery, and failure handling."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.device.method.mumu_mouse import (
    MuMuMouseInput, MuMuWheelClient, MuMuWheelError,
    find_mumu_mouse_device, mumu_mouse_position,
)


MUMU_DEVICES = '''add device 1: /dev/input/event4
  name: "Xiaomi Touchscreen"
  ABS (0003): ABS_MT_POSITION_X ABS_MT_POSITION_Y
add device 2: /dev/input/event12
  name: "Xiaomi Mouse"
  REL (0002): REL_X REL_Y REL_HWHEEL REL_WHEEL
add device 3: /dev/input/event3
  name: "Xiaomi integration"
  ABS (0003): ABS_X ABS_Y
  REL (0002): REL_HWHEEL REL_WHEEL
'''


class MuMuNativeWheelTest(unittest.TestCase):
    def setUp(self):
        self.adb = Mock()
        self.uid = '0'
        self.rotation = 1
        self.width, self.height = 1280, 720
        self.service = 'running'
        self.native_error = ''
        self.viewport_available = True
        self.adb.shell.side_effect = self.shell
        self.device = SimpleNamespace(adb=self.adb, adb_push=Mock())
        self.client = MuMuWheelClient(self.device)

    def shell(self, command, **kwargs):
        if isinstance(command, str) and command.startswith('sendevent '):
            return self.native_error
        if command == ['getprop', 'init.svc.nemuinput']:
            return self.service
        if command == ['id', '-u']:
            return self.uid
        if command == ['getevent', '-pl']:
            return MUMU_DEVICES
        if command == ['dumpsys', 'input']:
            if not self.viewport_available:
                return ''
            return (f'Viewport INTERNAL: displayId=0, uniqueId=local:123, port=0, '
                    f'orientation={self.rotation}, logicalFrame=[0, 0, {self.width}, {self.height}], '
                    'isActive=[1]')
        if command[0] == 'sendevent':
            return ''
        self.fail(f'Unexpected ADB command: {command}')

    def motion_commands(self):
        return [call.args[0] for call in self.adb.shell.call_args_list
                if isinstance(call.args[0], list) and call.args[0][0] == 'sendevent']

    def test_connect_discovers_native_input_once_without_server_or_socket(self):
        self.client.connect()
        self.client.connect()
        self.assertEqual(self.client.backend, 'mumu_native')
        self.assertEqual([call.args[0] for call in self.adb.shell.call_args_list],
                         [['getprop', 'init.svc.nemuinput'], ['id', '-u'], ['getevent', '-pl']])
        self.device.adb_push.assert_not_called()
        self.adb.create_connection.assert_not_called()

    def test_prepare_uses_detected_device_and_current_display_rotation(self):
        self.client.prepare_scroll(1165, 400)
        self.assertEqual(self.motion_commands(), [
            ['sendevent', '/dev/input/event12', '2', '0', '319'],
            ['sendevent', '/dev/input/event12', '2', '1', '1165'],
            ['sendevent', '/dev/input/event12', '0', '0', '0'],
        ])

    def test_each_notch_repositions_and_keeps_its_direction_in_one_frame(self):
        self.client.prepare_scroll(1165, 400)
        self.adb.shell.reset_mock()
        self.client.scroll(1165, 400)
        self.client.scroll(1165, 400, vertical=1)
        commands = [call.args[0] for call in self.adb.shell.call_args_list]
        expected = ('sendevent /dev/input/event12 2 0 319 && '
                    'sendevent /dev/input/event12 2 1 1165 && '
                    'sendevent /dev/input/event12 2 8 {} && '
                    'sendevent /dev/input/event12 0 0 0')
        self.assertEqual(commands, [expected.format(-100), expected.format(100)])
        self.device.adb_push.assert_not_called()
        self.adb.create_connection.assert_not_called()

    def test_direct_scroll_prepares_before_sending_a_wheel_frame(self):
        self.client.scroll(1165, 400)
        self.assertEqual(len(self.motion_commands()), 3)
        self.assertIn('2 8 -100', self.adb.shell.call_args.args[0])

    def test_input_failure_stops_without_replaying_partial_scroll(self):
        self.client.prepare_scroll(1165, 400)
        self.adb.shell.reset_mock()
        self.native_error = 'Permission denied'
        with self.assertRaisesRegex(MuMuWheelError, 'partial scroll batch was not replayed'):
            self.client.scroll(1165, 400)
        self.adb.shell.assert_called_once()
        self.assertIsNone(self.client._input)

    def test_each_batch_refreshes_rotation_without_redetecting_device(self):
        mouse = MuMuMouseInput(self.adb)
        mouse.prepare(1165, 400, 1280, 720)
        self.rotation = 3
        mouse.prepare(1165, 400, 1280, 720)
        commands = [call.args[0] for call in self.adb.shell.call_args_list]
        self.assertEqual(commands.count(['getevent', '-pl']), 1)
        self.assertEqual(commands.count(['dumpsys', 'input']), 2)
        self.assertEqual(self.motion_commands()[-3:], [
            ['sendevent', '/dev/input/event12', '2', '0', '400'],
            ['sendevent', '/dev/input/event12', '2', '1', '114'],
            ['sendevent', '/dev/input/event12', '0', '0', '0'],
        ])

    def test_unsupported_device_fails_before_writing_input(self):
        self.service = ''
        with self.assertRaisesRegex(MuMuWheelError, 'requires the MuMu input service'):
            self.client.prepare_scroll(1165, 400)
        self.adb.shell.assert_called_once_with(['getprop', 'init.svc.nemuinput'], timeout=5)
        self.assertIsNone(self.client._input)

    def test_missing_root_fails_before_positioning_or_wheel_input(self):
        self.uid = '2000'
        with self.assertRaisesRegex(MuMuWheelError, 'root access'):
            self.client.prepare_scroll(1165, 400)
        self.assertEqual(self.motion_commands(), [])
        self.assertIsNone(self.client._input)

    def test_http_device_fails_before_adb_commands(self):
        self.device.is_over_http = True
        with self.assertRaisesRegex(MuMuWheelError, 'ADB device connection'):
            self.client.connect()
        self.adb.shell.assert_not_called()

    def test_unexpected_display_size_stops_before_positioning(self):
        self.width, self.height = 720, 1280
        with self.assertRaisesRegex(MuMuWheelError, 'expected 1280x720'):
            self.client.prepare_scroll(1165, 400)
        self.assertEqual(self.motion_commands(), [])
        self.assertIsNone(self.client._input)

    def test_missing_viewport_stops_before_positioning(self):
        self.viewport_available = False
        with self.assertRaisesRegex(MuMuWheelError, 'rotation could not be read'):
            self.client.prepare_scroll(1165, 400)
        self.assertEqual(self.motion_commands(), [])

    def test_ambiguous_or_unrelated_mouse_devices_are_rejected(self):
        for devices in (MUMU_DEVICES.replace('Xiaomi Mouse', 'USB Mouse'),
                        MUMU_DEVICES + MUMU_DEVICES.replace('event12', 'event8')):
            with self.assertRaises(MuMuWheelError):
                find_mumu_mouse_device(devices)

    def test_rotation_and_outside_points_are_validated(self):
        for rotation, expected in ((0, (1165, 400)), (1, (319, 1165)),
                                   (2, (114, 319)), (3, (400, 114))):
            self.assertEqual(mumu_mouse_position(1165, 400, 1280, 720, rotation), expected)
        for point in ((-1, 400), (1280, 400), (1165, 720)):
            with self.assertRaises(MuMuWheelError):
                mumu_mouse_position(*point, 1280, 720, 1)

    def test_invalid_wheel_delta_stops_before_writing_input(self):
        for delta in (-17, 17, float('nan')):
            with self.subTest(delta=delta), self.assertRaises(MuMuWheelError):
                self.client.scroll(1165, 400, vertical=delta)
        self.assertEqual(self.motion_commands(), [])


if __name__ == '__main__':
    unittest.main()
