from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from module.server.resource_router import resource_snapshot
from tasks.ResourceInventory.config import ResourceInventory
from tasks.ResourceInventory.storage import save_snapshot


class ResourceApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / 'config'
        config.mkdir()
        for name in ('alpha', 'beta'):
            (config / f'{name}.json').write_text('{}')
        self.patches = [
            patch('module.server.resource_router.ConfigManager.config_dir', return_value=config),
            patch('module.server.resource_router.result_directory', side_effect=lambda name: self.root / 'resources' / name),
            patch('module.server.resource_router.ConfigModel', return_value=SimpleNamespace(resource_inventory=ResourceInventory())),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_reads_latest_and_historical_values_for_the_selected_instance(self):
        for name, quantity in [('alpha', 125), ('beta', 222)]:
            for day in ('30', '31'):
                save_snapshot({
                    'captured_at': f'2026-10-{day}T23:00:00+08:00',
                    'status': 'complete',
                    'resources': {'mystery_amulets': {'quantity': quantity}},
                }, self.root / 'resources' / name)
        alpha = resource_snapshot('alpha', None)
        beta = resource_snapshot('beta', '2026-10-30')
        self.assertEqual(alpha['dates'], ['2026-10-31', '2026-10-30'])
        self.assertEqual(alpha['snapshot']['resources']['mystery_amulets']['quantity'], 125)
        self.assertEqual(beta['snapshot']['resources']['mystery_amulets']['quantity'], 222)
        self.assertTrue(alpha['schedule']['enabled'])
        self.assertEqual(alpha['schedule']['cron'], '0 23 * * *')

    def test_no_snapshot_is_empty_instead_of_an_invented_zero_balance(self):
        response = resource_snapshot('alpha', None)
        self.assertIsNone(response['snapshot'])
        self.assertEqual(response['dates'], [])

    def test_rejects_path_traversal_and_nonexistent_instances(self):
        for script, day, code in [('alpha', '../latest', 422), ('../alpha', None, 422), ('missing', None, 404)]:
            with self.subTest(script=script, day=day), self.assertRaises(HTTPException) as context:
                resource_snapshot(script, day)
            self.assertEqual(context.exception.status_code, code)


if __name__ == '__main__':
    unittest.main()
