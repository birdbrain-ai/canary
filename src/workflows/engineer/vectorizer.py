from langgraph.graph import StateGraph, END
from langchain_community.document_loaders import TextLoader
import os
import subprocess
import shutil
import argparse
import json
import tempfile
import sys

# Add src/ to path so we can import from utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.more_helpers import extract_functions, find_files_with_ext, find_target_files, extract_file_context, match_remark_files, filter_remarks_by_function, extract_compilation_errors
from typing import TypedDict, Dict, List
from langchain_openai import ChatOpenAI

from utils.logger import LLMLogger
from prompts import get_engineer_prompt
import re


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

    current_iteration: int
    max_iterations: int # const
    manager_chosen_i: int

    function_drafts: Dict[int, FunctionDraft]
    logger: 'LLMLogger'

MAX_LINT_RETRIES = 3

def check_syntax(file_path: str, use_clang_not_intel: bool, logger=None) -> tuple[bool, str]:
    """
    Check syntax of a C/C++ file using the compiler's syntax-only mode.

    Args:
        file_path: Path to the source file to check
        use_clang_not_intel: If True, use clang; if False, use icx
        logger: Optional logger for debug output

    Returns:
        Tuple of (success: bool, errors: str)
    """
    compiler = "clang" if use_clang_not_intel else "icx"
    cmd = f"{compiler} -fsyntax-only {file_path}"

    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return (True, "")
    else:
        # Combine stderr (where compiler errors go) with any stdout
        errors = result.stderr
        if result.stdout:
            errors = result.stdout + "\n" + errors
        return (False, errors.strip())


# Helper: Serialize VectorizationState to JSON
def serialize_state_to_json(state: VectorizationState) -> dict:
    """
    Convert VectorizationState to a JSON-serializable dictionary.

    Args:
        state: The VectorizationState to serialize

    Returns:
        A dictionary that can be JSON-serialized
    """
    # Convert function_drafts to serializable format
    serialized_drafts = {}
    for iteration, draft in state["function_drafts"].items():
        serialized_drafts[str(iteration)] = draft.to_dict()

    # Create serialized state, excluding non-serializable fields
    serialized_state = {
        "bench_path": state["bench_path"],
        "file_path": state["file_path"],
        "make_command": state["make_command"],
        "run_command": state["run_command"],
        "use_compiler_feedback": state["use_compiler_feedback"],
        "program_slice": state["program_slice"],
        "compiler_feedback": state["compiler_feedback"],
        "optimization_remarks": state["optimization_remarks"],
        "current_iteration": state["current_iteration"],
        "max_iterations": state["max_iterations"],
        "manager_chosen_i": state["manager_chosen_i"],
        "function_drafts": serialized_drafts,
    }

    return serialized_state


# Node: compile_code
def compile_code(state: VectorizationState):
    '''
    Compiles code base. 
    This node is responsible for updating the following fields in VectorizationState.
    
    In state:
    1. compiler_feedback
    2. optimization_remarks

    In function_drafts[current_iteration]:
    1. compile_success
    2. vectorization_success

    '''
    logger = state["logger"]
    logger.log_state(state, "compile_code", "before")
    
    bench_path = state["bench_path"]
    cur_working_dir = os.getcwd()
    make_command = state["make_command"]
    current_file = state["file_path"]
    use_clang_not_intel = state["use_clang_not_intel"]

    current_iteration = state["current_iteration"]
    function_drafts = state["function_drafts"]
    cur_function_draft = function_drafts[current_iteration]
    cur_function_info = cur_function_draft.modified_function_text
    cur_function_name = cur_function_info["name"]

    os.chdir(bench_path)

    if current_iteration == 1 and function_drafts[0].vectorization_success:
        return {}
    
    subprocess.run(
        "find . -name '*.opt.yaml' -type f -delete",
        shell=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        "find . -name '*.optrpt' -type f -delete",
        shell=True,
        capture_output=True,
        text=True,
    )
    
    result = subprocess.run(
        make_command,
        shell=True,
        capture_output=True,
        text=True,
    )

    # 1. Extract compilation feedback.
    # TODO(akash): obviously just replace this with a compiler option instead of filtering it manually. Just make the compiler only output warnings and errors instead of an insane quantity of notes.
    # Convert 0-indexed function line numbers to 1-indexed compiler line numbers
    func_start_line_1indexed = cur_function_info["start_line"] + 1
    func_end_line_1indexed = cur_function_info["end_line"] + 1
    compilation_feedback = extract_compilation_errors(
        result.stderr,
        line_range_start=func_start_line_1indexed,
        line_range_end=func_end_line_1indexed
    )

    # print(result)
    cur_function_draft.compile_success = result.returncode == 0

    # 2. Extract optimization remarks
    if use_clang_not_intel:
        all_remark_files = find_files_with_ext(bench_path, [".yaml"])
    else:
        all_remark_files = find_files_with_ext(bench_path, [".optrpt"])
    relevant_remark_files: List[str] = match_remark_files(current_file, all_remark_files, use_clang_not_intel)
    relevant_remarks: List[str] = []
    only_vec_remarks: List[str] = []
    for remark_file in relevant_remark_files:
        relevant_remarks.append(filter_remarks_by_function(remark_file,
                                                           cur_function_name,
                                                           False,
                                                           use_clang_not_intel))
        only_vec_remarks.append(filter_remarks_by_function(remark_file,
                                                           cur_function_name,
                                                           False,
                                                           use_clang_not_intel))
    optimization_remarks = "\n".join(relevant_remarks)
    only_vec_remarks = "\n".join(only_vec_remarks)
    if use_clang_not_intel:
        vectorization_success = "!Passed" in only_vec_remarks
    else:
        vectorization_success = re.search(r"was vectorized", optimization_remarks, re.IGNORECASE) is not None

    cur_function_draft.vectorization_success = vectorization_success

    function_drafts[current_iteration] = cur_function_draft
    
    os.chdir(cur_working_dir)

    result_dict = {
        "compiler_feedback": compilation_feedback,
        "optimization_remarks": optimization_remarks,
        "function_drafts": function_drafts
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "compile_code", "after")
    
    return result_dict


