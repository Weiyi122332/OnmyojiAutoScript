"""ADB-only transport shared by the scheduled task and the standalone reader."""

from pathlib import Path
import random
import subprocess

import cv2
import numpy as np


class AdbInventoryTransport:
    def __init__(self, adb: str | Path, serial: str):
        self.adb = str(adb)
        self.serial = serial
        self.screen_size: tuple[int, int] | None = None
        self.random = random.SystemRandom()
        self.tap_history: list[tuple[tuple[int, int, int, int], tuple[int, int]]] = []

    def _run(self, *args: str, timeout: float = 15) -> bytes:
        result = subprocess.run(
            [self.adb, '-s', self.serial, *args], capture_output=True, timeout=timeout,
        )
        if result.returncode:
            message = result.stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(f'ADB command failed: {message}')
        return result.stdout

    def capture(self) -> np.ndarray:
        data = self._run('exec-out', 'screencap', '-p')
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError('ADB screenshot could not be decoded')
        height, width = image.shape[:2]
        if abs(width / height - 1280 / 720) > 0.02:
            raise RuntimeError(f'Resource inventory requires a landscape 16:9 screen, got {width}x{height}')
        self.screen_size = width, height
        if (width, height) != (1280, 720):
            image = cv2.resize(image, (1280, 720), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def _point(self, x: int, y: int) -> tuple[str, str]:
        if self.screen_size is None:
            raise RuntimeError('Capture the screen before sending input')
        width, height = self.screen_size
        return str(round(x * width / 1280)), str(round(y * height / 720))

    def _random_point(self, area: tuple[int, int, int, int]) -> tuple[int, int]:
        x, y, width, height = area
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 1280 or y + height > 720:
            raise ValueError(f'Invalid resource click area: {area}')
        return self.random.randrange(x, x + width), self.random.randrange(y, y + height)

    def tap_area(self, area: tuple[int, int, int, int]) -> None:
        x, y = self._random_point(area)
        self.tap_history.append((area, (x, y)))
        self._run('shell', 'input', 'tap', *self._point(x, y))

    def scroll_down(self) -> None:
        start = self._random_point((610, 570, 86, 50))
        end = self._random_point((610, 220, 86, 70))
        self._run('shell', 'input', 'swipe', *self._point(*start), *self._point(*end),
                  str(self.random.randint(380, 550)))
