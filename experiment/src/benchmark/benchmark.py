from abc import ABC, abstractmethod
from pathlib import Path
from typing import Type


class Benchmark(ABC):
    def __init__(self, bench_path: Path):
        self.bench_path = bench_path

    @abstractmethod
    def docker_image(self) -> str: ...

    @abstractmethod
    def make_command(self) -> str: ...

    @abstractmethod
    def run_command(self) -> str: ...

    @abstractmethod
    def baseline(self, workspace: Path) -> float: ...

    @abstractmethod
    def verify(self, workspace: Path) -> bool: ...


class MyBenchBenchmark(Benchmark):
    def docker_image(self) -> str:
        return "ubuntu:22.04"

    def make_command(self) -> str:
        return "make"

    def run_command(self) -> str:
        return "./c_prog"

    def baseline(self, workspace: Path) -> float:
        return 0.0

    def verify(self, workspace: Path) -> bool:
        return True


BENCHMARKS: dict[str, Type[Benchmark]] = {"my_bench": MyBenchBenchmark}
