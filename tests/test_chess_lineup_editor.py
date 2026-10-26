"""Validate lineup persistence, dynamic choices, snapshots and editor HTTP routes."""

from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import httpx
from pydantic import ValidationError

from module.config.config_model import ConfigModel
from module.server import chesslineup_router as router
from tasks.Chess.config import Chess, ChessConfig
from tasks.Chess.script_task import ScriptTask
from tasks.Chess.strategy import custom_lineups as custom
from tasks.Chess.strategy import lineup_loader as loader


def document(key='sample'):
    return custom.CustomLineup(key=key, display_name='测试阵容', slots=[
        custom.Slot(shikigami='hakurou'), *[custom.Slot() for _ in range(11)]])


class ChessLineupPersistenceTest(unittest.TestCase):
    def test_save_reload_and_delete_roundtrip_in_temporary_store(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'lineups.json'
            model = document()
            custom.save_lineup(model, path)
            self.assertEqual(custom.read_collection(path)['sample'], model.model_dump())
            with self.assertRaises(FileExistsError):
                custom.save_lineup(model, path, overwrite=False)
            custom.delete_lineup('sample', path)
            self.assertEqual(custom.read_collection(path), {})

    def test_v1_migration_preserves_backup_and_equipment(self):
        old = {'key': 'legacy', 'display_name': '旧阵容',
               'shikigami_positions': {'白狼': [2, 7, ['网切']]}}
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'custom_lineups.json'
            original = json.dumps({'version': 1, 'lineups': [old]}, ensure_ascii=False).encode('utf-8')
            path.write_bytes(original)
            custom.migrate_collection(path)
            self.assertEqual(path.with_suffix('.v1.bak.json').read_bytes(), original)
            slot = custom.read_collection(path)['legacy']['slots'][6]
            self.assertEqual(slot['shikigami'], 'hakurou')
            self.assertEqual(slot['equipment'], [{'kind': 'soul', 'key': 'wangqie'}])
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['version'], 2)

    def test_rejects_duplicate_units_and_unknown_equipment(self):
        raw = document().model_dump()
        raw['slots'][1]['shikigami'] = 'hakurou'
        with self.assertRaises(ValidationError):
            custom.CustomLineup.model_validate(raw)
        raw['slots'][1]['shikigami'] = None
        raw['slots'][0]['equipment'] = [{'kind': 'soul', 'key': 'missing'}]
        with self.assertRaises(ValidationError):
            custom.CustomLineup.model_validate(raw)

    def test_goldfish_assignment_moves_to_an_empty_slot(self):
        raw = document().model_dump()
        raw['slots'][0]['shikigami'] = 'shouzu'
        raw['slots'][1]['shikigami'] = 'kappa'
        raw['arakawa_goldfish_position'] = 1
        model = custom.CustomLineup.model_validate(raw)
        self.assertEqual(model.arakawa_goldfish_position, 12)

    def test_legacy_haiguo_uses_available_builtin_and_preserves_saved_custom(self):
        with patch.object(custom, 'read_lineups', return_value={}):
            self.assertEqual(ChessConfig(lineup_bond='海国').custom_lineup, 'builtin:haiguo')
        with patch.object(custom, 'read_lineups', return_value={'haiguo': {}}):
            self.assertEqual(ChessConfig(lineup_bond='海国').custom_lineup, 'custom:haiguo')
        self.assertEqual(ChessConfig(lineup_bond='荒川').lineup_bond.value, '荒川')

    def test_dynamic_choice_updates_persisted_identity_and_hides_internal_field(self):
        choice = '自定义 · 测试阵容 [sample]'
        with patch('tasks.Chess.config.oasx_lineup_choices', return_value={choice: 'custom:sample'}):
            chess = Chess()
            self.assertTrue(chess.select_oasx_lineup(choice))
            groups = chess.oasx_args({'chess_config': [
                {'name': 'lineup_bond'}, {'name': 'custom_lineup'}]})
            self.assertEqual(groups['chess_config'][0]['value'], choice)
            self.assertEqual(len(groups['chess_config']), 1)
            self.assertEqual(chess.chess_config.custom_lineup, 'custom:sample')
            self.assertFalse(chess.select_oasx_lineup('custom:missing'))

    def test_config_model_exposes_and_saves_dynamic_chess_choice(self):
        config = ConfigModel()
        with patch.object(ConfigModel, 'save') as save:
            self.assertTrue(config.script_set_arg('Chess', 'chess_config', 'lineup_bond', 'builtin:haiguo'))
        save.assert_called_once()
        values = {item['name']: item for item in config.script_task('Chess')['chess_config']}
        self.assertIn('内置 · 荒川 [haiguo]', values['lineup_bond']['enumEnum'])
        self.assertEqual(values['lineup_bond']['value'], '内置 · 荒川 [haiguo]')
        self.assertNotIn('custom_lineup', values)

    def test_running_lineup_snapshot_is_stable_until_next_selection(self):
        registry = loader.load_lineup_registry()
        with patch.object(loader, 'load_lineup_registry', side_effect=lambda: deepcopy(registry)):
            task = ScriptTask.__new__(ScriptTask)
            task.select_lineup_strategy('builtin:qijiaoshan')
            registry['qijiaoshan']['strategy']['display_name'] = '下一局阵容'
            self.assertEqual(task.get_lineup_strategy()['display_name'], '七角山')
            task.select_lineup_strategy('builtin:qijiaoshan')
            self.assertEqual(task.get_lineup_strategy()['display_name'], '下一局阵容')


class ChessLineupRouterTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        folder = stack.enter_context(TemporaryDirectory())
        self.root = Path(folder)
        self.store = self.root / 'custom.json'
        self.builtin = self.root / 'builtin.json'
        custom.write_collection(self.builtin, {'sample': document().model_dump()})
        (self.root / 'config').mkdir()
        self.config = self.root / 'config/demo.json'
        self.config.write_text(json.dumps({'chess': {'chess_config': {'lineup_bond': '七角山'}}}), encoding='utf-8')
        stack.enter_context(patch.object(custom, 'STORE', self.store))
        stack.enter_context(patch.object(router, 'LINEUPS_FILE', self.builtin))
        stack.enter_context(patch.object(router, 'ROOT', self.root))
        app = FastAPI()
        app.include_router(router.chesslineup_app)
        app.mount('/tool/chesslineup/static', StaticFiles(directory=str(router.WEB / 'static')))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')
        self.addAsyncCleanup(self.client.aclose)
        self.url = '/tool/chesslineup'

    async def test_editor_catalog_and_every_card_image_are_served(self):
        self.assertEqual((await self.client.get(self.url)).status_code, 200)
        data = (await self.client.get(self.url + '/api/catalog')).json()
        self.assertEqual(data['configs'], ['demo'])
        for kind in ('shikigami', 'soul', 'emblem'):
            for item in data[kind]:
                with self.subTest(kind=kind, key=item['key']):
                    response = await self.client.get(item['image'])
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.content)

    async def test_save_promote_conflict_and_delete_roundtrip(self):
        raw = document('second').model_dump()
        self.assertEqual((await self.client.post(self.url + '/api/lineups', json=raw)).status_code, 200)
        self.assertEqual((await self.client.post(self.url + '/api/lineups/promote', json=raw)).status_code, 200)
        self.assertEqual((await self.client.post(self.url + '/api/lineups/promote', json=raw)).status_code, 409)
        self.assertEqual((await self.client.delete(self.url + '/api/lineups/custom/second')).status_code, 200)
        response = (await self.client.get(self.url + '/api/lineups')).json()
        self.assertEqual(response['custom'], [])
        self.assertEqual({item['key'] for item in response['builtin']}, {'sample', 'second'})

    async def test_invalid_save_and_script_name_are_rejected(self):
        raw = document().model_dump()
        raw['slots'][0]['shikigami'] = 'missing'
        self.assertEqual((await self.client.post(self.url + '/api/lineups', json=raw)).status_code, 422)
        response = await self.client.post(self.url + '/api/apply', json={
            'source': 'builtin', 'key': 'sample', 'script': '../demo'})
        self.assertEqual(response.status_code, 400)

    async def test_active_lineup_cannot_be_deleted(self):
        self.config.write_text(json.dumps({'chess': {'chess_config': {
            'lineup_bond': '自定义阵容', 'custom_lineup': 'builtin:sample'}}}), encoding='utf-8')
        response = await self.client.delete(self.url + '/api/lineups/builtin/sample')
        self.assertEqual(response.status_code, 409)
        self.assertIn('demo', response.json()['detail'])

    async def test_apply_uses_existing_config_model_and_only_selects_lineup(self):
        model = ConfigModel(chess={'chess_config': {'run_count': 3}})
        manager = SimpleNamespace(config_cache=Mock(return_value=SimpleNamespace(model=model)))
        with patch.dict(sys.modules, {'module.server.main_manager': SimpleNamespace(mm=manager)}), \
                patch.object(ConfigModel, 'save') as save:
            response = await self.client.post(self.url + '/api/apply', json={
                'source': 'builtin', 'key': 'sample', 'script': 'demo'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(model.chess.chess_config.custom_lineup, 'builtin:sample')
        self.assertEqual(model.chess.chess_config.run_count, 3)
        save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
