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

    # Bookkeeping
    remarks_attempt: int
    syntax_attempt: int
    semantics_attempt: int

    # Tool state
    remarks_valid: bool
    remarks_output: str
    syntax_valid: bool
    syntax_output: str
    semantics_valid: bool
    semantics_output: str

    # Configuration
    temperature: float
    original_bitcode: float

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

import os

MAX_ATTEMPTS: int = os.getenv("MAX_ATTEMPTS", 1)
MAX_SYNTAX_ATTEMPTS: int = os.getenv("MAX_SYNTAX_ATTEMPTS", 3)
MAX_SEMANTICS_ATTEMPTS: int = os.getenv("MAX_SEMANTICS_ATTEMPTS", 1)


class Agent:
    """
    Canary agent for automatic vectorization.
    """

    # ====---- State ----==== #
    _orig_ir: str
    _llm: BaseLanguageModel
    _app: CompiledStateGraph

    # ====---- Initialization ----==== #
    def __init__(
        self,
        llm: BaseLanguageModel,
        orig_ir: str,
    ):
        self._orig_ir = orig_ir
        self._llm = llm
        self._app = self._build_graph()

    # ====---- Public API ----==== #
    def run(self, config: RunConfig) -> RunResult:
        final: State = self._app.invoke(
            initial_state(config),
            config={"configurable": {"thread_id": config.run_id}},
        )
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
        pass

    def _repair_remarks(self, state: State):
        return {"attempts": state["attempts"] + 1}

    def _valid_remarks(self, state: State):

        return {"success": True}

    # ----

    def _check_syntax(self, state: State):  # run linter on temp file
        """
        Check syntax of the kernel using the linter.
        """

        # Run the linter.
        result = subprocess.run(
            ["clang", "-fsyntax-only", "-x", "c", "-"],
            input=state["kernel"],
            capture_output=True,
            text=True,
        )

        return {
            "syntax_valid": result.returncode == 0,
            "syntax_output": result.stdout,
        }

    def _repair_syntax(self, state: State):
        """
        Repair syntax of the kernel using an LLM call.
        """
        return {"syntax_attempts": state["syntax_attempts"] + 1}

    def _valid_syntax(self, state: State):
        """
        Transition state for when syntax is valid.
        """
        pass

    # ----

    def _check_semantics(self, state: State):
        """
        Check semantics preservation using alive2.
        """
        # Set up a pipe for command substitution
        read_fd, write_fd = os.pipe()

        try:
            clang = subprocess.Popen(
                [
                    "clang",
                    "-O1",
                    "-emit-llvm",
                    "-c",
                    "-x",
                    "c",
                    "-",
                    "-o",
                    f"/dev/fd/{write_fd}",
                ],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(write_fd,),
            )
            alive = subprocess.Popen(
                ["alive-tv", self._orig_ir, f"/dev/fd/{read_fd}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(read_fd,),
            )

            # Close the pipe so the commands can use it.
            os.close(read_fd)
            os.close(write_fd)
            # Run clang
            clang.stdin.write(state["kernel"].encode())
            clang.stdin.close()
            clang.wait()
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

    # ----

    # ====---- Edges (conditional) ----==== #

    def _vectorized(self, state: State):
        return True

    def _remarks_loop(self, state: State):
        # TODO: Check that remarks check passed.
        state["success"] = self._vectorized(state)
        if state["success"]:
            state["reason"] = "success"
            return "valid_remarks"
        if state["attempts"] >= MAX_ATTEMPTS:
            state["reason"] = "remarks_timeout"
            return END
        return "repair_remarks"

    def _syntax_loop(self, state: State):
        # TODO: Check that syntax check passed.
        if linter_passed(stats):
            return "valid_syntax"
        if state["syntax_attempts"] >= MAX_SYNTAX_ATTEMPTS:
            state["reason"] = "syntax_timeout"
            return END
        return "repair_syntax"

    def _semantics_loop(self, state: State):
        # TODO: Check that semantics check passed.
        if alive2_passed(state):
            return "valid_semantics"
        if state["semantics_attempts"] >= MAX_SEMANTICS_REPAIR:
            state["reason"] = "semantics_timeout"
            return END
        return "repair_semantics"

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
        return graph.compile()
