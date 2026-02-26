"""
Tests for WF Round 1 pairing — half-split matchups in bracket-fold order.
"""

from app.services.wf_pairing import (
    PairingResult,
    TeamSeed,
    bracket_fold_positions,
    build_wf_r1_pairings,
)


def _make_teams(n: int, groups: dict[int, str] | None = None) -> list[TeamSeed]:
    """Helper: create n teams with seeds 1..n, optional avoid_group map."""
    groups = groups or {}
    return [
        TeamSeed(seed=s, team_id=100 + s, avoid_group=groups.get(s))
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
    """Conflicts are reported when half-split opponents share avoid_group."""

    def test_single_conflict(self):
        # Seed 1 and seed 5 both in group 'a' — they're half-split opponents
        groups = {1: "a", 5: "a"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 1
        c = result.conflicts[0]
        assert c.seed_a == 1
        assert c.seed_b == 5
        assert c.group == "a"

    def test_multiple_conflicts(self):
        # Seeds 1v5 both 'a', seeds 2v6 both 'b'
        groups = {1: "a", 5: "a", 2: "b", 6: "b"}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.conflicts) == 2

    def test_all_same_group(self):
        groups = {s: "x" for s in range(1, 9)}
        teams = _make_teams(8, groups)
        result = build_wf_r1_pairings(teams, 8)
        assert len(result.pairs) == 4
        assert len(result.conflicts) == 4

    def test_conflict_fields(self):
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
