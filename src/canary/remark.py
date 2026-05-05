from dataclasses import dataclass
import yaml


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


def parse_remarks(raw: str) -> list[Passed | Missed | Analysis]:
    return list(yaml.safe_load_all(raw))
