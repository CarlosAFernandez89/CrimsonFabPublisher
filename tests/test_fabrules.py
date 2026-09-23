"""The rule table is the app's only record of what Fab requires.

These tests pin the contract that keeps its two consumers - the validator and
the drafting prompt - honest about where each rule came from.
"""

from __future__ import annotations

import pytest

from fabpublisher.listing import fabrules


def test_every_rule_is_populated():
    for rule in fabrules.RULES:
        assert rule.id, "a rule with no id cannot be cited"
        assert rule.text.strip()
        assert rule.applies_to in (fabrules.PACKAGE, fabrules.COPY, fabrules.MEDIA)
        assert rule.confidence in (fabrules.DOCUMENTED, fabrules.OBSERVED)


def test_rule_ids_are_unique():
    ids = [rule.id for rule in fabrules.RULES]
    assert len(ids) == len(set(ids))


def test_documented_rules_cite_a_section_and_observed_ones_do_not():
    """The whole point of the confidence field.

    A number quoted from Fab's document and a number read off the portal must
    never be indistinguishable in the code.
    """
    for rule in fabrules.RULES:
        if rule.confidence == fabrules.DOCUMENTED:
            assert rule.section, f"{rule.id} claims to be documented but cites nothing"
            assert rule.citation.startswith("Fab ")
        else:
            assert not rule.section, f"{rule.id} is observed but cites {rule.section}"


def test_cite_names_the_source():
    assert fabrules.cite("no-user-plugin-deps") == "Fab 4.3.6.d"
    assert fabrules.cite("title-length") == "Fab publisher portal"


def test_unknown_rule_id_raises():
    """A typo'd id must fail loudly rather than produce an empty citation."""
    with pytest.raises(KeyError):
        fabrules.rule("no-such-rule")


def test_rules_for_partitions_the_table():
    buckets = [
        fabrules.rules_for(target)
        for target in (fabrules.PACKAGE, fabrules.COPY, fabrules.MEDIA)
    ]
    assert sum(len(b) for b in buckets) == len(fabrules.RULES)
    assert all(buckets), "every target should have at least one rule"
