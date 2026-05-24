from dataclasses import dataclass
import yaml
import subprocess
from enum import StrEnum
from pathlib import Path


class RemarkKind(StrEnum):
    PASSED = "Passed"
    MISSED = "Missed"
    ANALYSIS = "Analysis"
    ANALYSIS_FP_COMMUTE = "AnalysisFPCommute"
    ANALYSIS_ALIASING = "AnalysisAliasing"
    FAILURE = "Failure"
    UNKNOWN = "Unknown"


@dataclass
class Remark:
    kind: RemarkKind
    Pass: str
    Name: str
    Function: str
    Args: list
    DebugLoc: dict = None

    def __init__(self, kind: str, **kwargs):
        self.kind = kind
        self.Pass = kwargs.get("Pass", "")
        self.Name = kwargs.get("Name", "")
        self.Function = kwargs.get("Function", "")
        self.Args = kwargs.get("Args", [])
        self.DebugLoc = kwargs.get("DebugLoc", None)


def _remark_constructor(kind):
    def constructor(loader, node):
        data = loader.construct_mapping(node, deep=True)
        return Remark(kind=kind, **data)

    return constructor


# Add tagged constructors for LLVM YAML
for tag in RemarkKind:
    yaml.add_constructor(f"!{tag}", _remark_constructor(tag), Loader=yaml.SafeLoader)


def get_remarks(source: str, exe: str, flags: list[str] = None) -> tuple[int, str, str]:
    args = [exe, "-c", "-x", "c", "-", "-o", "/dev/null"]
    if flags is not None:
        args.extend(flags)

    # Run the remarks
    result = subprocess.run(
        args,
        input=source,
        capture_output=True,
        text=True,
        timeout=600,
    )

    return result.returncode, result.stdout, result.stderr


def parse_remarks(raw: str) -> list[Remark]:
    """
    Parse the raw LLVM optimization remarks into a list of structured remarks.
    """
    return list(yaml.safe_load_all(raw))


def pretty_debug_loc(loc: dict | None) -> str:
    if not loc:
        return "DebugLoc:\t<none>\n"
    file = Path(loc.get("File", "?")).name
    if file == "<stdin>":
        file = "kernel.c"
    return f"DebugLoc:\t{file}:{loc.get('Line', '?')}:{loc.get('Column', '?')}\n"


def pretty_args(args: list[dict] | None) -> str:
    if not args:
        return "Args:\t<none>\n"
    msg = "".join(str(next(v for k, v in a.items() if k != "DebugLoc")) for a in args)
    return f"Args:\t{msg.replace(chr(10), ' ').strip()}\n"


# Extra context emitted by -Rpass-missed but missing from the YAML record.
_REMARK_HINTS: dict[tuple[str, str], str] = {
    ("loop-vectorize", "CantReorderFPOps"): (
        "allow reordering by specifying "
        "'#pragma clang loop vectorize(enable)' before the loop "
        "or by providing the compiler option '-ffast-math'"
    ),
}


def to_string(remark: Remark) -> str:
    args_line = pretty_args(remark.Args)
    hint = _REMARK_HINTS.get((remark.Pass, remark.Name))
    if hint:
        args_line = args_line.rstrip("\n") + "; " + hint + "\n"
    return (
        f"Pass:\t{remark.Pass}\n"
        f"Name:\t{remark.Name}\n"
        f"Function:\t{remark.Function}\n"
        + pretty_debug_loc(remark.DebugLoc)
        + args_line
    )


def is_optimized(transform: str, remarks: list[Remark]) -> bool:
    """Return True if transformation fired in the given remarks."""
    return any(r.Pass == transform and r.kind == RemarkKind.PASSED for r in remarks)


def check_optimized(
    source: str, exe: str, transform: str, flags: list[str] = None
) -> bool:
    """Compile source and return True if the compiler already vectorized it."""
    retval, stdout, _ = get_remarks(source, exe, flags)
    if retval != 0:
        return False
    return is_optimized(transform, parse_remarks(stdout))
