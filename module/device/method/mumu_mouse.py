"""Background MuMu mouse wheel input through the emulator's Android device.

The Xiaomi Mouse driver takes absolute, unrotated coordinates in REL_X/REL_Y.
One wheel notch is REL_WHEEL +/-100. All input stays inside the ADB device.
"""

import re


MUMU_WHEEL_UNIT = 100


class MuMuWheelError(RuntimeError):
    pass


def find_mumu_mouse_device(devices: str) -> str:
    matches = []
    for block in re.split(r'(?=add device \d+:)', devices):
        if not re.search(r'name:\s*"Xiaomi Mouse"', block):
            continue
        if not all(re.search(r'\b' + axis + r'\b', block)
                   for axis in ('REL_X', 'REL_Y', 'REL_WHEEL')):
            continue
        path = re.match(r'add device \d+: (/dev/input/event\d+)\b', block)
        if path:
            matches.append(path.group(1))
    if len(matches) != 1:
        raise MuMuWheelError('MuMu native mouse device could not be uniquely identified')
    return matches[0]


def mumu_mouse_position(x: int, y: int, width: int, height: int, rotation: int) -> tuple[int, int]:
    if not (0 <= x < width and 0 <= y < height):
        raise MuMuWheelError('Mouse position is outside the Android display')
    if rotation == 0:
        return x, y
    if rotation == 1:
        return height - 1 - y, x
    if rotation == 2:
        return width - 1 - x, height - 1 - y
    if rotation == 3:
        return y, width - 1 - x
    raise MuMuWheelError('Unknown Android display rotation')


class MuMuMouseInput:
    def __init__(self, adb):
        self.adb = adb
        self._mouse_device = None
        self._prepared_point = None
        self._native_point = None

    def connect(self):
        if self._mouse_device is not None:
            return
        # Phone brand/hardware can be spoofed; use MuMu's input service.
        if self.adb.shell(['getprop', 'init.svc.nemuinput'], timeout=5).strip() != 'running':
            raise MuMuWheelError('Native mouse wheel selection requires the MuMu input service')
        if self.adb.shell(['id', '-u'], timeout=5).strip() != '0':
            raise MuMuWheelError('MuMu mouse wheel input requires root access over ADB')
        self._mouse_device = find_mumu_mouse_device(self.adb.shell(['getevent', '-pl'], timeout=5))

    def prepare(self, x: int, y: int, width: int, height: int):
        self.connect()
        # Refresh rotation for each batch rather than trusting portrait wm sizes.
        dump = self.adb.shell(['dumpsys', 'input'], timeout=5)
        viewport = re.search(
            r'Viewport INTERNAL: displayId=0,[^\n]*orientation=(\d),\s*'
            r'logicalFrame=\[\s*0,\s*0,\s*(\d+),\s*(\d+)\]', dump)
        if viewport is None:
            raise MuMuWheelError('MuMu mouse display rotation could not be read')
        rotation, actual_width, actual_height = map(int, viewport.groups())
        if (actual_width, actual_height) != (width, height):
            raise MuMuWheelError(f'MuMu mouse display is {actual_width}x{actual_height}, '
                                 f'expected {width}x{height}')
        native_x, native_y = mumu_mouse_position(x, y, width, height, rotation)
        for event_type, code, value in ((2, 0, native_x), (2, 1, native_y), (0, 0, 0)):
            output = self.adb.shell(['sendevent', self._mouse_device, str(event_type),
                                     str(code), str(value)], timeout=5)
            if output.strip():
                raise MuMuWheelError(f'MuMu mouse positioning failed: {output.strip()}')
        self._prepared_point = (x, y, width, height)
        self._native_point = (native_x, native_y)

    def scroll(self, x: int, y: int, width: int, height: int, vertical: float):
        if not -16 <= vertical <= 16:
            raise MuMuWheelError('MuMu wheel delta must be between -16 and 16')
        if self._prepared_point != (x, y, width, height):
            self.prepare(x, y, width, height)
        native_x, native_y = self._native_point
        # Position and wheel belong to the same input frame. Host mouse motion
        # cannot redirect a notch; only one ADB round trip is needed per frame.
        events = ((2, 0, native_x), (2, 1, native_y),
                  (2, 8, round(vertical * MUMU_WHEEL_UNIT)), (0, 0, 0))
        command = ' && '.join(f'sendevent {self._mouse_device} {event_type} {code} {value}'
                              for event_type, code, value in events)
        output = self.adb.shell(command, timeout=5)
        if output.strip():
            raise MuMuWheelError(f'MuMu native wheel input failed: {output.strip()}')


class MuMuWheelClient:
    """Use the configured ADB device; abort without replaying partial batches."""

    backend = 'mumu_native'

    def __init__(self, device):
        self.device = device
        self._input = None

    def connect(self):
        if self._input is not None:
            return
        if getattr(self.device, 'is_over_http', False):
            raise MuMuWheelError('MuMu mouse wheel selection requires an ADB device connection')
        mouse = MuMuMouseInput(self.device.adb)
        try:
            mouse.connect()
        except Exception as exc:
            raise MuMuWheelError(f'Cannot initialize MuMu native mouse input: {exc}') from exc
        self._input = mouse

    def prepare_scroll(self, x: int, y: int):
        self.connect()
        try:
            self._input.prepare(x, y, 1280, 720)
        except Exception as exc:
            self.close()
            raise MuMuWheelError(f'Cannot position the MuMu mouse: {exc}') from exc

    def scroll(self, x: int, y: int, *, vertical: float = -1):
        self.connect()
        try:
            self._input.scroll(x, y, 1280, 720, vertical)
        except Exception as exc:
            self.close()
            raise MuMuWheelError(f'MuMu native wheel input failed: {exc}; '
                                 'partial scroll batch was not replayed') from exc

    def close(self):
        self._input = None
