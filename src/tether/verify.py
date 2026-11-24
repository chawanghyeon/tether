import dataclasses
from collections.abc import Sequence
from pathlib import Path

from tether.changes import changed_since
from tether.checks import (
    CheckResult,
    Deadline,
    Status,
    failed,
    format_report,
    summarize,
)
from tether.claims import read_turn, unsupported_claims
from tether.config import Config
from tether.pipeline import turn_results
from tether.state import TurnState, state_dir
from tether.summary import one_line, summarize_changes, write_summary
from tether.tamper import find_tampering, turn_diff

CLAIMS_HEADING = "tether: unsupported claims"
CLAIMS_ADVICE = "\nRun the check now, or correct your message."
TAMPER_HEADING = "tether: edits to review"
TAMPER_ADVICE = "\nUndo these, or say why each one is needed."
TIMEOUT_NOTE = "tether: checks timed out; run `tether check`"


@dataclasses.dataclass(frozen=True)
class TurnSnapshot:
    started_at: float
    edited: tuple[str, ...]
    baseline: str
    transcript_path: str | None = None

    @classmethod
    def of(cls, turn: TurnState, transcript: Path | None) -> "TurnSnapshot":
        return cls(
            turn.started_at,
            tuple(turn.edited),
            turn.baseline,
            str(transcript) if transcript else None,
        )


@dataclasses.dataclass(frozen=True)
class TurnReport:
    changed: tuple[str, ...]
    results: tuple[CheckResult, ...]
    claims: tuple[str, ...]
    findings: tuple[str, ...]
    summary_line: str | None

    def problems(self, config: Config) -> bool:
        tamper = bool(self.findings) and config.tamper_blocks
        return bool(failed(self.results) or self.claims or tamper)

    def agent_message(self, config: Config) -> str:
        sections = []
        if failed(self.results):
            sections.append(
                format_report(self.results, config.max_report_chars)
            )
        if self.claims:
            sections.append(
                _bullets(CLAIMS_HEADING, self.claims) + CLAIMS_ADVICE
            )
        if self.findings and config.tamper_blocks:
            sections.append(
                _bullets(TAMPER_HEADING, self.findings) + TAMPER_ADVICE
            )
        return "\n\n".join(sections)

    def user_messages(self, attempts: int | None) -> list[str]:
        messages = []
        if failed(self.results):
            lead = (
                "tether: checks failed. "
                if attempts is None
                else f"tether: still failing after {attempts} fix attempts. "
            )
            messages.append(lead + summarize(self.results))
        if self.claims:
            messages.append(_bullets(CLAIMS_HEADING, self.claims))
        if self.findings:
            messages.append(_bullets(TAMPER_HEADING, self.findings))
        if any(r.status is Status.TIMED_OUT for r in self.results):
            messages.append(TIMEOUT_NOTE)
        if self.summary_line:
            messages.append(self.summary_line)
        return messages


def verify_turn(
    config: Config, snapshot: TurnSnapshot, deadline: Deadline
) -> TurnReport:
    changed = changed_since(config.root, snapshot.started_at, snapshot.edited)
    results = turn_results(config, changed, deadline)
    claims = _unsupported_claims(config, snapshot, results)
    diffs = turn_diff(config, snapshot.baseline, changed)
    findings = [str(finding) for finding in find_tampering(config, diffs)]
    summary_line = None
    if config.summary_on_stop and diffs:
        changes = summarize_changes(config, snapshot.baseline, diffs)
        write_summary(state_dir(config.root), changes)
        summary_line = one_line(changes)
    return TurnReport(
        tuple(changed),
        tuple(results),
        tuple(claims),
        tuple(findings),
        summary_line,
    )


def _unsupported_claims(
    config: Config, snapshot: TurnSnapshot, results: Sequence[CheckResult]
) -> list[str]:
    if not config.verify_claims or snapshot.transcript_path is None:
        return []
    turn = read_turn(Path(snapshot.transcript_path), snapshot.started_at)
    return unsupported_claims(turn, results)


def _bullets(heading: str, items: Sequence[str]) -> str:
    return heading + "".join(f"\n- {item}" for item in items)
