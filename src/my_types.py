from typing import TypedDict, List, Dict
# from logger import LLMLogger 
from langchain_openai import ChatOpenAI


# llm = ChatOpenAI(
#     model="Qwen/Qwen2.5-Coder-7B-Instruct", 
#     base_url="http://localhost:8000/v1",
# )


class PragmaAction(TypedDict):
    action_type: str  # Must be "pragma"
    line_number: int  # Line number in the function (0-indexed)
    pragma_type: str  # "vectorize", "interleave", or "vectorize_width"
    width: int | None  # For vectorize_width(N), otherwise None
    reasoning: str  # Brief explanation from LLM

    
class CodeReplaceAction(TypedDict):
    action_type: str  # Must be "code_replace"
    start_line: int  # Start line (0-indexed, relative to function)
    end_line: int  # End line (0-indexed, inclusive)
    new_code: str  # Replacement code (can be multi-line)
    reasoning: str  # Explanation of change


class FunctionInfo(TypedDict):
    name: str
    signature: str
    body: str
    full_text: str
    start_line: int
    end_line: int


class FunctionDraft:
    compile_success: bool
    dead_end: bool
    vectorization_success: bool
    reviewer_feedback: str
    modified_function_text: FunctionInfo

    def __init__(self, function_info):
        self.compile_success = False
        self.dead_end = False
        self.vectorization_success = False
        self.reviewer_feedback = ""
        self.modified_function_text = function_info


class VectorizationState(TypedDict):
    bench_path: str # const
    file_path: str # const
    make_command: str # const
    run_command: str # const

    raw_function: FunctionInfo
    start_line: int
    end_line: int
    program_slice: str # const
    compiler_feedback: str
    optimization_remarks: str

    current_iteration: int
    max_iterations: int # const
    manager_chosen_i: int

    function_drafts: Dict[int, FunctionDraft]