# Helper: Parse runtime from validation script output
def parse_runtime_from_output(output: str) -> float | None:
    """
    Parse RUNTIME_S: <value> from validation script stdout.

    Args:
        output: stdout from the validation script

    Returns:
        Runtime in seconds as float, or None if not found/invalid
    """
    import re
    match = re.search(r'RUNTIME_S:\s*([\d.]+)', output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


# Node: run_code
def run_code(state: VectorizationState):
    '''
    Runs code
    This node is responsible for the following fields:

    In function_drafts[current_iteration],
    1. run_success
    2. runtime_s (parsed from RUNTIME_S: <value> in stdout)

    '''
    logger = state["logger"]
    logger.log_state(state, "run_code", "before")

    run_command = state['run_command']

    function_drafts = state["function_drafts"]
    current_iteration = state["current_iteration"]
    cur_function_draft = function_drafts[current_iteration]

    # Early exit: if compile failed, skip running and mark run as failed
    if not cur_function_draft.compile_success:
        cur_function_draft.run_success = False
        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }

    if current_iteration == 0 and function_drafts[current_iteration].vectorization_success:
        cur_function_draft.run_success = True
        function_drafts[current_iteration] = cur_function_draft
        return {
            "function_drafts": function_drafts
        }

    # Early exit: No run command provided, so the run is presumed successful
    if not run_command:
        logger.print("No run command provided")
        cur_function_draft.run_success = True
        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }

    bench_path = state['bench_path']
    cur_working_dir = os.getcwd()

    # Serialize state to JSON and write to temporary file
    serialized_state = serialize_state_to_json(state)
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_file_path = temp_file.name

    try:
        json.dump(serialized_state, temp_file, indent=2)
        temp_file.close()

        os.chdir(bench_path)

        # Append the temp file path to the run command

        # perf stat -e 'cache-misses,cache-references,instructions,cycles'

        full_command = f"{run_command} {temp_file_path}"

        try:
           result = subprocess.run(
               full_command,
               shell=True,
               capture_output=True,
               text=True,
               timeout=600
           )

           # Log stdout and stderr from validation script
           if result.stdout:
               logger.print(result.stdout, end='')
           if result.stderr:
               logger.print(result.stderr, end='')
        # Early exit: Timeout, so run failed
        except subprocess.TimeoutExpired:
            logger.print("Running the benchmark took too much time")
            cur_function_draft.run_success = False
            function_drafts[current_iteration] = cur_function_draft
            logger.log_state(state, "run_code", "after")
            os.chdir(cur_working_dir)
            return {
                "function_drafts": function_drafts
            }

        # Main case: either the run throws an error, or it succeeds
        if result.returncode != 0:
            logger.print(f"Running the benchmark threw an error: {result.returncode}")

        os.chdir(cur_working_dir)
        cur_function_draft.run_success = result.returncode == 0

        # reviewer_feedback now holds perf data!
        cur_function_draft.reviewer_feedback = result.stderr

        # Parse runtime from stdout if run succeeded
        if cur_function_draft.run_success and result.stdout:
            cur_function_draft.runtime_s = parse_runtime_from_output(result.stdout)
            if cur_function_draft.runtime_s is not None:
                logger.print(f"Runtime: {cur_function_draft.runtime_s:.6f}s")

        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }
    finally:
        # Clean up temporary file
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


