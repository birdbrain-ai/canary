import os
import subprocess


def build_benchmark(make_command):
    with open("make.log", "w") as make_log:
        subprocess.run(make_command,
                       shell=True,
                       stdout=make_log,
                       stderr=make_log)


def run_benchmark(run_command):
    with open("run.log", "w") as run_log:
        subprocess.run(run_command,
                       shell=True,
                       stdout=run_log,
                       stderr=run_log)


def main():
    # Make the benchmark
    make_command = "ls -l"    
    build_benchmark(make_command)

    # Run the benchmark and time it
    run_command = "ls -a"
    run_benchmark(run_command)

    # Collect analysis remarks
    # Assumption: run_command automatically generates .opt.yaml files
    # with the -fsave-optimization-record compiler option
    pass

    # With analysis remark information, find which .opt.yaml
    # files you need to optimize, and which you must leave alone
    # For all files, task AI with annotating the code with user
    # directives
    pass


def ai_annotations(file):
    # Split the file up by function using libclang
    # For every function
    # Make a call to ChatGPT's API
    # Update the benchmark with that exact code
    pass


main()
