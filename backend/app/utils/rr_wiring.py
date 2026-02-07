"""
Round Robin Placeholder Wiring

This module handles deterministic wiring of RR match placeholders based on:
1. Pool assignment by seed order (deterministic)
2. Top 2 seeds in each pool play in the last round
3. SEED_<n> placeholder assignment
"""

from typing import List, Tuple, Dict
from collections import defaultdict

from app.services.draw_plan_rules import rr_pairings_by_round, rr_round_count


def enforce_top2_last_round(
    pool_size: int, pairings: List[Tuple[int, int, int, int]]
) -> List[Tuple[int, int, int, int]]:
    """
    Post-process RR pairings to ensure positions (1,2) play in the last round.
    
    Args:
        pool_size: Number of teams in the pool
        pairings: List of (round_index, sequence_in_round, idx_a, idx_b) tuples
                 where idx_a, idx_b are 0-based positions (0 = seed 1, 1 = seed 2, etc.)
    
    Returns:
        Modified pairings list with (1,2) matchup in the last round
    
    Strategy:
        - Find the round where (0,1) pairing occurs (positions 0 and 1 = seeds 1 and 2)
        - Find the last round
        - Swap the entire round's pairings if needed
    """
    if pool_size < 2:
        return pairings
    
    # Group pairings by round
    rounds: Dict[int, List[Tuple[int, int, int, int]]] = defaultdict(list)
    for pairing in pairings:
        round_idx = pairing[0]
        rounds[round_idx].append(pairing)
    
    # Find which round contains the (0,1) pairing (seeds 1 and 2)
    round_with_top2 = None
    last_round = max(rounds.keys()) if rounds else 1
    
    for round_idx, round_pairings in rounds.items():
        for _, _, idx_a, idx_b in round_pairings:
            # Check if this is the (0,1) or (1,0) pairing
            if (idx_a == 0 and idx_b == 1) or (idx_a == 1 and idx_b == 0):
                round_with_top2 = round_idx
                break
        if round_with_top2 is not None:
            break
    
    # If top 2 are already in last round, no swap needed
    if round_with_top2 == last_round or round_with_top2 is None:
        return pairings
    
    # Swap the rounds: move top2 round to last, last round to top2 position
    top2_round_pairings = rounds[round_with_top2]
    last_round_pairings = rounds[last_round]
    
    # Rebuild pairings with swapped rounds
    # Maintain deterministic ordering: sort rounds, then sort pairings within each round
    result: List[Tuple[int, int, int, int]] = []
    for round_idx in sorted(rounds.keys()):
        if round_idx == round_with_top2:
            # Replace with last round pairings, updating round_index to current round_idx
            # Sort by sequence_in_round for determinism
            sorted_last = sorted(last_round_pairings, key=lambda x: x[1])
            for _, seq, idx_a, idx_b in sorted_last:
                result.append((round_idx, seq, idx_a, idx_b))
        elif round_idx == last_round:
            # Replace with top2 round pairings, updating round_index to current round_idx
            # Sort by sequence_in_round for determinism
            sorted_top2 = sorted(top2_round_pairings, key=lambda x: x[1])
            for _, seq, idx_a, idx_b in sorted_top2:
                result.append((round_idx, seq, idx_a, idx_b))
        else:
            # Keep other rounds as-is, sorted by sequence_in_round
            sorted_round = sorted(rounds[round_idx], key=lambda x: x[1])
            result.extend(sorted_round)
    
    return result


def calculate_pool_assignment(seed: int, pool_size: int) -> Tuple[int, int]:
    """
    Calculate pool assignment for a given seed.
    
    Args:
        seed: Global seed number (1-based)
        pool_size: Number of teams per pool
    
    Returns:
        Tuple of (pool_index, position_in_pool) where:
        - pool_index: 0-based pool index (0 = Pool 1, 1 = Pool 2, etc.)
        - position_in_pool: 0-based position within pool (0 = seed 1 in pool, 1 = seed 2, etc.)
    
    Formula:
        pool_index = (seed - 1) // pool_size
        position_in_pool = (seed - 1) % pool_size
    """
    seed_0based = seed - 1  # Convert to 0-based
    pool_index = seed_0based // pool_size
    position_in_pool = seed_0based % pool_size
    return pool_index, position_in_pool


def wire_rr_match_placeholders(
    pool_index: int,
    pool_size: int,
    pairings: List[Tuple[int, int, int, int]],
    enforce_top2_last: bool = True,
) -> List[Tuple[int, int, str, str]]:
    """
    Wire RR match placeholders based on pool assignment and pairings.
    
    Args:
        pool_index: 0-based pool index (0 = Pool 1, etc.)
        pool_size: Number of teams per pool
        pairings: List of (round_index, sequence_in_round, idx_a, idx_b) tuples
                 where idx_a, idx_b are 0-based positions within the pool
        enforce_top2_last: If True, ensure (1,2) matchup is in last round
    
    Returns:
        List of (round_index, sequence_in_round, placeholder_a, placeholder_b) tuples
        where placeholders are "SEED_<n>" format
    
    Process:
        1. Optionally enforce top2-last-round constraint
        2. For each pairing, convert pool positions to global seeds
        3. Generate SEED_<n> placeholders
    """
    # Apply top2-last-round constraint if requested
    if enforce_top2_last:
        pairings = enforce_top2_last_round(pool_size, pairings)
    
    result: List[Tuple[int, int, str, str]] = []
    
    for round_index, seq_in_round, pos_a, pos_b in pairings:
        # Convert 0-based positions to 1-based seeds within pool
        seed_a_in_pool = pos_a + 1
        seed_b_in_pool = pos_b + 1
        
        # Convert to global seeds
        # Pool 0 (pool_index=0): seeds 1..pool_size
        # Pool 1 (pool_index=1): seeds pool_size+1..2*pool_size
        # etc.
        global_seed_a = pool_index * pool_size + seed_a_in_pool
        global_seed_b = pool_index * pool_size + seed_b_in_pool
        
        placeholder_a = f"SEED_{global_seed_a}"
        placeholder_b = f"SEED_{global_seed_b}"
        
        result.append((round_index, seq_in_round, placeholder_a, placeholder_b))
    
    return result
