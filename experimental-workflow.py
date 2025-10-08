'''
TODO:
0. Check if my session management actually works - why am I not getting
the correct session_id?
1. Review and test the current experimental workflow
a. Test on my_bench for multiple shots.
b. Make logs easier to read
c. Test on blackscholes for multiple shots.

Note: Measure a few things:
1) Does it work? Use logs to verify that.
2) How long does it take?

2. Make this configurable with other cheaper LLMs like DeepSeek

3. Enforce more strict permissions / rules for the experimental workflow

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
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
import asyncio


def get_rel_file(abs_file):
    rel_file = os.path.relpath(abs_file, os.getcwd())
    # print("RELATIVE FILE in the function: " + rel_file)
    # parts = rel_file.split(os.sep)
    # rel_file = os.sep.join(parts[1:])
    return rel_file


def run_cmd(make_command):
    subprocess.run(make_command,
                   shell=True,
                   stdout=sys.stdout,
                   stderr=subprocess.STDOUT)


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

    sessions = {}

    for i in range(n_iters):
        print(f"### Starting {i}th Iteration ###")

        os.chdir("..")
        print("### Copying Benchmark ###")
        shutil.copytree(bench_folder_name, f"{bench_folder_name}_AI_{i}")

        os.chdir(f"{bench_folder_name}_AI_{i}")

        print("### Annotating codes with AI-generated user directives ###")

        # Gather all target files and remark files.
        target_files = find_target_files()

        # Map target_files to sessions
        if i == 0:
            for target_file in target_files:
                print(target_file)
                print("RELATIVE FILE: " + get_rel_file(target_file))
                sessions[get_rel_file(target_file)] = None

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

        options = ClaudeAgentOptions(
            max_turns=50,
            allowed_tools=["Read", "Edit", "Write", "Grep"],
            system_prompt="You are a performance engineer, with the goal of reducing execution time in a specified file. The compiler you are using is clang 18. You are ONLY permitted to add any compiler hints to enable and configure loop autovectorization. This at least includes #pragma clang loop vectorize(enable), interleave(enable), vectorize_width(X), interleave_count(X), where X is in the set of any natural numbers, and any combination of those compiler hints. You are NOT permitted to do anything else."
        )
        client = ClaudeSDKClient(options)

        for file, yaml_files in target_and_yaml_files:
            print(f"### Annotating {file} ###")
            await ai_annotations(file, yaml_files, sessions, client)

        # Build the benchmark
        run_cmd(make_command)

        # Run the modified benchmark and time it
        run_cmd(run_command)

        # Update yaml files from prev iter
        yaml_files_from_prev_iter = find_opt_yaml_files()


async def ai_annotations(file, remark_files, sessions, client):
    await client.connect()

    rel_file = get_rel_file(file)

    # Either original session
    if sessions[rel_file] is None:
        await client.query(f"Please add compiler hints to the file at this \
        path {file}, and use information from remark files at these paths: \
        {remark_files}")
    # Or resume session
    else:
        print(sessions[rel_file])
        await client.query(
            prompt=f"Please add compiler hints to the file at this \
            path {file}, and use information from remark files at these paths:\
            {remark_files}. Use information from previous attempts at changing\
            a similar file too.",
            session_id=sessions[rel_file]
        )
    async for message in client.receive_response():
        if hasattr(message, 'subtype') and message.subtype == 'init':
            sessions[rel_file] = message.data.get('session_id')
        print(message)


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
