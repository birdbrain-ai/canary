from dataclasses import dataclass
import yaml
import subprocess


@dataclass
class Remark:
    kind: str  # "Passed", "Missed", "Analysis", "Failure"
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
for tag in ("Passed", "Missed", "Analysis", "Failure"):
    yaml.add_constructor(f"!{tag}", _remark_constructor(tag), Loader=yaml.SafeLoader)


def get_remarks(source: str, exe: str, flags: list[str] = None) -> tuple[int, str, str]:
    args = [exe, "-c", "-x", "c", "-"]
    if flags is not None:
        args.extend(flags)

    # Run the remarks
    result = subprocess.run(
        args,
        input=source,
        capture_output=True,
        text=True,
    )

    return result.returncode, result.stdout, result.stderr


def parse_remarks(raw: str) -> list[Remark]:
    """
    Parse the raw LLVM optimization remarks into a list of structured remarks.
    """
    return list(yaml.safe_load_all(raw))
