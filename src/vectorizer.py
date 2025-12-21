# Vectorizer
from langgraph.graph import StateGraph, END
from langchain_community.document_loaders import TextLoader
import os
import subprocess
import shutil
import argparse
from more_helpers import extract_functions, find_files_with_ext, find_target_files, extract_file_context, match_remark_files, filter_remarks_by_function, extract_compilation_errors
from typing import List
from my_types import llm, FunctionInfo, FunctionDraft, VectorizationState, PragmaAction, CodeReplaceAction
from logger import LLMLogger


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

    current_iteration = state["current_iteration"]
    function_drafts = state["function_drafts"]
    cur_function_draft = function_drafts[current_iteration]
    cur_function_info = cur_function_draft.modified_function_text
    cur_function_name = cur_function_info["name"]

    os.chdir(bench_path)

    result = subprocess.run(
        make_command,
        shell=True,
        capture_output=True,
        text=True,
    )

    # 1. Extract compilation feedback.
    # TODO(akash): obviously just replace this with a compiler option instead of filtering it manually. Just make the compiler only output warnings and errors instead of an insane quantity of notes. 
    compilation_feedback = extract_compilation_errors(result.stderr)
    cur_function_draft.compile_success = result.returncode == 0

    # 2. Extract optimization remarks
    all_remark_files = find_files_with_ext(bench_path, [".yaml"])
    relevant_remark_files: List[str] = match_remark_files(current_file, all_remark_files)
    relevant_remarks: List[str] = []
    for remark_file in relevant_remark_files:
        relevant_remarks.append(filter_remarks_by_function(remark_file,
                                                           cur_function_name))
    optimization_remarks = "\n".join(relevant_remarks)
    vectorization_success = "!Passed" in optimization_remarks
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


