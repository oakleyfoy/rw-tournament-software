"""
Tests for WF Round 1 pairing — half-split matchups in bracket-fold order,
with avoid-group conflict resolution.
"""

from app.services.wf_pairing import (
    PairingConflict,
    PairingResult,
    TeamSeed,
    bracket_fold_positions,
    build_wf_r1_pairings,
    _groups_conflict,
)


def _make_teams(
    n: int,
    groups: dict[int, str] | None = None,
    names: dict[int, str] | None = None,
    display_names: dict[int, str] | None = None,
) -> list[TeamSeed]:
    """Helper: create n teams with seeds 1..n, optional avoid_group/name/display_name maps."""
    groups = groups or {}
    names = names or {}
    display_names = display_names or {}
    return [
        TeamSeed(
            seed=s,
            team_id=100 + s,
            avoid_group=groups.get(s),
            name=names.get(s),
            display_name=display_names.get(s),
        )
        for s in range(1, n + 1)
    ]


class TestBracketFoldPositions:
    """Verify the bracket fold ordering function."""

    def test_2_entries(self):
        assert bracket_fold_positions(2) == [1, 2]

    def test_4_entries(self):
        assert bracket_fold_positions(4) == [1, 4, 2, 3]

    def test_8_entries(self):
        assert bracket_fold_positions(8) == [1, 8, 4, 5, 3, 6, 2, 7]

    def test_16_entries(self):
        expected = [1, 16, 8, 9, 4, 13, 5, 12, 3, 14, 6, 11, 7, 10, 2, 15]
        assert bracket_fold_positions(16) == expected

    def test_all_seeds_present(self):
        for n in (2, 4, 8, 16):
            positions = bracket_fold_positions(n)
            assert sorted(positions) == list(range(1, n + 1))

    def test_non_power_of_two_falls_back_to_seed_order(self):
        # Used by 12-team WF flows where top-half size is 6.
        assert bracket_fold_positions(6) == [1, 2, 3, 4, 5, 6]


class TestHalfSplitMatchups:
    """Matchups must be seed i vs seed (i + n/2), ordered by bracket fold."""

    def test_8_teams_pairs(self):
        teams = _make_teams(8)
        result = build_wf_r1_pairings(teams, 8)
        # fold_order for 4 top seeds: [1, 4, 2, 3]
        # half-split: 1v5, 4v8, 2v6, 3v7
        expected = [(1, 5), (4, 8), (2, 6), (3, 7)]
        assert result.pairs == expected

    def test_16_teams_pairs(self):
        teams = _make_teams(16)
        result = build_wf_r1_pairings(teams, 16)
        # fold_order for 8 top seeds: [1, 8, 4, 5, 3, 6, 2, 7]
        # half-split: 1v9, 8v16, 4v12, 5v13, 3v11, 6v14, 2v10, 7v15
        expected = [(1, 9), (8, 16), (4, 12), (5, 13), (3, 11), (6, 14), (2, 10), (7, 15)]
        assert result.pairs == expected

    def test_32_teams_first_and_last_pair(self):
        teams = _make_teams(32)
        result = build_wf_r1_pairings(teams, 32)
        assert len(result.pairs) == 16
        assert result.pairs[0] == (1, 17)
        assert result.pairs[-1] == (15, 31)

    def test_all_seeds_appear_once(self):
        for n in (8, 16, 32):
            teams = _make_teams(n)
            result = build_wf_r1_pairings(teams, n)
            all_seeds = [s for p in result.pairs for s in p]
            assert sorted(all_seeds) == list(range(1, n + 1))

    def test_12_teams_pairs(self):
        teams = _make_teams(12)
        result = build_wf_r1_pairings(teams, 12)
        expected = [(1, 7), (2, 8), (3, 9), (4, 10), (5, 11), (6, 12)]
        assert result.pairs == expected


class TestNoConflicts:
    """When avoid groups don't collide in half-split pairs, zero conflicts."""

    def test_no_groups_at_all(self):
        teams = _make_teams(16)
        result = build_wf_r1_pairings(teams, 16)
        assert len(result.conflicts) == 0

    def test_groups_dont_collide_across_halves(self):
        # Top-half groups differ from their half-split opponents
        groups = {1: "a", 9: "b", 2: "c", 10: "d"}
        teams = _make_teams(16, groups)
        result = build_wf_r1_pairings(teams, 16)
        assert len(result.conflicts) == 0


