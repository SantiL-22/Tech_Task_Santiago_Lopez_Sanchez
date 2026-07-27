from app.compliance import detect, load_approved_consequences, most_severe


def test_cease_request_is_detected():
    assert "cease_and_desist" in detect("look, just stop calling me")


def test_attorney_mention_is_detected():
    assert "attorney_representation" in detect("you need to talk to my lawyer")


def test_dispute_is_detected():
    assert "dispute" in detect("I don't owe this, it's not my debt")


def test_wrong_party_is_detected():
    assert "wrong_party" in detect("you've got the wrong number, pal")


def test_bankruptcy_is_detected():
    assert "bankruptcy" in detect("I filed chapter 7 last year")


def test_recording_notice_does_not_end_the_call():
    rule = most_severe(detect("just so you know, I'm recording this"))
    assert rule.ends_call is False


def test_ordinary_refusal_is_not_a_cease_request():
    # Being difficult is not a statutory trigger. This is the false-positive
    # boundary that matters commercially.
    assert detect("I'm not paying you anything") == []
    assert detect("this is a bad time") == []
    assert detect("I can't afford that") == []


def test_severity_ordering_prefers_the_call_ending_rule():
    rule = most_severe(["recording_notice", "cease_and_desist"])
    assert rule.id == "cease_and_desist"


def test_every_rule_has_a_statutory_basis():
    from app.compliance import RULES

    assert all(r.basis for r in RULES.values())


def test_approved_consequences_load():
    consequences = load_approved_consequences()
    assert len(consequences) >= 4
    assert all(isinstance(c, str) for c in consequences)