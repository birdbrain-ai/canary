from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from benchmark.benchmark import Benchmark


class Topic(str, Enum):
    VECTORIZATION = "vectorization"
    RUST = "rust"


class Compiler(str, Enum):
    CLANG = "clang"
    CLANG_CANARY = "clang_canary"
    CLANG_CANARY_21_1_8 = "clang_canary_21.1.8"
    CLANG_TRUNK = "clang_trunk"
    ICX_2025_3 = "icx-2025.3"


class TrialResult(BaseModel):
    success: bool
    compile_ok: bool
    iterations_used: int = Field(ge=0)


class Trial(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trial_number: int = Field(ge=0)
    benchmark: Benchmark
    compiler: Compiler
    compiler_diagnostics: str
    handwritten_diagnostics: str
    llm_name: str
    llm_url: HttpUrl
    temperature: float = Field(ge=0.0, le=2.0)
    iterations: int = Field(ge=1)
    skip_files: list[str] = Field(default_factory=list)
    skip_funcs: list[str] = Field(default_factory=list)
    result: TrialResult | None = None
