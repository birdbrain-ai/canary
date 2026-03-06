import os
import sys

# Add src/ to path so we can import from utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from typing import TypedDict, Dict, Optional
from utils.logger import LLMLogger
from langchain_openai import ChatOpenAI


llm = ChatOpenAI(
    model="Qwen/Qwen2.5-Coder-7B-Instruct",
    api_key="",
    base_url="http://localhost:8000/v1"
    # temperature=0.7
)

print(llm.temperature)

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


class FunctionDraft:
    compile_success: bool
    run_success: bool
    dead_end: bool
    vectorization_success: bool
    runtime_s: float | None
    reviewer_feedback: str
    modified_function_text: FunctionInfo

    def __init__(self, function_info):
        self.compile_success = False
        self.run_success = False
        self.dead_end = False
        self.vectorization_success = False
        self.runtime_s = None
        self.reviewer_feedback = ""
        self.modified_function_text = function_info

    def to_dict(self):
        return {
            "compile_success": self.compile_success,
            "run_success": self.run_success,
            "dead_end": self.dead_end,
            "vectorization_success": self.vectorization_success,
            "runtime_s": self.runtime_s,
            "reviewer_feedback": self.reviewer_feedback,
            "modified_function_text": self.modified_function_text
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
    # perf_data: str

    current_iteration: int
    max_iterations: int # const
    manager_chosen_i: int

    function_drafts: Dict[int, FunctionDraft]
    logger: 'LLMLogger'
