import dataclasses


@dataclasses.dataclass(frozen=True)
class Outcome:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
