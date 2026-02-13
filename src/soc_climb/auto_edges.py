from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from .models import PersonNode

if TYPE_CHECKING:
    from .graph import SocGraph


# Output distance scale.
MIN_DISTANCE = 1
MIN_INFERRED_DISTANCE = 2  # Reserve 1 mostly for strongest explicit ties.
MAX_DISTANCE = 12

# Only infer edges if there is meaningful evidence (unless explicit).
RELEVANCE_THRESHOLD = 5

# Score shaping.
SCORE_DIVISOR = 2
MAX_CLOSENESS_STEPS = 10

# Category caps (prevents clique explosion).
CAP_SCHOOLS = 6
CAP_EMPLOYERS = 8
CAP_ECOSYSTEMS = 4
CAP_PLATFORMS = 2
CAP_LOCATION = 2
CAP_DECISION = 10
CAP_SOCIETIES = 8
CAP_FAMILY = 8

# Explicit tie policy.
EXPLICIT_DISTANCE = 2

assert MIN_DISTANCE >= 1
assert MIN_INFERRED_DISTANCE >= MIN_DISTANCE
assert MAX_DISTANCE > MIN_INFERRED_DISTANCE


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def _years_ago(value: date | None, today: date) -> int | None:
    if not value:
        return None
    delta_days = (today - value).days
    if delta_days < 0:
        return 0
    return delta_days // 365


def _clip_int(value: int, low: int, high: int) -> int:
    return low if value < low else high if value > high else value


def _set_overlap_points(weight: int, values_a: set[str], values_b: set[str]) -> int:
    if not values_a or not values_b:
        return 0
    intersection_count = len(values_a & values_b)
    return weight * intersection_count


def _society_score(societies_a: dict[str, int], societies_b: dict[str, int]) -> int:
    score = 0
    for name, rank_a in societies_a.items():
        rank_b = societies_b.get(name)
        if rank_b is None:
            continue
        score += max(1, 4 - abs(rank_a - rank_b))
    return score


def _tier_assortativity(tier_a: int | None, tier_b: int | None) -> int:
    if tier_a is None or tier_b is None:
        return 0
    tier_diff = abs(tier_a - tier_b)
    return 2 if tier_diff == 0 else 1 if tier_diff == 1 else 0


def _date_ranges_overlap(
    a_start: date | None,
    a_end: date | None,
    b_start: date | None,
    b_end: date | None,
) -> bool:
    if a_start is None or b_start is None:
        return False
    a_effective_end = a_end or date.max
    b_effective_end = b_end or date.max
    return not (a_effective_end < b_start or b_effective_end < a_start)


def _pair_decision_score(
    a_start: date | None,
    a_end: date | None,
    b_start: date | None,
    b_end: date | None,
    today: date,
) -> int:
    if _date_ranges_overlap(a_start, a_end, b_start, b_end):
        return 6
    a_ref = a_end or a_start
    b_ref = b_end or b_start
    years_a = _years_ago(a_ref, today)
    years_b = _years_ago(b_ref, today)
    if years_a is None or years_b is None:
        return 1
    most_recent_years = min(years_a, years_b)
    return 3 if most_recent_years < 3 else 2 if most_recent_years < 7 else 1


def _decision_node_overlap_score(nodes_a: list[object], nodes_b: list[object], today: date) -> int:
    by_org_a: dict[str, list[tuple[date | None, date | None]]] = {}
    by_org_b: dict[str, list[tuple[date | None, date | None]]] = {}

    for node in nodes_a:
        org = getattr(node, "org", None)
        if not org:
            continue
        by_org_a.setdefault(org, []).append(
            (_parse_iso(getattr(node, "start", None)), _parse_iso(getattr(node, "end", None)))
        )

    for node in nodes_b:
        org = getattr(node, "org", None)
        if not org:
            continue
        by_org_b.setdefault(org, []).append(
            (_parse_iso(getattr(node, "start", None)), _parse_iso(getattr(node, "end", None)))
        )

    score = 0
    for org in set(by_org_a) & set(by_org_b):
        best_pair_score = 0
        for a_start, a_end in by_org_a[org]:
            for b_start, b_end in by_org_b[org]:
                best_pair_score = max(
                    best_pair_score,
                    _pair_decision_score(a_start, a_end, b_start, b_end, today),
                )
        score += best_pair_score
    return score


def _diminishing_returns(score: int) -> int:
    if score <= 0:
        return 0
    return int(score**0.5) * 4


def _score_to_distance(
    score: int,
    *,
    min_distance: int,
    max_closeness_steps: int,
) -> int:
    span = MAX_DISTANCE - min_distance
    steps = score // SCORE_DIVISOR
    steps = _clip_int(steps, 0, min(span, max_closeness_steps))
    distance = MAX_DISTANCE - steps
    return _clip_int(distance, min_distance, MAX_DISTANCE)


