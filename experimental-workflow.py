'''
Quick experimental workflow. Still a work in progress.

What I need to do:
=======
0. Fix some bugs related to pattern matching, and make ai_annotations write
1. Use Claude Agent SDK, and see if I can time stuff 
2. Test
3. Do I need to pass older files in the proceeding prompts? 
4. Make this configurable with other LLMs' APIs

What it currently does:
0. Only works for 1 iteration right now. It kinda works for n iterations. 
1. Makes a benchmark, ingesting a 'make_command' from the user
2. Runs a benchmark, ingesting a 'run_command' from the user
3. Run the AI-generated files after writing them to a directory.
a. Copy all the AI-generated files to a different folder, with
the exact same structure as the old benchmark
b. Make that version of the benchmark
c. Run that version of the benchmark

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
import re
from openai import OpenAI
import json
import fnmatch


def build_benchmark(make_command):
    subprocess.run(make_command,
                   shell=True,
                   stdout=sys.stdout,
                   stderr=subprocess.STDOUT)


def run_benchmark(run_command):
    subprocess.run(run_command,
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


def main(make_command, run_command, bench_folder_name, n_iters=1):
    '''
    Runs experimental workflow.

    Input:
     make_command: if your directory was in the benchmark
       (like $bench_folder_name$), this is the command you would
       run to build the benchmark.
       This should have the '-fsave-optimization-record' compiler option.
     run_command: this is the command to run your benchmark. it should also
       write trial times to a file. 
     bench_folder_name: the base benchmark, with all the files that we
       can copy to other directories.
     n_iters: number of passes for AI remarks.
    '''

    make_command = "clang++ -O3 -fsave-optimization-record c_prog.cpp"
    run_command = "./a.out"
    bench_folder_name = "my_bench"
    n_iters = 1

    # Copy the base directory
    print("### Copying Benchmark to Base ###")
    shutil.copytree(bench_folder_name, f"{bench_folder_name}_base")

    # Make the project in the new folder
    print("### Building Base Benchmark ###")
    os.chdir(f"{bench_folder_name}_base")
    build_benchmark(make_command)

    # Run the project in the new folder
    print("### Running Base Benchmark ###")
    run_benchmark(run_command)

    # Assumption: run_command automatically generates .opt.yaml files
    # with the -fsave-optimization-record compiler option
    print("### Finding *.opt.yaml files ###")
    yaml_files_from_prev_iter = find_opt_yaml_files()

    for i in range(n_iters):
        print(f"### STARTING {i}TH ITERATION ###")

        os.chdir("..")
        print("### Copying Benchmark ###")
        shutil.copytree(bench_folder_name, f"{bench_folder_name}_AI_{i}")

        os.chdir(f"{bench_folder_name}_AI_{i}")

        print("### Annotating codes with AI-generated user directives ###") 

        # Gather all target files and remark files. 
        target_files = find_target_files()
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

        for file, yaml_files in target_and_yaml_files:
            ai_annotations(file, yaml_files)

        # Build the benchmark
        build_benchmark(make_command)

        # Run the modified benchmark and time it
        run_benchmark(run_command)

        # Update yaml files from prev iter
        yaml_files_from_prev_iter = find_opt_yaml_files()


def ai_annotations(file, remark_files=None):
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    inputs = []

    # Construct target file as input
    with open(file) as f:
        inputs.append({
            "role": "user",
            "content": f"<<TARGET FILE (WRITE CHANGES HERE ONLY):\
                {os.path.basename(file)}>>\n{f.read()}"
            })

    # Construct remark files as inputs
    remark_files = remark_files or []
    for path in remark_files:
        with open(path, "r") as rf:
            inputs.append({
                "role": "user",
                "content": f"<<REMARK FILE: {os.path.basename(path)}>>\
                \n{rf.read()}"
            })

    response = client.responses.create(
        model="gpt-5",
        instructions="You are a performance engineer, with the goal of reducing execution time in a file. The compiler you are using is clang 18. You are ONLY permitted to add any compiler hints to enable and configure loop autovectorization. This at least includes #pragma clang loop vectorize(enable), interleave(enable), vectorize_width(X), interleave_count(X), where X is in the set of any natural numbers, and any combination of those compiler hints. You are NOT permitted to do anything else. Only return the text of the modified file. Do not return anything else.",
        input=inputs,
    )

    with open("openaiapicalls.log", "a") as log:
        log.write(json.dumps(response.to_dict(), indent=2))
        log.write("\n\n")

    with open(file, "w") as f:
        f.write(response.output_text)

main()
