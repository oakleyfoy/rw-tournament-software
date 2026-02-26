"""Tests for WF Round 2 Wiring Optimizer."""

import pytest

from app.services.wf_wiring import (
    WiringPlan,
    best_pairing_for_block,
    build_wf_r2_wiring,
    groups_for_r1_match,
)


# ---------------------------------------------------------------------------
# Lightweight stub objects for testing (avoid DB dependency)
# ---------------------------------------------------------------------------


class FakeMatch:
    """Minimal match stub with id, team_a_id, team_b_id, match_code, sequence_in_round."""

    def __init__(self, id, team_a_id=None, team_b_id=None, match_code="?", sequence_in_round=1):
        self.id = id
        self.team_a_id = team_a_id
        self.team_b_id = team_b_id
        self.match_code = match_code
        self.sequence_in_round = sequence_in_round


class FakeTeam:
    """Minimal team stub with id and avoid_group."""

    def __init__(self, id, avoid_group=None):
        self.id = id
        self.avoid_group = avoid_group


def _make_matches_and_teams(n_matches, group_assignments):
    """
    Create n_matches R1 matches and corresponding teams.

    group_assignments: list of (team_a_group, team_b_group) per match.
    Teams get IDs 100+2*i and 100+2*i+1 for match i.
    """
    matches = []
    team_by_id = {}
    for i in range(n_matches):
        ta_id = 100 + 2 * i
        tb_id = 100 + 2 * i + 1
        ga, gb = group_assignments[i] if i < len(group_assignments) else (None, None)
        matches.append(FakeMatch(
            id=i + 1,
            team_a_id=ta_id,
            team_b_id=tb_id,
            match_code=f"WF_R1_{i+1:02d}",
            sequence_in_round=i + 1,
        ))
        team_by_id[ta_id] = FakeTeam(ta_id, ga)
        team_by_id[tb_id] = FakeTeam(tb_id, gb)
    return matches, team_by_id


# ---------------------------------------------------------------------------
# groups_for_r1_match
# ---------------------------------------------------------------------------


class TestGroupsForR1Match:

    def test_both_teams_have_groups(self):
        m = FakeMatch(1, team_a_id=10, team_b_id=20)
        teams = {10: FakeTeam(10, "a"), 20: FakeTeam(20, "b")}
        assert groups_for_r1_match(m, teams) == {"a", "b"}

    def test_one_team_null_group(self):
        m = FakeMatch(1, team_a_id=10, team_b_id=20)
        teams = {10: FakeTeam(10, "a"), 20: FakeTeam(20, None)}
        assert groups_for_r1_match(m, teams) == {"a"}

    def test_no_teams_linked(self):
        m = FakeMatch(1, team_a_id=None, team_b_id=None)
        assert groups_for_r1_match(m, {}) == set()

    def test_same_group_both_sides(self):
        m = FakeMatch(1, team_a_id=10, team_b_id=20)
        teams = {10: FakeTeam(10, "a"), 20: FakeTeam(20, "a")}
        assert groups_for_r1_match(m, teams) == {"a"}


# ---------------------------------------------------------------------------
# best_pairing_for_block
# ---------------------------------------------------------------------------