def edge_distance_value(
    new_person: PersonNode,
    other_person: PersonNode,
    *,
    today: date | None = None,
) -> tuple[int, bool] | None:
    if today is None:
        today = date.today()

    explicit_link = False
    score = 0

    # Explicit declared ties (dominant).
    new_close = set(new_person.close_connections or [])
    other_close = set(other_person.close_connections or [])
    if other_person.id in new_close:
        score += 12
        explicit_link = True
    if new_person.id in other_close:
        score += 10
        explicit_link = True

    # Explicit family-link ties.
    new_family_ids = {link.person_id for link in (new_person.family_links or []) if link.person_id}
    other_family_ids = {
        link.person_id for link in (other_person.family_links or []) if link.person_id
    }
    if other_person.id in new_family_ids or new_person.id in other_family_ids:
        score += 12
        explicit_link = True

    # Same family name is weaker evidence than explicit family-link.
    family_points = 0
    if new_person.family and new_person.family == other_person.family:
        family_points += 4
    score += min(CAP_FAMILY, family_points)

    # Inferred evidence by category (all capped).
    score += min(
        CAP_SCHOOLS,
        _set_overlap_points(3, set(new_person.schools or []), set(other_person.schools or [])),
    )
    score += min(
        CAP_EMPLOYERS,
        _set_overlap_points(4, set(new_person.employers or []), set(other_person.employers or [])),
    )
    score += min(
        CAP_ECOSYSTEMS,
        _set_overlap_points(
            2,
            set(new_person.ecosystems or []),
            set(other_person.ecosystems or []),
        ),
    )
    score += min(
        CAP_PLATFORMS,
        _set_overlap_points(
            1,
            set((new_person.platforms or {}).keys()),
            set((other_person.platforms or {}).keys()),
        ),
    )
    if new_person.location and new_person.location == other_person.location:
        score += CAP_LOCATION

    score += min(
        CAP_DECISION,
        _decision_node_overlap_score(
            new_person.decision_nodes or [],
            other_person.decision_nodes or [],
            today,
        ),
    )
    score += min(
        CAP_SOCIETIES,
        _society_score(new_person.societies or {}, other_person.societies or {}),
    )
    score += _tier_assortativity(new_person.tier, other_person.tier)

    if not explicit_link and score < RELEVANCE_THRESHOLD:
        return None

    if explicit_link:
        explicit_distance = min(
            EXPLICIT_DISTANCE,
            _score_to_distance(
                score,
                min_distance=MIN_DISTANCE,
                max_closeness_steps=MAX_DISTANCE - MIN_DISTANCE,
            ),
        )
        return explicit_distance, True

    shaped_score = _diminishing_returns(score)
    inferred_distance = _score_to_distance(
        shaped_score,
        min_distance=MIN_INFERRED_DISTANCE,
        max_closeness_steps=MAX_CLOSENESS_STEPS,
    )
    return inferred_distance, False


def auto_connect_new_person(
    new_person: PersonNode,
    graph: SocGraph,
    *,
    top_k: int | None = None,
    today: date | None = None,
) -> dict[str, int]:
    if top_k is not None and top_k < 0:
        raise ValueError(f"top_k must be >= 0 when provided, got {top_k!r}")
    if today is None:
        today = date.today()

    candidates: list[tuple[str, int, bool]] = []
    for other in graph.people.values():
        if other.id == new_person.id:
            continue
        candidate = edge_distance_value(new_person, other, today=today)
        if candidate is None:
            continue
        distance, is_explicit = candidate
        candidates.append((other.id, distance, is_explicit))

    if not candidates:
        return {}

    if top_k is None:
        return {person_id: distance for person_id, distance, _ in candidates}

    explicit_edges = [(person_id, distance) for person_id, distance, explicit in candidates if explicit]
    inferred_edges = [(person_id, distance) for person_id, distance, explicit in candidates if not explicit]
    inferred_edges.sort(key=lambda edge: edge[1])

    room = max(0, top_k - len(explicit_edges))
    selected = explicit_edges + inferred_edges[:room]
    return {person_id: distance for person_id, distance in selected}


def upsert_person_with_auto_edges(
    graph: SocGraph,
    person: PersonNode,
    *,
    overwrite: bool = True,
    top_k: int | None = None,
    today: date | None = None,
) -> dict[str, int]:
    existed = person.id in graph.people
    graph.add_person(person, overwrite=overwrite)
    if existed:
        graph.clear_incident_edges(person.id)

    distances = auto_connect_new_person(person, graph, top_k=top_k, today=today)
    for other_id, distance in distances.items():
        graph.remove_connection(person.id, other_id, symmetric=True)
        graph.add_connection(person.id, other_id, float(distance), symmetric=True)
    return distances