# Node: run_code
def run_code(state: VectorizationState):
    '''
    Runs code
    This node is responsible for the following fields:

    In function_drafts[current_iteration],
    1. run_success

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

    # Early exit: No run command provided, so the run is presumed successful
    if not run_command:
        print("No run command provided")
        cur_function_draft.run_success = True
        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }

    bench_path = state['bench_path']
    cur_working_dir = os.getcwd()

    os.chdir(bench_path)

    try: 
       result = subprocess.run(
           run_command,
           shell=True,
           capture_output=False,
           text=True,
           timeout=30
       )
    # Early exit: Timeout, so run failed
    except subprocess.TimeoutExpired:
        print(f"Running the benchmark took too much time")
        cur_function_draft.run_success = False
        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }

    # Main case: either the run throws an error, or it succeeds
    if result.returncode != 0:
        print(f"Running the benchmark threw an error: {result.returncode}")

    os.chdir(cur_working_dir)
    cur_function_draft.run_success = result.returncode == 0
    function_drafts[current_iteration] = cur_function_draft
    logger.log_state(state, "run_code", "after")
    return {
        "function_drafts": function_drafts
    }


# Node: reviewer
def reviewer(state: VectorizationState):
    '''
    Reviews code.
    This node is responsible for the following fields in VectorizationState

    In function_drafts[current_iteration]
    1. dead_end
    2. reviewer_feedback
    '''
    logger = state["logger"]
    logger.log_state(state, "reviewer", "before")
    
    function_drafts = state["function_drafts"]
    current_iteration = state["current_iteration"]
    cur_function_draft = function_drafts[current_iteration]
    cur_function_info = cur_function_draft.modified_function_text
    cur_function_name = cur_function_info["name"]
    reviewer_feedback = function_drafts[current_iteration].reviewer_feedback
    make_command = state["make_command"]
    program_slice = state["program_slice"]
    compiler_feedback = state["compiler_feedback"]
    optimization_remarks = state["optimization_remarks"]

    # Early exit: if compile or run failed, mark as dead_end and skip LLM call
    if not cur_function_draft.compile_success or not cur_function_draft.run_success:
        cur_function_draft.dead_end = True
        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "reviewer", "after")
        return {
            "function_drafts": function_drafts
        }

    # Read vectorization_success that was set by compile_code
    vectorization_success = cur_function_draft.vectorization_success

    if reviewer_feedback == "":
        prompt = f"""You are reviewing THIS FUNCTION for opportunities to autovectorize it.

{cur_function_info["full_text"]}

        The function is compiled with Clang, using the following command: {make_command}

        You have access to some information to help.

First, the PROGRAM

{program_slice}

Second, COMPILER FEEDBACK:

{compiler_feedback}

Third, OPTIMIZATION REMARKS.

{optimization_remarks}

You MUST return a JSON object in this format:

```
{{
  "dead_end": bool
  "reviewer_feedback": str
}}
```
        
RULES:
- If the function was already autovectorized, you must set the dead_end field to false, and the vectorization_success field to true.
- You must set 'dead_end' to false is the function is a useful starting point for autovectorization.
- Fill out the reviewer_feedback field to include future directions to modify the function in order to autovectorize it.

EXAMPLE OUTPUTS:
{{
  "dead_end": false,
  "reviewer_feedback": "This function is already fully autovectorized. No further work is needed." 
}}

{{
  "dead_end": true,
  "reviewer_feedback": "" 
}}

{{
  "dead_end": true,
  "reviewer_feedback": "Optimization remarks for this function suggest that a non-reduction value in the loop body is used outside the loop. Compiler feedback indicates that this function could be autovectorized if we make a copy of the variable 'a'. Suggestion: Make a copy of the variable 'a'."
}}

YOUR OUTPUT:

        """

        output: str = llm.invoke(prompt).content
        

        logger.log_llm_call(
            iteration=current_iteration,
            file_path=state["file_path"],
            call_type="reviewer",
            prompt=prompt,
            response=output, # Replace with actual LLM output when available
            function_name=cur_function_name
        )

        # Parse reviewer agent's output
        parsed = parse_reviewer_output(output)

        if parsed:
            llm_dead_end = parsed.get("dead_end", True)
            cur_function_draft.reviewer_feedback = parsed.get("reviewer_feedback", "")
        else:
            print("⚠️  Failed to parse reviewer output, using defaults")
            llm_dead_end = True
            cur_function_draft.reviewer_feedback = ""

        # Set dead_end based on vectorization success or LLM assessment
        if vectorization_success:
            # Code is already autovectorized - not a dead end
            cur_function_draft.dead_end = False
        else:
            # Use LLM's assessment
            cur_function_draft.dead_end = llm_dead_end
        
        function_drafts[current_iteration] = cur_function_draft
        
        result_dict = {
            "function_drafts": function_drafts
        }
        
        after_state = state.copy()
        after_state.update(result_dict)
        logger.log_state(after_state, "reviewer", "after")
        
        return result_dict

    logger.log_state(state, "reviewer", "after")
    return {}


# Generic JSON parser for LLM outputs
def parse_llm_json_output(
    output: str,
    required_fields: dict[str, type],
    agent_name: str = "LLM"
) -> dict | None:
    """
    Generic JSON parser for LLM outputs.
    
    Args:
        output: Raw LLM output string
        required_fields: Dict mapping field names to their expected types
                        e.g., {"dead_end": bool, "reviewer_feedback": str}
        agent_name: Name of the agent for error messages
    
    Returns:
        Parsed and validated dict, or None if parsing fails
    """
    import json
    import re
    
    # Try to extract JSON from the output
    # First, try to find JSON in code blocks
    json_match = re.search(r'```(?:json)?\s*({[^`]+})\s*```', output, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object with any of the required fields
        # Build a pattern that looks for any required field
        field_names = '|'.join(re.escape(f'"{field}"') for field in required_fields.keys())
        pattern = rf'{{[^{{}}]*(?:{field_names})[^{{}}]*}}'
        json_match = re.search(pattern, output, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            # Last resort: assume the entire output is JSON
            json_str = output.strip()
    
    try:
        parsed = json.loads(json_str)
        
        # Validate required fields
        missing_fields = [field for field in required_fields if field not in parsed]
        if missing_fields:
            print(f"⚠️  Missing required fields in {agent_name} output: {missing_fields}")
            return None
        
        # Type-cast fields according to required_fields
        result = {}
        for field, expected_type in required_fields.items():
            try:
                result[field] = expected_type(parsed[field])
            except (ValueError, TypeError) as e:
                print(f"⚠️  Failed to convert {field} to {expected_type.__name__} in {agent_name} output: {e}")
                return None
        
        return result
            
    except json.JSONDecodeError as e:
        print(f"⚠️  Failed to parse {agent_name} JSON: {e}")
        print(f"    Output was: {output[:200]}...")
        return None


# Generic JSON array parser for LLM outputs
def parse_llm_json_array(
    output: str,
    agent_name: str = "LLM"
) -> list | None:
    """
    Generic JSON array parser for LLM outputs.
    
    Args:
        output: Raw LLM output string
        agent_name: Name of the agent for error messages
    
    Returns:
        Parsed list, or None if parsing fails
    """
    import json
    import re
    
    # Try to extract JSON array from the output
    # First, try to find JSON in code blocks
    json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', output, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON array
        json_match = re.search(r'\[.*\]', output, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            # Last resort: assume the entire output is JSON
            json_str = output.strip()
    
    try:
        parsed = json.loads(json_str)
        
        # Validate it's a list
        if not isinstance(parsed, list):
            print(f"⚠️  {agent_name} output is not a JSON array: {type(parsed)}")
            return None
        
        return parsed
            
    except json.JSONDecodeError as e:
        print(f"⚠️  Failed to parse {agent_name} JSON array: {e}")
        print(f"    Output was: {output[:200]}...")
        return None


# Node: reviewer: parse output
def parse_reviewer_output(output: str) -> dict | None:
    """
    Parse the reviewer LLM output to extract JSON.
    
    Expected format:
    {
      "dead_end": bool,
      "reviewer_feedback": str
    }
    
    Returns:
        dict with 'dead_end' and 'reviewer_feedback' keys, or None if parsing fails
    """
    return parse_llm_json_output(
        output,
        required_fields={"dead_end": bool, "reviewer_feedback": str},
        agent_name="reviewer"
    )


# Node: increment
def increment(state: VectorizationState):
    '''
    Increments current_iteration.
    This node is responsible for the following field in VectorizationState.
    1. current_iteration.
    
    '''
    logger = state["logger"]
    logger.log_state(state, "increment", "before")
    
    current_iteration = state["current_iteration"]
    result_dict = {
        "current_iteration": current_iteration + 1
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "increment", "after")
    
    return result_dict


# Node: manager
def manager(state: VectorizationState):
    '''
    The manager chooses the best starting point out of all previous iterations.
    This node is responsible for the following fields in VectorizationState.
    1. manager_chosen_i
    '''
    logger = state["logger"]
    logger.log_state(state, "manager", "before")
    
    function_drafts = state["function_drafts"]
    make_command = state["make_command"]
    
    # Pretty print function_drafts
    drafts_str = ""
    for i, draft in function_drafts.items():
        drafts_str += f"""
## Draft {i}
- **Compile Success**: {draft.compile_success}
- **Vectorization Success**: {draft.vectorization_success}
- **Dead End**: {draft.dead_end}
- **Reviewer Feedback**: {draft.reviewer_feedback if draft.reviewer_feedback else "None"}

**Function Code:**
```c
{draft.modified_function_text.get("full_text", "")}
```

---
"""
    
    prompt = f"""Given a few drafts of the same function, pick the function that is most likely to be autovectorized by the compiler.

The command that this function will be compiled with is:

{make_command}

The FUNCTION DRAFTS are below:

{drafts_str}

OUTPUT RULES:
- Your output MUST be a JSON object in the following format.
```
{{
  "i": int,
  "explanation": str,
}}
```
- Your output i must be in the valid range: 0 <= i < {state["current_iteration"]}. This means i can be between 0 and {state["current_iteration"] - 1} (inclusive). DO NOT output any value outside this range. 


EXAMPLE OUTPUT:
```
{{
  "i": {state["current_iteration"] - 1},
  "explanation": "It was the only function draft that was successfully autovectorized. This is a good starting point for further autovectorization attempts."
}}
```

YOUR OUTPUT:
    
    """

    result: str = llm.invoke(prompt).content
    
    current_iteration = state["current_iteration"]
    logger.log_llm_call(
        iteration=current_iteration,
        file_path=state["file_path"],
        call_type="manager",
        prompt=prompt,
        response=result,
        function_name=function_drafts[0].modified_function_text["name"]
    )

    # Parse manager agent's output and update vectorization state
    parsed = parse_manager_output(result)
    
    if parsed:
        chosen_index = parsed.get("i", 0)
        # print(f"✅ Manager chose draft {chosen_index}: {parsed.get('explanation', 'No explanation')}")
    else:
        print("⚠️  Failed to parse manager output, defaulting to draft 0")
        chosen_index = 0
    
    # Bounds checking: ensure chosen_index is valid
    current_iteration = state["current_iteration"]
    if chosen_index < 0 or chosen_index >= current_iteration:
        print(f"⚠️  Invalid draft index {chosen_index} (must be 0 <= i < {current_iteration}), defaulting to draft 0")
        chosen_index = 0
    
    result_dict = {
        "manager_chosen_i": chosen_index
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "manager", "after")
    
    return result_dict


# Node: manager: parse output
def parse_manager_output(output: str) -> dict | None:
    """
    Parse the manager LLM output to extract the chosen draft index.
    
    Expected format:
    {
      "i": int,
      "explanation": str
    }
    
    Returns:
        dict with 'i' and 'explanation' keys, or None if parsing fails
    """
    return parse_llm_json_output(
        output,
        required_fields={"i": int, "explanation": str},
        agent_name="manager"
    )


# Helper: Validate and cast pragma action
def validate_and_cast_pragma_action(action: dict, index: int) -> PragmaAction | None:
    """
    Validate and type-cast a pragma action from a JSON object.
    
    Args:
        action: Raw JSON object from LLM output
        index: Index of the action in the array (for error messages)
    
    Returns:
        PragmaAction object, or None if validation fails
    """
    # Validate required fields
    required = ["action_type", "line_number", "pragma_type", "reasoning"]
    missing = [f for f in required if f not in action]
    if missing:
        print(f"⚠️  PragmaAction {index} missing fields: {missing}")
        return None
    
    # Validate pragma_type
    valid_pragma_types = ["vectorize", "interleave", "vectorize_width"]
    if action["pragma_type"] not in valid_pragma_types:
        print(f"⚠️  Invalid pragma_type in action {index}: {action['pragma_type']}")
        return None
    
    # Type-cast fields
    try:
        pragma_action: PragmaAction = {
            "action_type": "pragma",
            "line_number": int(action["line_number"]),
            "pragma_type": action["pragma_type"],
            "width": int(action["width"]) if action.get("width") is not None else None,
            "reasoning": str(action["reasoning"])
        }
        return pragma_action
    except (ValueError, TypeError) as e:
        print(f"⚠️  Failed to convert PragmaAction {index} fields: {e}")
        return None


# Helper: Validate and cast code replace action
def validate_and_cast_code_replace_action(action: dict, index: int) -> CodeReplaceAction | None:
    """
    Validate and type-cast a code replace action from a JSON object.
    
    Args:
        action: Raw JSON object from LLM output
        index: Index of the action in the array (for error messages)
    
    Returns:
        CodeReplaceAction object, or None if validation fails
    """
    # Validate required fields
    required = ["action_type", "start_line", "end_line", "new_code", "reasoning"]
    missing = [f for f in required if f not in action]
    if missing:
        print(f"⚠️  CodeReplaceAction {index} missing fields: {missing}")
        return None
    
    # Type-cast fields
    try:
        code_action: CodeReplaceAction = {
            "action_type": "code_replace",
            "start_line": int(action["start_line"]),
            "end_line": int(action["end_line"]),
            "new_code": str(action["new_code"]),
            "reasoning": str(action["reasoning"])
        }
        return code_action
    except (ValueError, TypeError) as e:
        print(f"⚠️  Failed to convert CodeReplaceAction {index} fields: {e}")
        return None


# Node: engineer: parse output
def parse_engineer_output(output: str) -> list[PragmaAction | CodeReplaceAction] | None:
    """
    Parse the engineer LLM output to extract an array of actions.
    
    Expected format:
    [
      {"action_type": "pragma", "line_number": int, "pragma_type": str, "width": int|null, "reasoning": str},
      {"action_type": "code_replace", "start_line": int, "end_line": int, "new_code": str, "reasoning": str}
    ]
    
    Returns:
        List of PragmaAction and/or CodeReplaceAction objects, or None if parsing fails
    """
    # Use generic array parser to extract and parse the JSON array
    parsed = parse_llm_json_array(output, agent_name="engineer")
    
    if parsed is None:
        return None
    
    # Empty array is valid (no modifications needed)
    if len(parsed) == 0:
        return []
    
    # Validate and type-cast each action
    actions = []
    for i, action in enumerate(parsed):
        if not isinstance(action, dict):
            print(f"⚠️  Action {i} is not a JSON object: {type(action)}")
            return None
        
        action_type = action.get("action_type")
        
        if action_type == "pragma":
            validated_action = validate_and_cast_pragma_action(action, i)
        elif action_type == "code_replace":
            validated_action = validate_and_cast_code_replace_action(action, i)
        else:
            print(f"⚠️  Unknown action_type in action {i}: {action_type}")
            return None
        
        if validated_action is None:
            return None
        
        actions.append(validated_action)
    
    return actions


# Helper: Write function to file
def write_function_to_file(
    file_path: str,
    function_info: FunctionInfo,
    replace_start: int | None = None,
    replace_end: int | None = None
) -> bool:
    """
    Write a modified function back to its source file.
    
    Args:
        file_path: Absolute path to the source file
        function_info: FunctionInfo with modified full_text to write
        replace_start: Start line to replace (0-indexed). If None, use function_info["start_line"]
        replace_end: End line to replace (0-indexed). If None, use function_info["end_line"]
    
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
            print(f"⚠️  Invalid line range {start}-{end} for file with {len(lines)} lines")
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
        print(f"⚠️  Failed to write function to {file_path}: {e}")
        return False


# Node: engineer: apply actions to function
def apply_actions_to_function(
    function_info: FunctionInfo,
    actions: list[PragmaAction | CodeReplaceAction]
) -> FunctionInfo:
    """
    Apply a list of actions to a function to create a modified version.
    
    Args:
        function_info: Original function information
        actions: List of PragmaAction and/or CodeReplaceAction objects
    
    Returns:
        Modified FunctionInfo with updated full_text and body
    """
    # Split function text into lines
    lines = function_info["full_text"].split("\n")
    
    # Sort actions by line number (descending) to avoid line number shifts
    # For code_replace, use start_line; for pragma, use line_number
    sorted_actions = sorted(
        actions,
        key=lambda a: a.get("start_line", a.get("line_number", 0)),
        reverse=True
    )
    
    for action in sorted_actions:
        if action["action_type"] == "pragma":
            # Insert pragma before the specified line
            line_num = action["line_number"]
            pragma_type = action["pragma_type"]
            
            # Build pragma string
            if pragma_type == "vectorize":
                pragma_str = "#pragma clang loop vectorize(enable)"
            elif pragma_type == "interleave":
                pragma_str = "#pragma clang loop interleave(enable)"
            elif pragma_type == "vectorize_width":
                width = action["width"]
                pragma_str = f"#pragma clang loop vectorize_width({width})"
            else:
                continue  # Skip invalid pragma types
            
            # Get indentation of the target line
            if 0 <= line_num < len(lines):
                target_line = lines[line_num]
                indent = len(target_line) - len(target_line.lstrip())
                pragma_str = " " * indent + pragma_str
                
                # Insert pragma before the line
                lines.insert(line_num, pragma_str)
        
        elif action["action_type"] == "code_replace":
            # Replace lines from start_line to end_line (inclusive)
            start = action["start_line"]
            end = action["end_line"]
            new_code = action["new_code"]
            
            # Validate line numbers
            if start < 0 or end >= len(lines) or start > end:
                print(f"⚠️  Invalid line range for code_replace: {start}-{end} (function has {len(lines)} lines)")
                continue
            
            # Get indentation from the first line being replaced
            if start < len(lines):
                original_line = lines[start]
                indent = len(original_line) - len(original_line.lstrip())
                
                # Apply indentation to new code (if it's multi-line)
                new_lines = new_code.split("\n")
                indented_new_lines = [" " * indent + line if line.strip() else line for line in new_lines]
                
                # Replace the lines
                lines[start:end+1] = indented_new_lines
    
    # Reconstruct the function text
    modified_full_text = "\n".join(lines)
    
    # Calculate new end_line based on number of lines in modified text
    # Note: start_line is 0-indexed relative to the file
    new_num_lines = len(modified_full_text.splitlines())
    new_end_line = function_info["start_line"] + new_num_lines - 1
    
    # Create modified function info
    modified_info: FunctionInfo = {
        "name": function_info["name"],
        "signature": function_info["signature"],
        "body": modified_full_text,  # Update body as well
        "full_text": modified_full_text,
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

    manager_chosen_i = state["manager_chosen_i"]
    function_drafts = state["function_drafts"]
    current_function_draft = function_drafts[manager_chosen_i]
    reviewer_feedback = current_function_draft.reviewer_feedback
    current_function_info = current_function_draft.modified_function_text
    current_function_body = current_function_info["full_text"]

    # Add line numbers to function body for clarity
    numbered_function_body = "\n".join(
        f"{i}: {line}" for i, line in enumerate(current_function_body.split("\n"))
    )

    prompt = f"""Your task is to take a function and modify it to make it easier to autovectorize.

The FUNCTION is (with line numbers):

{numbered_function_body}

(This function starts at line {current_function_info["start_line"]} in the original file)

The surrounding context is:

{program_slice}

It is compiled with Clang, using the following command:

{make_command}

Please use SUGGESTIONS FROM A REVIEWER when modifying the function.

{reviewer_feedback}

You have two options:

1. PRAGMA ACTIONS: Suggest pragmas for FOR LOOPS where vectorization still failed
- You may suggest: "vectorize", "interleave", or "vectorize_width"
- Be conservative - only suggest if you're confident it will help

2. CODE REPLACE: Make targeted code changes:
- Fix specific issues identified in optimization remarks
- Add temporaries, hoist computations, break dependencies
- Avoid making changes that alter the meaning of the function

OPTION 1 - PRAGMA ACTIONS (for simple vectorization hints):
For each loop that needs a pragma, create a JSON object:
{{
  "action_type": "pragma",
  "line_number": <line number from the numbered function above>,
  "pragma_type": "vectorize" OR "interleave" OR "vectorize_width",
  "width": <number (only if pragma_type is vectorize_width), otherwise null>,
  "reasoning": "<brief explanation>"
}}

OPTION 2 - CODE REPLACE (for targeted code changes):
For each code change, create a JSON object:
{{
  "action_type": "code_replace",
  "start_line": <start line number from the numbered function above>,
  "end_line": <end line number from the numbered function above (inclusive)>,
  "new_code": "<replacement code (can be multi-line)>",
  "reasoning": "<brief explanation>"
}}

Examples:
- Add variable: {{"action_type": "code_replace", "start_line": 0, "end_line": 0, "new_code": "int temp = 0;", "reasoning": "Add local temporary"}}
- Replace line: {{"action_type": "code_replace", "start_line": 5, "end_line": 5, "new_code": "result[i] = a[i] * factor;", "reasoning": "Use hoisted variable"}}
- Multi-line: {{"action_type": "code_replace", "start_line": 3, "end_line": 5, "new_code": "for (int i = 0; i < n; i++) {{\\n    output[i] = input[i];\\n}}", "reasoning": "Simplify loop"}}

CRITICAL OUTPUT RULES:
- Output a JSON ARRAY: [{{...}}] or [{{...}}, {{...}}] for multiple actions
- You can mix pragma and code_replace actions in the same array
- If NO modifications needed, output an empty array: []
- DO NOT include any explanatory text, markdown, or code fences
- Output ONLY the JSON array, nothing else
    
    """
    response:str = llm.invoke(prompt).content


    current_iteration = state["current_iteration"]
    logger.log_llm_call(
        iteration=current_iteration,
        file_path=state["file_path"],
        call_type="engineer",
        prompt=prompt,
        response=response,
        function_name=current_function_info["name"]
    )

    # Parse engineer agent's outputs into an array of CodeReplaceAction and PragmaAction objects
    actions = parse_engineer_output(response)
    
    if actions is None:
        print("⚠️  Failed to parse engineer output, using original function")
        new_func_info = current_function_info
    elif len(actions) == 0:
        print("ℹ️  Engineer suggested no modifications")
        new_func_info = current_function_info
    else:
        print(f"✅ Engineer suggested {len(actions)} action(s)")
        # Apply actions to create modified function
        new_func_info = apply_actions_to_function(current_function_info, actions)

    # Write the modified function back to the file
    # Always write to ensure file stays in sync with function_drafts
    file_path = state["file_path"]
    current_iteration = state["current_iteration"]

    # Determine what's currently in the file by finding the last written draft
    # The last written draft is the one from the previous iteration (current_iteration - 1)
    last_written_index = current_iteration - 1 if current_iteration > 0 else 0
    last_written_info = function_drafts[last_written_index].modified_function_text

    # Use the last written draft's coordinates for replacement
    success = write_function_to_file(
        file_path,
        new_func_info,
        replace_start=last_written_info["start_line"],
        replace_end=last_written_info["end_line"]
    )
    if success:
        print(f"✅ Wrote modified function to {file_path}")
    else:
        print(f"⚠️  Failed to write function to file, continuing anyway")

    # Create new function draft with modified function
    current_iteration = state["current_iteration"]
    function_drafts[current_iteration] = FunctionDraft(new_func_info)

    result_dict = {
        "function_drafts": function_drafts
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
    # Find the best draft
    # Priority 1: First draft that is both compiled and vectorized
    for i in range(len(function_drafts) - 1, -1, -1):
        if function_drafts[i].compile_success and function_drafts[i].vectorization_success:
            final_draft = function_drafts[i]
            the_thing_i_want_to_return = i
            break

    # Priority 2: Fall back to draft 0
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
        replace_end=last_draft_info["end_line"]
    )
    
    if success:
        print(f"✅ Finalized and wrote function '{final_function_info['name']}' to {file_path}")
        if final_draft.vectorization_success:
            print(f"🎉 Function was successfully vectorized!")
    else:
        print(f"⚠️  Failed to write final function to file")

    logger.log_state(state, "finalize", "after")
    return {
        "manager_chosen_i": the_thing_i_want_to_return
    }


# Decision point: should_continue
def should_continue(state: VectorizationState):
    max_iterations = state["max_iterations"]
    current_iteration = state["current_iteration"]
    if current_iteration < max_iterations:
        return "continue"
    else:
        return "done"


def create_vectorization_graph():
    workflow = StateGraph(VectorizationState)

    workflow.add_node("compile_code", compile_code)
    workflow.add_node("run_code", run_code)
    workflow.add_node("reviewer", reviewer)
    workflow.add_node("increment", increment)
    workflow.add_node("manager", manager)
    workflow.add_node("engineer", engineer)
    workflow.add_node("finalize", finalize)

    workflow.set_entry_point("compile_code")
    workflow.add_edge("compile_code", "run_code")
    workflow.add_edge("run_code", "reviewer")        
    workflow.add_conditional_edges(
        "reviewer",
        should_continue,
        {
            "continue": "increment",
            "done": "finalize"
        }
    )
    workflow.add_edge("increment", "manager")
    workflow.add_edge("manager", "engineer")
    workflow.add_edge("engineer", "compile_code")

    workflow.add_edge("finalize", END)
    
    return workflow.compile()
    
    
def vectorize_benchmark(benchmark_dir: str,
                        make_command: str,
                        max_iterations: int,
                        run_command: str,
                        ):

    abs_benchmark_dir = os.path.abspath(benchmark_dir)
    benchmark_name = os.path.basename(abs_benchmark_dir)
    parent_dir = os.path.dirname(abs_benchmark_dir)
    opt_dir = os.path.join(parent_dir, f"{benchmark_name}_opt")
    current_dir = os.getcwd()

    print(f"{'='*60}\n")
    print(f"Vectorizing {benchmark_dir} ")
    print(f"Make command: {make_command}")
    print(f"Max iterations: {max_iterations}")
    print(f"Absolute Benchmark: {abs_benchmark_dir}")
    print(f"Benchmark name: {benchmark_name}")
    print(f"Parent Dir: {parent_dir}")
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
    log_dir = os.path.join(current_dir, f"{benchmark_name}_logs")
    logger = LLMLogger(log_dir)

    target_files = find_target_files(opt_dir)
    for current_file in target_files:
        # Initial read to find out how many functions we have
        loader = TextLoader(current_file, encoding='utf-8')
        document = loader.load()
        initial_code: str = document[0].page_content
        initial_functions: List[FunctionInfo] = extract_functions(initial_code)
        num_functions = len(initial_functions)

        for func_idx in range(num_functions):
            # Re-read the file every time to get updated line numbers if it was modified
            loader = TextLoader(current_file, encoding='utf-8')
            document = loader.load()
            code: str = document[0].page_content
            
            # Re-extract context and functions to handle line number shifts
            program_slice: str = extract_file_context(code)
            functions: List[FunctionInfo] = extract_functions(code)
            
            if func_idx >= len(functions):
                print(f"⚠️  Warning: Expected {num_functions} functions but found {len(functions)} in {current_file} at index {func_idx}")
                continue

            function = functions[func_idx]
            
            # Construct an initial state
            initial_function_draft: FunctionDraft = FunctionDraft(function)
            initial_state = VectorizationState(
                bench_path=opt_dir,
                file_path=current_file,
                make_command=make_command,
                run_command=run_command,

                program_slice=program_slice,
                compiler_feedback="",
                optimization_remarks="",

                current_iteration=0,
                max_iterations=max_iterations,
                manager_chosen_i=0,
                function_drafts={
                    0: initial_function_draft
                },
                logger=logger,
            )

            # Pass it to LangGraph workflow: Compile -> Run -> Reviewer -> Manager -> Engineer
            print(f"🚀 Starting vectorization workflow for function: {function['name']} in {os.path.basename(current_file)}")
            final_state = vectorization_graph.invoke(initial_state, config={"recursion_limit": 1000})

    return {"success": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add vectorization pragmas to C/C++ code using iterative AI analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark directory mode (recommended):
  python vectorizer.py my_benchmark --make-command "make" --iterations 3

  # Legacy single-file mode:
  python vectorizer.py my_file.cpp --iterations 3
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
        help="Optional command to run benchmark (not used yet)"
    )

    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=3,
        help="Number of iterative refinement passes (default: 3)"
    )

    args = parser.parse_args()

    # Determine mode based on path type
    if os.path.isdir(args.path):
        # Directory mode (benchmark)
        if not args.make_command:
            print("✗ Error: --make-command is required for benchmark directory mode")
            print("Example: python vectorizer.py my_benchmark --make-command 'make'")
            exit(1)

        result = vectorize_benchmark(
            args.path,
            args.make_command,
            max_iterations=args.iterations,
            run_command=args.run_command,
        )
    else:
        print(f"✗ Error: Directory not found: {args.path}")
        exit(1)

    # Exit with appropriate code
    if result and result.get('success'):
        exit(0)
    else:
        exit(1)
