# ====---- Run Configuration ----==== #
from dataclasses import dataclass


@dataclass
class RunConfig:
    run_id: str
    kernel: str
    temperature: int


# ====---- Run Results ----==== #
from dataclasses import dataclass


@dataclass
class RunResult:
    run_id: str
    success: bool
    reason: str
    attempts: int
    final_kernel: str
    log: dict


# ====---- State ----==== #
from typing import TypedDict


class State(TypedDict):
    # Run information
    run_id: str

    # Kernel state
    kernel: str
    orig_kernel: str

    # Bookkeeping
    attempts: int
    syntax_attempts: int
    semantics_attempts: int

    # Tool state
    remarks_valid: bool
    remarks_output: str
    syntax_valid: bool
    syntax_output: str
    semantics_valid: bool
    semantics_output: str

    # LLM state
    response: str

    # Configuration
    temperature: float

    # Output
    log: dict
    success: bool
    reason: str


def initial_state(config: RunConfig) -> State:
    return State(
        # Run information
        run_id=config.run_id,
        # Kernel
        kernel=config.kernel,
        orig_kernel=config.kernel,
        # Attempts
        attempts=0,
        syntax_attempts=0,
        semantics_attempts=0,
        # Tool output
        remarks_valid=False,
        remarks_output="",
        syntax_valid=False,
        syntax_output="",
        semantics_valid=False,
        semantics_output="",
        # Model parameters
        temperature=config.temperature,
        # Agent output
        log={},
        success=False,
        reason="",
    )


# ====---- Agent ----==== #
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.prompts import PromptTemplate

import subprocess
import os
import asyncio

MAX_ATTEMPTS: int = os.getenv("MAX_ATTEMPTS", 1)
MAX_SYNTAX_ATTEMPTS: int = os.getenv("MAX_SYNTAX_ATTEMPTS", 3)
MAX_SEMANTICS_ATTEMPTS: int = os.getenv("MAX_SEMANTICS_ATTEMPTS", 1)

CFLAGS: str = os.getenv("CFLAGS", "")
INCLUDES: str = os.getenv("INCLUDES", "")
CC: str = os.getenv("CC", "clang")
REMARKS: str = os.getenv("REMARKS", "clang-remarks")
TV: str = os.getenv("TV", "alive-tv")


