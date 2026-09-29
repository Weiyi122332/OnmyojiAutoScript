"""Check task registration without importing game, OCR, or GUI dependencies.

Run from the repository root: ``python dev_tools/check_structure.py``.
The checker uses its own location to find the repository, so an absolute script
path also works from another directory.
The check covers the contracts that must stay in sync when adding a task.
"""

import argparse
import ast
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
NON_TASK_MENU_SECTIONS = {'Overview', 'TaskList', 'Tools'}
NON_RUNNABLE_MENU_ENTRIES = {'Script', 'GlobalGame'}
MODEL_METADATA_FIELDS = {'config_name', 'running_task'}
INTERNAL_TASKS = {'GotoMain'}
# Kept for compatibility with existing instance JSON; it has no runnable script.
LEGACY_CONFIG_ONLY = {'OrochiMoans'}


def source_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))


def class_node(tree: ast.Module, name: str) -> ast.ClassDef | None:
    return next((node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == name), None)


def model_fields(path: Path) -> dict[str, str]:
    model = class_node(source_tree(path), 'ConfigModel')
    if model is None:
        raise ValueError(f'{path}: ConfigModel class is missing')
    return {node.target.id: node.annotation.id
            for node in model.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.annotation, ast.Name)}


def menu_sections(path: Path) -> dict[str, list[str]]:
    menu = class_node(source_tree(path), 'ConfigMenu')
    if menu is None:
        raise ValueError(f'{path}: ConfigMenu class is missing')
    init = next((node for node in menu.body
                 if isinstance(node, ast.FunctionDef) and node.name == '__init__'), None)
    if init is None:
        raise ValueError(f'{path}: ConfigMenu.__init__ is missing')
    sections = {}
    for node in init.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute)
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == 'self' and target.value.attr == 'menu'):
            sections[ast.literal_eval(target.slice)] = ast.literal_eval(node.value)
    return sections


def group_choices(path: Path) -> set[str]:
    choice = class_node(source_tree(path), 'GroupTaskChoice')
    if choice is None:
        raise ValueError(f'{path}: GroupTaskChoice is missing')
    return {ast.literal_eval(node.value) for node in choice.body
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)}


def scheduler_priority(path: Path) -> set[str]:
    manual = class_node(source_tree(path), 'ConfigManual')
    if manual is None:
        raise ValueError(f'{path}: ConfigManual is missing')
    for node in manual.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'SCHEDULER_PRIORITY'):
            return set(re.findall(r'[A-Za-z][A-Za-z0-9]*', ast.literal_eval(node.value)))
    raise ValueError(f'{path}: SCHEDULER_PRIORITY is missing')


def check_structure(root: Path = PROJECT_ROOT) -> list[str]:
    """Return contract violations; an empty list means task wiring is coherent."""
    root = Path(root)
    tasks_dir = root / 'tasks'
    fields = model_fields(root / 'module/config/config_model.py')
    template = json.loads((root / 'config/template.json').read_text(encoding='utf-8-sig'))
    sections = menu_sections(root / 'module/config/config_menu.py')
    choices = group_choices(tasks_dir / 'TaskGroup/config.py')
    priority = scheduler_priority(root / 'module/config/config_manual.py')
    issues = []

    for name in sorted(set(fields) - set(template)):
        issues.append(f'config/template.json: missing ConfigModel field {name}')
    for name in sorted(set(template) - set(fields)):
        issues.append(f'config/template.json: unknown ConfigModel field {name}')

    menu_names = [name for section, names in sections.items()
                  if section not in NON_TASK_MENU_SECTIONS for name in names]
    if len(menu_names) != len(set(menu_names)):
        issues.append('ConfigMenu: duplicate task or settings entry')
    field_by_type = {type_name: field for field, type_name in fields.items()
                     if field not in MODEL_METADATA_FIELDS}
    runnable = set(menu_names) - NON_RUNNABLE_MENU_ENTRIES
    for name in menu_names:
        if name not in field_by_type:
            issues.append(f'ConfigMenu: {name} has no ConfigModel field')
    for name in sorted(set(field_by_type) - set(menu_names) - LEGACY_CONFIG_ONLY):
        issues.append(f'ConfigModel: {name} is absent from ConfigMenu')

    for name in sorted(runnable):
        script = tasks_dir / name / 'script_task.py'
        if not script.is_file():
            issues.append(f'{name}: missing tasks/{name}/script_task.py')
        elif class_node(source_tree(script), 'ScriptTask') is None:
            issues.append(f'{name}: script_task.py has no ScriptTask class')

        config = tasks_dir / ('TaskGroup' if name.startswith('TaskGroup') else name) / 'config.py'
        if not config.is_file():
            issues.append(f'{name}: missing config.py')
            continue
        config_class = class_node(source_tree(config), name)
        if config_class is None:
            issues.append(f'{name}: config.py has no {name} class')
        elif not name.startswith('TaskGroup') and not any(
                isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == 'scheduler' for node in config_class.body):
            issues.append(f'{name}: config class has no scheduler field')

    for folder in sorted(tasks_dir.iterdir()):
        if folder.is_dir() and (folder / 'script_task.py').is_file():
            if folder.name not in runnable | INTERNAL_TASKS:
                issues.append(f'{folder.name}: runnable directory is absent from ConfigMenu')

    group_names = {name for name in runnable if name.startswith('TaskGroup')}
    group_candidates = runnable - group_names
    for name in sorted(group_candidates - choices):
        issues.append(f'GroupTaskChoice: missing {name}')
    for name in sorted(choices - group_candidates):
        issues.append(f'GroupTaskChoice: unknown {name}')
    for name in sorted(runnable - priority):
        issues.append(f'SCHEDULER_PRIORITY: missing {name}')
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PROJECT_ROOT,
                        help='repository root (defaults to this script parent)')
    args = parser.parse_args()
    try:
        issues = check_structure(args.root)
    except (OSError, SyntaxError, ValueError, json.JSONDecodeError) as exc:
        print(f'Project structure check failed: {exc}')
        return 1
    if issues:
        print('\n'.join(f'ERROR: {issue}' for issue in issues))
        return 1
    print('Project structure OK: model, template, menu, scripts, groups, and priority agree.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
