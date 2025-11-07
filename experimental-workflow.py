'''
TODO:
1. Enforce more strict permissions / rules for the experimental workflow
2. Change prompt so that it gives more freedom to LLM to search through
remark files

What does the directory structure look like at the beginning?:
Root
|
--- experimental-workflow.py
--- base (for copying)

So what does the directory structure look like at the end?:

Root
|
--- experimental-workflow.py
--- base (for copying)
--- Base Benchmark copy
--- AI_0 benchmark (use remarks from the base benchmark in prompt)
--- AI_1 benchmark (use remarks from AI_0 in prompt)
--- AI_2 benchmark (use remarks from AI_1 in prompt)
--- ...
'''
import shutil
import sys
import os
import subprocess
import fnmatch
import argparse
from agents import Agent, Runner, OpenAIChatCompletionsModel, AsyncOpenAI
from agents.mcp import MCPServerStdio
import asyncio


def get_rel_file(abs_file):
    rel_file = os.path.relpath(abs_file, os.getcwd())
    # print("RELATIVE FILE in the function: " + rel_file)
    parts = rel_file.split(os.sep)
    rel_file = os.sep.join(parts[1:])
    return rel_file


def run_cmd(make_command):
    subprocess.run(make_command,
                   shell=True,
                   stdout=sys.stdout,
                   stderr=subprocess.STDOUT)


def run_cmd_with_capture(make_command, output_file=None):
    """
    Run command and capture all output for diagnostics
    Returns the captured output as string
    """
    result = subprocess.run(
        make_command,
        shell=True,
        capture_output=True,
        text=True
    )

    # Combine stdout and stderr
    full_output = result.stdout + result.stderr

    # Write to file if specified
    if output_file:
        with open(output_file, 'w') as f:
            f.write(full_output)

    # Also print to console for user visibility
    print(full_output)

    return full_output


def analyze_build_diagnostics(build_output):
    """
    Extract pragma-related warnings and errors from build output
    Returns structured diagnostics
    """
    diagnostics = {
        'errors': [],
        'warnings': [],
        'pragma_issues': []
    }

    lines = build_output.split('\n')

    for line in lines:
        line_lower = line.lower()

        # Check for pragma-related issues
        if 'pragma' in line_lower:
            if 'error' in line_lower or 'unknown' in line_lower:
                diagnostics['pragma_issues'].append(line.strip())
            elif 'warning' in line_lower:
                diagnostics['pragma_issues'].append(line.strip())

        # General error detection
        elif 'error:' in line_lower:
            diagnostics['errors'].append(line.strip())

        # General warning detection
        elif 'warning:' in line_lower:
            diagnostics['warnings'].append(line.strip())

    return diagnostics


def find_files_with_ext(file_exts):
    '''
    Given a list of file extensions (strings), return
    a list of filepaths that have those extensions
    in the current working directory
    Input:
     file_exts: [string]
    Output:
     filepaths: [path]
    '''
    files_with_ext = []
    for root, dirs, files in os.walk(os.getcwd()):
        for file in files:
            _, file_extension = os.path.splitext(os.path.join(root,
                                                              file))
            if file_extension in file_exts:
                files_with_ext.append(os.path.join(root, file))
    return files_with_ext


def find_opt_yaml_files():
    return find_files_with_ext([".yaml"])


def filter_vector_remarks(remark_files):
    """
    Filter remark files to only include those with Pass field containing 'vector'
    Uses YQ to filter YAML documents where .Pass contains "vector"
    """
    filtered_files = []

    for remark_file in remark_files:
        try:
            # Use YQ to check if the file contains any documents with Pass field containing 'vector'
            result = subprocess.run(
                ['yq', 'eval', 'select(.Pass | contains("vector"))', remark_file],
                capture_output=True,
                text=True,
                check=False
            )

            # If YQ found any matching documents (non-empty output), include the file
            if result.stdout.strip():
                filtered_files.append(remark_file)
                print(f"Including remark file with vector passes: {remark_file}")
            else:
                print(f"Excluding remark file (no vector passes): {remark_file}")

        except Exception as e:
            print(f"Error filtering remark file {remark_file}: {e}")
            # If there's an error processing the file, include it to be safe
            filtered_files.append(remark_file)

    return filtered_files


def find_target_files():
    return find_files_with_ext([".h", ".c", ".cpp", ".hxx", ".hpp"])


