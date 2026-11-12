"""Replay the refresh confirmation from the target emulator."""

from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from tasks.RealmRaid.assets import RealmRaidAssets


class RealmRaidRefreshConfirmationTest(unittest.TestCase):
    def test_refresh_dialog_is_recognized_at_its_live_position(self):
        fixture = Path(__file__).parent / 'fixtures' / 'realm_raid' / 'refresh_confirmation.png'
        dialog = np.array(Image.open(fixture).convert('RGB'))
        height, width = dialog.shape[:2]
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[228:228 + height, 404:404 + width] = dialog

        confirm = deepcopy(RealmRaidAssets.I_FRESH_ENSURE)
        self.assertTrue(confirm.template_match(frame))
        x, y, width, height = confirm.roi_front
        self.assertGreaterEqual(x, 664)
        self.assertGreaterEqual(y, 407)
        self.assertLessEqual(x + width, 844)
        self.assertLessEqual(y + height, 472)


if __name__ == '__main__':
    unittest.main()
