from deploy.source_guard import validate_update_source
import datetime
import subprocess
from typing import Tuple

from deploy.config import ExecutionError
from deploy.git import GitManager
from deploy.pip import PipManager
from deploy.utils import DEPLOY_CONFIG
from module.logger import logger
from module.base.retry import retry
from module.server.config import DeployConfig


DEFAULT_GIT_TIMEOUT = 5
DEFAULT_FETCH_TIMEOUT = 15
FETCH_RETRY = 2


class Updater(DeployConfig, GitManager, PipManager):
    def __init__(self, file=DEPLOY_CONFIG):
        super().__init__(file=file)
        self.state = 0

    @property
    def delay(self):
        self.read()
        return int(self.CheckUpdateInterval) * 60

    @property
    def schedule_time(self):
        self.read()
        t = self.AutoRestartTime
        if t is not None:
            return datetime.time.fromisoformat(t)
        else:
            return None

    def execute_command(self, command, timeout=DEFAULT_GIT_TIMEOUT) -> subprocess.CompletedProcess | None:
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
                shell=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"Git command timeout after {timeout}s: {command}")
            return None
        except OSError as e:
            logger.warning(f"Git command failed: {command}, error: {e}")
            return None

    def execute_output(self, command, timeout=DEFAULT_GIT_TIMEOUT) -> str:
        result = self.execute_command(command, timeout=timeout)
        if result is None:
            return ""
        if result.returncode:
            logger.warning(f"Git command failed: {command}, stderr: {result.stderr.strip()}")
            return ""
        return result.stdout

    def get_commit(self, revision="", n=1, short_sha1=False) -> Tuple:
        """
        Return:
            (sha1, author, isotime, message,)
        """
        ph = "h" if short_sha1 else "H"

        log = self.execute_output(
            f'"{self.git}" --no-pager log {revision} --pretty=format:"%{ph}---%an---%ad---%s" --date=iso -{n}'
        )

        if not log:
            return None, None, None, None

        logs = log.split("\n")
        logs = list(map(lambda log: tuple(log.split("---")), logs))

        if n == 1:
            return logs[0]
        else:
            return logs

    def current_branch(self) -> str:
        return self.Branch

    def current_commit(self) -> str:
        return self.get_commit()

    def latest_commit(self) -> str:
        source = "origin"
        return self.get_commit(f"{source}/{self.Branch}")

    def fetch_remote(self) -> bool:
        if not self.AutoUpdate:
            logger.info("AutoUpdate is disabled, skip git fetch")
            return False

        source = "origin"
        validate_update_source(self.git, self.root_filepath, self.Repository, source)
        for _ in range(FETCH_RETRY):
            result = self.execute_command(
                f'"{self.git}" fetch {source} {self.Branch}',
                timeout=DEFAULT_FETCH_TIMEOUT,
            )
            if result is not None and result.returncode == 0:
                return True
            if result is not None:
                logger.warning(f"Git fetch failed: {result.stderr.strip()}")

        logger.warning("Git fetch failed")
        return False

    def revision_distance(self, left: str, right: str) -> tuple[int, int] | None:
        log = self.execute_output(
            f'"{self.git}" rev-list --left-right --count {left}...{right}'
        )
        if not log:
            return None

        try:
            ahead, behind = log.split()
            return int(ahead), int(behind)
        except ValueError:
            logger.warning(f"Unexpected git rev-list output: {log.strip()}")
            return None

    def get_update_info(self) -> dict:
        is_update = False
        source = "origin"
        remote_revision = f"{source}/{self.Branch}"

        if self.fetch_remote():
            distance = self.revision_distance("HEAD", remote_revision)
            if distance is None:
                is_update = False
            else:
                ahead, behind = distance
                is_update = not ahead and bool(behind)
                if ahead:
                    logger.info("Local branch has commits not in upstream, skip update")
                logger.info("New update available" if is_update else "No update")

        commits = self.get_commit(remote_revision, n=15)
        latest_commit = commits[0] if commits and isinstance(commits, list) else commits
        return {
            'is_update': is_update,
            'branch': self.current_branch(),
            'current_commit': self.current_commit(),
            'latest_commit': latest_commit,
            'commit': commits,
        }

    def execute_pull(self) -> bool:
        if not self.AutoUpdate:
            logger.info("AutoUpdate is disabled, skip git pull")
            return False

        source = "origin"
        for _ in range(FETCH_RETRY):
            if self.execute(
                    f'"{self.git}" pull {source} {self.Branch} --no-rebase', allow_failure=True
            ):
                break
        else:
            logger.warning("Git fetch failed")
            return False


if __name__ == "__main__":
    updater = Updater()
    print(updater.latest_commit())
