from dataclasses import dataclass


@dataclass
class RunConfig:
    run_id: str
    kernel: str
    temperature: int


@dataclass
class RunResult:
    run_id: str
    success: bool
    reason: str
    attempts: int
    final_kernel: str
    log: dict