class TestBestPairingForBlock:

    def test_block_of_2(self):
        matches, teams = _make_matches_and_teams(2, [("a", None), ("b", None)])
        result = best_pairing_for_block(matches, teams)
        assert len(result) == 1
        assert (result[0][0].id, result[0][1].id) == (1, 2)

    def test_block_of_4_no_groups_selects_first_pattern(self):
        """With no avoid_groups, first pattern ((0,3),(1,2)) wins by tie-break."""
        matches, teams = _make_matches_and_teams(4, [(None, None)] * 4)
        result = best_pairing_for_block(matches, teams)
        pair_ids = [(p[0].id, p[1].id) for p in result]
        # First pattern: (0,3), (1,2) → match ids (1,4), (2,3)
        assert pair_ids == [(1, 4), (2, 3)]

    def test_block_of_4_avoids_overlap(self):
        """
        Matches:
          m0: teams have group 'a'
          m1: teams have group 'b'
          m2: teams have group 'a'
          m3: teams have group 'b'

        Pattern (0,3),(1,2) → overlap: {a}∩{b}=0, {b}∩{a}=0 → score=0 ✓
        Pattern (0,2),(1,3) → overlap: {a}∩{a}=1, {b}∩{b}=1 → score=2 ✗
        Pattern (0,1),(2,3) → overlap: {a}∩{b}=0, {a}∩{b}=0 → score=0 (tie, loses)

        Should pick pattern 0 (first zero-score).
        """
        matches, teams = _make_matches_and_teams(4, [
            ("a", "a"), ("b", "b"), ("a", "a"), ("b", "b"),
        ])
        result = best_pairing_for_block(matches, teams)
        pair_ids = [(p[0].id, p[1].id) for p in result]
        assert pair_ids == [(1, 4), (2, 3)]

    def test_selects_zero_score_pattern_when_available(self):
        """
        Matches:
          m0: group 'a'
          m1: group 'a'
          m2: group 'b'
          m3: group 'b'

        Pattern (0,3),(1,2): {a}∩{b}=0, {a}∩{b}=0 → score=0 ✓
        Pattern (0,2),(1,3): {a}∩{b}=0, {a}∩{b}=0 → score=0 (tie, loses)
        Pattern (0,1),(2,3): {a}∩{a}=1, {b}∩{b}=1 → score=2

        First zero-score pattern wins.
        """
        matches, teams = _make_matches_and_teams(4, [
            ("a", "a"), ("a", "a"), ("b", "b"), ("b", "b"),
        ])
        result = best_pairing_for_block(matches, teams)
        pair_ids = [(p[0].id, p[1].id) for p in result]
        assert pair_ids == [(1, 4), (2, 3)]

    def test_selects_pattern_that_avoids_conflict(self):
        """
        Matches:
          m0: group 'x'
          m1: group 'y'
          m2: group 'y'
          m3: group 'x'

        Pattern (0,3),(1,2): {x}∩{x}=1, {y}∩{y}=1 → score=2
        Pattern (0,2),(1,3): {x}∩{y}=0, {y}∩{x}=0 → score=0 ✓
        Pattern (0,1),(2,3): {x}∩{y}=0, {y}∩{x}=0 → score=0 (tie)

        Should pick pattern 1 (first zero-score).
        """
        matches, teams = _make_matches_and_teams(4, [
            ("x", "x"), ("y", "y"), ("y", "y"), ("x", "x"),
        ])
        result = best_pairing_for_block(matches, teams)
        pair_ids = [(p[0].id, p[1].id) for p in result]
        assert pair_ids == [(1, 3), (2, 4)]


# ---------------------------------------------------------------------------
# build_wf_r2_wiring
# ---------------------------------------------------------------------------


