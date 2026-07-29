"""Deterministic compliance guardrails.

These do not depend on the language model noticing anything. Every consumer
turn is scanned server-side, and a match here overrides the negotiation
entirely: the agent reads a fixed script and, where required, the call ends.

Detection is deliberately conservative and biased toward false positives.
Ending a call unnecessarily costs one contact attempt. Continuing to negotiate
after a cease request is a violation.

The scripts below are illustrative. A production deployment would use wording
reviewed by counsel for each jurisdiction and portfolio.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CONSEQUENCES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "approved_consequences.yaml"
)


@dataclass(frozen=True)
class ComplianceRule:
    id: str
    # Statutory anchor, kept next to the rule so the repo is auditable.
    basis: str
    script: str
    ends_call: bool
    blocks_negotiation: bool


RULES: dict[str, ComplianceRule] = {
    "cease_and_desist": ComplianceRule(
        id="cease_and_desist",
        basis="FDCPA 15 U.S.C. 1692c(c) - consumer request to cease communication",
        # 1692c(c) permits notifying that collection efforts are terminated.
        # The balance statement is on the approved-consequences list; it is a
        # neutral fact, not leverage to reverse the cease request.
        script=(
            "Understood. I've recorded your request and we'll stop contacting you "
            "about this account. The balance does remain on the account until "
            "it's resolved. Thank you for your time."
        ),
        ends_call=True,
        blocks_negotiation=True,
    ),
    "attorney_representation": ComplianceRule(
        id="attorney_representation",
        basis="FDCPA 15 U.S.C. 1692c(a)(2) - consumer represented by counsel",
        script=(
            "Thank you for telling me. Since you're represented by an attorney on "
            "this account, I'll direct any further communication to them rather "
            "than to you. Have a good day."
        ),
        ends_call=True,
        blocks_negotiation=True,
    ),
    "dispute": ComplianceRule(
        id="dispute",
        basis="FDCPA 15 U.S.C. 1692g(b) - verification of debt",
        script=(
            "I've noted that you dispute this account. We'll send you written "
            "verification, and collection activity pauses until that's provided."
        ),
        ends_call=True,
        blocks_negotiation=True,
    ),
    "wrong_party": ComplianceRule(
        id="wrong_party",
        basis="FDCPA 15 U.S.C. 1692b - location information from third parties",
        script=(
            "I'm sorry for the confusion. I'll update our records so you're not "
            "contacted again. Thank you."
        ),
        ends_call=True,
        blocks_negotiation=True,
    ),
    "bankruptcy": ComplianceRule(
        id="bankruptcy",
        basis="11 U.S.C. 362 - automatic stay",
        script=(
            "Thank you for letting me know. Collection activity stops while a "
            "bankruptcy case is active. I'll note that on the account."
        ),
        ends_call=True,
        blocks_negotiation=True,
    ),
    "recording_notice": ComplianceRule(
        id="recording_notice",
        basis="State two-party consent statutes",
        script=(
            "That's fine. This call is recorded on our side as well, and you're "
            "speaking with an automated assistant."
        ),
        ends_call=False,
        blocks_negotiation=False,
    ),
}


# Patterns are matched against the consumer's transcribed speech, lowercased.
# Word boundaries keep them tight: "stop calling" should fire, "I can't stop
# thinking about it" should not.
PATTERNS: dict[str, list[str]] = {
    "cease_and_desist": [
        r"\bstop calling\b",
        r"\bdon'?t call me\b",
        r"\bdo not call me\b",
        r"\bnever call\b",
        r"\bstop contacting\b",
        r"\btake me off\b.*\blist\b",
        r"\bcease and desist\b",
        r"\bquit calling\b",
        r"\bremove my number\b",
    ],
    "attorney_representation": [
        r"\bmy (attorney|lawyer)\b",
        r"\bi have (an|a) (attorney|lawyer)\b",
        r"\btalk to my (attorney|lawyer)\b",
        r"\brepresented by\b",
        r"\bcall my (attorney|lawyer)\b",
    ],
    "dispute": [
        r"\bi (don'?t|do not) owe\b",
        r"\bnot my debt\b",
        r"\bthis (isn'?t|is not) my\b",
        r"\bi dispute\b",
        r"\bprove (it|that i owe)\b",
        r"\bidentity theft\b",
        r"\bvalidat(e|ion) (of )?(this |the )?debt\b",
        r"\bdebt validation\b",
    ],
    "wrong_party": [
        r"\bwrong number\b",
        r"\bwrong person\b",
        r"\bno one by that name\b",
        r"\bnobody (here )?by that name\b",
        r"\bthey don'?t live here\b",
    ],
    "bankruptcy": [
        r"\bbankrupt(cy)?\b",
        r"\bchapter (7|13|seven|thirteen)\b",
        r"\bfiled chapter\b",
    ],
    "recording_notice": [
        r"\bi'?m recording\b",
        r"\brecording this call\b",
        r"\bthis is being recorded\b",
        r"\bcall is being recorded\b",
    ],
}

_COMPILED = {
    rule_id: [re.compile(p) for p in patterns] for rule_id, patterns in PATTERNS.items()
}


def detect(utterance: str) -> list[str]:
    """Return the ids of every compliance rule triggered by this utterance."""
    if not utterance:
        return []
    text = utterance.lower()
    return [
        rule_id
        for rule_id, regexes in _COMPILED.items()
        if any(r.search(text) for r in regexes)
    ]


def most_severe(rule_ids: list[str]) -> ComplianceRule | None:
    """When several rules fire at once, the one that ends the call wins."""
    rules = [RULES[r] for r in rule_ids if r in RULES]
    if not rules:
        return None
    return max(rules, key=lambda r: (r.ends_call, r.blocks_negotiation))


def load_approved_consequences(path: Path = CONSEQUENCES_PATH) -> list[str]:
    raw = yaml.safe_load(path.read_text())
    return [item["text"] for item in raw["approved"]]