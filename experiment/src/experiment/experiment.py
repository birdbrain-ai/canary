from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl, model_validator

from benchmark.benchmark import BENCHMARKS
from trial.trial import Compiler, Topic, Trial, TrialResult
from worker.vectorize_worker import VectorizeWorker
from worker_pool.worker_pool import WorkerPool


class ExperimentConfig(BaseModel):
    experiment_name: str
    topic: Topic
    compiler: Compiler

    compiler_diagnostics: str
    handwritten_diagnostics: str

    llm_name: str
    llm_url: HttpUrl
    temperature: float = Field(ge=0.0, le=2.0)

    iterations: int = Field(ge=1)
    num_trials: int = Field(ge=1)

    results_dir: Path
    data_dir: Path

    benchmark: str

    max_jobs: int = Field(default=8, ge=1)
    skip_files: list[str] = Field(default_factory=list)
    skip_funcs: list[str] = Field(default_factory=list)

    compiler_for_makefile: str | None = None
    filter_distribute_suggestion: bool = False

    @model_validator(mode="after")
    def _check_topic_fields(self) -> "ExperimentConfig":
        if self.topic == Topic.VECTORIZATION and self.compiler_for_makefile is None:
            raise ValueError(
                "compiler_for_makefile is required when topic='vectorization'"
            )
        return self

    @model_validator(mode="after")
    def _check_benchmark(self) -> "ExperimentConfig":
        if self.benchmark not in BENCHMARKS:
            known = sorted(BENCHMARKS.keys())
            raise ValueError(
                f"unknown benchmark {self.benchmark!r}; known: {known}"
            )
        return self


class Experiment:
    def __init__(self, config_json: str | Path):
        self.config = ExperimentConfig.model_validate_json(
            Path(config_json).read_text()
        )
        self.benchmark = BENCHMARKS[self.config.benchmark](
            bench_path=self.config.data_dir
        )
        self.results: list[TrialResult] = []

    def start_experiment(self) -> None:
        if self.config.topic == Topic.VECTORIZATION:
            worker_class = VectorizeWorker
        elif self.config.topic == Topic.RUST:
            raise NotImplementedError("rust worker not implemented yet")
        else:
            raise NotImplementedError(f"no worker for topic {self.config.topic}")

        trials = [self._make_trial(i) for i in range(self.config.num_trials)]

        pool = WorkerPool(
            max_workers=self.config.max_jobs,
            worker_class=worker_class,
            bench_path=self.config.data_dir,
            results_dir=self.config.results_dir,
        )

        for result in pool.run(trials):
            self.results.append(result)

    def _make_trial(self, trial_number: int) -> Trial:
        c = self.config
        return Trial(
            trial_number=trial_number,
            benchmark=self.benchmark,
            compiler=c.compiler,
            compiler_diagnostics=c.compiler_diagnostics,
            handwritten_diagnostics=c.handwritten_diagnostics,
            llm_name=c.llm_name,
            llm_url=c.llm_url,
            temperature=c.temperature,
            iterations=c.iterations,
            skip_files=c.skip_files,
            skip_funcs=c.skip_funcs,
        )

    def write_out_results(self) -> None:
        for result in self.results:
            print(result.model_dump_json())
