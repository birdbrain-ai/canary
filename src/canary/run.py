from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunConfig:
    run_id: str
    filepath: Path
    source: str
    model: str
    transform: str
    temperature: int
    ablated: str | None  # TODO: if we have a multidim ablation, this fails
    filters: list[str]

    def __init__(
        self,
        filepath: Path,
        model: str,
        transform: str,
        temperature: int,
        ablated: str | None,
        filters: list[str],
    ):
        self.run_id = f"{filepath}_{temperature}_{ablated or 'base'}"
        self.filepath = filepath
        self.source = filepath.read_text()
        self.model = model
        self.transform = transform
        self.temperature = temperature
        self.ablated = ablated
        self.filters = filters


@dataclass
class RunResult:
    run_id: str
    success: bool
    reason: str
    attempts: int
    final_kernel: str
