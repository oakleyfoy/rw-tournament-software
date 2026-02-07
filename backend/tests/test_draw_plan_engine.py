"""
Tests for Draw Plan Engine — the authoritative source of match inventory and generation.
"""

import json
from datetime import date, time

import pytest
from sqlmodel import select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.services.draw_plan_engine import (
    DrawPlanSpec,
    InventoryCounts,
    BRACKET_MATCHES_G4,
    BRACKET_MATCHES_G5,
    bracket_inventory,
    bracket_matches_for_guarantee,
    compute_inventory,
    normalize_template_key,
    resolve_event_family,
    validate_spec,
)
from app.services.draw_plan_rules import rr_pairings_by_round, rr_round_count
from app.utils.wf_seeding import pool_assignment_contiguous, wf_rank_key, WFTeamResult


# -----------------------------------------------------------------------------
# Helper to build specs quickly
# -----------------------------------------------------------------------------

def make_spec(
    template_type: str,
    team_count: int,
    wf_rounds: int = 0,
    guarantee: int = 5,
    event_id: int = 1,
    event_name: str = "Test Event",
) -> DrawPlanSpec:
    """Build a DrawPlanSpec for testing."""
    return DrawPlanSpec(
        event_id=event_id,
        event_name=event_name,
        division="Mixed",
        team_count=team_count,
        template_type=template_type,
        template_key=normalize_template_key(template_type),
        guarantee=guarantee,
        waterfall_rounds=wf_rounds,
        waterfall_minutes=60,
        standard_minutes=105,
    )


# -----------------------------------------------------------------------------
# normalize_template_key tests
# -----------------------------------------------------------------------------

class TestNormalizeTemplateKey:
    def test_uppercase(self):
        assert normalize_template_key("wf_to_pools_4") == "WF_TO_POOLS_4"

    def test_strip_whitespace(self):
        assert normalize_template_key("  RR_ONLY  ") == "RR_ONLY"

    def test_spaces_to_underscores(self):
        assert normalize_template_key("WF TO POOLS 4") == "WF_TO_POOLS_4"

    def test_none_returns_empty(self):
        assert normalize_template_key(None) == ""


# -----------------------------------------------------------------------------
# resolve_event_family tests
# -----------------------------------------------------------------------------

class TestResolveEventFamily:
    def test_rr_only(self):
        spec = make_spec("RR_ONLY", 8)
        assert resolve_event_family(spec) == "RR_ONLY"

    def test_wf_to_pools_4(self):
        spec = make_spec("WF_TO_POOLS_4", 16, wf_rounds=2)
        assert resolve_event_family(spec) == "WF_TO_POOLS_4"

    def test_wf_to_brackets_8(self):
        spec = make_spec("WF_TO_BRACKETS_8", 32, wf_rounds=2)
        assert resolve_event_family(spec) == "WF_TO_BRACKETS_8"

    def test_wf2_to_4brackets_8_alias(self):
        spec = make_spec("WF2_TO_4BRACKETS_8", 32, wf_rounds=2)
        assert resolve_event_family(spec) == "WF_TO_BRACKETS_8"

    def test_canonical_32_with_8_teams(self):
        # Legacy CANONICAL_32 with 8 teams maps to WF_TO_BRACKETS_8
        spec = make_spec("CANONICAL_32", 8, wf_rounds=2)
        assert resolve_event_family(spec) == "WF_TO_BRACKETS_8"

    def test_canonical_32_with_32_teams_is_unsupported(self):
        # CANONICAL_32 with 32 teams is NOT supported - use WF_TO_BRACKETS_8 instead
        spec = make_spec("CANONICAL_32", 32, wf_rounds=2)
        assert resolve_event_family(spec) == "UNSUPPORTED"

    def test_unsupported_template(self):
        spec = make_spec("UNKNOWN_TEMPLATE", 16)
        assert resolve_event_family(spec) == "UNSUPPORTED"


# -----------------------------------------------------------------------------
# validate_spec tests
# -----------------------------------------------------------------------------

class TestValidateSpec:
    def test_valid_spec(self):
        spec = make_spec("RR_ONLY", 8)
        errors = validate_spec(spec)
        assert errors == []

    def test_team_count_too_small(self):
        spec = make_spec("RR_ONLY", 1)
        errors = validate_spec(spec)
        assert any("team_count must be at least 2" in e for e in errors)

    def test_team_count_odd(self):
        spec = make_spec("RR_ONLY", 7)
        errors = validate_spec(spec)
        assert any("team_count must be even" in e for e in errors)

    def test_invalid_guarantee(self):
        spec = make_spec("RR_ONLY", 8, guarantee=3)
        errors = validate_spec(spec)
        assert any("guarantee must be 4 or 5" in e for e in errors)

    def test_negative_wf_rounds(self):
        spec = make_spec("RR_ONLY", 8, wf_rounds=-1)
        errors = validate_spec(spec)
        assert any("waterfall_rounds cannot be negative" in e for e in errors)


# -----------------------------------------------------------------------------
# RR round numbering (circle method)
# -----------------------------------------------------------------------------


