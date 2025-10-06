from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock
import asyncio
import subprocess
import sys
import os
import shutil


def execute_command(cmd):
    subprocess.run(cmd,
                   shell=True,
                   stdout=sys.stdout,
                   stderr=subprocess.STDOUT)


async def orchestrate_exp():
    options = ClaudeAgentOptions(
        max_turns=50,
        allowed_tools=["Read", "Edit", "Write", "Grep"],
    )

    client = ClaudeSDKClient(options)

    os.chdir("c_prog_cpp")
    
    # execute compile command, with remarks generation
    make_command = "clang++ -O3 -fsave-optimization-record c_prog.cpp"
    execute_command(make_command)

    # execute run command
    run_command = "./a.out"
    execute_command(run_command)

    shutil.copytree("/home/adv7053/tank/AI_Pragmas/new_exp/c_prog", "/home/adv7053/tank/AI_Pragmas/new_exp/c_prog_cpp_ai")
    os.chdir("..")

    # tell ai to annotate and write a new file, using remarks info
    await annotate_a_file(client)
        

async def annotate_a_file(client):
    await client.connect()
    await client.query("Please add #pragma clang loop vectorize(enable) to each loop in the cpp file in the 'c_prog_cpp_AI' folder. Determine whether it is optimal to interleave, and what the optimal vector width is. In the 'cpp_prog_cpp' folder, there is a file that ends with the '.opt.yaml' extension that will give you information that is relevant to this task. Use it to inform the compiler hints you add. DO NOT add compiler hints in the 'cpp_prog_cpp' folder.")
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"Claude: {message}")
        else:
            print(message)


async def main():
    await orchestrate_exp()


asyncio.run(main())
