from typing import TypedDict, Dict, Optional
from logger import LLMLogger
from langchain_openai import ChatOpenAI


llm = ChatOpenAI(
    model="Qwen/Qwen3-8B",
    api_key="",
    base_url="http://localhost:8000/v1",
)


class SearchReplaceAction(TypedDict):
    search: str  # The exact text to search for
    replace: str  # The replacement text


class FunctionInfo(TypedDict):
    name: str
    signature: str
    body: str
    full_text: str
    start_line: int
    end_line: int


class KernelInfo(TypedDict):
    kernel_text: str
    kernel_start_line: int  # Relative to function start
    kernel_end_line: int    # Relative to function start


class FunctionDraft:
    compile_success: bool
    run_success: bool
    dead_end: bool
    vectorization_success: bool
    runtime_s: float | None
    reviewer_feedback: str
    modified_function_text: FunctionInfo
    kernel_info: KernelInfo | None
    modified_kernel_text: str | None

    def __init__(self, function_info, kernel_info=None):
        self.compile_success = False
        self.run_success = False
        self.dead_end = False
        self.vectorization_success = False
        self.runtime_s = None
        self.reviewer_feedback = ""
        self.modified_function_text = function_info
        self.kernel_info = kernel_info
        self.modified_kernel_text = kernel_info["kernel_text"] if kernel_info else None

    def to_dict(self):
        return {
            "compile_success": self.compile_success,
            "run_success": self.run_success,
            "dead_end": self.dead_end,
            "vectorization_success": self.vectorization_success,
            "runtime_s": self.runtime_s,
            "reviewer_feedback": self.reviewer_feedback,
            "modified_function_text": self.modified_function_text,
            "kernel_info": self.kernel_info,
            "modified_kernel_text": self.modified_kernel_text
        }


class VectorizationState(TypedDict):
    bench_path: str # const
    file_path: str # const
    make_command: str # const
    run_command: str # const
    use_compiler_feedback: bool # const
    use_clang_not_intel: bool # const

    program_slice: str # const
    compiler_feedback: str
    optimization_remarks: str

    current_iteration: int
    max_iterations: int # const
    manager_chosen_i: int

    function_drafts: Dict[int, FunctionDraft]
    logger: 'LLMLogger'