# Node: engineer: parse search-replace output
def parse_search_replace_output(output: str, logger = None) -> list[SearchReplaceAction] | None:
    """
    Parse the engineer LLM output to extract ONE search-replace block.

    Expected format:
    <<<<<<< SEARCH
    code to search
    =======
    replacement code
    >>>>>>> REPLACE

    Args:
        output: Raw LLM output string
        logger: Optional LLMLogger instance for logging

    Returns:
        List with one SearchReplaceAction dict, or None if parsing fails, or empty list if NO_CHANGES
    """
    import re

    # Strip thinking tokens: everything up to and including </think> (Qwen3.5 style)
    if '</think>' in output:
        output = output.split('</think>', 1)[1]

    # Check for NO_CHANGES
    if "NO_CHANGES" in output.strip():
        return []

    # Pattern to match search-replace blocks
    pattern = r'<{7,}\s*SEARCH\s*\n(.*?)\n={7,}\s*\n(.*?)\n>{7,}\s*REPLACE'

    matches = re.findall(pattern, output, re.DOTALL)

    if not matches:
        msg1 = "⚠️  No valid search-replace block found in engineer output"
        msg2 = f"    Output: {output[:200]}..."
        if logger:
            logger.print(msg1)
            logger.print(msg2)
        else:
            print(msg1)
            print(msg2)
        return None

    if len(matches) > 1:
        msg = f"⚠️  Warning: Found {len(matches)} search-replace blocks, expected 1. Using only the first."
        if logger:
            logger.print(msg)
        else:
            print(msg)

    # Take only the first block
    search_text, replace_text = matches[0]
    action: SearchReplaceAction = {
        "search": search_text,
        "replace": replace_text
    }

    msg = "✅ Parsed 1 search-replace block"
    if logger:
        logger.print(msg)
    else:
        print(msg)
    return [action]


# Helper: Write function to file
def write_function_to_file(
    file_path: str,
    function_info: FunctionInfo,
    replace_start: int | None = None,
    replace_end: int | None = None,
    logger = None
) -> bool:
    """
    Write a modified function back to its source file.

    Args:
        file_path: Absolute path to the source file
        function_info: FunctionInfo with modified full_text to write
        replace_start: Start line to replace (0-indexed). If None, use function_info["start_line"]
        replace_end: End line to replace (0-indexed). If None, use function_info["end_line"]
        logger: Optional LLMLogger instance for logging

    Returns:
        True if successful, False otherwise
    """
    try:
        # Read the entire file
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Determine range to replace
        start = replace_start if replace_start is not None else function_info["start_line"]
        end = replace_end if replace_end is not None else function_info["end_line"]
        
        # Validate line numbers
        if start < 0 or end >= len(lines) or start > end:
            msg = f"⚠️  Invalid line range {start}-{end} for file with {len(lines)} lines"
            if logger:
                logger.print(msg)
            else:
                print(msg)
            return False
        
        # Replace the function lines with the modified function
        modified_function_lines = function_info["full_text"].splitlines(keepends=True)
        # Ensure the last line has a newline if it's not the end of the file
        if modified_function_lines and not modified_function_lines[-1].endswith('\n'):
            modified_function_lines[-1] += '\n'
        
        # Replace the old function with the new one
        new_lines = lines[:start] + modified_function_lines + lines[end+1:]
        
        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        return True

    except IOError as e:
        msg = f"⚠️  Failed to write function to {file_path}: {e}"
        if logger:
            logger.print(msg)
        else:
            print(msg)
        return False


