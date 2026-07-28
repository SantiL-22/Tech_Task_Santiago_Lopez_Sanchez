"""Compliance detector corpus.

A curated set of utterances on both sides of every rule: phrases that MUST
trigger (including paraphrases), phrases that must NOT, false positives the
conservative bias accepts on purpose, and known gaps pinned as xfail so they
are visible in every run and flip loudly if ever fixed.

Rationale: the detector has two opposite failure modes. Missing a statutory
trigger is a legal violation; firing on innocent speech costs a contact
attempt. The corpus pins the current balance so any future pattern change is
validated against the whole set at once.
"""

import pytest

from app import compliance

# --- Must trigger: direct phrasings and paraphrases the detector covers -----

TRUE_POSITIVES = [
    ("stop calling me", "cease_and_desist"),
    ("please stop calling", "cease_and_desist"),
    ("don't call me again", "cease_and_desist"),
    ("do not call me anymore", "cease_and_desist"),
    ("never call this number again", "cease_and_desist"),
    ("stop contacting me", "cease_and_desist"),
    ("take me off your list", "cease_and_desist"),
    ("this is a cease and desist", "cease_and_desist"),
    ("quit calling me", "cease_and_desist"),
    ("remove my number", "cease_and_desist"),
    ("talk to my lawyer", "attorney_representation"),
    ("my attorney handles this", "attorney_representation"),
    ("i have a lawyer", "attorney_representation"),
    ("i'm represented by counsel", "attorney_representation"),
    ("call my attorney instead", "attorney_representation"),
    ("i don't owe this", "dispute"),
    ("i do not owe you anything", "dispute"),
    ("this is not my debt", "dispute"),
    ("this isn't my account", "dispute"),
    ("i dispute this", "dispute"),
    ("prove that i owe it", "dispute"),
    ("that was identity theft", "dispute"),
    ("i want validation of this debt", "dispute"),
    ("wrong number", "wrong_party"),
    ("you have the wrong person", "wrong_party"),
    ("no one by that name lives here", "wrong_party"),
    ("they don't live here anymore", "wrong_party"),
    ("i filed for bankruptcy", "bankruptcy"),
    ("i'm bankrupt", "bankruptcy"),
    ("i filed chapter 7", "bankruptcy"),
    ("chapter thirteen, look it up", "bankruptcy"),
    ("i'm recording this", "recording_notice"),
    ("i am recording this call", "recording_notice"),
    ("just so you know, this is being recorded", "recording_notice"),
]


@pytest.mark.parametrize("utterance,rule_id", TRUE_POSITIVES)
def test_statutory_phrasings_trigger(utterance, rule_id):
    assert rule_id in compliance.detect(utterance)


# --- Must NOT trigger: innocent speech near the patterns --------------------

TRUE_NEGATIVES = [
    "i can't stop thinking about this debt",
    "my brother is a lawyer",
    "i owe you an apology",
    "i'll record the payment date somewhere",
    "you're wrong about the amount",
    "call me tomorrow instead",
    "i need to stop spending so much",
    "the chapter of my life where i had money",
    "",
]


@pytest.mark.parametrize("utterance", TRUE_NEGATIVES)
def test_innocent_speech_does_not_trigger(utterance):
    assert compliance.detect(utterance) == []


# --- Conservative bias, accepted on purpose ---------------------------------
# The detector is deliberately biased toward false positives: ending a call
# unnecessarily costs one contact attempt; continuing after a real trigger is
# a violation. These pin that accepted cost so a future "fix" that loosens
# the patterns is a conscious decision, not an accident.

ACCEPTED_FALSE_POSITIVES = [
    ("don't call me a liar", "cease_and_desist"),
    ("the company might go bankrupt someday", "bankruptcy"),
]


@pytest.mark.parametrize("utterance,rule_id", ACCEPTED_FALSE_POSITIVES)
def test_conservative_bias_is_pinned(utterance, rule_id):
    assert rule_id in compliance.detect(utterance)


# --- Known gaps: SHOULD trigger, currently do not ---------------------------
# Kept visible as xfail. If a pattern is added and one starts passing, the
# xpass shows up in the run and the phrase moves to TRUE_POSITIVES.

KNOWN_GAPS = [
    ("this call is being recorded", "recording_notice"),
    ("i want debt validation", "dispute"),
    ("leave me alone", "cease_and_desist"),
]


@pytest.mark.parametrize("utterance,rule_id", KNOWN_GAPS)
@pytest.mark.xfail(reason="paraphrase not covered by current patterns", strict=False)
def test_known_paraphrase_gaps(utterance, rule_id):
    assert rule_id in compliance.detect(utterance)


# --- Severity resolution ----------------------------------------------------


def test_call_ending_rule_wins_over_non_ending():
    triggered = compliance.detect("i'm recording this, and stop calling me")
    assert set(triggered) >= {"recording_notice", "cease_and_desist"}
    rule = compliance.most_severe(triggered)
    assert rule.ends_call and rule.blocks_negotiation


def test_no_triggers_resolves_to_none():
    assert compliance.most_severe([]) is None
    assert compliance.most_severe(["nonexistent_rule_id"]) is None