async def main(make_command, run_command, bench_folder_name, n_iters):
    '''
    Runs experimental workflow.

    Input:
     make_command: if your directory was in the benchmark
       (like $bench_folder_name$), this is the command you would
       run to build the benchmark.
       This should have the '-fsave-optimization-record' compiler option.
     run_command: this is the command to run your benchmark. It should also
       write trial times to a file.
     bench_folder_name: the base benchmark, with all the files that we
       can copy to other directories.
     n_iters: number of passes for AI remarks.
    '''

    # Copy the base directory
    print("### Copying Benchmark to Base ###")
    shutil.copytree(bench_folder_name, f"{bench_folder_name}_base")

    # Make the project in the new folder
    print("### Building Base Benchmark ###")
    os.chdir(f"{bench_folder_name}_base")
    run_cmd(make_command)

    # Run the project in the new folder
    print("### Running Base Benchmark ###")
    run_cmd(run_command)

    # Assumption: run_command automatically generates .opt.yaml files
    # with the -fsave-optimization-record compiler option
    print("### Finding *.opt.yaml files ###")
    yaml_files_from_prev_iter = find_opt_yaml_files()

    build_diagnostics = {}  # Store diagnostics per iteration

    os.chdir("..")

    # Setup Ollama model and Codex MCP server once
    # Use gpt-oss:20b which is known to work with tool calling
    ollama_model = OpenAIChatCompletionsModel(
        model="gpt-oss:20b",
        openai_client=AsyncOpenAI(
            base_url="http://localhost:11434/v1",
            api_key="dummy"
        )
    )

    codex_mcp_server = MCPServerStdio(
        name="Codex CLI",
        params={
            "command": "npx",
            "args": ["-y", "codex", "--oss", "-m", "gpt-oss:20b", "mcp-server"],
        },
        client_session_timeout_seconds=360000,
    )

    # Use async context manager for MCP server
    async with codex_mcp_server:
        for i in range(n_iters):
            print(f"### Starting {i}th Iteration ###")

            print("### Copying Benchmark ###")
            shutil.copytree(bench_folder_name, f"{bench_folder_name}_AI_{i}")

            os.chdir(f"{bench_folder_name}_AI_{i}")

            print("### Annotating codes with AI-generated user directives ###")

            # Gather all target files and remark files.
            target_files = find_target_files()

            os.chdir("..")
            os.chdir(f"{bench_folder_name}_AI_{i}")
            target_and_yaml_files = []
            for target_file in target_files:
                # For every target file, scan through all the past remark files
                # and see if there are any remark files that match the pattern
                # "{target_prefix}*.opt.yaml", where target_prefix is the basename
                # without the extension.

                target_prefix = os.path.splitext(os.path.basename(target_file))[0]
                pat = f"{target_prefix}*.opt.yaml"
                corresponding_yaml_files = []
                for yaml_file in yaml_files_from_prev_iter:
                    yaml_basename = os.path.basename(yaml_file)
                    if (fnmatch.fnmatch(yaml_basename, pat)):
                        corresponding_yaml_files.append(yaml_file)
                target_and_yaml_files.append([target_file,
                                              corresponding_yaml_files])

            # Print all the files that are going to be annotated so the user can
            # review it
            print("### Listing Target Files so you can inspect it ###")
            for target_file in target_files:
                print(target_file)

            os.chdir("..")

            # Must be in the orchestration working directory otherwise, context management
            # doesn't work properly
            for file, yaml_files in target_and_yaml_files:
                print(f"### Annotating {file} ###")
                # Pass previous iteration's diagnostics (if any)
                prev_diagnostics = build_diagnostics.get(i-1, {})

                # Retry logic to handle model hallucination errors (e.g., "codx?" instead of "codex")
                max_retries = 3
                success = False
                for attempt in range(max_retries):
                    try:
                        await ai_annotations_codex(file, yaml_files, prev_diagnostics, i, ollama_model, codex_mcp_server)
                        success = True
                        break  # Success, exit retry loop
                    except Exception as e:
                        error_msg = str(e)
                        # Check if it's a tool calling error (model hallucination)
                        if "not found in agent" in error_msg:
                            if attempt < max_retries - 1:
                                print(f"  ⚠️  Warning: Model generated invalid tool call (attempt {attempt + 1}/{max_retries})")
                                print(f"  Error: {error_msg}")
                                print(f"  Retrying...")
                                continue
                            else:
                                print(f"  ❌ Error: Failed after {max_retries} attempts: {error_msg}")
                                print(f"  Skipping file {file}")
                        else:
                            # Unexpected error, re-raise
                            print(f"  ❌ Unexpected error: {error_msg}")
                            raise

                if not success:
                    print(f"  ⚠️  File {file} was not successfully annotated after {max_retries} attempts")

            os.chdir(f"{bench_folder_name}_AI_{i}")

            # Build the benchmark with diagnostics capture
            print("### Building Benchmark with Diagnostics Capture ###")
            build_output = run_cmd_with_capture(make_command, f"build_diagnostics_AI_{i}.log")

            # Analyze build diagnostics
            diagnostics = analyze_build_diagnostics(build_output)
            build_diagnostics[i] = diagnostics

            # Print diagnostic summary
            print(f"### Build Diagnostics Summary for AI_{i} ###")
            print(f"  Errors: {len(diagnostics['errors'])}")
            print(f"  Warnings: {len(diagnostics['warnings'])}")
            print(f"  Pragma Issues: {len(diagnostics['pragma_issues'])}")

            if diagnostics['pragma_issues']:
                print("  Pragma Issues Found:")
                for issue in diagnostics['pragma_issues']:
                    print(f"    - {issue}")

            # Run the modified benchmark and time it
            run_cmd(run_command)

            # Update yaml files from prev iter
            yaml_files_from_prev_iter = find_opt_yaml_files()

            os.chdir("..")