class Agent:
    """
    Canary agent for automatic vectorization.
    """

    # ====---- State ----==== #
    _llm: BaseLanguageModel
    _app: CompiledStateGraph
    _checkpointer: MemorySaver
    _timeout: int

    # ====---- Initialization ----==== #
    def __init__(
        self,
        llm: BaseLanguageModel,
    ):
        self._llm = llm
        self._checkpointer = MemorySaver()
        self._app = self._build_graph().compile(
            checkpointer=self._checkpointer,
        )

    # ====---- Public API ----==== #
    def run(self, config: RunConfig) -> RunResult:

        thread = {"configurable": {"thread_id": config.run_id}}
        for step in self._app.stream(
            initial_state(config),
            config=thread,
            stream_mode="updates",
        ):
            print(step)

        final: State = self._app.get_state(thread).values

        return RunResult(
            run_id=final["run_id"],
            success=final["success"],
            reason=final["reason"],
            attempts=final["attempts"],
            final_kernel=final["kernel"],
            log=final["log"],
        )

    # ====---- Nodes ----==== #
    def _check_remarks(self, state: State):  # run remarks on temp file
        # Run the remarks
        result = subprocess.run(
            [
                CC,
                CFLAGS,
                INCLUDES,
                "-x",
                "c",
                "-",
                "-O3",
                "-fsave-optimization-record=yaml",
                "-foptimization-record-file=/dev/stdout",
            ],
            input=state["kernel"],
            capture_output=True,
            text=True,
        )

        # Fetch the output.
        remarks_valid = result.returncode == 0
        remarks_output = result.stdout

        # TODO: Determine if the kernel was vectorized
        vectorized: bool = remarks_valid

        return {
            "success": vectorized,
            "remarks_valid": remarks_valid,
            "remarks_output": remarks_output,
        }

    async def _prompt_llm(self, prompt: str, timeout: float = None):
        try:
            result = await asyncio.wait_for(
                self._llm.ainvoke(prompt),
                timeout=86400.0,
            )
            return result.content
        except asyncio.TimeoutError:
            print("The LLM invocation timed out and was canceled.")
            raise  # TODO: Add retry logic.

    def _repair_remarks(self, state: State):
        """
        Repair remarks using an LLM invocation.
        """
        # TODO: Format the prompt.
        template = PromptTemplate.from_template(
            open("prompts/optimize.j2").read(),
            template_format="jinja2",
        )

        prompt = template.format(
            kernel=state["kernel"],
            remarks=state["remarks_output"],
            compiler={
                "family": "clang",
            },
            explain={
                "transformations": True,
                "diagnostics": True,
            },
        )

        print(f"Asking the LLM:\n{prompt}")

        # Invoke the LLM with the remarks output
        response: str = asyncio.run(self._prompt_llm(prompt, 86400.0))

        # TODO: Parse the SEARCH/REPLACE text edit
        # TODO: Should we loop on correct SEARCH/REPLACE text edit?
        # TODO: Construct the new kernel
        kernel: str = state["kernel"]

        return {
            "response": response,
            "attempts": state["attempts"] + 1,
            "kernel": kernel,
        }

    def _valid_remarks(self, state: State):
        """
        Transition state when remarks indicate success.
        """
        pass

    def _remarks_loop(self, state: State):
        if state["success"]:
            return "valid_remarks"
        if state["attempts"] >= MAX_ATTEMPTS:
            state["reason"] = "remarks_timeout"
            return END
        return "repair_remarks"

    # ----

    def _check_syntax(self, state: State):
        """
        Check syntax of the kernel using the linter.
        """

        # Run the linter.
        result = subprocess.run(
            [CC, INCLUDES, "-fsyntax-only", "-x", "c", "-"],
            input=state["kernel"],
            capture_output=True,
            text=True,
        )

        print(f"linter exit {result.returncode}")

        return {
            "syntax_valid": result.returncode == 0,
            "syntax_output": result.stdout,
        }

    def _repair_syntax(self, state: State):
        """
        Repair syntax of the kernel using an LLM call.
        """
        # TODO: call the LLM, providing the linter output
        return {"syntax_attempts": state["syntax_attempts"] + 1}

    def _valid_syntax(self, state: State):
        """
        Transition state for when syntax is valid.
        """
        pass

    def _syntax_loop(self, state: State):
        if state["syntax_valid"]:
            return "valid_syntax"
        if state["syntax_attempts"] >= MAX_SYNTAX_ATTEMPTS:
            state["reason"] = "syntax_timeout"
            return END
        return "repair_syntax"

    # ----

    def _check_semantics(self, state: State):
        """
        Check semantics preservation using alive2.
        """
        # Set up a pipe for command substitution
        tgt_read_fd, tgt_write_fd = os.pipe()
        src_read_fd, src_write_fd = os.pipe()

        try:
            compile_src = subprocess.Popen(
                [
                    CC,
                    INCLUDES,
                    "-O1",
                    "-emit-llvm",
                    "-c",
                    "-x",
                    "c",
                    "-",
                    "-o",
                    f"/dev/fd/{src_write_fd}",
                ],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(src_write_fd,),
            )
            compile_tgt = subprocess.Popen(
                [
                    CC,
                    INCLUDES,
                    "-O1",
                    "-emit-llvm",
                    "-c",
                    "-x",
                    "c",
                    "-",
                    "-o",
                    f"/dev/fd/{tgt_write_fd}",
                ],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(tgt_write_fd,),
            )
            alive = subprocess.Popen(
                [
                    TV,
                    "--src-unroll=3",
                    "--tgt-unroll=3",
                    f"/dev/fd/{src_read_fd}",
                    f"/dev/fd/{tgt_read_fd}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(src_read_fd, tgt_read_fd),
            )

            # Close the pipe so the commands can use it.
            os.close(src_read_fd)
            os.close(src_write_fd)
            os.close(tgt_read_fd)
            os.close(tgt_write_fd)
            # Compile source
            compile_src.stdin.write(state["orig_kernel"].encode())
            compile_src.stdin.close()
            compile_src.wait()
            # Compile target
            compile_tgt.stdin.write(state["kernel"].encode())
            compile_tgt.stdin.close()
            compile_tgt.wait()
            # Run alive
            stdout, stderr = alive.communicate()
            exitcode = alive.returncode == 0

            return {
                "semantics_valid": exitcode == 0,
                "semantics_output": stdout.decode(),
            }

        except Exception:
            os.close(read_fd)
            os.close(write_fd)
            raise

    def _repair_semantics(self, state: State):
        """
        Repair semantic errors with an LLM invocation.
        """
        return {"semantics_attempts": state["semantics_attempts"] + 1}

    def _valid_semantics(self, state: State):
        """
        Transition state for when semantics are valid.
        """
        return {}

    def _semantics_loop(self, state: State):
        # TODO: Check that semantics check passed.
        if state["semantics_valid"]:
            return "valid_semantics"
        if state["semantics_attempts"] >= MAX_SEMANTICS_ATTEMPTS:
            state["reason"] = "semantics_timeout"
            return END
        return "repair_semantics"

    # ----

    # ====---- Graph ----==== #
    def _build_graph(self):
        graph = StateGraph(State)

        # ---- Nodes ---- #
        # Optimization loop
        graph.add_node("check_remarks", self._check_remarks)
        graph.add_node("repair_remarks", self._repair_remarks)
        graph.add_node("valid_remarks", self._valid_remarks)

        # Syntax loop
        graph.add_node("check_syntax", self._check_syntax)
        graph.add_node("repair_syntax", self._repair_syntax)
        graph.add_node("valid_syntax", self._valid_syntax)

        # Semantics loop
        graph.add_node("check_semantics", self._check_semantics)
        graph.add_node("repair_semantics", self._repair_semantics)
        graph.add_node("valid_semantics", self._valid_semantics)

        # ---- Edges ---- #
        # First, check the remarks.
        graph.set_entry_point("check_remarks")

        # If vectorized --> valid_remarks; else --> repair_remarks
        graph.add_conditional_edges("check_remarks", self._remarks_loop)
        # After we attempt to repair_remarks --> check_syntax.
        graph.add_edge("repair_remarks", "check_syntax")
        # Repair any syntax violations.
        graph.add_conditional_edges("check_syntax", self._syntax_loop)
        # After syntax check passes, check for semantics.
        graph.add_edge("valid_syntax", "check_semantics")
        # Repair any semantics violations.
        graph.add_conditional_edges("check_semantics", self._semantics_loop)
        # After semantics check passes, check remarks.
        graph.add_edge("check_semantics", "check_remarks")

        # Graceful exit.
        graph.add_edge("valid_remarks", END)

        # ---- Compile ---- #
        return graph
