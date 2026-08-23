"""Waterfall bracket-split planner. Planning only — does not create brackets or matches."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median, pstdev
from typing import Any, Optional

from app.services.canonical_teams import SnapshotTeam, sort_teams_for_planning
from app.services.draw_catalog import bracket_family_label
from app.services.team_rating import RATING_STATUS_MISSING, RATING_STATUS_PARTIAL

MAX_BRACKET_SIZE = 32
MIN_BRACKET_SIZE = 8
MAX_FORECAST_TEAMS = 160
MAX_BRACKETS = 5
MAX_DEFAULT_SCENARIOS = 5
MAX_PERMUTATION_FAMILY = 2

# Operational Racquet War sizes. Awkward integers in 8–32 are allowed only when needed.
OPERATIONAL_BRACKET_SIZES = (8, 10, 12, 14, 16, 20, 24, 28, 32)
PREFERRED_BRACKET_SIZES = OPERATIONAL_BRACKET_SIZES
AWKWARD_BRACKET_SIZES = tuple(
    size for size in range(MIN_BRACKET_SIZE, MAX_BRACKET_SIZE + 1) if size not in OPERATIONAL_BRACKET_SIZES
)
SMALL_FINAL_RANGE = range(8, 12)

# Existing Waterfall engine does not pad general brackets into a power-of-two shell.
BYE_LOGIC_APPLICABLE = False

# Scoring weights. Awkward sizes can still win when a cut is materially stronger.
CUT_QUALITY_MAX = 40.0
SIZE_QUALITY_PER_OPERATIONAL = 6.0
ALL_OPERATIONAL_BONUS = 8.0
BALANCE_BONUS = 6.0
SINGLE_BRACKET_BONUS = 10.0
EXTRA_BRACKET_PENALTY = 12.0
AWKWARD_SIZE_PENALTY = 22.0
TINY_UNDER_8_PENALTY = 40.0
VERY_SMALL_PENALTY = 14.0
PROVISIONAL_CUT_PENALTY = 8.0
UNKNOWN_FUTURE_PENALTY = 4.0
UNRATED_PENALTY = 3.0
PARTIAL_PENALTY = 1.0
MATERIAL_CUT_IMPROVEMENT = 16.0


def _round_rating(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 4)


def option_key(sizes: tuple[int, ...]) -> str:
    return "-".join(str(size) for size in sizes)


def parse_option_key(raw: str) -> tuple[int, ...]:
    parts = []
    for token in str(raw or "").replace("/", "-").replace(",", "-").split("-"):
        token = token.strip()
        if not token:
            continue
        if not token.isdigit():
            raise ValueError(f"Structure '{raw}' contains a non-numeric size.")
        parts.append(int(token))
    if not parts:
        raise ValueError("Structure must include at least one bracket size.")
    return tuple(parts)


def is_operational_size(size: int) -> bool:
    return size in OPERATIONAL_BRACKET_SIZES


def is_awkward_size(size: int) -> bool:
    return size in AWKWARD_BRACKET_SIZES


def validate_custom_sizes(sizes: tuple[int, ...], forecast_count: int) -> None:
    if any(size <= 0 for size in sizes):
        raise ValueError("Bracket sizes must be positive whole numbers.")
    if any(size > MAX_BRACKET_SIZE for size in sizes):
        raise ValueError(f"No bracket may be larger than {MAX_BRACKET_SIZE}.")
    if len(sizes) > MAX_BRACKETS:
        raise ValueError(f"A structure may have at most {MAX_BRACKETS} brackets.")
    if sum(sizes) != forecast_count:
        raise ValueError(f"Bracket sizes must sum to the expected final count of {forecast_count}.")
    if forecast_count >= MIN_BRACKET_SIZE and any(size < MIN_BRACKET_SIZE for size in sizes) and len(sizes) > 1:
        raise ValueError("Multi-bracket plans cannot include a bracket smaller than 8.")


def generate_split_sizes(team_count: int) -> list[tuple[int, ...]]:
    """Generate ordered compositions that sum to team_count. Size order is cut-rank order."""
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
        if parts in seen:
            return
        seen.add(parts)
        options.append(parts)

    if team_count <= MAX_BRACKET_SIZE:
        add((team_count,))

    def recurse(remaining: int, acc: list[int], used_awkward: bool) -> None:
        if remaining <= 0 or len(acc) >= MAX_BRACKETS:
            return
        if acc and MIN_BRACKET_SIZE <= remaining <= MAX_BRACKET_SIZE:
            add(tuple(acc + [remaining]))
        if len(acc) + 1 >= MAX_BRACKETS:
            return
        for size in OPERATIONAL_BRACKET_SIZES:
            leftover = remaining - size
            if leftover < 0:
                continue
            if leftover == 0:
                add(tuple(acc + [size]))
                continue
            if leftover < MIN_BRACKET_SIZE:
                continue
            recurse(leftover, acc + [size], used_awkward)
        if not used_awkward:
            for size in AWKWARD_BRACKET_SIZES:
                leftover = remaining - size
                if leftover < MIN_BRACKET_SIZE and leftover != 0:
                    continue
                if leftover == 0:
                    add(tuple(acc + [size]))
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


def _cut_quality_label(gap: Optional[float], typical_gap: Optional[float], provisional: bool) -> str:
    if provisional:
        return "Provisional"
    if gap is None or gap <= 0:
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
    provisional: bool = False
    message: Optional[str] = None
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
            "provisional": self.provisional,
            "message": self.message,
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
    known_team_count: int = 0
    unknown_team_count: int = 0

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
            "knownTeamCount": self.known_team_count,
            "unknownTeamCount": self.unknown_team_count,
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


def _review_player(player) -> dict[str, Any]:
    return {
        "name": player.name,
        "rwId": player.rw_id,
        "rw_id": player.rw_id,
        "rating": player.rating,
    }


def rating_review_teams(teams: list[SnapshotTeam]) -> list[dict[str, Any]]:
    """Identify current snapshot teams with partial or missing ratings. Display only."""
    rows = []
    for team in teams:
        if team.rating_status not in {RATING_STATUS_PARTIAL, RATING_STATUS_MISSING}:
            continue
        rows.append(
            {
                "teamKey": team.team_key,
                "name": _team_display_name(team),
                "drawKind": team.draw_kind,
                "ratingStatus": team.rating_status,
                "teamRating": team.team_rating,
                "player1": _review_player(team.player1),
                "player2": _review_player(team.player2),
            }
        )
    return rows


def _neighborhood(sorted_teams: list[SnapshotTeam], cut_after: int, window: int = 2) -> list[dict[str, Any]]:
    if cut_after < 1 or cut_after > len(sorted_teams):
        return []
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


def _bracket_metrics(sorted_teams: list[SnapshotTeam], size: int, rank_start: int) -> BracketPreview:
    rank_end = rank_start + size - 1
    known = [
        team
        for index, team in enumerate(sorted_teams, start=1)
        if rank_start <= index <= min(rank_end, len(sorted_teams))
    ]
    ratings = [team.team_rating for team in known if team.team_rating is not None]
    highest = max(ratings) if ratings else None
    lowest = min(ratings) if ratings else None
    unknown = max(0, rank_end - len(sorted_teams))
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
        known_team_count=len(known),
        unknown_team_count=unknown,
    )


def analyze_option(
    sorted_teams: list[SnapshotTeam],
    sizes: tuple[int, ...],
    typical_gap: Optional[float],
    *,
    current_count: Optional[int] = None,
) -> dict[str, Any]:
    current_count = len(sorted_teams) if current_count is None else current_count
    family = bracket_family_label(sorted_teams[0].draw_kind if sorted_teams else "womens")
    brackets: list[BracketPreview] = []
    cuts: list[CutAnalysis] = []
    cursor = 1
    for index, size in enumerate(sizes):
        preview = _bracket_metrics(sorted_teams, size, cursor)
        letter = _letter_for_index(index)
        preview.letter = letter
        preview.label = f"{family} {letter}"
        brackets.append(preview)
        cursor += size

    for index in range(len(brackets) - 1):
        upper = brackets[index]
        lower = brackets[index + 1]
        provisional = upper.rank_end > current_count or lower.rank_start > current_count
        if provisional:
            cuts.append(
                CutAnalysis(
                    from_label=upper.label,
                    to_label=lower.label,
                    upper_rank=upper.rank_end,
                    lower_rank=lower.rank_start,
                    upper_team_key="",
                    lower_team_key="",
                    upper_team_name="",
                    lower_team_name="",
                    upper_rating=None,
                    lower_rating=None,
                    rating_gap=None,
                    quality="Provisional",
                    provisional=True,
                    message=(
                        "Rating cut cannot yet be fully evaluated because this boundary includes "
                        "teams that have not registered."
                    ),
                    neighborhood=[],
                )
            )
            continue
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
                quality=_cut_quality_label(gap, typical_gap, False),
                neighborhood=_neighborhood(sorted_teams, upper.rank_end),
            )
        )

    return {
        "optionKey": option_key(sizes),
        "sizes": list(sizes),
        "brackets": [bracket.to_dict() for bracket in brackets],
        "cuts": [cut.to_dict() for cut in cuts],
        "custom": False,
        "fakeTeamCount": 0,
    }


def score_option(
    option: dict[str, Any],
    *,
    current_count: int,
    forecast_count: int,
    unrated_count: int,
    partial_count: int,
    max_cut_gap: Optional[float],
    has_unavoidable_small: bool,
) -> dict[str, Any]:
    sizes = tuple(option["sizes"])
    reasons: list[str] = []
    known_cuts = [cut for cut in option["cuts"] if not cut.get("provisional")]
    provisional_cuts = [cut for cut in option["cuts"] if cut.get("provisional")]
    cut_gaps = [cut["ratingGap"] for cut in known_cuts if cut.get("ratingGap") is not None]

    if max_cut_gap and max_cut_gap > 0 and known_cuts:
        raw_cut = sum(cut_gaps) if cut_gaps else 0.0
        cut_quality = min(CUT_QUALITY_MAX, CUT_QUALITY_MAX * (raw_cut / (max_cut_gap * max(1, len(known_cuts)))))
    elif not option["cuts"]:
        cut_quality = 18.0 if forecast_count <= MAX_BRACKET_SIZE else 8.0
    elif not known_cuts:
        cut_quality = 6.0
    else:
        cut_quality = 10.0 if cut_gaps else 4.0

    for cut in known_cuts:
        gap = cut.get("ratingGap")
        gap_text = f"{gap:.2f}" if gap is not None else "n/a"
        prefix = "+" if cut.get("quality") in {"Strong", "Good"} else "-"
        reasons.append(f"{prefix} {cut['quality']} natural rating break after #{cut['upperRank']} · Gap {gap_text}")
    if len(sizes) == 1:
        reasons.append("+ Single bracket — no rating cut required")

    operational_count = sum(1 for size in sizes if is_operational_size(size))
    awkward_count = sum(1 for size in sizes if is_awkward_size(size))
    size_quality = SIZE_QUALITY_PER_OPERATIONAL * operational_count
    if operational_count == len(sizes) and sizes:
        size_quality += ALL_OPERATIONAL_BONUS
        reasons.append("+ All bracket sizes operationally preferred")
    if len(sizes) == 1 and MIN_BRACKET_SIZE <= sizes[0] <= MAX_BRACKET_SIZE:
        size_quality += SINGLE_BRACKET_BONUS
        reasons.append("+ One healthy-sized bracket")
    elif len(sizes) > 1:
        if max(sizes) - min(sizes) <= 8:
            size_quality += BALANCE_BONUS
            reasons.append("+ Balanced field sizes")
        else:
            reasons.append("- Bracket sizes are usable but uneven")
        if len(sizes) > 1:
            size_quality += max(0.0, 8.0 - pstdev(sizes))

    min_brackets = max(1, (forecast_count + MAX_BRACKET_SIZE - 1) // MAX_BRACKET_SIZE)
    extra_penalty = 0.0
    if len(sizes) > min_brackets:
        extra_penalty = EXTRA_BRACKET_PENALTY * (len(sizes) - min_brackets)
        reasons.append("- Extra brackets beyond the minimum needed for the field")

    awkward_penalty = AWKWARD_SIZE_PENALTY * awkward_count
    if awkward_count and cut_quality >= MATERIAL_CUT_IMPROVEMENT:
        rebate = min(awkward_penalty, MATERIAL_CUT_IMPROVEMENT * (cut_quality / CUT_QUALITY_MAX))
        awkward_penalty -= rebate
        reasons.append("+ Rating-cut improvement is large enough to justify an awkward size")
    elif awkward_count:
        reasons.append(f"- Awkward bracket size penalty ({awkward_count} non-standard size(s))")

    tiny_penalty = 0.0
    tiny_parts = [size for size in sizes if size < MIN_BRACKET_SIZE]
    very_small = [size for size in sizes if size in SMALL_FINAL_RANGE]
    if tiny_parts and not has_unavoidable_small:
        tiny_penalty += TINY_UNDER_8_PENALTY * len(tiny_parts)
        reasons.append("- Contains an undersized bracket below 8")
    elif very_small and forecast_count >= 16 and len(sizes) > 1:
        tiny_penalty += VERY_SMALL_PENALTY * len(very_small)
        reasons.append("- Penalized for an unnecessarily tiny final bracket")

    provisional_penalty = PROVISIONAL_CUT_PENALTY * len(provisional_cuts)
    if forecast_count > current_count:
        provisional_penalty += UNKNOWN_FUTURE_PENALTY
        unknown = forecast_count - current_count
        reasons.append(
            f"- {unknown} additional team{'s' if unknown != 1 else ''} not yet known. "
            "Final rating cut positions may move as registration changes."
        )
    if provisional_cuts:
        reasons.append("- One or more cuts are provisional because expected teams have not registered")
    if forecast_count < current_count:
        reasons.append(
            f"Planning target is {current_count - forecast_count} team(s) below the current registration count. "
            f"Rating cut analysis is based on the current {current_count}-team field."
        )

    unrated_penalty = (UNRATED_PENALTY * unrated_count) + (PARTIAL_PENALTY * partial_count)
    if unrated_count or partial_count:
        reasons.append(f"- {unrated_count + partial_count} current team(s) need rating review — confidence is lower")

    total = round(
        cut_quality
        + size_quality
        - extra_penalty
        - awkward_penalty
        - tiny_penalty
        - provisional_penalty
        - unrated_penalty,
        3,
    )
    return {
        "cutQuality": round(cut_quality, 3),
        "sizeQuality": round(size_quality, 3),
        "awkwardSizePenalty": round(awkward_penalty, 3),
        "tinyBracketPenalty": round(tiny_penalty, 3),
        "provisionalCutPenalty": round(provisional_penalty, 3),
        "unratedTeamPenalty": round(unrated_penalty, 3),
        "extraBracketPenalty": round(extra_penalty, 3),
        "total": total,
        "reasons": reasons,
    }


def _cut_signature(option: dict[str, Any]) -> tuple[int, ...]:
    return tuple(int(cut["upperRank"]) for cut in option.get("cuts") or [])


def _size_profile(option: dict[str, Any]) -> tuple[int, ...]:
    return tuple(sorted(option.get("sizes") or []))


def diversify_options(scored: list[dict[str, Any]], limit: int = MAX_DEFAULT_SCENARIOS) -> list[dict[str, Any]]:
    """Keep the best option, then add meaningfully different structures."""
    if not scored:
        return []
    selected = [scored[0]]
    for candidate in scored[1:]:
        if len(selected) >= limit:
            break
        cand_cuts = _cut_signature(candidate)
        cand_profile = _size_profile(candidate)
        same_family = 0
        skip = False
        for existing in selected:
            if cand_cuts == _cut_signature(existing) and cand_profile == _size_profile(existing):
                skip = True
                break
            if cand_profile == _size_profile(existing):
                same_family += 1
        if skip or same_family >= MAX_PERMUTATION_FAMILY:
            continue
        selected.append(candidate)
    return selected


def build_scored_option(
    sorted_teams: list[SnapshotTeam],
    sizes: tuple[int, ...],
    *,
    typical_gap: Optional[float],
    current_count: int,
    forecast_count: int,
    unrated_count: int,
    partial_count: int,
    max_cut_gap: Optional[float],
    has_unavoidable_small: bool,
    custom: bool = False,
) -> dict[str, Any]:
    option = analyze_option(sorted_teams, sizes, typical_gap, current_count=current_count)
    option["custom"] = custom
    option["score"] = score_option(
        option,
        current_count=current_count,
        forecast_count=forecast_count,
        unrated_count=unrated_count,
        partial_count=partial_count,
        max_cut_gap=max_cut_gap,
        has_unavoidable_small=has_unavoidable_small,
    )
    option["recommended"] = False
    return option


def analyze_custom_structure(
    teams: list[SnapshotTeam],
    sizes: tuple[int, ...],
    *,
    forecast_count: Optional[int] = None,
) -> dict[str, Any]:
    sorted_teams = sort_teams_for_planning(teams)
    current_count = len(sorted_teams)
    target = current_count if forecast_count is None else forecast_count
    validate_custom_sizes(sizes, target)
    typical_gap = _median(_adjacent_gaps([team.team_rating for team in sorted_teams]))
    generated = [
        analyze_option(sorted_teams, parts, typical_gap, current_count=current_count)
        for parts in generate_split_sizes(target)
    ]
    custom_raw = analyze_option(sorted_teams, sizes, typical_gap, current_count=current_count)
    known_gaps = [
        cut["ratingGap"]
        for option in (*generated, custom_raw)
        for cut in option["cuts"]
        if cut.get("ratingGap") is not None
    ]
    option = build_scored_option(
        sorted_teams,
        sizes,
        typical_gap=typical_gap,
        current_count=current_count,
        forecast_count=target,
        unrated_count=sum(1 for team in sorted_teams if team.rating_status == RATING_STATUS_MISSING),
        partial_count=sum(1 for team in sorted_teams if team.rating_status == RATING_STATUS_PARTIAL),
        max_cut_gap=max(known_gaps) if known_gaps else None,
        has_unavoidable_small=target < MIN_BRACKET_SIZE,
        custom=True,
    )
    return option


def plan_draw(
    draw_kind: str,
    teams: list[SnapshotTeam],
    forecast_count: Optional[int] = None,
) -> dict[str, Any]:
    sorted_teams = sort_teams_for_planning(teams)
    current_count = len(sorted_teams)
    if forecast_count is None:
        target = current_count
    else:
        target = int(forecast_count)
    unrated_count = sum(1 for team in sorted_teams if team.rating_status == RATING_STATUS_MISSING)
    partial_count = sum(1 for team in sorted_teams if team.rating_status == RATING_STATUS_PARTIAL)
    unknown_count = max(0, target - current_count)
    shrink_count = max(0, current_count - target)

    if target <= 0:
        return {
            "drawKind": draw_kind,
            "drawLabel": bracket_family_label(draw_kind),
            "teamCount": current_count,
            "currentCount": current_count,
            "forecastCount": target,
            "unknownCount": 0,
            "shrinkCount": shrink_count,
            "unratedCount": unrated_count,
            "partialCount": partial_count,
            "ratingReviewNeeded": unrated_count + partial_count,
            "ratingReviewTeams": rating_review_teams(sorted_teams),
            "byeLogicApplicable": BYE_LOGIC_APPLICABLE,
            "generatedCount": 0,
            "optionCount": 0,
            "topOptionCount": 0,
            "options": [],
            "teams": [_preview_team(index + 1, team) for index, team in enumerate(sorted_teams)],
            "planningNote": "Forecast is 0 — no bracket plan was generated for this draw.",
        }

    sizes_list = generate_split_sizes(target)
    typical_gap = _median(_adjacent_gaps([team.team_rating for team in sorted_teams]))
    analyzed = [analyze_option(sorted_teams, sizes, typical_gap, current_count=current_count) for sizes in sizes_list]
    known_gaps = [cut["ratingGap"] for option in analyzed for cut in option["cuts"] if cut.get("ratingGap") is not None]
    max_cut_gap = max(known_gaps) if known_gaps else None
    has_unavoidable_small = target < MIN_BRACKET_SIZE

    scored = []
    for option in analyzed:
        score = score_option(
            option,
            current_count=current_count,
            forecast_count=target,
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
    selected = diversify_options(scored, MAX_DEFAULT_SCENARIOS)
    if selected:
        selected[0]["recommended"] = True

    note = None
    if unknown_count:
        note = (
            f"Planning target: {target} teams. Currently registered: {current_count} teams. "
            f"{unknown_count} additional team{'s' if unknown_count != 1 else ''} "
            "are not yet known. Final rating cut positions may move as registration changes."
        )
    elif shrink_count:
        note = (
            f"Planning target is {shrink_count} team{'s' if shrink_count != 1 else ''} below the current "
            f"registration count. Rating cut analysis is based on the current {current_count}-team field."
        )

    return {
        "drawKind": draw_kind,
        "drawLabel": bracket_family_label(draw_kind),
        "teamCount": current_count,
        "currentCount": current_count,
        "forecastCount": target,
        "unknownCount": unknown_count,
        "shrinkCount": shrink_count,
        "unratedCount": unrated_count,
        "partialCount": partial_count,
        "ratingReviewNeeded": unrated_count + partial_count,
        "ratingReviewTeams": rating_review_teams(sorted_teams),
        "byeLogicApplicable": BYE_LOGIC_APPLICABLE,
        "generatedCount": len(scored),
        "optionCount": len(selected),
        "topOptionCount": len(selected),
        "options": selected,
        "teams": [_preview_team(index + 1, team) for index, team in enumerate(sorted_teams)],
        "planningNote": note,
    }


def plan_snapshot(
    active_teams: list[SnapshotTeam],
    forecasts: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    by_draw: dict[str, list[SnapshotTeam]] = {}
    for team in active_teams:
        by_draw.setdefault(team.draw_kind, []).append(team)
    draws = []
    for draw_kind, teams in sorted(by_draw.items()):
        forecast = None if not forecasts else forecasts.get(draw_kind)
        draws.append(plan_draw(draw_kind, teams, forecast))
    # Include forecast-only draws with no current teams only when staff set a positive forecast
    # for an existing draw; empty draws stay omitted.
    return {
        "draws": draws,
        "maxBracketSize": MAX_BRACKET_SIZE,
        "minBracketSize": MIN_BRACKET_SIZE,
        "maxForecastTeams": MAX_FORECAST_TEAMS,
        "preferredBracketSizes": list(OPERATIONAL_BRACKET_SIZES),
        "awkwardBracketSizes": list(AWKWARD_BRACKET_SIZES),
        "maxDefaultScenarios": MAX_DEFAULT_SCENARIOS,
        "byeLogicApplicable": BYE_LOGIC_APPLICABLE,
        "teamRatingFormula": "sum_of_player_ntrp",
        "forecasts": forecasts or {},
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