class TestRRRoundNumbering:
    """RR pool match round_index must reflect actual RR rounds."""

    def test_pool_4_rounds_and_matches_per_round(self):
        """Pool of 4: rounds = {1,2,3}, 2 matches per round."""
        pairings = rr_pairings_by_round(4)
        assert len(pairings) == 6, f"Expected 6 matches, got {len(pairings)}"
        rounds = {r for r, _s, _a, _b in pairings}
        assert rounds == {1, 2, 3}, f"Expected rounds {{1,2,3}}, got {rounds}"
        from collections import Counter
        per_round = Counter(r for r, _s, _a, _b in pairings)
        assert per_round == {1: 2, 2: 2, 3: 2}, f"Expected 2 per round, got {dict(per_round)}"
        assert rr_round_count(4) == 3

    def test_pool_5_rounds_and_total_matches(self):
        """Pool of 5: rounds = {1..5}, total matches = 10 (5C2)."""
        pairings = rr_pairings_by_round(5)
        assert len(pairings) == 10, f"Expected 10 matches, got {len(pairings)}"
        rounds = {r for r, _s, _a, _b in pairings}
        assert rounds == {1, 2, 3, 4, 5}, f"Expected rounds {{1..5}}, got {rounds}"
        assert rr_round_count(5) == 5

    def test_pool_6_rounds_and_total_matches(self):
        """Pool of 6: rounds = {1..5}, total matches = 15 (6C2)."""
        pairings = rr_pairings_by_round(6)
        assert len(pairings) == 15, f"Expected 15 matches, got {len(pairings)}"
        rounds = {r for r, _s, _a, _b in pairings}
        assert rounds == {1, 2, 3, 4, 5}, f"Expected rounds {{1..5}}, got {rounds}"
        from collections import Counter
        per_round = Counter(r for r, _s, _a, _b in pairings)
        assert all(c == 3 for c in per_round.values()), f"Expected 3 per round, got {dict(per_round)}"
        assert rr_round_count(6) == 5

    def test_pool_4_exact_order_r1_1v4_2v3_r2_1v3_2v4_r3_1v2_3v4(self):
        """Pool 4 RR must use exact preset: R1: 1v4,2v3; R2: 1v3,2v4; R3: 1v2,3v4."""
        pairings = rr_pairings_by_round(4)
        expected = [
            (1, 1, 0, 3),  # R1: 1v4
            (1, 2, 1, 2),  # R1: 2v3
            (2, 1, 0, 2),  # R2: 1v3
            (2, 2, 1, 3),  # R2: 2v4
            (3, 1, 0, 1),  # R3: 1v2
            (3, 2, 2, 3),  # R3: 3v4
        ]
        assert pairings == expected, f"Got {pairings}"

    def test_wf_to_pools_4_pool_a_rr_matches_use_exact_pool4_order(
        self, session, client
    ):
        """WF_TO_POOLS_4 pool RR matches must have R1: 1v4,2v3; R2: 1v3,2v4; R3: 1v2,3v4."""
        from app.models.tournament_time_window import TournamentTimeWindow

        t = Tournament(
            name="Pool4 Order Test",
            location="Test",
            timezone="America/New_York",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            court_names=["Court 1"],
        )
        session.add(t)
        session.commit()
        session.refresh(t)
        day = TournamentDay(
            tournament_id=t.id,
            date=date(2026, 3, 1),
            is_active=True,
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
        )
        session.add(day)
        session.commit()
        tw = TournamentTimeWindow(
            tournament_id=t.id,
            day_date=date(2026, 3, 1),
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
            block_minutes=105,
        )
        session.add(tw)
        session.commit()
        version = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)
        event = Event(
            tournament_id=t.id,
            name="WF16",
            category="mixed",
            team_count=16,
            draw_status="final",
            draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_4", "wf_rounds": 2}),
            wf_block_minutes=60,
            standard_block_minutes=120,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        for i in range(16):
            session.add(Team(event_id=event.id, name=f"Seed {i+1}", seed=i + 1, rating=1000.0))
        session.commit()

        r = client.post(f"/api/tournaments/{t.id}/schedule/versions/{version.id}/matches/generate")
        assert r.status_code == 200, r.text

        pool_a_rr = session.exec(
            select(Match).where(
                Match.schedule_version_id == version.id,
                Match.event_id == event.id,
                Match.match_type == "RR",
                Match.match_code.like("%POOLA_RR%"),
            )
        ).all()
        pool_a_rr.sort(key=lambda m: (m.round_index, m.sequence_in_round))
        assert len(pool_a_rr) == 6
        expected_round_seq = [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)]
        for i, m in enumerate(pool_a_rr):
            exp_r, exp_s = expected_round_seq[i]
            assert m.round_index == exp_r and m.sequence_in_round == exp_s, (
                f"Match {i+1}: expected R{exp_r} seq{exp_s}, got R{m.round_index} seq{m.sequence_in_round}"
            )

    def test_rr_only_4_teams_generated_matches_have_rounds_1_2_3(
        self, session, client
    ):
        """RR_ONLY with 4 teams: generated matches have round_index in {1,2,3}, 2 per round."""
        from app.models.tournament_time_window import TournamentTimeWindow

        t = Tournament(
            name="RR Round Test",
            location="Test",
            timezone="America/New_York",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            court_names=["Court 1"],
        )
        session.add(t)
        session.commit()
        session.refresh(t)

        day = TournamentDay(
            tournament_id=t.id,
            date=date(2026, 3, 1),
            is_active=True,
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
        )
        session.add(day)
        session.commit()

        version = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)

        tw = TournamentTimeWindow(
            tournament_id=t.id,
            day_date=date(2026, 3, 1),
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
            block_minutes=120,
        )
        session.add(tw)
        session.commit()

        event = Event(
            tournament_id=t.id,
            name="Pool4",
            category="mixed",
            team_count=4,
            draw_status="final",
            draw_plan_json=json.dumps({"template_type": "RR_ONLY", "wf_rounds": 0}),
            wf_block_minutes=60,
            standard_block_minutes=120,
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        for i in range(4):
            session.add(Team(event_id=event.id, name=f"Team {i+1}", seed=i + 1, rating=1000.0))
        session.commit()

        r = client.post(
            f"/api/tournaments/{t.id}/schedule/versions/{version.id}/matches/generate"
        )
        assert r.status_code == 200, r.text

        matches = session.exec(
            select(Match).where(
                Match.schedule_version_id == version.id,
                Match.event_id == event.id,
                Match.match_type == "RR",
            )
        ).all()
        assert len(matches) == 6
        round_indices = [m.round_index for m in matches]
        assert set(round_indices) == {1, 2, 3}
        from collections import Counter
        per_round = Counter(round_indices)
        assert per_round == {1: 2, 2: 2, 3: 2}


# -----------------------------------------------------------------------------
# WF Round 1 pairing (half-split)
# -----------------------------------------------------------------------------


class TestWFRound1Pairing:
    """WF Round 1 must use half-split: A[i] vs B[i], A=1..n/2, B=n/2+1..n."""

    def test_wf_r1_8_teams_half_split(self, session, client):
        """8 teams: WF R1 matchups = (1,5), (2,6), (3,7), (4,8)."""
        from app.models.tournament_time_window import TournamentTimeWindow

        t = Tournament(
            name="WF R1 Test 8",
            location="Test",
            timezone="America/New_York",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            court_names=["Court 1"],
        )
        session.add(t)
        session.commit()
        session.refresh(t)
        day = TournamentDay(
            tournament_id=t.id,
            date=date(2026, 3, 1),
            is_active=True,
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
        )
        session.add(day)
        session.commit()
        tw = TournamentTimeWindow(
            tournament_id=t.id,
            day_date=date(2026, 3, 1),
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
            block_minutes=105,
        )
        session.add(tw)
        session.commit()
        version = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)
        event = Event(
            tournament_id=t.id,
            name="WF8",
            category="mixed",
            team_count=8,
            draw_status="final",
            draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_DYNAMIC", "wf_rounds": 1}),
            wf_block_minutes=60,
            standard_block_minutes=120,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        for i in range(8):
            session.add(Team(event_id=event.id, name=f"Seed {i+1}", seed=i + 1, rating=1000.0))
        session.commit()

        r = client.post(f"/api/tournaments/{t.id}/schedule/versions/{version.id}/matches/generate")
        assert r.status_code == 200, r.text

        wf_r1 = session.exec(
            select(Match).where(
                Match.schedule_version_id == version.id,
                Match.event_id == event.id,
                Match.match_type == "WF",
                Match.round_number == 1,
            )
        ).all()
        wf_r1.sort(key=lambda m: m.sequence_in_round)
        assert len(wf_r1) == 4

        def parse_seed(ph: str) -> int:
            return int(ph.replace("Seed ", "").strip())

        expected = [(1, 5), (2, 6), (3, 7), (4, 8)]
        for i, m in enumerate(wf_r1):
            a, b = parse_seed(m.placeholder_side_a), parse_seed(m.placeholder_side_b)
            pair = tuple(sorted([a, b]))
            exp = expected[i]
            assert pair == (min(exp), max(exp)), f"Match {i+1}: expected {exp}, got ({a},{b})"

    def test_wf_r1_16_teams_half_split(self, session, client):
        """16 teams: WF R1 matchups = (1,9), (2,10), ..., (8,16)."""
        from app.models.tournament_time_window import TournamentTimeWindow

        t = Tournament(
            name="WF R1 Test 16",
            location="Test",
            timezone="America/New_York",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            court_names=["Court 1"],
        )
        session.add(t)
        session.commit()
        session.refresh(t)
        day = TournamentDay(
            tournament_id=t.id,
            date=date(2026, 3, 1),
            is_active=True,
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
        )
        session.add(day)
        session.commit()
        tw = TournamentTimeWindow(
            tournament_id=t.id,
            day_date=date(2026, 3, 1),
            start_time=time(9, 0),
            end_time=time(18, 0),
            courts_available=2,
            block_minutes=105,
        )
        session.add(tw)
        session.commit()
        version = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)
        event = Event(
            tournament_id=t.id,
            name="WF16",
            category="mixed",
            team_count=16,
            draw_status="final",
            draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_4", "wf_rounds": 2}),
            wf_block_minutes=60,
            standard_block_minutes=120,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        for i in range(16):
            session.add(Team(event_id=event.id, name=f"Seed {i+1}", seed=i + 1, rating=1000.0))
        session.commit()

        r = client.post(f"/api/tournaments/{t.id}/schedule/versions/{version.id}/matches/generate")
        assert r.status_code == 200, r.text

        wf_r1 = session.exec(
            select(Match).where(
                Match.schedule_version_id == version.id,
                Match.event_id == event.id,
                Match.match_type == "WF",
                Match.round_number == 1,
            )
        ).all()
        wf_r1.sort(key=lambda m: m.sequence_in_round)
        assert len(wf_r1) == 8

        def parse_seed(ph: str) -> int:
            return int(ph.replace("Seed ", "").strip())

        expected = [(1, 9), (2, 10), (3, 11), (4, 12), (5, 13), (6, 14), (7, 15), (8, 16)]
        for i, m in enumerate(wf_r1):
            a, b = parse_seed(m.placeholder_side_a), parse_seed(m.placeholder_side_b)
            pair = tuple(sorted([a, b]))
            exp = expected[i]
            assert pair == (min(exp), max(exp)), f"Match {i+1}: expected {exp}, got ({a},{b})"


# -----------------------------------------------------------------------------
# Pool assignment and WF seeding (Step 6)
# -----------------------------------------------------------------------------


class TestPoolAssignmentContiguous:
    """Pool assignment must use contiguous seed blocks."""

    def test_8_teams_2_pools_seeds_1_4_in_a_5_8_in_b(self):
        """8 teams, 2 pools: Pool A = seeds 1-4, Pool B = seeds 5-8."""
        seeds = [101, 102, 103, 104, 105, 106, 107, 108]  # team IDs in rank order
        pools = pool_assignment_contiguous(seeds, num_pools=2, teams_per_pool=4)
        assert len(pools) == 2
        assert pools[0] == [101, 102, 103, 104]
        assert pools[1] == [105, 106, 107, 108]

    def test_12_teams_3_pools_contiguous_blocks(self):
        """12 teams, 3 pools: A=1-4, B=5-8, C=9-12."""
        seeds = list(range(1, 13))
        pools = pool_assignment_contiguous(seeds, num_pools=3, teams_per_pool=4)
        assert pools[0] == [1, 2, 3, 4]
        assert pools[1] == [5, 6, 7, 8]
        assert pools[2] == [9, 10, 11, 12]


class TestWFSeedingTiebreak:
    """WF ranking tiebreak must be deterministic."""

    def test_same_inputs_same_order(self):
        """Same WF results → same sort order."""
        results = [
            WFTeamResult(team_id=1, bucket_rank=1, wf_matches_won=1, wf_game_diff=2),
            WFTeamResult(team_id=2, bucket_rank=1, wf_matches_won=1, wf_game_diff=1),
        ]
        key1a = wf_rank_key(results[0], 100, 10)
        key1b = wf_rank_key(results[0], 100, 10)
        assert key1a == key1b

    def test_stable_hash_tie_breaks_consistently(self):
        """When all other fields equal, stable_hash determines order."""
        r1 = WFTeamResult(team_id=1, bucket_rank=0, wf_matches_won=0)
        r2 = WFTeamResult(team_id=2, bucket_rank=0, wf_matches_won=0)
        k1 = wf_rank_key(r1, 1, 1)
        k2 = wf_rank_key(r2, 1, 1)
        assert k1 != k2
        # Same team, same context → same key
        assert wf_rank_key(r1, 1, 1) == k1


# -----------------------------------------------------------------------------
# compute_inventory tests: RR_ONLY
# -----------------------------------------------------------------------------

class TestInventoryRROnly:
    def test_8_teams(self):
        spec = make_spec("RR_ONLY", 8)
        inv = compute_inventory(spec)
        assert inv.wf_matches == 0
        assert inv.bracket_matches == 0
        assert inv.rr_matches == 28  # 8 * 7 / 2
        assert inv.total_matches == 28
        assert not inv.has_errors()

    def test_4_teams(self):
        spec = make_spec("RR_ONLY", 4)
        inv = compute_inventory(spec)
        assert inv.rr_matches == 6  # 4 * 3 / 2
        assert inv.total_matches == 6

    def test_16_teams(self):
        spec = make_spec("RR_ONLY", 16)
        inv = compute_inventory(spec)
        assert inv.rr_matches == 120  # 16 * 15 / 2
        assert inv.total_matches == 120


# -----------------------------------------------------------------------------
# compute_inventory tests: WF_TO_POOLS_4
# -----------------------------------------------------------------------------

class TestInventoryWFToPools4:
    def test_valid_16_teams_2_rounds(self):
        spec = make_spec("WF_TO_POOLS_4", 16, wf_rounds=2)
        inv = compute_inventory(spec)
        assert inv.wf_matches == 16  # 8 * 2
        assert inv.bracket_matches == 0
        assert inv.rr_matches == 24  # 4 pools * 6
        assert inv.total_matches == 40
        assert not inv.has_errors()

    def test_invalid_team_count(self):
        spec = make_spec("WF_TO_POOLS_4", 8, wf_rounds=2)
        inv = compute_inventory(spec)
        assert inv.has_errors()
        assert any("team_count=16" in e for e in inv.errors)

    def test_invalid_wf_rounds(self):
        spec = make_spec("WF_TO_POOLS_4", 16, wf_rounds=1)
        inv = compute_inventory(spec)
        assert inv.has_errors()
        assert any("waterfall_rounds=2" in e for e in inv.errors)


# -----------------------------------------------------------------------------
# compute_inventory tests: WF_TO_BRACKETS_8
# -----------------------------------------------------------------------------

class TestInventoryWFToBrackets8:
    def test_32_teams_2_rounds_g5(self):
        """32 teams, 2 WF rounds, guarantee 5 → 4 brackets of 8."""
        spec = make_spec("WF2_TO_4BRACKETS_8", 32, wf_rounds=2, guarantee=5)
        inv = compute_inventory(spec)
        assert inv.wf_matches == 32  # 16 * 2
        assert inv.bracket_matches == 4 * BRACKET_MATCHES_G5  # 4 * 12 = 48
        assert inv.rr_matches == 0
        assert inv.total_matches == 32 + 48  # 80
        assert not inv.has_errors()

    def test_32_teams_2_rounds_g4(self):
        """32 teams, 2 WF rounds, guarantee 4 → 4 brackets of 8."""
        spec = make_spec("WF_TO_BRACKETS_8", 32, wf_rounds=2, guarantee=4)
        inv = compute_inventory(spec)
        assert inv.wf_matches == 32
        assert inv.bracket_matches == 4 * BRACKET_MATCHES_G4  # 4 * 9 = 36
        assert inv.total_matches == 32 + 36  # 68

    def test_8_teams_0_rounds_g5(self):
        """8 teams, 0 WF rounds, guarantee 5 → 1 bracket of 8."""
        spec = make_spec("WF_TO_BRACKETS_8", 8, wf_rounds=0, guarantee=5)
        inv = compute_inventory(spec)
        assert inv.wf_matches == 0
        assert inv.bracket_matches == BRACKET_MATCHES_G5  # 12
        assert inv.total_matches == 12

    def test_16_teams_2_rounds_g5(self):
        """16 teams, 2 WF rounds, guarantee 5 → 2 brackets of 8."""
        spec = make_spec("WF_TO_BRACKETS_8", 16, wf_rounds=2, guarantee=5)
        inv = compute_inventory(spec)
        assert inv.wf_matches == 16  # 8 * 2
        assert inv.bracket_matches == 2 * BRACKET_MATCHES_G5  # 2 * 12 = 24
        assert inv.total_matches == 16 + 24  # 40

    def test_invalid_team_count(self):
        """Unsupported team count should return error."""
        spec = make_spec("WF_TO_BRACKETS_8", 24, wf_rounds=2)
        inv = compute_inventory(spec)
        assert inv.has_errors()
        assert any("{8,12,16,32}" in e for e in inv.errors)

    def test_invalid_wf_rounds(self):
        """Unsupported WF rounds should return error."""
        spec = make_spec("WF_TO_BRACKETS_8", 32, wf_rounds=3)
        inv = compute_inventory(spec)
        assert inv.has_errors()
        assert any("{0,1,2}" in e for e in inv.errors)


# -----------------------------------------------------------------------------
# bracket_matches_for_guarantee tests
# -----------------------------------------------------------------------------

class TestBracketMatchesForGuarantee:
    def test_g4(self):
        assert bracket_matches_for_guarantee(4) == BRACKET_MATCHES_G4

    def test_g5(self):
        assert bracket_matches_for_guarantee(5) == BRACKET_MATCHES_G5

    def test_unknown_defaults_to_g5(self):
        assert bracket_matches_for_guarantee(6) == BRACKET_MATCHES_G5


# -----------------------------------------------------------------------------
# compute_inventory: unsupported template
# -----------------------------------------------------------------------------

class TestInventoryUnsupported:
    def test_unknown_template(self):
        spec = make_spec("FOOBAR_TEMPLATE", 16)
        inv = compute_inventory(spec)
        assert inv.has_errors()
        assert any("Unsupported template" in e for e in inv.errors)


# -----------------------------------------------------------------------------
# Regression: CANONICAL_32 is unsupported for 32 teams; use WF_TO_BRACKETS_8
# -----------------------------------------------------------------------------

class TestCanonical32IsUnsupportedFor32Teams:
    def test_canonical_32_with_32_teams_returns_error(self):
        """
        CANONICAL_32 with 32 teams is NOT supported.
        Draw Builder should store WF_TO_BRACKETS_8 for 32-team Women's events.
        """
        spec = make_spec("CANONICAL_32", 32, wf_rounds=2, guarantee=5)
        
        # Family should be UNSUPPORTED
        assert resolve_event_family(spec) == "UNSUPPORTED"
        
        # Inventory should return an error
        inv = compute_inventory(spec)
        assert inv.has_errors(), "Expected errors for CANONICAL_32 with 32 teams"
        assert any("Unsupported template" in e for e in inv.errors)

    def test_wf_to_brackets_8_with_32_teams_returns_correct_inventory(self):
        """
        WF_TO_BRACKETS_8 with 32 teams should return correct inventory:
        - WF matches: 32 (16 R1 + 16 R2)
        - Bracket matches: 48 (4 brackets × 12 for G5 V1)
        - RR matches: 0
        - Total: 80
        """
        spec = make_spec("WF_TO_BRACKETS_8", 32, wf_rounds=2, guarantee=5)
        
        # Family should be WF_TO_BRACKETS_8
        assert resolve_event_family(spec) == "WF_TO_BRACKETS_8"
        
        # Inventory should match expected values
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Unexpected errors: {inv.errors}"
        assert inv.wf_matches == 32, f"Expected WF=32, got {inv.wf_matches}"
        assert inv.bracket_matches == 48, f"Expected Bracket=48, got {inv.bracket_matches}"
        assert inv.rr_matches == 0, f"Expected RR=0, got {inv.rr_matches}"
        assert inv.total_matches == 80, f"Expected Total=80, got {inv.total_matches}"

    def test_guarantee_4_vs_5_bracket_inventory(self):
        """
        Guarantee 4 vs 5 must change bracket totals for WF_TO_BRACKETS_8.
        32 teams → 4 brackets. G4: 4×9=36 bracket matches. G5: 4×12=48. Delta=+12.
        """
        # bracket_inventory helper
        assert bracket_inventory(4)["TOTAL"] == 9
        assert bracket_inventory(4)["BRACKET_MAIN"] == 7
        assert bracket_inventory(4)["CONSOLATION_T1"] == 2
        assert bracket_inventory(4)["CONSOLATION_T2"] == 0
        assert bracket_inventory(4)["PLACEMENT"] == 0

        assert bracket_inventory(5)["TOTAL"] == 12
        assert bracket_inventory(5)["BRACKET_MAIN"] == 7
        assert bracket_inventory(5)["CONSOLATION_T1"] == 2
        assert bracket_inventory(5)["CONSOLATION_T2"] == 1
        assert bracket_inventory(5)["PLACEMENT"] == 2

        spec_g4 = make_spec("WF_TO_BRACKETS_8", 32, wf_rounds=2, guarantee=4)
        inv_g4 = compute_inventory(spec_g4)
        assert not inv_g4.has_errors()
        assert inv_g4.bracket_matches == 36, f"G4: expected 36, got {inv_g4.bracket_matches}"
        assert inv_g4.total_matches == 68, f"G4 total: expected 68, got {inv_g4.total_matches}"

        spec_g5 = make_spec("WF_TO_BRACKETS_8", 32, wf_rounds=2, guarantee=5)
        inv_g5 = compute_inventory(spec_g5)
        assert not inv_g5.has_errors()
        assert inv_g5.bracket_matches == 48, f"G5: expected 48, got {inv_g5.bracket_matches}"
        assert inv_g5.total_matches == 80, f"G5 total: expected 80, got {inv_g5.total_matches}"

        assert inv_g5.bracket_matches - inv_g4.bracket_matches == 12


# -----------------------------------------------------------------------------
# WF_TO_POOLS_DYNAMIC: Phase 1 Pools-only template
# -----------------------------------------------------------------------------

class TestWfToPoolsDynamic:
    """Tests for WF_TO_POOLS_DYNAMIC template (Phase 1)."""

    def test_family_resolution(self):
        """WF_TO_POOLS_DYNAMIC should resolve to its own family."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 12, wf_rounds=2)
        assert resolve_event_family(spec) == "WF_TO_POOLS_DYNAMIC"

    # -------------------------------------------------------------------------
    # Inventory tests per the table
    # -------------------------------------------------------------------------

    def test_8_teams_wf1(self):
        """8 teams, 1 WF round → wf=4, rr=12 (2 pools×6), total=16."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 8, wf_rounds=1)
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Errors: {inv.errors}"
        assert inv.wf_matches == 4, f"Expected WF=4, got {inv.wf_matches}"
        assert inv.bracket_matches == 0, f"Expected Bracket=0, got {inv.bracket_matches}"
        assert inv.rr_matches == 12, f"Expected RR=12, got {inv.rr_matches}"
        assert inv.total_matches == 16, f"Expected Total=16, got {inv.total_matches}"

    def test_10_teams_wf1(self):
        """10 teams, 1 WF round → wf=5, rr=20 (2 pools×10), total=25."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 10, wf_rounds=1)
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Errors: {inv.errors}"
        assert inv.wf_matches == 5, f"Expected WF=5, got {inv.wf_matches}"
        assert inv.bracket_matches == 0, f"Expected Bracket=0, got {inv.bracket_matches}"
        assert inv.rr_matches == 20, f"Expected RR=20, got {inv.rr_matches}"
        assert inv.total_matches == 25, f"Expected Total=25, got {inv.total_matches}"

    def test_12_teams_wf2(self):
        """12 teams, 2 WF rounds → wf=12, rr=18 (3 pools×6), total=30."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 12, wf_rounds=2)
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Errors: {inv.errors}"
        assert inv.wf_matches == 12, f"Expected WF=12, got {inv.wf_matches}"
        assert inv.bracket_matches == 0, f"Expected Bracket=0, got {inv.bracket_matches}"
        assert inv.rr_matches == 18, f"Expected RR=18, got {inv.rr_matches}"
        assert inv.total_matches == 30, f"Expected Total=30, got {inv.total_matches}"

    def test_16_teams_wf2(self):
        """16 teams, 2 WF rounds → wf=16, rr=24 (4 pools×6), total=40."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 16, wf_rounds=2)
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Errors: {inv.errors}"
        assert inv.wf_matches == 16, f"Expected WF=16, got {inv.wf_matches}"
        assert inv.bracket_matches == 0, f"Expected Bracket=0, got {inv.bracket_matches}"
        assert inv.rr_matches == 24, f"Expected RR=24, got {inv.rr_matches}"
        assert inv.total_matches == 40, f"Expected Total=40, got {inv.total_matches}"

    def test_20_teams_wf2(self):
        """20 teams, 2 WF rounds → wf=20, rr=30 (5 pools×6), total=50."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 20, wf_rounds=2)
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Errors: {inv.errors}"
        assert inv.wf_matches == 20, f"Expected WF=20, got {inv.wf_matches}"
        assert inv.bracket_matches == 0, f"Expected Bracket=0, got {inv.bracket_matches}"
        assert inv.rr_matches == 30, f"Expected RR=30, got {inv.rr_matches}"
        assert inv.total_matches == 50, f"Expected Total=50, got {inv.total_matches}"

    def test_24_teams_wf2(self):
        """24 teams, 2 WF rounds → wf=24, rr=36 (6 pools×6), total=60."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 24, wf_rounds=2)
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Errors: {inv.errors}"
        assert inv.wf_matches == 24, f"Expected WF=24, got {inv.wf_matches}"
        assert inv.bracket_matches == 0, f"Expected Bracket=0, got {inv.bracket_matches}"
        assert inv.rr_matches == 36, f"Expected RR=36, got {inv.rr_matches}"
        assert inv.total_matches == 60, f"Expected Total=60, got {inv.total_matches}"

    def test_28_teams_wf2(self):
        """28 teams, 2 WF rounds → wf=28, rr=42 (7 pools×6), total=70."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 28, wf_rounds=2)
        inv = compute_inventory(spec)
        assert not inv.has_errors(), f"Errors: {inv.errors}"
        assert inv.wf_matches == 28, f"Expected WF=28, got {inv.wf_matches}"
        assert inv.bracket_matches == 0, f"Expected Bracket=0, got {inv.bracket_matches}"
        assert inv.rr_matches == 42, f"Expected RR=42, got {inv.rr_matches}"
        assert inv.total_matches == 70, f"Expected Total=70, got {inv.total_matches}"

    # -------------------------------------------------------------------------
    # Validation tests
    # -------------------------------------------------------------------------

    def test_unsupported_14_teams(self):
        """14 teams is not supported in Phase 1 → should error."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 14, wf_rounds=2)
        inv = compute_inventory(spec)
        assert inv.has_errors(), "Expected error for 14 teams"
        assert any("WF_TO_POOLS_DYNAMIC supports" in e for e in inv.errors)

    def test_unsupported_18_teams(self):
        """18 teams is not supported in Phase 1 → should error."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 18, wf_rounds=2)
        inv = compute_inventory(spec)
        assert inv.has_errors(), "Expected error for 18 teams"

    def test_wrong_wf_rounds_for_8_teams(self):
        """8 teams requires wf_rounds=1, not 2."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 8, wf_rounds=2)
        inv = compute_inventory(spec)
        assert inv.has_errors(), "Expected error for wf_rounds=2 with 8 teams"
        assert any("requires waterfall_rounds=1" in e for e in inv.errors)

    def test_wrong_wf_rounds_for_12_teams(self):
        """12 teams requires wf_rounds=2, not 1."""
        spec = make_spec("WF_TO_POOLS_DYNAMIC", 12, wf_rounds=1)
        inv = compute_inventory(spec)
        assert inv.has_errors(), "Expected error for wf_rounds=1 with 12 teams"
        assert any("requires waterfall_rounds=2" in e for e in inv.errors)


# -----------------------------------------------------------------------------
# Match Generation Tests: WF_TO_BRACKETS_8 with WF2 wiring
# -----------------------------------------------------------------------------

class TestWF2BracketWiring:
    """Test that WF Round 2 results are wired into bracket slots correctly."""

    def test_wf2_wiring_for_16_teams_ww_bracket(self, session):
        """Test that WW bracket QF placeholders reference WF2 winners correctly."""
        from app.services.draw_plan_engine import generate_matches_for_event

        # Create tournament and event
        tournament = Tournament(
            name="Test Tournament",
            location="Test Location",
            timezone="America/New_York",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 17),
            use_time_windows=False,
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        event = Event(
            tournament_id=tournament.id,
            category="mixed",
            name="Test Event",
            team_count=16,
            guarantee_selected=5,
        )
        event.draw_plan_json = json.dumps({
            "template_type": "WF_TO_BRACKETS_8",
            "wf_rounds": 2,
        })
        session.add(event)
        session.commit()
        session.refresh(event)

        version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
        session.add(version)
        session.commit()
        session.refresh(version)

        # Build spec
        spec = DrawPlanSpec(
            event_id=event.id,
            event_name=event.name,
            division="Mixed",
            team_count=16,
            template_type="WF_TO_BRACKETS_8",
            template_key="WF_TO_BRACKETS_8",
            guarantee=5,
            waterfall_rounds=2,
            waterfall_minutes=60,
            standard_minutes=105,
            tournament_id=tournament.id,
            event_category="mixed",
        )

        # Generate matches
        session._allow_match_generation = True
        linked_team_ids = list(range(1, 17))  # 16 teams
        existing_codes = set()
        matches, warnings = generate_matches_for_event(
            session, version.id, spec, linked_team_ids, existing_codes
        )
        session.add_all(matches)
        session.commit()

        # Extract event prefix from match_code (e.g., "MIX_TES_E1" from "MIX_TES_E1_BWW_M1")
        # Find a WW bracket match to extract prefix
        ww_match = next((m for m in matches if "BWW_M" in m.match_code), None)
        assert ww_match is not None, "No WW bracket matches found"
        # Extract prefix: everything before "_BWW_"
        match_code_parts = ww_match.match_code.split("_BWW_")[0]
        # Remove trailing underscore if present
        event_prefix = match_code_parts.rstrip('_')

        # Find WW bracket QF matches (M1-M4)
        ww_qf_matches = [
            m for m in matches
            if m.match_type == "MAIN" and "BWW_M" in m.match_code and m.round_index <= 4
        ]
        ww_qf_matches.sort(key=lambda m: m.round_index)

        assert len(ww_qf_matches) == 4, f"Expected 4 WW QF matches, got {len(ww_qf_matches)}"

        # Check QF1 (M1): should have W01 vs W02 (slots 1 vs 2)
        qf1 = ww_qf_matches[0]
        expected_token_1 = f"{event_prefix}_WF_R2_W01"
        expected_token_2 = f"{event_prefix}_WF_R2_W02"
        assert expected_token_1 in qf1.placeholder_side_a or expected_token_1 in qf1.placeholder_side_b, \
            f"QF1 missing {expected_token_1}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"
        assert expected_token_2 in qf1.placeholder_side_a or expected_token_2 in qf1.placeholder_side_b, \
            f"QF1 missing {expected_token_2}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"

        # Check QF2 (M2): should have W03 vs W04 (slots 3 vs 4)
        qf2 = ww_qf_matches[1]
        expected_token_3 = f"{event_prefix}_WF_R2_W03"
        expected_token_4 = f"{event_prefix}_WF_R2_W04"
        assert expected_token_3 in qf2.placeholder_side_a or expected_token_3 in qf2.placeholder_side_b, \
            f"QF2 missing {expected_token_3}, got {qf2.placeholder_side_a} / {qf2.placeholder_side_b}"
        assert expected_token_4 in qf2.placeholder_side_a or expected_token_4 in qf2.placeholder_side_b, \
            f"QF2 missing {expected_token_4}, got {qf2.placeholder_side_a} / {qf2.placeholder_side_b}"

        # Check QF3 (M3): should have W05 vs W06 (slots 5 vs 6)
        qf3 = ww_qf_matches[2]
        expected_token_5 = f"{event_prefix}_WF_R2_W05"
        expected_token_6 = f"{event_prefix}_WF_R2_W06"
        assert expected_token_5 in qf3.placeholder_side_a or expected_token_5 in qf3.placeholder_side_b, \
            f"QF3 missing {expected_token_5}, got {qf3.placeholder_side_a} / {qf3.placeholder_side_b}"
        assert expected_token_6 in qf3.placeholder_side_a or expected_token_6 in qf3.placeholder_side_b, \
            f"QF3 missing {expected_token_6}, got {qf3.placeholder_side_a} / {qf3.placeholder_side_b}"

        # Check QF4 (M4): should have W07 vs W08 (slots 7 vs 8)
        qf4 = ww_qf_matches[3]
        expected_token_7 = f"{event_prefix}_WF_R2_W07"
        expected_token_8 = f"{event_prefix}_WF_R2_W08"
        assert expected_token_7 in qf4.placeholder_side_a or expected_token_7 in qf4.placeholder_side_b, \
            f"QF4 missing {expected_token_7}, got {qf4.placeholder_side_a} / {qf4.placeholder_side_b}"
        assert expected_token_8 in qf4.placeholder_side_a or expected_token_8 in qf4.placeholder_side_b, \
            f"QF4 missing {expected_token_8}, got {qf4.placeholder_side_a} / {qf4.placeholder_side_b}"

        # Verify no "TBD" placeholders in WW bracket QFs
        for qf in ww_qf_matches:
            assert "TBD" not in qf.placeholder_side_a, f"QF {qf.match_code} has TBD in placeholder_a"
            assert "TBD" not in qf.placeholder_side_b, f"QF {qf.match_code} has TBD in placeholder_b"
            assert "Division" not in qf.placeholder_side_a, f"QF {qf.match_code} has 'Division' in placeholder_a"
            assert "Division" not in qf.placeholder_side_b, f"QF {qf.match_code} has 'Division' in placeholder_b"

    def test_wf2_wiring_for_16_teams_wl_bracket(self, session):
        """Test that WL bracket QF placeholders reference WF2 losers correctly."""
        from app.services.draw_plan_engine import generate_matches_for_event

        # Create tournament and event (same as above)
        tournament = Tournament(
            name="Test Tournament",
            location="Test Location",
            timezone="America/New_York",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 17),
            use_time_windows=False,
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        event = Event(
            tournament_id=tournament.id,
            category="mixed",
            name="Test Event",
            team_count=16,
            guarantee_selected=5,
        )
        event.draw_plan_json = json.dumps({
            "template_type": "WF_TO_BRACKETS_8",
            "wf_rounds": 2,
        })
        session.add(event)
        session.commit()
        session.refresh(event)

        version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
        session.add(version)
        session.commit()
        session.refresh(version)

        spec = DrawPlanSpec(
            event_id=event.id,
            event_name=event.name,
            division="Mixed",
            team_count=16,
            template_type="WF_TO_BRACKETS_8",
            template_key="WF_TO_BRACKETS_8",
            guarantee=5,
            waterfall_rounds=2,
            waterfall_minutes=60,
            standard_minutes=105,
            tournament_id=tournament.id,
            event_category="mixed",
        )

        session._allow_match_generation = True
        linked_team_ids = list(range(1, 17))
        existing_codes = set()
        matches, warnings = generate_matches_for_event(
            session, version.id, spec, linked_team_ids, existing_codes
        )
        session.add_all(matches)
        session.commit()

        # Extract event prefix from match_code
        wl_match = next((m for m in matches if "BWL_M" in m.match_code), None)
        assert wl_match is not None, "No WL bracket matches found"
        match_code_parts = wl_match.match_code.split("_BWL_")[0]
        event_prefix = match_code_parts.rstrip('_')

        # Find WL bracket QF matches
        wl_qf_matches = [
            m for m in matches
            if m.match_type == "MAIN" and "BWL_M" in m.match_code and m.round_index <= 4
        ]
        wl_qf_matches.sort(key=lambda m: m.round_index)

        assert len(wl_qf_matches) == 4, f"Expected 4 WL QF matches, got {len(wl_qf_matches)}"

        # Check that WL QF1 references loser tokens (L01 vs L02)
        # WL uses losers of WF R2 sequence 1-8 → L01-L08
        qf1 = wl_qf_matches[0]
        expected_l_token_1 = f"{event_prefix}_WF_R2_L01"
        expected_l_token_2 = f"{event_prefix}_WF_R2_L02"
        assert expected_l_token_1 in qf1.placeholder_side_a or expected_l_token_1 in qf1.placeholder_side_b, \
            f"WL QF1 missing {expected_l_token_1}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"
        assert expected_l_token_2 in qf1.placeholder_side_a or expected_l_token_2 in qf1.placeholder_side_b, \
            f"WL QF1 missing {expected_l_token_2}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"
        
        # Verify WL uses L tokens (losers), not W tokens
        assert "_WF_R2_W" not in qf1.placeholder_side_a and "_WF_R2_W" not in qf1.placeholder_side_b, \
            f"WL QF1 should use L tokens (losers), but found W token: {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"

        # Verify no "TBD" or "Division" placeholders
        for qf in wl_qf_matches:
            assert "TBD" not in qf.placeholder_side_a, f"QF {qf.match_code} has TBD in placeholder_a"
            assert "TBD" not in qf.placeholder_side_b, f"QF {qf.match_code} has TBD in placeholder_b"
            assert "Division" not in qf.placeholder_side_a, f"QF {qf.match_code} has 'Division' in placeholder_a"
            assert "Division" not in qf.placeholder_side_b, f"QF {qf.match_code} has 'Division' in placeholder_b"

    def test_wf2_wiring_for_32_teams_blw_bracket(self, session):
        """Test that BLW (Division III) bracket QF placeholders reference WF2 winners bracket tokens W09-W16."""
        from app.services.draw_plan_engine import generate_matches_for_event

        tournament = Tournament(
            name="Test Tournament",
            location="Test Location",
            timezone="America/New_York",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 17),
            use_time_windows=False,
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        event = Event(
            tournament_id=tournament.id,
            category="mixed",
            name="Test Event",
            team_count=32,  # 32 teams = 4 brackets (WW, WL, LW, LL)
            guarantee_selected=5,
        )
        event.draw_plan_json = json.dumps({
            "template_type": "WF_TO_BRACKETS_8",
            "wf_rounds": 2,
        })
        session.add(event)
        session.commit()
        session.refresh(event)

        version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
        session.add(version)
        session.commit()
        session.refresh(version)

        spec = DrawPlanSpec(
            event_id=event.id,
            event_name=event.name,
            division="Mixed",
            team_count=32,
            template_type="WF_TO_BRACKETS_8",
            template_key="WF_TO_BRACKETS_8",
            guarantee=5,
            waterfall_rounds=2,
            waterfall_minutes=60,
            standard_minutes=105,
            tournament_id=tournament.id,
            event_category="mixed",
        )

        session._allow_match_generation = True
        linked_team_ids = list(range(1, 33))  # 32 teams
        existing_codes = set()
        matches, warnings = generate_matches_for_event(
            session, version.id, spec, linked_team_ids, existing_codes
        )
        session.add_all(matches)
        session.commit()

        # Extract event prefix from BLW bracket match
        blw_match = next((m for m in matches if "BLW_M" in m.match_code), None)
        assert blw_match is not None, "No BLW bracket matches found"
        match_code_parts = blw_match.match_code.split("_BLW_")[0]
        event_prefix = match_code_parts.rstrip('_')

        # Find BLW bracket QF matches (M1-M4)
        blw_qf_matches = [
            m for m in matches
            if m.match_type == "MAIN" and "BLW_M" in m.match_code and m.round_index <= 4
        ]
        blw_qf_matches.sort(key=lambda m: m.round_index)

        assert len(blw_qf_matches) == 4, f"Expected 4 BLW QF matches, got {len(blw_qf_matches)}"

        # Check BLW QF1 (sequence_in_round=1): should reference W09 vs W10 (winners of WF R2 sequence 9-16)
        qf1 = blw_qf_matches[0]
        expected_w_token_9 = f"{event_prefix}_WF_R2_W09"
        expected_w_token_10 = f"{event_prefix}_WF_R2_W10"
        assert expected_w_token_9 in qf1.placeholder_side_a or expected_w_token_9 in qf1.placeholder_side_b, \
            f"BLW QF1 missing {expected_w_token_9}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"
        assert expected_w_token_10 in qf1.placeholder_side_a or expected_w_token_10 in qf1.placeholder_side_b, \
            f"BLW QF1 missing {expected_w_token_10}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"

        # Check BLW QF4 (sequence_in_round=4): should reference W15 vs W16
        qf4 = blw_qf_matches[3]
        expected_w_token_15 = f"{event_prefix}_WF_R2_W15"
        expected_w_token_16 = f"{event_prefix}_WF_R2_W16"
        assert expected_w_token_15 in qf4.placeholder_side_a or expected_w_token_15 in qf4.placeholder_side_b, \
            f"BLW QF4 missing {expected_w_token_15}, got {qf4.placeholder_side_a} / {qf4.placeholder_side_b}"
        assert expected_w_token_16 in qf4.placeholder_side_a or expected_w_token_16 in qf4.placeholder_side_b, \
            f"BLW QF4 missing {expected_w_token_16}, got {qf4.placeholder_side_a} / {qf4.placeholder_side_b}"

        # Verify BLW uses W tokens (winners), not L tokens
        assert "_WF_R2_L" not in qf1.placeholder_side_a and "_WF_R2_L" not in qf1.placeholder_side_b, \
            f"BLW QF1 should use W tokens (winners), but found L token: {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"

        # Verify no legacy placeholders
        for qf in blw_qf_matches:
            assert "TBD" not in qf.placeholder_side_a, f"QF {qf.match_code} has TBD in placeholder_a"
            assert "TBD" not in qf.placeholder_side_b, f"QF {qf.match_code} has TBD in placeholder_b"
            assert "Division" not in qf.placeholder_side_a, f"QF {qf.match_code} has 'Division' in placeholder_a"
            assert "Division" not in qf.placeholder_side_b, f"QF {qf.match_code} has 'Division' in placeholder_b"

    def test_wf2_wiring_for_32_teams_bll_bracket(self, session):
        """Test that BLL (Division IV) bracket QF placeholders reference WF2 losers bracket tokens L09-L16."""
        from app.services.draw_plan_engine import generate_matches_for_event

        tournament = Tournament(
            name="Test Tournament",
            location="Test Location",
            timezone="America/New_York",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 17),
            use_time_windows=False,
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        event = Event(
            tournament_id=tournament.id,
            category="mixed",
            name="Test Event",
            team_count=32,  # 32 teams = 4 brackets (WW, WL, LW, LL)
            guarantee_selected=5,
        )
        event.draw_plan_json = json.dumps({
            "template_type": "WF_TO_BRACKETS_8",
            "wf_rounds": 2,
        })
        session.add(event)
        session.commit()
        session.refresh(event)

        version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
        session.add(version)
        session.commit()
        session.refresh(version)

        spec = DrawPlanSpec(
            event_id=event.id,
            event_name=event.name,
            division="Mixed",
            team_count=32,
            template_type="WF_TO_BRACKETS_8",
            template_key="WF_TO_BRACKETS_8",
            guarantee=5,
            waterfall_rounds=2,
            waterfall_minutes=60,
            standard_minutes=105,
            tournament_id=tournament.id,
            event_category="mixed",
        )

        session._allow_match_generation = True
        linked_team_ids = list(range(1, 33))  # 32 teams
        existing_codes = set()
        matches, warnings = generate_matches_for_event(
            session, version.id, spec, linked_team_ids, existing_codes
        )
        session.add_all(matches)
        session.commit()

        # Extract event prefix from BLL bracket match
        bll_match = next((m for m in matches if "BLL_M" in m.match_code), None)
        assert bll_match is not None, "No BLL bracket matches found"
        match_code_parts = bll_match.match_code.split("_BLL_")[0]
        event_prefix = match_code_parts.rstrip('_')

        # Find BLL bracket QF matches (M1-M4)
        bll_qf_matches = [
            m for m in matches
            if m.match_type == "MAIN" and "BLL_M" in m.match_code and m.round_index <= 4
        ]
        bll_qf_matches.sort(key=lambda m: m.round_index)

        assert len(bll_qf_matches) == 4, f"Expected 4 BLL QF matches, got {len(bll_qf_matches)}"

        # Check BLL QF1 (sequence_in_round=1): should reference L09 vs L10 (losers of WF R2 sequence 9-16)
        qf1 = bll_qf_matches[0]
        expected_l_token_9 = f"{event_prefix}_WF_R2_L09"
        expected_l_token_10 = f"{event_prefix}_WF_R2_L10"
        assert expected_l_token_9 in qf1.placeholder_side_a or expected_l_token_9 in qf1.placeholder_side_b, \
            f"BLL QF1 missing {expected_l_token_9}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"
        assert expected_l_token_10 in qf1.placeholder_side_a or expected_l_token_10 in qf1.placeholder_side_b, \
            f"BLL QF1 missing {expected_l_token_10}, got {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"

        # Check BLL QF4 (sequence_in_round=4): should reference L15 vs L16
        qf4 = bll_qf_matches[3]
        expected_l_token_15 = f"{event_prefix}_WF_R2_L15"
        expected_l_token_16 = f"{event_prefix}_WF_R2_L16"
        assert expected_l_token_15 in qf4.placeholder_side_a or expected_l_token_15 in qf4.placeholder_side_b, \
            f"BLL QF4 missing {expected_l_token_15}, got {qf4.placeholder_side_a} / {qf4.placeholder_side_b}"
        assert expected_l_token_16 in qf4.placeholder_side_a or expected_l_token_16 in qf4.placeholder_side_b, \
            f"BLL QF4 missing {expected_l_token_16}, got {qf4.placeholder_side_a} / {qf4.placeholder_side_b}"

        # Verify BLL uses L tokens (losers), not W tokens
        assert "_WF_R2_W" not in qf1.placeholder_side_a and "_WF_R2_W" not in qf1.placeholder_side_b, \
            f"BLL QF1 should use L tokens (losers), but found W token: {qf1.placeholder_side_a} / {qf1.placeholder_side_b}"

        # Verify no legacy placeholders
        for qf in bll_qf_matches:
            assert "TBD" not in qf.placeholder_side_a, f"QF {qf.match_code} has TBD in placeholder_a"
            assert "TBD" not in qf.placeholder_side_b, f"QF {qf.match_code} has TBD in placeholder_b"
            assert "Division" not in qf.placeholder_side_a, f"QF {qf.match_code} has 'Division' in placeholder_a"
            assert "Division" not in qf.placeholder_side_b, f"QF {qf.match_code} has 'Division' in placeholder_b"

    def test_wf2_wiring_all_divisions_use_correct_tokens(self, session):
        """Test that all 4 divisions use correct WF2 token sequences: WW/WL use 1-8, LW/LL use 9-16."""
        from app.services.draw_plan_engine import generate_matches_for_event

        tournament = Tournament(
            name="Test Tournament",
            location="Test Location",
            timezone="America/New_York",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 17),
            use_time_windows=False,
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        event = Event(
            tournament_id=tournament.id,
            category="mixed",
            name="Test Event",
            team_count=32,  # 32 teams = 4 brackets
            guarantee_selected=5,
        )
        event.draw_plan_json = json.dumps({
            "template_type": "WF_TO_BRACKETS_8",
            "wf_rounds": 2,
        })
        session.add(event)
        session.commit()
        session.refresh(event)

        version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
        session.add(version)
        session.commit()
        session.refresh(version)

        spec = DrawPlanSpec(
            event_id=event.id,
            event_name=event.name,
            division="Mixed",
            team_count=32,
            template_type="WF_TO_BRACKETS_8",
            template_key="WF_TO_BRACKETS_8",
            guarantee=5,
            waterfall_rounds=2,
            waterfall_minutes=60,
            standard_minutes=105,
            tournament_id=tournament.id,
            event_category="mixed",
        )

        session._allow_match_generation = True
        linked_team_ids = list(range(1, 33))  # 32 teams
        existing_codes = set()
        matches, warnings = generate_matches_for_event(
            session, version.id, spec, linked_team_ids, existing_codes
        )
        session.add_all(matches)
        session.commit()

        # Extract event prefix
        any_match = next((m for m in matches if "_B" in m.match_code), None)
        assert any_match is not None, "No bracket matches found"
        event_prefix = any_match.match_code.split("_B")[0].rstrip('_')

        # Check each division's QF1
        # WW: winners of WF R2 sequence 1-8 → W01, W02
        # WL: losers of WF R2 sequence 1-8 → L01, L02
        # LW: winners of WF R2 sequence 9-16 → W09, W10
        # LL: losers of WF R2 sequence 9-16 → L09, L10
        expected_mappings = [
            ("BWW", "W", "01", "02"),  # WW QF1 → W01 vs W02
            ("BWL", "L", "01", "02"),  # WL QF1 → L01 vs L02
            ("BLW", "W", "09", "10"),  # LW QF1 → W09 vs W10
            ("BLL", "L", "09", "10"),  # LL QF1 → L09 vs L10
        ]
        
        for bracket_label, token_type, seq_a, seq_b in expected_mappings:
            qf1_match = next(
                (m for m in matches if f"{bracket_label}_M1" in m.match_code and m.match_type == "MAIN"),
                None
            )
            assert qf1_match is not None, f"No {bracket_label} QF1 match found"
            
            expected_token_a = f"{event_prefix}_WF_R2_{token_type}{seq_a}"
            expected_token_b = f"{event_prefix}_WF_R2_{token_type}{seq_b}"
            
            assert expected_token_a in qf1_match.placeholder_side_a or expected_token_a in qf1_match.placeholder_side_b, \
                f"{bracket_label} QF1 should have {expected_token_a}, got {qf1_match.placeholder_side_a} / {qf1_match.placeholder_side_b}"
            assert expected_token_b in qf1_match.placeholder_side_a or expected_token_b in qf1_match.placeholder_side_b, \
                f"{bracket_label} QF1 should have {expected_token_b}, got {qf1_match.placeholder_side_a} / {qf1_match.placeholder_side_b}"
