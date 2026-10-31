import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tasks.ResourceInventory.config import ResourceInventory, next_inventory_run
from tasks.ResourceInventory.recognition import (
    is_regular_amulet, owned_amount, parse_amount, popup_owned_amount, TextRegion,
)
from tasks.ResourceInventory.adb import AdbInventoryTransport
from tasks.ResourceInventory.reader import WarehouseReader
from tasks.ResourceInventory.storage import available_dates, read_snapshot, save_snapshot


class ResourceRecognitionTest(unittest.TestCase):
    def test_compact_coins_keep_their_precision_flag(self):
        self.assertEqual(parse_amount('5208万', allow_compact=True), (52080000, False))
        self.assertEqual(parse_amount('1.25亿', allow_compact=True), (125000000, False))
        self.assertIsNone(parse_amount('2.1万'))
        self.assertEqual(parse_amount('21,220'), (21220, True))

    def test_missing_and_malformed_ocr_are_not_zero(self):
        for text in ('', 'O0', '12/100', '持有125', '12.34', '1,2', '购买50金币'):
            with self.subTest(text=text):
                self.assertIsNone(parse_amount(text, allow_compact=True))
        self.assertEqual(parse_amount('0'), (0, True))

    def test_owned_count_requires_the_correct_item_name(self):
        self.assertEqual(owned_amount(['体力', '持有:1', '已拥有:21220'], '体力', prefix='已拥有'), 21220)
        self.assertEqual(owned_amount(['神秘的符咒', '持有：125'], '神秘的符咒'), 125)
        self.assertIsNone(owned_amount(['金币', '已拥有:21220'], '体力', prefix='已拥有'))
        self.assertIsNone(owned_amount(['体力', '持有:1'], '体力', prefix='已拥有'))
        self.assertIsNone(owned_amount(['体力', '2.1万'], '体力', prefix='已拥有'))

    def test_limited_amulets_never_match_the_regular_ticket(self):
        self.assertTrue(is_regular_amulet(['神秘的符咒', '持有:125']))
        for title in ('限时神秘的符咒', '神秘的符咒(限时)', '现时神秘的符咒'):
            self.assertFalse(is_regular_amulet([title, '持有:5']))
        self.assertFalse(is_regular_amulet(['神秘的符咒', '限时', '持有:5']))

    def test_stamina_popup_can_move_and_ignores_other_items(self):
        for offset in (-100, 0, 180):
            texts = [
                TextRegion('体力', 420 + offset, 135, 60, 30),
                TextRegion('已拥有:21220', 424 + offset, 175, 150, 25),
                TextRegion('已拥有:1', 870, 171, 110, 25),
                TextRegion('持有:1', 870, 171, 110, 25),
            ]
            self.assertEqual(popup_owned_amount(texts, '体力'), 21220)

    def test_stamina_random_taps_stay_in_safe_area_away_from_plus(self):
        transport = AdbInventoryTransport('adb', 'device')
        transport.screen_size = (1280, 720)
        with patch.object(transport, '_run'):
            for _ in range(100):
                transport.tap_area((679, 16, 23, 27))
        points = {point for _area, point in transport.tap_history}
        self.assertGreater(len(points), 1)
        self.assertTrue(all(679 <= x < 702 and 16 <= y < 43 for x, y in points))
        search = WarehouseReader.STAMINA_SAFE_REGION
        self.assertLess(search[0] + search[2], 819)


class ResourceScheduleTest(unittest.TestCase):
    def test_next_run_is_23_and_moves_to_tomorrow_after_the_boundary(self):
        self.assertEqual(next_inventory_run(datetime(2026, 10, 31, 22, 59)), datetime(2026, 10, 31, 23))
        self.assertEqual(next_inventory_run(datetime(2026, 10, 31, 23)), datetime(2026, 11, 1, 23))

    def test_old_instances_and_template_get_an_enabled_nightly_schedule(self):
        fresh = ResourceInventory().scheduler
        self.assertTrue(fresh.enable)
        self.assertEqual(fresh.cron, '0 23 * * *')
        template = ResourceInventory(scheduler={
            'enable': True, 'cron': '0 23 * * *', 'next_run': '2023-01-01 00:00:00',
        }).scheduler
        self.assertEqual(template.next_run.hour, 23)
        self.assertGreater(template.next_run, datetime.now())


class ResourceHistoryTest(unittest.TestCase):
    def test_daily_history_is_retained_and_partial_does_not_replace_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            def sample(timestamp, status='complete'):
                return {'captured_at': timestamp, 'status': status, 'resources': {}}
            first = sample('2026-10-30T23:00:00+08:00')
            second = sample('2026-10-31T23:00:00+08:00')
            save_snapshot(first, directory)
            save_snapshot(second, directory)
            save_snapshot(sample('2026-10-31T23:10:00+08:00', 'partial'), directory)
            self.assertEqual(available_dates(directory), ['2026-10-31', '2026-10-30'])
            self.assertEqual(read_snapshot(directory/'days/2026-10-31.json')['status'], 'complete')
            self.assertEqual(read_snapshot(directory/'latest.json')['status'], 'partial')
            self.assertEqual(len((directory/'history.jsonl').read_text(encoding='utf-8').splitlines()), 3)
            self.assertEqual(read_snapshot(directory/'days/2026-10-30.json')['captured_at'], first['captured_at'])

    def test_dates_are_grouped_in_beijing_time(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            save_snapshot({'captured_at': '2026-10-31T18:00:00+00:00', 'status': 'complete'}, directory)
            self.assertEqual(available_dates(directory), ['2026-11-01'])
            self.assertEqual(json.loads((directory/'latest.json').read_text())['date'], '2026-11-01')


if __name__ == '__main__':
    unittest.main()
