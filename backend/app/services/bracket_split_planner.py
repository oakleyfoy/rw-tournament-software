"""Phase 1 Waterfall bracket-split planner. Does not create brackets or matches."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median, pstdev
from typing import Any, Optional

from app.services.canonical_teams import SnapshotTeam, sort_teams_for_planning
from app.services.draw_catalog import bracket_family_label
from app.services.team_rating import RATING_STATUS_MISSING, RATING_STATUS_PARTIAL

MAX_BRACKET_SIZE = 32
MIN_BRACKET_SIZE = 8
PREFERRED_BRACKET_SIZES = (32, 28, 24, 20, 16)
SMALL_FINAL_RANGE = range(8, 16)
MAX_BRACKETS = 5
TOP_ALTERNATIVES_LIMIT = 8

# Existing Waterfall engine does not pad general brackets into a power-of-two shell.
# Byes exist only for WF_14 top-2 seeds and odd RR pools, so Phase 1 does not estimate byes.
BYE_LOGIC_APPLICABLE = False


def _round_rating(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 4)


def option_key(sizes: tuple[int, ...]) -> str:
    return "-".join(str(size) for size in sizes)


def generate_split_sizes(team_count: int) -> list[tuple[int, ...]]:
    """Generate ordered compositions. Size order is the cut-rank order (A, then B, …)."""
    if team_count <= 0:
        return []
    if team_count < MIN_BRACKET_SIZE:
        return [(team_count,)]

    options: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()

    def add(parts: tuple[int, ...]) -> None:
        if not parts or any(part < 1 for part in parts):
            return
        if any(part > MAX_BRACKET_SIZE for part in parts):
            return
        if sum(parts) != team_count:
            return
        if len(parts) > 1 and any(part < MIN_BRACKET_SIZE for part in parts):
            return
        # True duplicates only: the exact ordered sequence, not a sorted partition.
        if parts in seen:
            return
        seen.add(parts)
        options.append(parts)

    if team_count <= MAX_BRACKET_SIZE:
        add((team_count,))

    def recurse(remaining: int, acc: list[int], used_small: bool) -> None:
        if remaining <= 0 or len(acc) >= MAX_BRACKETS:
            return
        if acc and MIN_BRACKET_SIZE <= remaining <= MAX_BRACKET_SIZE:
            add(tuple(acc + [remaining]))
        if len(acc) + 1 >= MAX_BRACKETS:
            return
        for size in PREFERRED_BRACKET_SIZES:
            leftover = remaining - size
            if leftover < MIN_BRACKET_SIZE:
                continue
            recurse(leftover, acc + [size], used_small)
        # One 8–15 leftover may sit in any ordered position; do not explode into all-tiny trees.
        if not used_small:
            for size in range(15, 7, -1):
                leftover = remaining - size
                if leftover < MIN_BRACKET_SIZE:
                    continue
                recurse(leftover, acc + [size], True)

    recurse(team_count, [], False)
    return options


def _team_display_name(team: SnapshotTeam) -> str:
    return f"{team.player1.name} / {team.player2.name}"


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return _round_rating(median(values))


def _adjacent_gaps(ratings: list[Optional[float]]) -> list[float]:
    gaps: list[float] = []
    for index in range(len(ratings) - 1):
        upper = ratings[index]
        lower = ratings[index + 1]
        if upper is None or lower is None:
            continue
        gaps.append(upper - lower)
    return gaps


def _cut_quality_label(gap: Optional[float], typical_gap: Optional[float]) -> str:
    if gap is None:
        return "No Natural Break"
    if gap <= 0:
        return "No Natural Break"
    if typical_gap is None or typical_gap <= 0:
        return "Good" if gap > 0 else "No Natural Break"
    if gap >= typical_gap * 2:
        return "Strong"
    if gap >= typical_gap:
        return "Good"
    return "Weak"


@dataclass
class CutAnalysis:
    from_label: str
    to_label: str
    upper_rank: int
    lower_rank: int
    upper_team_key: str
    lower_team_key: str
    upper_team_name: str
    lower_team_name: str
    upper_rating: Optional[float]
    lower_rating: Optional[float]
    rating_gap: Optional[float]
    quality: str
    neighborhood: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fromLabel": self.from_label,
            "toLabel": self.to_label,
            "upperRank": self.upper_rank,
            "lowerRank": self.lower_rank,
            "upperTeamKey": self.upper_team_key,
            "lowerTeamKey": self.lower_team_key,
            "upperTeamName": self.upper_team_name,
            "lowerTeamName": self.lower_team_name,
            "upperRating": self.upper_rating,
            "lowerRating": self.lower_rating,
            "ratingGap": self.rating_gap,
            "quality": self.quality,
            "neighborhood": self.neighborhood,
        }


@dataclass
class BracketPreview:
    label: str
    letter: str
    size: int
    rank_start: int
    rank_end: int
    highest_rating: Optional[float]
    lowest_rating: Optional[float]
    average_rating: Optional[float]
    median_rating: Optional[float]
    rating_spread: Optional[float]
    teams: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "letter": self.letter,
            "size": self.size,
            "rankStart": self.rank_start,
            "rankEnd": self.rank_end,
            "highestRating": self.highest_rating,
            "lowestRating": self.lowest_rating,
            "averageRating": self.average_rating,
            "medianRating": self.median_rating,
            "ratingSpread": self.rating_spread,
            "teams": self.teams,
        }


def _letter_for_index(index: int) -> str:
    return chr(ord("A") + index)


def _preview_team(rank: int, team: SnapshotTeam) -> dict[str, Any]:
    return {
        "rank": rank,
        "teamKey": team.team_key,
        "name": _team_display_name(team),
        "teamRating": team.team_rating,
        "ratingStatus": team.rating_status,
        "status": team.status,
        "player1": team.player1.to_dict(),
        "player2": team.player2.to_dict(),
    }


def _neighborhood(sorted_teams: list[SnapshotTeam], cut_after: int, window: int = 2) -> list[dict[str, Any]]:
    start = max(1, cut_after - window)
    end = min(len(sorted_teams), cut_after + window)
    rows = []
    for rank in range(start, end + 1):
        team = sorted_teams[rank - 1]
        rows.append(
            {
                "rank": rank,
                "name": _team_display_name(team),
                "teamRating": team.team_rating,
                "isCutBoundary": rank == cut_after,
            }
        )
    return rows


def _bracket_metrics(sorted_teams: list[SnapshotTeam], draw_kind: str, size: int, rank_start: int) -> BracketPreview:
    rank_end = rank_start + size - 1
    slice_teams = sorted_teams[rank_start - 1 : rank_end]
    ratings = [team.team_rating for team in slice_teams if team.team_rating is not None]
    highest = max(ratings) if ratings else None
    lowest = min(ratings) if ratings else None
    return BracketPreview(
        label="",
        letter="",
        size=size,
        rank_start=rank_start,
        rank_end=rank_end,
        highest_rating=_round_rating(highest),
        lowest_rating=_round_rating(lowest),
        average_rating=_round_rating(mean(ratings)) if ratings else None,
        median_rating=_median(ratings),
        rating_spread=_round_rating(highest - lowest) if highest is not None and lowest is not None else None,
        teams=[],
    )


def analyze_option(
    sorted_teams: list[SnapshotTeam], sizes: tuple[int, ...], typical_gap: Optional[float]
) -> dict[str, Any]:
    family = bracket_family_label(sorted_teams[0].draw_kind if sorted_teams else "womens")
    brackets: list[BracketPreview] = []
    cuts: list[CutAnalysis] = []
    cursor = 1
    for index, size in enumerate(sizes):
        preview = _bracket_metrics(sorted_teams, sorted_teams[0].draw_kind if sorted_teams else "", size, cursor)
        letter = _letter_for_index(index)
        preview.letter = letter
        preview.label = f"{family} {letter}"
        brackets.append(preview)
        cursor += size

    for index in range(len(brackets) - 1):
        upper = brackets[index]
        lower = brackets[index + 1]
        upper_team = sorted_teams[upper.rank_end - 1]
        lower_team = sorted_teams[lower.rank_start - 1]
        gap = None
        if upper_team.team_rating is not None and lower_team.team_rating is not None:
            gap = _round_rating(upper_team.team_rating - lower_team.team_rating)
        cuts.append(
            CutAnalysis(
                from_label=upper.label,
                to_label=lower.label,
                upper_rank=upper.rank_end,
                lower_rank=lower.rank_start,
                upper_team_key=upper_team.team_key,
                lower_team_key=lower_team.team_key,
                upper_team_name=_team_display_name(upper_team),
                lower_team_name=_team_display_name(lower_team),
                upper_rating=_round_rating(upper_team.team_rating),
                lower_rating=_round_rating(lower_team.team_rating),
                rating_gap=gap,
                quality=_cut_quality_label(gap, typical_gap),
                neighborhood=_neighborhood(sorted_teams, upper.rank_end),
            )
        )

    return {
        "optionKey": option_key(sizes),
        "sizes": list(sizes),
        "brackets": [bracket.to_dict() for bracket in brackets],
        "cuts": [cut.to_dict() for cut in cuts],
    }


def score_option(
    option: dict[str, Any],
    *,
    team_count: int,
    unrated_count: int,
    partial_count: int,
    max_cut_gap: Optional[float],
    has_unavoidable_small: bool,
) -> dict[str, Any]:
    sizes = tuple(option["sizes"])
    reasons: list[str] = []

    cut_gaps = [cut["ratingGap"] for cut in option["cuts"] if cut.get("ratingGap") is not None]
    raw_cut = sum(cut_gaps) if cut_gaps else 0.0
    if max_cut_gap and max_cut_gap > 0 and option["cuts"]:
        cut_quality = min(40.0, 40.0 * (raw_cut / (max_cut_gap * max(1, len(option["cuts"])))))
    elif not option["cuts"]:
        cut_quality = 18.0 if team_count <= MAX_BRACKET_SIZE else 8.0
    else:
        cut_quality = 10.0 if raw_cut > 0 else 4.0

    if cut_gaps:
        for cut in option["cuts"]:
            gap = cut.get("ratingGap")
            upper = cut.get("upperRating")
            lower = cut.get("lowerRating")
            gap_text = f"{gap:.2f}" if gap is not None else "n/a"
            upper_text = f"{upper:.2f}" if upper is not None else "unrated"
            lower_text = f"{lower:.2f}" if lower is not None else "unrated"
            reasons.append(
                f"{cut['quality']} natural break: #{cut['upperRank']} {upper_text} / "
                f"#{cut['lowerRank']} {lower_text} · Gap {gap_text}"
            )
    elif len(sizes) == 1:
        reasons.append("Single bracket — no rating cut required")

    preferred_count = sum(1 for size in sizes if size in PREFERRED_BRACKET_SIZES)
    size_quality = 8.0 * preferred_count
    min_brackets = max(1, (team_count + MAX_BRACKET_SIZE - 1) // MAX_BRACKET_SIZE)
    if len(sizes) > min_brackets:
        size_quality -= 3.0 * (len(sizes) - min_brackets)
        reasons.append("Extra brackets beyond the minimum needed for the field")
    if len(sizes) == 1 and MIN_BRACKET_SIZE <= sizes[0] <= MAX_BRACKET_SIZE:
        size_quality += 16.0
        reasons.append("One healthy-sized bracket")
    elif sizes:
        size_quality += max(0.0, 16.0 - pstdev(sizes))
        if max(sizes) - min(sizes) <= 8:
            reasons.append(
                "Both brackets have healthy size" if len(sizes) == 2 else "Reasonably balanced bracket sizes"
            )
        else:
            reasons.append("Bracket sizes are usable but uneven")
        if all(MIN_BRACKET_SIZE <= size <= MAX_BRACKET_SIZE for size in sizes):
            reasons.append("All brackets within supported size range")

    tiny_penalty = 0.0
    tiny_parts = [size for size in sizes if size < MIN_BRACKET_SIZE]
    small_parts = [size for size in sizes if size in SMALL_FINAL_RANGE]
    if tiny_parts and not has_unavoidable_small:
        tiny_penalty += 40.0 * len(tiny_parts)
        reasons.append("Contains an undersized bracket below 8")
    elif small_parts and team_count >= 16 and len(sizes) > 1:
        # 8-11 is a true tiny-final smell; 12-15 is acceptable leftover.
        very_small = [size for size in small_parts if size <= 11]
        if very_small:
            tiny_penalty += 18.0 * len(very_small)
            reasons.append("Penalized for an unnecessarily tiny final bracket")
        else:
            tiny_penalty += 6.0 * len(small_parts)
            reasons.append("Final bracket is smaller than the preferred 16–32 range")
    elif not small_parts and not tiny_parts:
        reasons.append("No very small bracket")

    unrated_penalty = (3.0 * unrated_count) + (1.0 * partial_count)
    if unrated_count or partial_count:
        reasons.append(
            f"{unrated_count + partial_count} team(s) need rating review — recommendation confidence is lower"
        )

    total = round(cut_quality + size_quality - tiny_penalty - unrated_penalty, 3)
    return {
        "cutQuality": round(cut_quality, 3),
        "sizeQuality": round(size_quality, 3),
        "tinyBracketPenalty": round(tiny_penalty, 3),
        "unratedTeamPenalty": round(unrated_penalty, 3),
        "total": total,
        "reasons": reasons,
    }


def plan_draw(draw_kind: str, teams: list[SnapshotTeam]) -> dict[str, Any]:
    sorted_teams = sort_teams_for_planning(teams)
    team_count = len(sorted_teams)
    unrated_count = sum(1 for team in sorted_teams if team.rating_status == RATING_STATUS_MISSING)
    partial_count = sum(1 for team in sorted_teams if team.rating_status == RATING_STATUS_PARTIAL)
    sizes_list = generate_split_sizes(team_count)
    typical_gap = _median(_adjacent_gaps([team.team_rating for team in sorted_teams]))
    analyzed = [analyze_option(sorted_teams, sizes, typical_gap) for sizes in sizes_list]
    max_cut_gap = None
    all_gaps = [cut["ratingGap"] for option in analyzed for cut in option["cuts"] if cut.get("ratingGap") is not None]
    if all_gaps:
        max_cut_gap = max(all_gaps)
    has_unavoidable_small = team_count < MIN_BRACKET_SIZE

    scored = []
    for option in analyzed:
        score = score_option(
            option,
            team_count=team_count,
            unrated_count=unrated_count,
            partial_count=partial_count,
            max_cut_gap=max_cut_gap,
            has_unavoidable_small=has_unavoidable_small,
        )
        scored.append({**option, "score": score, "recommended": False})

    scored.sort(
        key=lambda option: (option["score"]["total"], option["score"]["cutQuality"], -len(option["sizes"])),
        reverse=True,
    )
    if scored:
        scored[0]["recommended"] = True

    return {
        "drawKind": draw_kind,
        "drawLabel": bracket_family_label(draw_kind),
        "teamCount": team_count,
        "unratedCount": unrated_count,
        "partialCount": partial_count,
        "ratingReviewNeeded": unrated_count + partial_count,
        "byeLogicApplicable": BYE_LOGIC_APPLICABLE,
        "optionCount": len(scored),
        "topOptionCount": min(TOP_ALTERNATIVES_LIMIT, len(scored)),
        "options": scored,
        "teams": [_preview_team(index + 1, team) for index, team in enumerate(sorted_teams)],
    }


def plan_snapshot(active_teams: list[SnapshotTeam]) -> dict[str, Any]:
    by_draw: dict[str, list[SnapshotTeam]] = {}
    for team in active_teams:
        by_draw.setdefault(team.draw_kind, []).append(team)
    draws = [plan_draw(draw_kind, teams) for draw_kind, teams in sorted(by_draw.items())]
    return {
        "draws": draws,
        "maxBracketSize": MAX_BRACKET_SIZE,
        "minBracketSize": MIN_BRACKET_SIZE,
        "preferredBracketSizes": list(PREFERRED_BRACKET_SIZES),
        "byeLogicApplicable": BYE_LOGIC_APPLICABLE,
        "teamRatingFormula": "sum_of_player_ntrp",
    }


def approved_brackets_from_option(option: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "label": bracket["label"],
            "size": bracket["size"],
            "rankStart": bracket["rankStart"],
            "rankEnd": bracket["rankEnd"],
        }
        for bracket in option["brackets"]
    ]
