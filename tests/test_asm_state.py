"""Three-state ASM evidence — is a decision about ASM, or only about a file?"""

from __future__ import annotations

from asm_state import INACTIVE, LIVE, UNKNOWN, AsmState


def test_no_evidence_is_unknown_not_safe():
    """The stale snapshot was self-consistent and wrong; absence must not read as 'new'."""
    state = AsmState()
    assert not state.has_evidence
    assert state.state("anyone") == UNKNOWN
    assert state.holding_back_is_destructive("anyone")
    assert state.keeping_is_destructive("anyone")


def test_an_unconfirmed_snapshot_is_no_evidence_at_all():
    """Exporting a ZIP proves nothing about what ASM received."""
    state = AsmState(snapshot_ids={"anna.meier"}, snapshot_confirmed=False)
    assert not state.has_evidence
    assert state.state("anna.meier") == UNKNOWN


def test_a_confirmed_snapshot_answers_both_ways():
    state = AsmState(snapshot_ids={"anna.meier"}, snapshot_confirmed=True)
    assert state.state("anna.meier") == LIVE
    assert state.state("neu.kollege") == INACTIVE
    assert state.holding_back_is_destructive("anna.meier")
    assert not state.holding_back_is_destructive("neu.kollege"), "a genuinely new person"
    assert not state.keeping_is_destructive("anna.meier")
    assert state.keeping_is_destructive("neu.kollege"), "re-sending would create them"


def test_the_activity_log_outranks_the_snapshot():
    """ASM's own record wins — it also sees accounts made outside this app."""
    state = AsmState(
        log_state={"anna.meier": False, "made.elsewhere": True},
        snapshot_ids={"anna.meier"},
        snapshot_confirmed=True,
    )
    assert state.state("anna.meier") == INACTIVE, "log says deactivated, snapshot is stale"
    assert state.state("made.elsewhere") == LIVE, "never in our snapshot, still real"


def test_a_log_says_nothing_about_people_it_does_not_name():
    """A delta log's silence is not evidence of absence."""
    state = AsmState(log_state={"anna.meier": True})
    assert state.state("anna.meier") == LIVE
    assert state.state("someone.else") == UNKNOWN
    assert state.holding_back_is_destructive("someone.else")


def test_labels_are_the_three_states():
    state = AsmState(log_state={"a": True, "b": False})
    assert (state.label("a"), state.label("b"), state.label("c")) == ("Yes", "No", "?")
