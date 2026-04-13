from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator, Type

from trial.trial import Trial, TrialResult
from worker.worker import Worker


class WorkerPool:
    def __init__(
        self,
        max_workers: int,
        worker_class: Type[Worker],
        bench_path: Path,
        results_dir: Path,
    ):
        self.max_workers = max_workers
        self.worker_class = worker_class
        self.bench_path = bench_path
        self.results_dir = results_dir

    def run(self, trials: list[Trial]) -> Iterator[TrialResult]:
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [ex.submit(self._run_one, t) for t in trials]
            for fut in as_completed(futures):
                yield fut.result()

    def _run_one(self, trial: Trial) -> TrialResult:
        worker_path = self.results_dir / f"trial_{trial.trial_number}"
        worker = self.worker_class(
            trial, self.bench_path, worker_path, self.results_dir
        )
        try:
            worker.setup_worker()
            worker.setup_trial()
            return worker.run_trial()
        finally:
            worker.cleanup_trial()
            worker.cleanup_worker()