async def ai_annotations_codex(file, remark_files, prev_diagnostics, iteration_num, ollama_model, codex_mcp_server):
    rel_file = get_rel_file(file)

    # Filter remark files to only include those with vector-related passes
    filtered_remark_files = filter_vector_remarks(remark_files)

    print(f"Original remark files: {len(remark_files)}, Filtered remark files: {len(filtered_remark_files)}")

    # Build compiler feedback section
    compiler_feedback = ""
    if prev_diagnostics:
        if prev_diagnostics.get('pragma_issues'):
            compiler_feedback = f"""

COMPILER FEEDBACK FROM PREVIOUS BUILD:
The compiler reported these pragma-related issues:
{chr(10).join(f"- {issue}" for issue in prev_diagnostics['pragma_issues'])}

Please review these issues and ensure your pragma placements are semantically correct."""
        elif prev_diagnostics.get('errors') or prev_diagnostics.get('warnings'):
            compiler_feedback = f"""

COMPILER FEEDBACK FROM PREVIOUS BUILD:
The compiler reported:
- {len(prev_diagnostics.get('errors', []))} errors
- {len(prev_diagnostics.get('warnings', []))} warnings

Please ensure your pragma placements don't cause compilation issues."""

    # Build iteration context
    iteration_context = ""
    if iteration_num > 0:
        iteration_context = f"""

ITERATION CONTEXT:
This is optimization iteration {iteration_num}. The file has been previously optimized in iteration {iteration_num - 1}.
Review the current state of the file and build upon previous optimizations.
Look for additional vectorization opportunities or refine existing pragmas based on compiler feedback."""

    # Build remark files section
    remark_section = ""
    if filtered_remark_files:
        remark_section = f"""

OPTIMIZATION REMARKS AVAILABLE:
The following compiler optimization remark files contain vectorization information:
{chr(10).join(filtered_remark_files)}

Read these files to identify loops that failed to vectorize and why.
Search for keywords: "vectorize", "loop", "pragma", "optimization"."""
    else:
        remark_section = """

No optimization remark files available. Analyze the code structure to identify loops that would benefit from vectorization."""

    # Unified prompt
    prompt = f"""You are a performance engineer optimizing C/C++ code for clang 18.

TARGET FILE: {file}

TASK:
Add compiler hints to enable loop autovectorization. You are ONLY permitted to add pragmas:
- #pragma clang loop vectorize(enable)
- #pragma clang loop interleave(enable)
- #pragma clang loop vectorize_width(X)
- #pragma clang loop interleave_count(X)

Where X is a positive integer. You may combine these pragmas.

CONSTRAINTS:
- ONLY read and edit the target file
- ONLY add pragmas before loop statements
- For nested loops, place pragmas on the innermost loop headers (right before the loop that executes the core work)
- DO NOT modify loop bodies or logic
- DO NOT add other types of changes{remark_section}{iteration_context}{compiler_feedback}

Begin optimization of {file}."""

    # Run Codex with Ollama
    with open("ai-annotations.log", "a") as f:
        coding_agent = Agent(
            name="Vectorization Agent",
            instructions=(
                "You are a performance engineer tasked with adding vectorization pragmas to C/C++ code. "
                "When asked to modify code files, actually modify them. "
                "Always call codex with \"approval-policy\": \"never\" and \"sandbox\": \"workspace-write\"."
            ),
            mcp_servers=[codex_mcp_server],
            model=ollama_model
        )

        result = await Runner.run(coding_agent, prompt)
        print(f"Codex: {result}")
        f.write(f"\n=== Iteration {iteration_num} - {file} ===\n")
        f.write(str(result))
        f.write("\n")


parser = argparse.ArgumentParser()
parser.add_argument("make_command")
parser.add_argument("run_command")
parser.add_argument("bench_name")
parser.add_argument("num_iters")
args = parser.parse_args()

asyncio.run(main(args.make_command,
                 args.run_command,
                 args.bench_name,
                 int(args.num_iters)))