# Helper: Normalize whitespace for flexible matching
def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text for flexible matching.
    Strips leading/trailing whitespace from each line and normalizes internal whitespace.

    Args:
        text: Original text with arbitrary whitespace

    Returns:
        Text with normalized whitespace
    """
    import re
    lines = text.split('\n')
    normalized_lines = []
    for line in lines:
        # Strip leading AND trailing whitespace from each line
        stripped = line.strip()
        if stripped:
            # Replace multiple spaces/tabs with single space
            normalized = re.sub(r'[ \t]+', ' ', stripped)
            normalized_lines.append(normalized)
        else:
            normalized_lines.append('')
    return '\n'.join(normalized_lines)


def find_fuzzy_match(search_text: str, target_text: str) -> tuple[int, int] | None:
    """
    Find a match for search_text in target_text using whitespace-forgiving matching.

    Args:
        search_text: Text to search for
        target_text: Text to search in

    Returns:
        Tuple of (start_pos, end_pos) if found, None otherwise
    """
    # First try exact match
    pos = target_text.find(search_text)
    if pos != -1:
        return (pos, pos + len(search_text))

    # Try whitespace-normalized matching
    normalized_search = normalize_whitespace(search_text)
    normalized_target = normalize_whitespace(target_text)

    pos = normalized_target.find(normalized_search)
    if pos == -1:
        return None

    # Now we need to map the position back to the original text
    # Count characters in normalized target up to pos
    # Then count same number of "meaningful" chars in original

    # This is complex, so let's use a simpler approach:
    # Split into lines and try to match line by line with fuzzy whitespace
    search_lines = search_text.split('\n')
    target_lines = target_text.split('\n')
    normalized_search_lines = normalized_search.split('\n')

    # Try to find a sequence of lines that match
    for i in range(len(target_lines) - len(search_lines) + 1):
        match = True
        for j in range(len(search_lines)):
            target_norm = normalize_whitespace(target_lines[i + j])
            if target_norm != normalized_search_lines[j]:
                match = False
                break

        if match:
            # Found a match! Calculate positions
            start_pos = sum(len(line) + 1 for line in target_lines[:i])  # +1 for \n

            # Calculate end position: sum of lines up to (but not including) the line after our match
            # We need to account for the newlines between lines, but not after the last matched line
            end_line_idx = i + len(search_lines)
            if end_line_idx < len(target_lines):
                # Not the last line in the file - include trailing newline
                end_pos = sum(len(line) + 1 for line in target_lines[:end_line_idx])
            else:
                # Last line(s) in file - don't include trailing newline that doesn't exist
                end_pos = sum(len(line) + 1 for line in target_lines[:end_line_idx]) - 1

            return (start_pos, end_pos)

    return None


# Helper: Apply search-replace actions to function
def apply_search_replace_actions(
    function_info: FunctionInfo,
    actions: list[SearchReplaceAction],
    logger = None
) -> FunctionInfo:
    """
    Apply a list of search-replace actions to a function to create a modified version.
    Uses whitespace-forgiving matching to handle indentation differences.

    Args:
        function_info: Original function information
        actions: List of SearchReplaceAction dicts
        logger: Optional LLMLogger instance for logging

    Returns:
        Modified FunctionInfo with updated full_text and body
    """
    modified_text = function_info["full_text"]

    for i, action in enumerate(actions):
        search_text = action["search"]
        replace_text = action["replace"]

        # Try fuzzy matching with whitespace tolerance
        match_result = find_fuzzy_match(search_text, modified_text)

        if match_result is None:
            if logger:
                logger.print(f"⚠️  Search-replace action {i}: search text not found")
                logger.print(f"    Looking for ({len(search_text)} chars):")
                logger.print(f"    {repr(search_text[:200])}")
                logger.print(f"\n    In modified text ({len(modified_text)} chars):")
                logger.print(f"    {repr(modified_text[:400])}")
            else:
                print(f"⚠️  Search-replace action {i}: search text not found")
                print(f"    Looking for ({len(search_text)} chars):")
                print(f"    {repr(search_text[:200])}")
                print(f"\n    In modified text ({len(modified_text)} chars):")
                print(f"    {repr(modified_text[:400])}")
            continue

        start_pos, end_pos = match_result

        # Check for multiple matches (try to find another occurrence)
        remaining_text = modified_text[end_pos:]
        second_match = find_fuzzy_match(search_text, remaining_text)

        if second_match is not None:
            if logger:
                logger.print(f"⚠️  Search-replace action {i}: search text appears multiple times (ambiguous)")
                logger.print(f"    Looking for: {search_text[:100]}...")
            else:
                print(f"⚠️  Search-replace action {i}: search text appears multiple times (ambiguous)")
                print(f"    Looking for: {search_text[:100]}...")
            continue

        # Perform the replacement
        # Preserve trailing newline if the original matched text had one
        original_match = modified_text[start_pos:end_pos]
        if original_match.endswith('\n') and not replace_text.endswith('\n'):
            replace_text = replace_text + '\n'

        modified_text = modified_text[:start_pos] + replace_text + modified_text[end_pos:]
        if logger:
            logger.print(f"✅ Applied search-replace action {i}")
        else:
            print(f"✅ Applied search-replace action {i}")

    # Calculate new end_line based on number of lines in modified text
    new_num_lines = len(modified_text.splitlines())
    new_end_line = function_info["start_line"] + new_num_lines - 1

    # Create modified function info
    modified_info: FunctionInfo = {
        "name": function_info["name"],
        "signature": function_info["signature"],
        "body": modified_text,  # Update body as well
        "full_text": modified_text,
        "start_line": function_info["start_line"],
        "end_line": new_end_line
    }

    return modified_info


# Node: engineer
def engineer(state: VectorizationState):
    '''
    This function is responsible for applying suggestions to a code base.

    In function_drafts[current_iteration],
    1. modified_function_text

    And, responsible for writing to file
    '''

    logger = state["logger"]
    logger.log_state(state, "engineer", "before")

    program_slice = state["program_slice"]
    make_command = state["make_command"]
    file_path = state["file_path"]
    use_clang_not_intel = state["use_clang_not_intel"]
    current_iteration = state["current_iteration"]

    function_drafts = state["function_drafts"]
    current_function_draft = function_drafts[0]
    perf_info = current_function_draft.reviewer_feedback
    opt_remarks = state["optimization_remarks"]
    compiler_feedback = state["compiler_feedback"]
    use_compiler_feedback = state["use_compiler_feedback"]
    current_function_info = current_function_draft.modified_function_text

    # Determine what's currently in the file by finding the last written draft
    # The last written draft is the one from the previous iteration (current_iteration - 1)
    last_written_index = current_iteration - 1 if current_iteration != 0 else 0
    last_written_info = function_drafts[last_written_index].modified_function_text

    # Retry loop for syntax errors
    lint_errors = None
    previous_search_replace = None
    new_func_info = last_written_info  # Default to what's in the file if all attempts fail

    # If the function is vectorized, then we skip
    if function_drafts[0].vectorization_success:
        logger.print("WE ARE SKIPPING THIS ITERATION BECAUSE THE FUNCTION WAS ALREADY VECTORIZED!")
        return {
            "current_iteration": current_iteration + 1
        }

    if not use_compiler_feedback:
        compiler_feedback = ""
        opt_remarks = ""

    
    for attempt in range(MAX_LINT_RETRIES):
        if attempt > 0:
            logger.print(f"🔄 Retry attempt {attempt + 1}/{MAX_LINT_RETRIES} due to syntax errors")

        prompt = get_engineer_prompt(
            None,  # numbered_function_body no longer used
            current_function_info,
            program_slice,
            make_command,
            "",
            compiler_feedback=compiler_feedback,
            optimization_remarks=opt_remarks,
            perf_data=perf_info,
            previous_search_replace=previous_search_replace,
            lint_errors=lint_errors,
            use_clang_not_intel=use_clang_not_intel
        )

        # Use attempt number in call_type to avoid overwriting logs
        call_type = f"engineer_{attempt}" if attempt > 0 else "engineer"

        # Log prompt before API call (in case of failure)
        logger.log_llm_prompt(
            iteration=current_iteration,
            file_path=file_path,
            call_type=call_type,
            prompt=prompt,
            function_name=current_function_info["name"]
        )

        response: str = llm.invoke(prompt).content

        # Log complete call after success
        logger.log_llm_call(
            iteration=current_iteration,
            file_path=file_path,
            call_type=call_type,
            prompt=prompt,
            response=response,
            function_name=current_function_info["name"]
        )

        # Parse engineer agent's outputs into search-replace actions
        actions = parse_search_replace_output(response, logger)

        if actions is None:
            logger.print("⚠️  Failed to parse engineer output, retrying...")
            continue
        elif len(actions) == 0:
            logger.print("ℹ️  Engineer suggested no modifications")
            new_func_info = current_function_info
            # Write to file to keep tracking in sync with file contents
            write_function_to_file(
                file_path,
                new_func_info,
                replace_start=last_written_info["start_line"],
                replace_end=last_written_info["end_line"],
                logger=logger
            )
            break
        else:
            # Apply search-replace actions to create modified function
            new_func_info = apply_search_replace_actions(current_function_info, actions, logger)

        # Write the modified function to the file
        success = write_function_to_file(
            file_path,
            new_func_info,
            replace_start=last_written_info["start_line"],
            replace_end=last_written_info["end_line"],
            logger=logger
        )

        if not success:
            logger.print("⚠️  Failed to write function to file, falling back to previous")
            new_func_info = last_written_info  # Keep tracking in sync with file
            break

        # Check syntax
        syntax_ok, syntax_errors = check_syntax(file_path, use_clang_not_intel, logger)

        if syntax_ok:
            logger.print(f"✅ Wrote modified function to {file_path}")
            # Log the entire file content after writing
            logger.log_file_content(
                iteration=current_iteration,
                file_path=file_path,
                call_type=call_type,
                function_name=current_function_info["name"]
            )
            break  # Success! Exit the retry loop
        else:
            logger.print("⚠️  Syntax errors detected in generated code")
            logger.print("    {syntax_errors[:500]}...")

            # Log the broken file for debugging before restoring
            logger.log_file_content(
                iteration=current_iteration,
                file_path=file_path,
                call_type=call_type,
                function_name=current_function_info["name"]
            )

            # Store the failed attempt for the next iteration
            if actions and len(actions) > 0:
                previous_search_replace = {
                    "search": actions[0]["search"],
                    "replace": actions[0]["replace"]
                }
            lint_errors = syntax_errors

            # Restore the previous function text to the file
            restore_success = write_function_to_file(
                file_path,
                last_written_info,
                replace_start=last_written_info["start_line"],
                replace_end=new_func_info["end_line"],  # Use new end line since we wrote it
                logger=logger
            )
            if restore_success:
                logger.print("🔙 Restored previous function text")
            else:
                logger.print("⚠️  Failed to restore previous function, continuing anyway")
                break  # Can't continue safely if we can't restore

            # If this was the last attempt, use the original function
            if attempt == MAX_LINT_RETRIES - 1:
                logger.print(f"⚠️  Max retries ({MAX_LINT_RETRIES}) reached, using original function")
                new_func_info = current_function_info
                # Write the original function back
                write_function_to_file(
                    file_path,
                    current_function_info,
                    replace_start=last_written_info["start_line"],
                    replace_end=last_written_info["end_line"],
                    logger=logger
                )
                break
    # Create new function draft with modified function in the NEXT iteration slot
    # (current slot already has baseline compile/run/vec results that we need to preserve)
    function_drafts[current_iteration + 1] = FunctionDraft(new_func_info)

    result_dict = {
        "function_drafts": function_drafts,
        "current_iteration": current_iteration + 1
    }

    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "engineer", "after")

    return result_dict


# Node: finalize
def finalize(state: VectorizationState):
    logger = state["logger"]
    logger.log_state(state, "finalize", "before")

    function_drafts = state["function_drafts"]

    final_draft = None
    the_thing_i_want_to_return = 0

    # Find all valid drafts (compile_success, run_success, vectorization_success all true)
    valid_drafts = []
    for i, draft in function_drafts.items():
        if draft.compile_success and draft.run_success and draft.vectorization_success:
            valid_drafts.append((i, draft))

    if valid_drafts:
        # Among valid drafts, pick the one with the lowest runtime
        # If runtime is None, treat it as infinity (less preferred)
        drafts_with_runtime = [(i, d) for i, d in valid_drafts if d.runtime_s is not None]

        if drafts_with_runtime:
            # Pick the draft with the lowest runtime
            best_i, best_draft = min(drafts_with_runtime, key=lambda x: x[1].runtime_s)
            final_draft = best_draft
            the_thing_i_want_to_return = best_i
        else:
            # No runtime data available, fall back to most recent valid draft
            best_i, best_draft = max(valid_drafts, key=lambda x: x[0])
            final_draft = best_draft
            the_thing_i_want_to_return = best_i

    # Fall back to draft 0 if no valid drafts
    if final_draft is None:
        final_draft = function_drafts[0]
        the_thing_i_want_to_return = 0

    # Write the final function draft to the file
    file_path = state["file_path"]
    final_function_info = final_draft.modified_function_text
    
    # Replace the range occupied by the LAST draft that was written to the file
    last_iteration = max(function_drafts.keys())
    last_draft_info = function_drafts[last_iteration].modified_function_text
    
    success = write_function_to_file(
        file_path,
        final_function_info,
        replace_start=last_draft_info["start_line"],
        replace_end=last_draft_info["end_line"],
        logger=logger
    )

    if success:
        logger.print(f"✅ Finalized and wrote function '{final_function_info['name']}' to {file_path}")
        if final_draft.vectorization_success:
            logger.print("🎉 Function was successfully vectorized")
    else:
        logger.print("⚠️  Failed to write final function to file")

    logger.log_state(state, "finalize", "after")
    return {
        "manager_chosen_i": the_thing_i_want_to_return
    }

# Decision point: should_continue
def should_continue(state: VectorizationState):
    max_iterations = 1
    print
    current_iteration = state["current_iteration"]
    # print(current_iteration)
    if current_iteration < max_iterations:
        return "continue"
    else:
        return "done"

    
def create_vectorization_graph():
    workflow = StateGraph(VectorizationState)

    workflow.add_node("compile_code", compile_code)
    workflow.add_node("run_code", run_code)
    workflow.add_node("engineer", engineer)
    workflow.add_node("finalize", finalize)

    workflow.set_entry_point("compile_code")
    workflow.add_edge("compile_code", "run_code")
    workflow.add_conditional_edges(
        "run_code",
        should_continue,
        {
            "continue": "engineer",
            "done": "finalize"
        }
    )
    workflow.add_edge("engineer", "compile_code")
    # workflow.add_edge("run_code", "engineer")        
    # workflow.add_edge("engineer", "finalize")

    workflow.add_edge("finalize", END)
    
    return workflow.compile()
    
    
def vectorize_benchmark(benchmark_dir: str,
                        make_command: str,
                        max_iterations: int,
                        run_command: str,
                        use_compiler_feedback: bool = True,
                        use_clang_not_intel: bool = True,
                        results_dir: str = "results"
                        ):

    abs_benchmark_dir = os.path.abspath(benchmark_dir)
    benchmark_name = os.path.basename(abs_benchmark_dir)
    opt_dir = os.path.join(results_dir, f"{benchmark_name}_opt")
    current_dir = os.getcwd()

    print(f"{'='*60}\n")
    print(f"Vectorizing {benchmark_dir} ")
    print(f"Make command: {make_command}")
    print(f"Max iterations: {max_iterations}")
    print(f"Absolute Benchmark: {abs_benchmark_dir}")
    print(f"Benchmark name: {benchmark_name}")
    print(f"Results Dir: {results_dir}")
    print(f"Opt Dir: {opt_dir}")
    print(f"Current Dir: {current_dir}")
    print(f"{'='*60}\n")

    print(f"Copying {benchmark_dir}")
    if os.path.exists(opt_dir):
        shutil.rmtree(opt_dir)
    shutil.copytree(abs_benchmark_dir, opt_dir)
    print(f"{'='*60}\n")

    print("Creating vectorization workflow graph")
    vectorization_graph = create_vectorization_graph()

    # Initialize logger once for the entire benchmark
    log_dir = os.path.join(results_dir, f"{benchmark_name}_logs")
    logger = LLMLogger(log_dir)

    target_files = find_target_files(opt_dir)
    for current_file in target_files:
        # Initial read to find out how many functions we have
        loader = TextLoader(current_file, encoding='utf-8')
        document = loader.load()
        initial_code: str = document[0].page_content
        initial_functions: List[FunctionInfo] = extract_functions(initial_code)
        num_functions = len(initial_functions)

        print(f"Starting to vectorize {current_file}")
        print("function,base_compile,base_run,base_vec,base_runtime,opt_compile,opt_run,opt_vec,opt_runtime")

        for func_idx in range(num_functions):
            # Re-read the file every time to get updated line numbers if it was modified
            loader = TextLoader(current_file, encoding='utf-8')
            document = loader.load()
            code: str = document[0].page_content
            
            # Re-extract context and functions to handle line number shifts
            program_slice: str = extract_file_context(code)
            functions: List[FunctionInfo] = extract_functions(code)
            
            if func_idx >= len(functions):
                logger.print(f"⚠️  Warning: Expected {num_functions} functions but found {len(functions)} in {current_file} at index {func_idx}")
                continue

            function = functions[func_idx]
            
            # Construct an initial state
            # initial_function_draft: FunctionDraft = FunctionDraft(function)
            initial_state = VectorizationState(
                bench_path=opt_dir,
                file_path=current_file,
                make_command=make_command,
                run_command=run_command,
                use_compiler_feedback=use_compiler_feedback,
                use_clang_not_intel=use_clang_not_intel,

                program_slice=program_slice,
                compiler_feedback="",
                optimization_remarks="",

                current_iteration=0,
                max_iterations=max_iterations,
                manager_chosen_i=0,
                function_drafts={
                    0: FunctionDraft(function),
                    1: FunctionDraft(function),
                },
                logger=logger,
            )

            # Pass it to LangGraph workflow: Compile -> Run -> Reviewer -> Manager -> Engineer
            logger.print(f"🚀 Starting vectorization workflow for function: {function['name']} in {os.path.basename(current_file)}")
            final_state = vectorization_graph.invoke(initial_state, config={"recursion_limit": 1000})

            # Print the Loop Table to stdout
            final_function_drafts = final_state["function_drafts"]
            finalized_i = final_state["manager_chosen_i"]
            base_function_draft = final_function_drafts[0]
            func_name = base_function_draft.modified_function_text["name"]
            base_compile = base_function_draft.compile_success
            base_run = base_function_draft.run_success
            base_vec = base_function_draft.vectorization_success
            base_runtime = base_function_draft.runtime_s if base_function_draft.runtime_s is not None else "N/A"
            final_function_draft = final_function_drafts[finalized_i]
            opt_compile = final_function_draft.compile_success
            opt_run = final_function_draft.run_success
            opt_vec = final_function_draft.vectorization_success
            opt_runtime = final_function_draft.runtime_s if final_function_draft.runtime_s is not None else "N/A"

            print(f"{func_name},{base_compile},{base_run},{base_vec},{base_runtime},{opt_compile},{opt_run},{opt_vec},{opt_runtime}")

    return {"success": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add vectorization pragmas to C/C++ code using iterative AI analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark directory mode (recommended):
  python vectorizer.py my_benchmark --make-command "make" --iterations 3

  # With custom model and results directory:
  python vectorizer.py my_benchmark --make-command "make" --iterations 3 \\
    --model-name "meta-llama/Llama-3-8B" --model-url "http://localhost:8000/v1" \\
    --results-dir results
        """
    )

    parser.add_argument(
        "path",
        type=str,
        help="Path to C++ file (legacy mode) or benchmark directory (recommended)"
    )

    parser.add_argument(
        "--make-command", "-m",
        type=str,
        default=None,
        help="Build command for benchmark (e.g., 'make'). Required for directory mode."
    )

    parser.add_argument(
        "--run-command", "-r",
        type=str,
        default="",
        help="Optional command to validate function behavior. "
             "The script receives a JSON file path as its first argument containing the full VectorizationState. "
             "Exit code 0 indicates success, non-zero indicates failure."
    )

    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=3,
        help="Number of iterative refinement passes (default: 3)"
    )

    parser.add_argument(
        "--compiler-feedback",
        type=str,
        choices=["on", "off"],
        default="on",
        help="Whether to provide compiler feedback and optimization remarks in LLM prompts. "
             "When 'off', feedback is still collected for logging but not provided to the LLM. "
             "(default: on)"
    )

    parser.add_argument(
        "--compiler",
        type=str,
        choices=["clang", "intel"],
        default="clang",
        help="Compiler toolchain to use for optimization remarks formatting. "
             "(default: clang)"
    )

    parser.add_argument(
        "--temperature", "-t",
        type=float,
        default=1.0,
        help="Temperature for the LLM (default: 1.0)"
    )

    parser.add_argument(
        "--model-name",
        type=str,
        default="Qwen/Qwen2.5-Coder-7B-Instruct",
        help="Model name for the LLM (default: Qwen/Qwen2.5-Coder-7B-Instruct)"
    )

    parser.add_argument(
        "--model-url",
        type=str,
        default="http://localhost:8001/v1",
        help="Base URL for the LLM API (default: http://localhost:8001/v1)"
    )

    parser.add_argument(
        "--results-dir",
        type=str,
        default="results",
        help="Directory for output results (default: results)"
    )

    args = parser.parse_args()

    # Initialize llm with the configured temperature
    global llm
    llm = ChatOpenAI(
        model=args.model_name,
        api_key="",
        base_url=args.model_url,
        temperature=args.temperature
    )

    # Determine mode based on path type
    if os.path.isdir(args.path):
        # Directory mode (benchmark)
        if not args.make_command:
            print("✗ Error: --make-command is required for benchmark directory mode")
            print("Example: python vectorizer.py my_benchmark --make-command 'make'")
            exit(1)

        results_dir = os.path.abspath(args.results_dir)
        os.makedirs(results_dir, exist_ok=True)

        result = vectorize_benchmark(
            args.path,
            args.make_command,
            max_iterations=args.iterations,
            run_command=args.run_command,
            use_compiler_feedback=(args.compiler_feedback == "on"),
            use_clang_not_intel=(args.compiler == "clang"),
            results_dir=results_dir
        )
    else:
        print(f"✗ Error: Directory not found: {args.path}")
        exit(1)

    # Exit with appropriate code
    if result and result.get('success'):
        exit(0)
    else:
        exit(1)
