"""Explicit source restriction for the public distribution's updater."""
from pathlib import Path
import re
import subprocess

from deploy.config import ExecutionError

OFFICIAL_REPOSITORY = 'https://github.com/xylolit-mu/OnmyojiAutoScript.git'


def is_official_repository(value):
    # Accept GitHub's HTTPS and SSH spellings of the same repository only.
    return bool(re.fullmatch(
        r'(?:https://github[.]com/|git@github[.]com:|ssh://git@github[.]com/)'
        r'xylolit-mu/OnmyojiAutoScript(?:[.]git)?/?',
        str(value or '').strip(), re.IGNORECASE))


def validate_update_source(git, root, repository, source='origin'):
    message = ('Repository source rejected: updates require '
               + OFFICIAL_REPOSITORY
               + '. No fetch or pull was performed.')
    if not is_official_repository(repository):
        raise ExecutionError(message)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', source):
        raise ExecutionError(message)
    if not (Path(root) / '.git').exists():
        return  # First installation; validate its configured URL above.
    try:
        result = subprocess.run(
            [git, 'remote', 'get-url', '--all', source], cwd=root,
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ExecutionError(message) from error
    urls = result.stdout.splitlines()
    if result.returncode or not urls or not all(is_official_repository(u) for u in urls):
        raise ExecutionError(message)
