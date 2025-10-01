'''
Quick experimental workflow. Still a work in progress.

What it currently does:
1. Makes a benchmark, ingesting a 'make_command' from the user
2. Runs a benchmark, ingesting a 'run_command' from the user
3. Executes an OpenAI API call with the contents of all target files
in the current working directory, and writes the output text
to a new file.

What I need to do:
1. Run the AI-generated files after writing them to a directory.
a. Copy all the AI-generated files to a different folder, with
the exact same structure as the old benchmark
b. Make that version of the benchmark
c. Run that version of the benchmark
d. Time and collect analysis remarks for that version of the benchmark
2. Use Claude Agent SDK, and see if I can time stuff 
3. Make this configurable with other LLMs' APIs



What does the directory structure look like at the beginning?:
Root
|
--- experimental-workflow.py
--- base (for copying)



So what does the directory structure look like at the end?:

Root
|
--- experimental-workflow.py
--- time_base.txt
--- time_ai_0.txt
--- time_ai_1.txt
--- ...
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
from openai import OpenAI


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


def main():
    make_command = "clang++ -O3 -fsave-optimization-record c_prog.cpp"
    run_command = "./a.out"
    bench_folder_name = "my_bench"
    n_iters = 1
    
    # copy the base directory
    print("### Copying Benchmark to Base ###")
    shutil.copytree(bench_folder_name, f"{bench_folder_name}_base")

    # make the project in the new folder
    print("### Building Base Benchmark ###")
    os.chdir(f"{bench_folder_name}_base")
    build_benchmark(make_command)

    # run the project in the new folder
    print("### Running Base Benchmark ###")
    # print(os.getcwd())
    run_benchmark(run_command)

    # get speedup numbers, and remarks
    
    # Assumption: run_command automatically generates .opt.yaml files
    # with the -fsave-optimization-record compiler option
    print("### Finding *.opt.yaml files ###")
    # print(find_opt_yaml_files())

    for i in range(n_iters):
        print(f"### STARTING {i}TH ITERATION ###")
        os.chdir("..")
        print("### Copying Benchmark ###")
        shutil.copytree(bench_folder_name, f"{bench_folder_name}_AI_{i}")
        os.chdir(f"{bench_folder_name}_AI_{i}")
        # For all files, task AI with annotating the code with user
        # directives
        print("### Annotating codes with AI-generated user directives ###") 
        for file in find_target_files():
            ai_annotations(file)

        # Build the benchmark
        build_benchmark(make_command)
        
        # Run the modified benchmark and time it
        run_benchmark(run_command)

        # Collect speedup numbers
        

def ai_annotations(file):
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    with open(file) as f:
        content = f.read()

    response = client.responses.create(
        model="gpt-5",
        instructions="You are a performance engineer, with the goal of reducing execution time in a file. The compiler you are using is clang 18. You are ONLY permitted to add any compiler hints to enable and configure loop autovectorization. This at least includes #pragma clang loop vectorize(enable), interleave(enable), vectorize_width(X), interleave_count(X), where X is in the set of any natural numbers, and any combination of those compiler hints. You are NOT permitted to do anything else. Only return the text of the modified file. Do not return anything else.",
        input=content,
    )

    # with open("openaiapicalls.log", "a") as log:
    #     log.write(response)

    with open(file, "w") as output:
        output.write(response.output_text)


main()
