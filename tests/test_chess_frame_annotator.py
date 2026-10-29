"""The Frame editor can normalize/save the new layouts and preview without input."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.atom.ocr import RuleOcr
from module.image.runtime import ImageRuntime
from module.server.annotator_rule_schema import default_rule, get_rule_types
from module.server.tool import AnnotatorManager


class ChessFrameAnnotatorTest(unittest.TestCase):
    def test_all_current_chess_layouts_save_and_reload_with_digit_operations(self):
        root = Path(__file__).resolve().parents[1]
        rules = json.loads((root / 'tasks/Chess/c/c_frame.json').read_text(encoding='utf-8'))
        self.assertIn('frame', get_rule_types())
        self.assertIn('roiBadge', default_rule('frame'))
        manager = AnnotatorManager.__new__(AnnotatorManager)
        manager._get_session = Mock()
        with TemporaryDirectory() as directory:
            project = Path(directory)
            task = project / 'tasks/Fixture'
            target = task / 'c/c_frame.json'
            with patch('module.server.tool.PROJECT_ROOT', project), \
                    patch.object(AnnotatorManager, '_resolve_json_path', return_value=(task, target)), \
                    patch.object(AnnotatorManager, '_resolve_assets_extract_target', return_value=(task, task / 'assets.py')), \
                    patch('module.server.tool.AssetsExtractor'):
                result = manager.save_rules_and_generate('session', 'Fixture', 'c/c_frame.json', 'frame', rules)
                loaded = manager.load_rule_file('Fixture', 'c/c_frame.json')
            self.assertEqual(result['save_status'], 'success')
            self.assertEqual(result['generate_status'], 'success')
            self.assertEqual(loaded['rule_type'], 'frame')
            saved = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(len(saved), len(rules))
            details = [row for row in saved if row['itemName'].startswith('chess_detail_')]
            self.assertEqual(len(details), 3)
            for row in details:
                self.assertEqual([op['mode'] for op in row['rangeOperations']], ['Digit', 'Single', 'Digit'])

    def test_frame_preview_rebases_digit_and_click_ranges_without_sending_input(self):
        runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(runtime.shutdown)
        manager = AnnotatorManager.__new__(AnnotatorManager)
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            badge = np.random.default_rng(11).integers(0, 256, (6, 8, 3), dtype=np.uint8)
            image = np.zeros((100, 100, 3), dtype=np.uint8)
            image[35:41, 40:48] = badge
            front, screenshot = folder / 'badge.png', folder / 'scene.png'
            cv2.imwrite(str(front), cv2.cvtColor(badge, cv2.COLOR_RGB2BGR))
            cv2.imwrite(str(screenshot), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
            manager._get_session = Mock(return_value=SimpleNamespace(images={'scene': SimpleNamespace(path=screenshot)}))
            manager.get_rule_image_file = Mock(return_value=front)
            manager._resolve_json_path = Mock(return_value=(folder, folder / 'frame.json'))
            rule = {'itemName': 'demo', 'imageName': 'badge.png', 'roiBadge': '10,10,8,6',
                    'roiBack': '0,0,100,100', 'roiRange': ['20,10,20,10', '20,30,10,10'],
                    'threshold': .99, 'method': 'Template matching',
                    'rangeOperations': [{'type': 'ocr', 'mode': 'Digit'}, {'type': 'click'}]}
            def detect(path, target):
                payload = runtime._match_rule_payload(image, target.to_service_payload())
                matched = target._apply_match_result(payload)
                return {'matched': bool(matched), 'similarity': 1.0 if matched else 0.0,
                        'roiFront': ','.join(map(str, target.roi_front)), 'roiBack': '0,0,100,100'}
            with patch('module.server.tool.detect_image_detail', side_effect=detect), \
                    patch.object(RuleOcr, 'ocr', return_value=42):
                result = manager.test_rule('session', 'scene', 'Fixture', 'c/frame.json', 'frame', rule)
        self.assertTrue(result['matched'])
        self.assertEqual(result['roiRanges'], ['50,35,20,10', '50,55,10,10'])
        self.assertEqual(result['rangeResults'][0]['value'], 42)
        self.assertEqual(result['rangeResults'][1]['status'], 'click_not_executed')


if __name__ == '__main__':
    unittest.main()
