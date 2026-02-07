"""
Phase 1 Invariant Tests — Ensures the allowed matrix is enforced end-to-end.

This test iterates all Phase 1 allowed team counts and verifies:
1. Template is valid for that team count
2. Schedule Builder returns no errors
3. Match generation produces correct counts
"""

import pytest
from app.services.draw_plan_rules import (
    ALLOWED_TEAM_COUNTS,
    PHASE1_SUPPORTED_TEAM_COUNTS,
    required_wf_rounds,
    calculate_wf_matches,
    calculate_rr_matches_for_pools,
    calculate_rr_only_matches,
)
from app.services.draw_plan_engine import (
    DrawPlanSpec,
    normalize_template_key,
    compute_inventory,
    resolve_event_family,
)


def make_spec_for_team_count(team_count: int, family: str) -> DrawPlanSpec:
    """Build a DrawPlanSpec for a given team count and family."""
    wf_rounds = required_wf_rounds(family, team_count)
    return DrawPlanSpec(
        event_id=1,
        event_name=f"Test Event {team_count}",
        division="Test",
        team_count=team_count,
        template_type=family,
        template_key=normalize_template_key(family),
        guarantee=5,
        waterfall_rounds=wf_rounds,
        waterfall_minutes=60,
        standard_minutes=105,
    )


class TestPhase1AllowedMatrix:
    """Iterate all Phase 1 allowed team counts and verify invariants."""

    @pytest.mark.parametrize("team_count", sorted(ALLOWED_TEAM_COUNTS["RR_ONLY"]))
    def test_rr_only_inventory(self, team_count: int):
        """RR_ONLY events produce correct inventory with no errors."""
        spec = make_spec_for_team_count(team_count, "RR_ONLY")
        
        # Verify family resolution
        assert resolve_event_family(spec) == "RR_ONLY"
        
        # Verify inventory
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Unexpected errors: {inv.errors}"
        
        # Verify counts
        expected_rr = calculate_rr_only_matches(team_count)
        assert inv.wf_matches == 0
        assert inv.bracket_matches == 0
        assert inv.rr_matches == expected_rr
        assert inv.total_matches == expected_rr

    @pytest.mark.parametrize("team_count", sorted(ALLOWED_TEAM_COUNTS["WF_TO_POOLS_DYNAMIC"]))
    def test_wf_to_pools_dynamic_inventory(self, team_count: int):
        """WF_TO_POOLS_DYNAMIC events produce correct inventory with no errors."""
        spec = make_spec_for_team_count(team_count, "WF_TO_POOLS_DYNAMIC")
        
        # Verify family resolution
        assert resolve_event_family(spec) == "WF_TO_POOLS_DYNAMIC"
        
        # Verify inventory
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Unexpected errors for {team_count} teams: {inv.errors}"
        
        # Verify counts using rules module
        wf_rounds = required_wf_rounds("WF_TO_POOLS_DYNAMIC", team_count)
        expected_wf = calculate_wf_matches(team_count, wf_rounds)
        expected_rr = calculate_rr_matches_for_pools(team_count)
        
        assert inv.wf_matches == expected_wf, f"WF mismatch for {team_count}: {inv.wf_matches} != {expected_wf}"
        assert inv.bracket_matches == 0, f"Bracket should be 0 for pools-only"
        assert inv.rr_matches == expected_rr, f"RR mismatch for {team_count}: {inv.rr_matches} != {expected_rr}"
        assert inv.total_matches == expected_wf + expected_rr

    @pytest.mark.parametrize("team_count", sorted(ALLOWED_TEAM_COUNTS["WF_TO_BRACKETS_8"]))
    def test_wf_to_brackets_8_inventory(self, team_count: int):
        """WF_TO_BRACKETS_8 events produce correct inventory with no errors."""
        spec = make_spec_for_team_count(team_count, "WF_TO_BRACKETS_8")
        
        # Verify family resolution
        assert resolve_event_family(spec) == "WF_TO_BRACKETS_8"
        
        # Verify inventory
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Unexpected errors for {team_count} teams: {inv.errors}"
        
        # Verify WF count using rules
        wf_rounds = required_wf_rounds("WF_TO_BRACKETS_8", team_count)
        expected_wf = calculate_wf_matches(team_count, wf_rounds)
        
        assert inv.wf_matches == expected_wf
        assert inv.bracket_matches > 0, "Brackets family should have bracket matches"
        assert inv.rr_matches == 0, "Brackets family should have no RR"


class TestPhase1RejectsUnsupported:
    """Verify unsupported team counts produce errors."""

    @pytest.mark.parametrize("team_count", [14, 18, 22, 26, 30])
    def test_phase2_team_counts_rejected(self, team_count: int):
        """Phase 2 team counts should error when using WF_TO_POOLS_DYNAMIC."""
        spec = make_spec_for_team_count(team_count, "WF_TO_POOLS_DYNAMIC")
        inv = compute_inventory(spec)
        assert inv.has_errors(), f"Expected error for {team_count} teams"
        assert any("WF_TO_POOLS_DYNAMIC supports" in e for e in inv.errors)

    def test_all_phase1_counts_covered(self):
        """Verify all Phase 1 team counts are in exactly one family."""
        all_counts = set()
        for counts in ALLOWED_TEAM_COUNTS.values():
            for c in counts:
                assert c not in all_counts, f"Team count {c} is in multiple families"
                all_counts.add(c)
        
        assert all_counts == set(PHASE1_SUPPORTED_TEAM_COUNTS)