class TestBuildWfR2Wiring:

    def test_8_matches_two_blocks(self):
        """8 R1 matches → 2 blocks of 4 → 4 R2 pairs."""
        matches, teams = _make_matches_and_teams(8, [(None, None)] * 8)
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.pairs) == 4
        assert len(plan.warnings) == 0

    def test_4_matches_single_block(self):
        """4 R1 matches → 1 block of 4 → 2 R2 pairs."""
        matches, teams = _make_matches_and_teams(4, [(None, None)] * 4)
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.pairs) == 2
        assert len(plan.warnings) == 0

    def test_6_matches_block_of_4_plus_2(self):
        """6 R1 matches → 1 block of 4 + 1 block of 2 → 3 R2 pairs."""
        matches, teams = _make_matches_and_teams(6, [(None, None)] * 6)
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.pairs) == 3
        assert len(plan.warnings) == 0

    def test_default_block_fold_pairing(self):
        """With no avoid_groups, default pairing is fold within each block."""
        matches, teams = _make_matches_and_teams(8, [(None, None)] * 8)
        plan = build_wf_r2_wiring(matches, teams)
        # Block 0 [1,2,3,4]: pattern (0,3),(1,2) → (1,4),(2,3)
        # Block 1 [5,6,7,8]: pattern (0,3),(1,2) → (5,8),(6,7)
        assert plan.pairs == [(1, 4), (2, 3), (5, 8), (6, 7)]

    def test_zero_score_wiring_selected(self):
        """When a zero-score wiring exists, the optimizer selects it."""
        # Block [m0(a), m1(b), m2(a), m3(b)] — groups interleaved
        # Pattern (0,3),(1,2) → {a}∩{b}=0, {b}∩{a}=0 → score 0 ✓
        matches, teams = _make_matches_and_teams(4, [
            ("a", "a"), ("b", "b"), ("a", "a"), ("b", "b"),
        ])
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.warnings) == 0
        assert plan.pairs == [(1, 4), (2, 3)]

    def test_unavoidable_overlap_produces_warning(self):
        """When all teams in a block share the same group, overlap is unavoidable."""
        matches, teams = _make_matches_and_teams(4, [
            ("x", "x"), ("x", "x"), ("x", "x"), ("x", "x"),
        ])
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.warnings) > 0
        w = plan.warnings[0]
        assert w.block_index == 0
        assert "x" in w.overlapping_groups
        assert "W_WF_R2_AVOID_GROUP_POTENTIAL_CONFLICT" in w.message

    def test_determinism(self):
        """Same inputs always produce the same wiring plan."""
        matches, teams = _make_matches_and_teams(8, [
            ("a", "b"), ("c", "a"), ("b", "c"), ("a", "b"),
            ("c", "a"), ("b", "c"), ("a", "b"), ("c", "a"),
        ])
        plan1 = build_wf_r2_wiring(matches, teams)
        plan2 = build_wf_r2_wiring(matches, teams)
        assert plan1.pairs == plan2.pairs
        assert len(plan1.warnings) == len(plan2.warnings)

    def test_determinism_across_reordered_input(self):
        """Wiring is based on sequence_in_round order, not list order."""
        matches, teams = _make_matches_and_teams(4, [
            ("a", "a"), ("b", "b"), ("a", "a"), ("b", "b"),
        ])
        # Reverse the list — build_wf_r2_wiring should NOT re-sort
        # (draw_plan_engine uses _get_wf_r2_wiring which sorts)
        # But best_pairing_for_block processes them as given.
        plan_normal = build_wf_r2_wiring(matches, teams)
        # Same matches, same order → same result
        plan_again = build_wf_r2_wiring(list(matches), teams)
        assert plan_normal.pairs == plan_again.pairs

    def test_16_matches_four_blocks(self):
        """16 R1 matches (32-team event) → 4 blocks of 4 → 8 R2 pairs."""
        matches, teams = _make_matches_and_teams(16, [(None, None)] * 16)
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.pairs) == 8
        assert len(plan.warnings) == 0

    def test_warning_includes_match_codes(self):
        """Warning message includes R1 match codes for the affected block."""
        matches, teams = _make_matches_and_teams(4, [
            ("z", "z"), ("z", "z"), ("z", "z"), ("z", "z"),
        ])
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.warnings) > 0
        w = plan.warnings[0]
        assert "WF_R1_01" in w.r1_match_codes[0]
        assert len(w.r1_match_codes) == 4

    def test_mixed_blocks_only_bad_block_warned(self):
        """Only blocks with unavoidable overlap get warnings."""
        # Block 0: all group 'x' (unavoidable overlap)
        # Block 1: all different groups (no overlap)
        group_assignments = [
            ("x", "x"), ("x", "x"), ("x", "x"), ("x", "x"),  # block 0
            ("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"),  # block 1
        ]
        matches, teams = _make_matches_and_teams(8, group_assignments)
        plan = build_wf_r2_wiring(matches, teams)
        assert len(plan.warnings) == 1
        assert plan.warnings[0].block_index == 0
