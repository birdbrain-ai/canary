from typing import TypedDict, List, Dict
from logger import LLMLogger 
from langchain_openai import ChatOpenAI


llm = ChatOpenAI(
    model="Qwen/Qwen2.5-Coder-7B-Instruct", 
    openai_api_key="EMPTY",
    openai_api_base="http://localhost:8000/v1",
)

class FunctionInfo(TypedDict):
    """Metadata about an extracted function"""
    name: str              # Function name (e.g., "vecAdd")
    signature: str         # Full signature line
    body: str              # Function body only
    full_text: str         # Complete function (signature + body)
    start_line: int        # Starting line number in file (0-indexed)
    end_line: int          # Ending line number in file (0-indexed)

class PragmaAction(TypedDict):
    """Action to insert a pragma at a specific line"""
    action_type: str  # Must be "pragma"
    line_number: int  # Line number in the function (0-indexed)
    pragma_type: str  # "vectorize", "interleave", or "vectorize_width"
    width: int | None  # For vectorize_width(N), otherwise None
    reasoning: str  # Brief explanation from LLM

class CodeReplaceAction(TypedDict):
    """Action to replace specific lines within a function"""
    action_type: str  # Must be "code_replace"
    start_line: int  # Start line (0-indexed, relative to function)
    end_line: int  # End line (0-indexed, inclusive)
    new_code: str  # Replacement code (can be multi-line)
    reasoning: str  # Explanation of change

class VectorizationState(TypedDict):
    # Directory-level fields
    original_benchmark_dir: str
    benchmark_base_dir: str
    current_iteration_dir: str

    # Build/run commands
    make_command: str
    run_command: str

    # File tracking
    target_files: List[str]
    current_file_index: int
    current_file: str
    current_file_code: str

    # Function tracking
    functions_in_file: List[FunctionInfo]
    current_function_index: int
    current_function: FunctionInfo
    modified_file_content: str
    summarized_file_context: str
    transformed_function: str
    modification_actions: List[PragmaAction | CodeReplaceAction]

    # Iteration tracking
    current_iteration: int
    max_iterations: int

    # Remark files (per-directory)
    remark_files_baseline: List[str]     # Remark files from baseline compilation
    remark_files_current: List[str]      # Remark files from current iteration

    # Per-function context (nested: file -> function -> context)
    function_analysis_history: Dict[str, Dict[str, List[str]]]  # file_path -> function_name -> [analyses]
    function_summarized_context: Dict[str, Dict[str, str]]      # file_path -> function_name -> summary

    # Compiler feedback
    file_compilation_feedback: Dict[str, str]  # file_path -> formatted error/warning text

    # Status
    compiler_errors: List[str]
    success: bool
    
    # LLM logging
    llm_logger: LLMLogger  # Logger for all LLM interactions
