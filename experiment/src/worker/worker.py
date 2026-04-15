# this is a worker.
# this is the thing that's responsible for
# taking in a benchmark, processing it somehow, etc.
# it should have some functions like:
# start the trial in the docker image
# clean up everything in the docker image, etc.
# this is going to be the meat of the whole thing
# consider making this an abstract class, and making workers that
# inherit from it per experiment
# so, we would have a different worker for the rust experiments
# than the workers for the vectorization experiments

# TODO: Vectorize a small copy of TSVC with one function in it, using mini-swe-agent, Docker, and git diffs to track evolutions between turns.

import shutil
import subprocess
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import docker
from docker.types import Mount

from trial.trial import Trial, TrialResult


class Worker(ABC):
    def __init__(
        self,
        trial: Trial,
        bench_path: Path,
        worker_path: Path,
        results_dir: Path,
    ):
        self.trial = trial
        self.bench_path = bench_path
        self.worker_path = worker_path
        self.results_dir = results_dir
        self.container = None
        self.baseline_commit: str | None = None

    def setup_worker(self):
        self.worker_path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.bench_path, self.worker_path, dirs_exist_ok=True)

        self._git("init", "-q")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "baseline")
        self.baseline_commit = self._git("rev-parse", "HEAD").strip()

        mounts = [
            Mount(
                target="/workspace",
                source=str(self.worker_path.resolve()),
                type="bind",
            ),
        ]
        client = docker.from_env()
        self.container = client.containers.run(
            image=self.trial.benchmark.docker_image(),
            command="sleep infinity",
            detach=True,
            mounts=mounts,
            name=f"canary-worker-{uuid.uuid4().hex[:8]}",
            working_dir="/workspace",
            auto_remove=False,
        )

    def setup_trial(self):
        # Reserved for a future shared-worker pattern; currently one worker per trial.
        pass

    @abstractmethod
    def run_trial(self) -> TrialResult:
        pass

    def cleanup_trial(self):
        if self.baseline_commit is None:
            return
        trial_dir = self.results_dir / f"trial_{self.trial.trial_number}"
        trial_dir.mkdir(parents=True, exist_ok=True)
        (trial_dir / "git_log.txt").write_text(self._git("log", "--oneline"))
        (trial_dir / "git_diff.patch").write_text(
            self._git("diff", f"{self.baseline_commit}..HEAD")
        )

    def cleanup_worker(self):
        if getattr(self, "container", None) is None:
            return
        self.container.stop(timeout=5)
        self.container.remove()
        self.container = None

    def _git(self, *args: str) -> str:
        res = subprocess.run(
            ["git", *args],
            cwd=self.worker_path,
            check=False,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (exit {res.returncode}): {res.stderr}"
            )
        return res.stdout