class TestConflictsReported:
    """Conflicts are reported when half-split opponents share avoid_group
    and cannot be resolved by swapping within the bracket quarter."""

    def test_single_conflict_resolved_by_swap(self):
        # Seed 1 and seed 5 both in group 'a' — half-split opponents.
        # Quarter [(1,5), (4,8)]: swap → (1,8), (4,5) — no conflict.
        groups = {1: "a", 5: "a"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 0  # resolved by swap

    def test_multiple_conflicts_resolved_by_swap(self):
        # Seeds 1v5 both 'a', seeds 2v6 both 'b'
        # Quarter 1: [(1,5), (4,8)] → swap resolves 1v5
        # Quarter 2: [(2,6), (3,7)] → swap resolves 2v6
        groups = {1: "a", 5: "a", 2: "b", 6: "b"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 0  # both resolved by swaps

    def test_all_same_group(self):
        # Every team in group 'x' — swaps can't help, all conflicts remain
        groups = {s: "x" for s in range(1, 9)}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.pairs) == 4
        assert len(result.conflicts) == 4

    def test_conflict_fields(self):
        # All teams in group 'z' — unavoidable conflicts
        groups = {s: "z" for s in range(1, 9)}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        for c in result.conflicts:
            assert c.seed_a > 0
            assert c.group == "z"
            assert "conflict" in c.reason.lower()
            assert str(c.seed_a) in c.reason
            assert str(c.seed_b) in c.reason

    def test_no_conflict_when_groups_in_same_half(self):
        # Seeds 1 and 2 share group 'a' but they're both in top half,
        # so they won't be paired against each other in R1
        groups = {1: "a", 2: "a"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 0


class TestDeterminism:
    """Same input must produce exactly the same output every time."""

    def test_deterministic_no_groups(self):
        teams = _make_teams(16)
        r1 = build_wf_r1_pairings(teams, 16)
        r2 = build_wf_r1_pairings(teams, 16)
        r3 = build_wf_r1_pairings(teams, 16)
        assert r1.pairs == r2.pairs == r3.pairs
        assert r1.team_id_pairs == r2.team_id_pairs == r3.team_id_pairs

    def test_deterministic_with_conflicts(self):
        groups = {s: "x" for s in range(1, 9)}
        teams = _make_teams(8, groups)
        results = [build_wf_r1_pairings(teams, 8) for _ in range(5)]
        for r in results[1:]:
            assert r.pairs == results[0].pairs
            assert len(r.conflicts) == len(results[0].conflicts)

    def test_shuffled_input_order_same_output(self):
        import random
        teams = _make_teams(16)
        baseline = build_wf_r1_pairings(teams, 16)

        shuffled = list(teams)
        random.seed(42)
        random.shuffle(shuffled)
        result = build_wf_r1_pairings(shuffled, 16)

        assert result.pairs == baseline.pairs
        assert result.team_id_pairs == baseline.team_id_pairs


class TestTeamIdPairs:
    """Verify team_id_pairs matches the seed-based pairs."""

    def test_team_ids_correspond_to_seeds(self):
        teams = _make_teams(8)
        result = build_wf_r1_pairings(teams, 8)

        by_seed = {t.seed: t.team_id for t in teams}
        for (sa, sb), (ta, tb) in zip(result.pairs, result.team_id_pairs):
            assert ta == by_seed[sa]
            assert tb == by_seed[sb]


class TestEdgeCases:

    def test_two_teams(self):
        teams = _make_teams(2, {1: "a", 2: "a"})
        result = build_wf_r1_pairings(teams, 2)
        assert result.pairs == [(1, 2)]
        assert len(result.conflicts) == 1

    def test_two_teams_no_conflict(self):
        teams = _make_teams(2)
        result = build_wf_r1_pairings(teams, 2)
        assert result.pairs == [(1, 2)]
        assert len(result.conflicts) == 0

    def test_large_field_32_teams(self):
        teams = _make_teams(32)
        result = build_wf_r1_pairings(teams, 32)
        assert len(result.pairs) == 16
        assert len(result.conflicts) == 0
        all_seeds = [s for p in result.pairs for s in p]
        assert sorted(all_seeds) == list(range(1, 33))


class TestSwapResolution:
    """Verify that avoid-group conflicts are resolved by swapping
    bottom-half teams within the same bracket quarter."""

    def test_swap_resolves_conflict(self):
        # 8 teams, seed 1 & 5 both group 'a' (half-split opponents).
        # Quarter: [(1,5), (4,8)]. Swap → (1,8), (4,5). Conflict gone.
        groups = {1: "a", 5: "a"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 0
        # Verify the swap actually happened: seed 1 is NOT paired with seed 5
        for sa, sb in result.pairs:
            if sa == 1 or sb == 1:
                assert sb != 5 and sa != 5

    def test_swap_does_not_introduce_new_conflicts(self):
        # Seed 1 & 5 both 'a'. Seed 4 has group 'b', seed 8 has group 'c'.
        # After swap: (1,8) → groups 'a' vs 'c' = OK.
        #             (4,5) → groups 'b' vs 'a' = OK.
        groups = {1: "a", 5: "a", 4: "b", 8: "c"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 0

    def test_swap_rejected_if_creates_new_conflict(self):
        # Seed 1 & 5 both 'a'. Seed 4 & 8 both 'a' too.
        # Swap (1,5)↔(4,8) → (1,8) still group 'a' vs 'a'. Can't resolve.
        # Both pairs remain conflicting.
        groups = {1: "a", 5: "a", 4: "a", 8: "a"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        # First quarter has 2 unavoidable conflicts
        quarter_conflicts = [c for c in result.conflicts
                             if c.seed_a in (1, 4) or c.seed_b in (5, 8)]
        assert len(quarter_conflicts) >= 2

    def test_all_seeds_present_after_swap(self):
        # After any swaps, every seed must still appear exactly once
        groups = {1: "a", 5: "a", 2: "b", 6: "b"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        all_seeds = [s for p in result.pairs for s in p]
        assert sorted(all_seeds) == list(range(1, 9))

    def test_unavoidable_conflicts_still_reported(self):
        # 4 teams, seeds 1&3 both 'a', seeds 2&4 both 'a'.
        # Only one quarter of 2 matches — both conflicting, swap can't help.
        groups = {1: "a", 3: "a", 2: "a", 4: "a"}
        teams = _make_teams(4, groups)
        result = build_wf_r1_pairings(teams, 4)
        assert len(result.conflicts) == 2
        for c in result.conflicts:
            assert c.group == "a"
            assert "unavoidable" in c.reason.lower()

    def test_swap_in_16_team_bracket(self):
        # 16 teams, conflict: seed 1 & 9 both 'a' (half-split opponents).
        # They're in the same quarter so swap can resolve it.
        groups = {1: "a", 9: "a"}
        teams = _make_teams(16, groups)
        result = build_wf_r1_pairings(teams, 16)
        assert len(result.conflicts) == 0
        # Verify seed 1 is no longer paired with seed 9
        for sa, sb in result.pairs:
            if sa == 1 or sb == 1:
                assert sb != 9 and sa != 9


class TestMultiGroupSupport:
    """Verify multi-group avoid strings like 'A,B' work correctly."""

    def test_groups_conflict_helper(self):
        assert _groups_conflict("a", "a") == "a"
        assert _groups_conflict("a", "b") is None
        assert _groups_conflict("a,b", "b,c") == "b"
        assert _groups_conflict("a,b", "c,d") is None
        assert _groups_conflict(None, "a") is None
        assert _groups_conflict("a", None) is None
        assert _groups_conflict(None, None) is None

    def test_multi_group_conflict_detected(self):
        # Seed 1 has 'a,b', seed 5 has 'b,c' — shared group 'b'
        groups = {1: "a,b", 5: "b,c"}
        teams = _make_teams(8, groups)
        # Without swap resolution this would be a conflict.
        # With swap resolution it should be resolved.
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 0

    def test_multi_group_no_overlap(self):
        # Seed 1 has 'a,b', seed 5 has 'c,d' — no overlap
        groups = {1: "a,b", 5: "c,d"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 0

    def test_multi_group_unavoidable(self):
        # All teams share group 'x' via multi-group strings
        groups = {
            1: "x,a", 2: "x,b", 3: "x,c", 4: "x,d",
            5: "x,e", 6: "x,f", 7: "x,g", 8: "x,h",
        }
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 4
        for c in result.conflicts:
            assert c.group == "x"


class TestNamePairsAndDisplayNamePairs:
    """Verify name_pairs and display_name_pairs are populated in PairingResult."""

    def test_name_pairs_populated(self):
        names = {s: f"Team {s} Full Name" for s in range(1, 9)}
        teams = _make_teams(8, names=names)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.name_pairs) == 4
        for name_a, name_b in result.name_pairs:
            assert name_a != ""
            assert name_b != ""
            assert "Full Name" in name_a
            assert "Full Name" in name_b

    def test_display_name_pairs_populated(self):
        display_names = {1: "Short 1", 2: "Short 2"}
        teams = _make_teams(8, display_names=display_names)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.display_name_pairs) == 4
        # Seeds 1 and 2 have display_names; others are None
        found_short = False
        for dn_a, dn_b in result.display_name_pairs:
            if dn_a == "Short 1" or dn_b == "Short 1":
                found_short = True
            if dn_a == "Short 2" or dn_b == "Short 2":
                found_short = True
        assert found_short

    def test_name_pairs_empty_when_no_names(self):
        teams = _make_teams(8)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.name_pairs) == 4
        for name_a, name_b in result.name_pairs:
            assert name_a == ""
            assert name_b == ""

    def test_display_name_pairs_none_when_not_set(self):
        teams = _make_teams(8)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.display_name_pairs) == 4
        for dn_a, dn_b in result.display_name_pairs:
            assert dn_a is None
            assert dn_b is None

    def test_name_pairs_follow_seed_pairs(self):
        """name_pairs should correspond to the same teams as seed_pairs."""
        names = {s: f"Name_{s}" for s in range(1, 9)}
        teams = _make_teams(8, names=names)
        result = build_wf_r1_pairings(teams, 8)
        for (seed_a, seed_b), (name_a, name_b) in zip(result.pairs, result.name_pairs):
            assert name_a == f"Name_{seed_a}"
            assert name_b == f"Name_{seed_b}"
