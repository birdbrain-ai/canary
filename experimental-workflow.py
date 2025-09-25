import sys
import os
import subprocess


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


def main():
    make_command = "clang++ -O3 c_prog.cpp"
    run_command = "./a.out"

    # Make the benchmark
    build_benchmark(make_command)

    # Run the benchmark and time it
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
