from pathlib import Path
from queue import Queue

from pydantic import BaseModel, Field, HttpUrl, model_validator

from trial.trial import Compiler, Topic, TrialResult


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


class Experiment:
    def __init__(self, config_json: str | Path):
        self.config = ExperimentConfig.model_validate_json(
            Path(config_json).read_text()
        )
        self.queue: Queue = Queue()
        self.results: list[TrialResult] = []

    def start_experiment(self):
        pass

    def write_out_results(self):
        pass
