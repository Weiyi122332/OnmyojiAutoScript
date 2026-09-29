"""Dependency-free checks for the repository's task layout contract."""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_tools.check_structure import PROJECT_ROOT, check_structure, menu_sections
from module.task_loader import load_task_script, task_script_path


class ProjectStructureTest(unittest.TestCase):
    def test_task_registration_is_consistent(self):
        self.assertEqual(check_structure(), [])

    def test_check_catches_a_task_missing_from_the_menu(self):
        menu = menu_sections(PROJECT_ROOT / 'module/config/config_menu.py')
        menu['Activity Task'].remove('LBS')
        with patch('dev_tools.check_structure.menu_sections', return_value=menu):
            issues = check_structure()
        self.assertIn('ConfigModel: LBS is absent from ConfigMenu', issues)

    def test_task_paths_do_not_depend_on_working_directory(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                path = task_script_path('LBS')
                self.assertEqual(path, PROJECT_ROOT / 'tasks/LBS/script_task.py')
                self.assertTrue(path.is_file())
            finally:
                os.chdir(original_cwd)

    def test_task_name_cannot_escape_task_directory(self):
        for name in ('../config', 'LBS/script_task', '', 'LBS.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                task_script_path(name)

    def test_task_loader_preserves_module_name_and_reloads_by_file(self):
        calls = []
        fake_utils = types.ModuleType('module.base.utils')
        fake_utils.load_module = lambda name, path: calls.append((name, path)) or 'loaded'
        with patch.dict(sys.modules, {'module.base.utils': fake_utils}):
            self.assertEqual(load_task_script('LBS', 'task_group_LBS'), 'loaded')
        self.assertEqual(calls, [('task_group_LBS', str(task_script_path('LBS')))])


if __name__ == '__main__':
    unittest.main()
