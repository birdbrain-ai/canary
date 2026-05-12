# Builtin
import subprocess
import os
import asyncio
import re
from typing import TypedDict

# LangChain
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.language_models.base import BaseLanguageModel

# Canary
from canary.remark import Remark, get_remarks, parse_remarks
from canary.validate import ValidationResult, check_semantics
from canary.run import RunConfig, RunResult

# ====---- Global Environment ----==== #
MAX_ATTEMPTS: int = os.getenv("MAX_ATTEMPTS", 1)
MAX_SYNTAX_ATTEMPTS: int = os.getenv("MAX_SYNTAX_ATTEMPTS", 3)
MAX_SEMANTICS_ATTEMPTS: int = os.getenv("MAX_SEMANTICS_ATTEMPTS", 1)

CFLAGS: str = os.getenv("CFLAGS", "")
INCLUDES: str = os.getenv("INCLUDES", "")
CC: str = os.getenv("CC", "clang")
REMARKS: str = os.getenv("REMARKS", "clang-remarks")
TV: str = os.getenv("TV", "alive-tv")


# ====---- State ----==== #
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
    def _is_optimized(self, remarks: list[Remark]) -> bool:
        """
        Inspect the remarks to see if loop vectorization fired.
        """

        # Check if the loop was vectorized
        for remark in remarks:
            if remark.Pass == "loop-vectorize" and remark.Name == "Vectorized":
                return True

        return False

    def _check_remarks(self, state: State):
        """
        Gather optimization remarks.
        Determine if function was successfully optimized.
        """

        # Run the remarks.
        retval, stdout, stderr = get_remarks(
            state["kernel"],
            REMARKS,
            flags=[CFLAGS, INCLUDES],
        )

        # Fetch the output.
        remarks_valid = retval == 0

        if not remarks_valid:
            return {"success": False, "remarks_valid": False}

        # Load the remarks as a list for processing
        remarks: list[Remark] = parse_remarks(stdout)

        # Determine if the kernel was vectorized
        optimized: bool = self._is_optimized(remarks)

        # Remove all irrelevant remarks
        remarks = [r for r in remarks if "loop" in r.Pass]

        # TODO: Filter remarks based on experimental configuration.

        return {
            "success": optimized,
            "remarks_valid": remarks_valid,
            "remarks_output": f"{remarks}",
        }

    def _format_template(self, file: str, **kwargs):
        template = PromptTemplate.from_template(
            open("prompts/optimize.j2").read(),
            template_format="jinja2",
        )

        return template.format(**kwargs)

    async def _prompt_llm(
        self,
        prompt: str,
        prefill: str = None,
        timeout: float = None,
    ):
        messages = [HumanMessage(prompt)]
        if prefill is not None:
            messages.append(AIMessage(content=prefill))

        try:
            result = await asyncio.wait_for(
                self._llm.ainvoke(messages),
                timeout=86400.0,
            )
            return result.content
        except asyncio.TimeoutError:
            print("The LLM invocation timed out and was canceled.")
            raise  # TODO: Add retry logic.

    def _apply_diff(self, response: str, kernel: str) -> str | None:
        m = re.search(
            r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
            response,
            re.DOTALL,
        )

        if not m:
            return None

        search, replace = m.group(1), m.group(2)
        if search not in kernel:
            return None  # trigger retry

        return kernel.replace(search, replace, 1)

    def _repair_remarks(self, state: State):
        """
        Repair remarks using an LLM invocation.
        """

        # Compute the attempt.
        attempt = state["attempts"] + 1

        # Iterate until the tool call works correctly...
        kernel: str = None
        while kernel is None:
            # Format the prompt.
            prompt = self._format_template(
                # Template
                "prompts/optimize.j2",
                # Arguments...
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

            # Prefill
            prefill: str = "<<<<<<< SEARCH\n"

            # Invoke the LLM with the remarks output
            response: str = asyncio.run(
                self._prompt_llm(
                    prompt,
                    prefill,
                    86400.0,
                )
            )

            # Apply the model changes to the existing kernel.
            kernel: str = self._apply_diff(response, state["kernel"])

        # TODO: Should we loop on correct SEARCH/REPLACE text edit?
        if kernel is None:
            # TODO: If we don't loop until we get a correct edit, then we should
            # signal the error in some way for counting.
            return {
                "response": response,
                "attempts": attempt,
            }

        return {
            "response": response,
            "attempts": attempt,
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

        kernel = state["kernel"]

        # Run the linter.
        result = subprocess.run(
            [
                CC,
                INCLUDES,
                "-fsyntax-only",
                "-x",
                "c",
                "-",
                "-o",
                "/dev/null",
            ],
            input=kernel,
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
        result: ValidationResult = check_semantics(
            TV,
            state["orig_kernel"],
            state["kernel"],
            cc=CC,  # TODO: if CC is not in the llvm family, default to one
            cflags=[INCLUDES, CFLAGS],
        )

        return {
            "semantics_valid": result.valid,
            "semantics_output": result.output,
        }

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
