"""
Tests for RR placeholder wiring functionality.
"""

import pytest
from app.utils.rr_wiring import (
    enforce_top2_last_round,
    wire_rr_match_placeholders,
    calculate_pool_assignment,
)
from app.services.draw_plan_rules import rr_pairings_by_round


def test_calculate_pool_assignment():
    """Test pool assignment calculation."""
    # Pool size 4
    assert calculate_pool_assignment(1, 4) == (0, 0)  # Pool 0, position 0
    assert calculate_pool_assignment(4, 4) == (0, 3)  # Pool 0, position 3
    assert calculate_pool_assignment(5, 4) == (1, 0)  # Pool 1, position 0
    assert calculate_pool_assignment(8, 4) == (1, 3)  # Pool 1, position 3
    assert calculate_pool_assignment(9, 4) == (2, 0)  # Pool 2, position 0


def test_enforce_top2_last_round_pool4():
    """Test that pool of 4 already has (1,2) in last round."""
    pairings = rr_pairings_by_round(4)
    # Pool 4 already has 1v2 in round 3 (last round)
    result = enforce_top2_last_round(4, pairings)
    
    # Verify (0,1) pairing is in last round (round 3)
    last_round_pairings = [p for p in result if p[0] == 3]
    assert any((p[2] == 0 and p[3] == 1) or (p[2] == 1 and p[3] == 0) for p in last_round_pairings)


def test_enforce_top2_last_round_pool5():
    """Test that pool of 5 gets (1,2) moved to last round."""
    pairings = rr_pairings_by_round(5)
    
    # Find initial round with (0,1) pairing
    initial_round_with_top2 = None
    for round_idx, seq, idx_a, idx_b in pairings:
        if (idx_a == 0 and idx_b == 1) or (idx_a == 1 and idx_b == 0):
            initial_round_with_top2 = round_idx
            break
    
    # Apply enforcement
    result = enforce_top2_last_round(5, pairings)
    
    # Verify (0,1) pairing is now in last round
    last_round = max(p[0] for p in result)
    last_round_pairings = [p for p in result if p[0] == last_round]
    assert any((p[2] == 0 and p[3] == 1) or (p[2] == 1 and p[3] == 0) for p in last_round_pairings)
    
    # If it wasn't already in last round, verify it was swapped
    if initial_round_with_top2 != last_round:
        # The old last round's pairings should now be in the old top2 round
        old_last_round_pairings = [p for p in pairings if p[0] == last_round]
        new_top2_round_pairings = [p for p in result if p[0] == initial_round_with_top2]
        # Should have same number of pairings (though positions may differ)
        assert len(old_last_round_pairings) == len(new_top2_round_pairings)


def test_wire_rr_placeholders_pool1():
    """Test wiring for Pool 1 (pool_index=0) with pool_size=4."""
    pairings = rr_pairings_by_round(4)
    wired = wire_rr_match_placeholders(
        pool_index=0,
        pool_size=4,
        pairings=pairings,
        enforce_top2_last=True,
    )
    
    # Pool 1 should have seeds 1-4
    # Verify all placeholders are SEED_1 through SEED_4
    for _, _, placeholder_a, placeholder_b in wired:
        seed_a = int(placeholder_a.replace("SEED_", ""))
        seed_b = int(placeholder_b.replace("SEED_", ""))
        assert 1 <= seed_a <= 4
        assert 1 <= seed_b <= 4
    
    # Verify (1,2) matchup is in last round
    last_round = max(p[0] for p in wired)
    last_round_pairings = [p for p in wired if p[0] == last_round]
    assert any(
        (p[2] == "SEED_1" and p[3] == "SEED_2") or (p[2] == "SEED_2" and p[3] == "SEED_1")
        for p in last_round_pairings
    )


def test_wire_rr_placeholders_pool2():
    """Test wiring for Pool 2 (pool_index=1) with pool_size=4."""
    pairings = rr_pairings_by_round(4)
    wired = wire_rr_match_placeholders(
        pool_index=1,
        pool_size=4,
        pairings=pairings,
        enforce_top2_last=True,
    )
    
    # Pool 2 should have seeds 5-8
    # Verify all placeholders are SEED_5 through SEED_8
    for _, _, placeholder_a, placeholder_b in wired:
        seed_a = int(placeholder_a.replace("SEED_", ""))
        seed_b = int(placeholder_b.replace("SEED_", ""))
        assert 5 <= seed_a <= 8
        assert 5 <= seed_b <= 8
    
    # Verify (5,6) matchup (top 2 in pool) is in last round
    last_round = max(p[0] for p in wired)
    last_round_pairings = [p for p in wired if p[0] == last_round]
    assert any(
        (p[2] == "SEED_5" and p[3] == "SEED_6") or (p[2] == "SEED_6" and p[3] == "SEED_5")
        for p in last_round_pairings
    )


def test_wire_rr_placeholders_pool5():
    """Test wiring for pool of 5 teams."""
    pairings = rr_pairings_by_round(5)
    wired = wire_rr_match_placeholders(
        pool_index=0,
        pool_size=5,
        pairings=pairings,
        enforce_top2_last=True,
    )
    
    # Pool should have seeds 1-5
    for _, _, placeholder_a, placeholder_b in wired:
        seed_a = int(placeholder_a.replace("SEED_", ""))
        seed_b = int(placeholder_b.replace("SEED_", ""))
        assert 1 <= seed_a <= 5
        assert 1 <= seed_b <= 5
    
    # Verify (1,2) matchup is in last round
    last_round = max(p[0] for p in wired)
    last_round_pairings = [p for p in wired if p[0] == last_round]
    assert any(
        (p[2] == "SEED_1" and p[3] == "SEED_2") or (p[2] == "SEED_2" and p[3] == "SEED_1")
        for p in last_round_pairings
    )


def test_wire_rr_placeholders_deterministic():
    """Test that wiring is deterministic (same input produces same output)."""
    pairings = rr_pairings_by_round(4)
    
    result1 = wire_rr_match_placeholders(0, 4, pairings, enforce_top2_last=True)
    result2 = wire_rr_match_placeholders(0, 4, pairings, enforce_top2_last=True)
    
    assert result1 == result2
