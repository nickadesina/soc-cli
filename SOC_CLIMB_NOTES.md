# Soc-Climb Codebase Notes (Current)

## Overview
- Core package: `src/soc_climb`.
- In-memory directed weighted graph (`SocGraph`) with JSON/CSV persistence.
- FastAPI web API (`src/soc_climb/web.py`) and static Cytoscape client (`src/soc_climb/static/`).
- Main pathfinding algorithm is Dijkstra with edge-distance cost only.

## Data Model
- `PersonNode` in `src/soc_climb/models.py` now uses:
  - `id: str`
  - `name: str`
  - `schools: List[str]`
  - `employers: List[str]`
  - `location: str`
  - `tier: int | None` (`1` highest, `4` lowest; descriptive only)
  - `dependency_weight: int` (`1` strongest, `5` weakest; descriptive only)
  - `decision_nodes: List[DecisionNode]`
  - `platforms: Dict[str, str]` (descriptive only)
  - `societies: Dict[str, int]` (membership strength rank, `1..5`, `1` strongest)
  - `ecosystems: List[str]`
  - `family_friends_links: List[FamilyFriendLink]`
  - `notes: str` (descriptive only)
- Nested types:
  - `DecisionNode { org, role, start, end }`, where `start/end` are ISO date strings or `None`.
  - `FamilyFriendLink { person_id, relationship, alliance_signal }`.
- Validation enforced in model:
  - `tier` in `1..4` when present.
  - `dependency_weight` in `1..5`.
  - each `societies[...]` rank in `1..5` and int.
  - decision node dates must parse with `date.fromisoformat`.

```python
# Proposed auto-edge algorithm (integer distance, v2):
# - smaller integer => closer relationship
# - larger integer => farther relationship
# - run this whenever a new person is added
# - all produced edge distances are integers
# - optional top-K cap if you decide to keep graph sparse later
#
# Output distance scale: 1..12
#   1 = very close
#   12 = weak/indirect
#
# IMPORTANT:
# If this distance model is adopted, shortest-path should use direct
# distance accumulation (sum of edge distances), not 1 / weight.

from datetime import date


# Output distance scale
MIN_DISTANCE = 1
MIN_INFERRED_DISTANCE = 2  # reserve 1 mostly for strongest explicit ties
MAX_DISTANCE = 12

# Only infer edges if there is meaningful evidence (unless explicit)
RELEVANCE_THRESHOLD = 5

# Score shaping
SCORE_DIVISOR = 2
MAX_CLOSENESS_STEPS = 10

# Category caps (prevents clique explosion)
CAP_SCHOOLS = 6
CAP_EMPLOYERS = 8
CAP_ECOSYSTEMS = 4
CAP_PLATFORMS = 2
CAP_LOCATION = 2
CAP_DECISION = 10
CAP_SOCIETIES = 8

# Explicit tie policy
EXPLICIT_DISTANCE = 2

assert MIN_DISTANCE >= 1
assert MIN_INFERRED_DISTANCE >= MIN_DISTANCE
assert MAX_DISTANCE > MIN_INFERRED_DISTANCE


def _parse_iso(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return date.fromisoformat(d)
    except Exception:
        return None


def _years_ago(d: date | None, today: date) -> int | None:
    if not d:
        return None
    delta_days = (today - d).days
    if delta_days < 0:
        return 0
    return delta_days // 365


def _clip_int(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else hi if x > hi else x


def _set_overlap_points(weight: int, a: set[str], b: set[str]) -> int:
    """
    Integer-only overlap scoring using scaled intersection:
      weight * |intersection|
    """
    if not a or not b:
        return 0
    inter = len(a & b)
    return weight * inter


def _society_score(a: dict[str, int], b: dict[str, int]) -> int:
    """
    Same society + similar rank => closer.
    Ranks are 1..5 (1 strongest). Closer ranks get more points.
    """
    score = 0
    for name, ra in a.items():
        rb = b.get(name)
        if rb is None:
            continue
        score += max(1, 4 - abs(ra - rb))
    return score


def _tier_assortativity(tier_a: int | None, tier_b: int | None) -> int:
    """
    Small bump for same/near tiers (descriptive tiers only; this is for inference).
    """
    if tier_a is None or tier_b is None:
        return 0
    diff = abs(tier_a - tier_b)
    return 2 if diff == 0 else 1 if diff == 1 else 0


def _date_ranges_overlap(
    a_start: date | None,
    a_end: date | None,
    b_start: date | None,
    b_end: date | None,
) -> bool:
    """
    Treat None end as open-ended. Treat None start as unknown => no overlap credit.
    """
    if a_start is None or b_start is None:
        return False
    a_e = a_end or date.max
    b_e = b_end or date.max
    return not (a_e < b_start or b_e < a_start)


def _pair_decision_score(a_start, a_end, b_start, b_end, today: date) -> int:
    if _date_ranges_overlap(a_start, a_end, b_start, b_end):
        return 6
    a_ref = a_end or a_start
    b_ref = b_end or b_start
    ya = _years_ago(a_ref, today)
    yb = _years_ago(b_ref, today)
    if ya is None or yb is None:
        return 1
    yrs = min(ya, yb)
    return 3 if yrs < 3 else 2 if yrs < 7 else 1


def _decision_node_overlap_score(nodes_a, nodes_b, today: date) -> int:
    """
    Org overlap, time-aware.
    Uses best-match-per-org to avoid repeated-org row inflation.
    """
    by_org_a: dict[str, list[tuple[date | None, date | None]]] = {}
    by_org_b: dict[str, list[tuple[date | None, date | None]]] = {}

    for n in nodes_a:
        org = getattr(n, "org", None)
        if not org:
            continue
        by_org_a.setdefault(org, []).append(
            (_parse_iso(getattr(n, "start", None)), _parse_iso(getattr(n, "end", None)))
        )
    for n in nodes_b:
        org = getattr(n, "org", None)
        if not org:
            continue
        by_org_b.setdefault(org, []).append(
            (_parse_iso(getattr(n, "start", None)), _parse_iso(getattr(n, "end", None)))
        )

    score = 0
    shared_orgs = set(by_org_a) & set(by_org_b)
    for org in shared_orgs:
        best = 0
        for a_start, a_end in by_org_a[org]:
            for b_start, b_end in by_org_b[org]:
                best = max(best, _pair_decision_score(a_start, a_end, b_start, b_end, today))
        score += best
    return score


def _diminishing_returns(score: int) -> int:
    """
    Integer-only mild compression to prevent runaway closeness in dense cliques.
    A simple concave transform: floor(sqrt(score) * 4).
    """
    if score <= 0:
        return 0
    r = int(score ** 0.5)
    return r * 4


def _score_to_distance(
    score: int,
    *,
    min_distance: int,
    max_closeness_steps: int,
) -> int:
    """
    Map evidence score -> integer distance.
    Higher score => smaller distance.
    """
    span = MAX_DISTANCE - min_distance
    steps = score // SCORE_DIVISOR
    steps = _clip_int(steps, 0, min(span, max_closeness_steps))
    dist = MAX_DISTANCE - steps
    return _clip_int(dist, min_distance, MAX_DISTANCE)


def edge_distance_value(new_person, other_person, *, today: date | None = None) -> tuple[int, bool] | None:
    """
    Returns (distance, explicit_link) or None if not relevant.
    Safe for Dijkstra (non-negative integer weights only).
    """
    if today is None:
        today = date.today()

    explicit = False
    score = 0

    # Explicit family/friends ties (dominant)
    new_links = getattr(new_person, "family_friends_links", []) or []
    other_links = getattr(other_person, "family_friends_links", []) or []
    new_link_ids = {f.person_id for f in new_links if getattr(f, "person_id", None)}
    other_link_ids = {f.person_id for f in other_links if getattr(f, "person_id", None)}
    if other_person.id in new_link_ids:
        score += 12
        explicit = True
    if new_person.id in other_link_ids:
        score += 10
        explicit = True
    for link in new_links:
        if getattr(link, "person_id", None) == other_person.id and getattr(link, "alliance_signal", False):
            score += 2
            explicit = True
            break
    for link in other_links:
        if getattr(link, "person_id", None) == new_person.id and getattr(link, "alliance_signal", False):
            score += 2
            explicit = True
            break

    # Inferred evidence by category (capped)
    schools = _set_overlap_points(3, set(getattr(new_person, "schools", []) or []), set(getattr(other_person, "schools", []) or []))
    score += min(CAP_SCHOOLS, schools)

    employers = _set_overlap_points(4, set(getattr(new_person, "employers", []) or []), set(getattr(other_person, "employers", []) or []))
    score += min(CAP_EMPLOYERS, employers)

    ecosystems = _set_overlap_points(2, set(getattr(new_person, "ecosystems", []) or []), set(getattr(other_person, "ecosystems", []) or []))
    score += min(CAP_ECOSYSTEMS, ecosystems)

    # Platform-key overlap is weak evidence.
    plats_a = set((getattr(new_person, "platforms", {}) or {}).keys())
    plats_b = set((getattr(other_person, "platforms", {}) or {}).keys())
    platforms = _set_overlap_points(1, plats_a, plats_b)
    score += min(CAP_PLATFORMS, platforms)

    if getattr(new_person, "location", None) and getattr(new_person, "location", None) == getattr(other_person, "location", None):
        score += CAP_LOCATION

    dn_score = _decision_node_overlap_score(
        getattr(new_person, "decision_nodes", []) or [],
        getattr(other_person, "decision_nodes", []) or [],
        today,
    )
    score += min(CAP_DECISION, dn_score)

    soc_score = _society_score(
        getattr(new_person, "societies", {}) or {},
        getattr(other_person, "societies", {}) or {},
    )
    score += min(CAP_SOCIETIES, soc_score)

    score += _tier_assortativity(
        getattr(new_person, "tier", None),
        getattr(other_person, "tier", None),
    )

    if not explicit and score < RELEVANCE_THRESHOLD:
        return None

    if explicit:
        dist = min(
            EXPLICIT_DISTANCE,
            _score_to_distance(
                score,
                min_distance=MIN_DISTANCE,
                max_closeness_steps=MAX_DISTANCE - MIN_DISTANCE,
            ),
        )
        return dist, True

    shaped = _diminishing_returns(score)
    return (
        _score_to_distance(
            shaped,
            min_distance=MIN_INFERRED_DISTANCE,
            max_closeness_steps=MAX_CLOSENESS_STEPS,
        ),
        False,
    )


def auto_connect_new_person(
    new_person,
    graph,
    *,
    top_k: int | None = None,
    today: date | None = None,
) -> dict[str, int]:
    """
    Returns edges to create from new_person -> existing person id as integer distances.
    - top_k=None: keep all inferred edges passing relevance gate.
    - top_k=N: keep all explicit edges plus closest inferred edges up to N total.
    """
    if today is None:
        today = date.today()

    candidates: list[tuple[str, int, bool]] = []
    for other in graph.people.values():
        if other.id == new_person.id:
            continue
        result = edge_distance_value(new_person, other, today=today)
        if result is None:
            continue
        dist, explicit = result
        candidates.append((other.id, dist, explicit))

    if not candidates:
        return {}

    if top_k is None:
        return {pid: dist for pid, dist, _ in candidates}

    explicit_edges = [(pid, d) for pid, d, is_explicit in candidates if is_explicit]
    inferred_edges = [(pid, d) for pid, d, is_explicit in candidates if not is_explicit]
    inferred_edges.sort(key=lambda x: x[1])

    room = max(0, top_k - len(explicit_edges))
    selected = explicit_edges + inferred_edges[:room]
    return {pid: dist for pid, dist in selected}
```

## Schema vs Algorithm Separation
- `tier` and `dependency_weight` are fully descriptive person attributes (like `notes`).
- They are serialized, validated, filterable, and included in path output metadata.
- They do not affect path scoring or traversal decisions.
- Pathfinding cost is computed from edge distance weight directly.
- `societies` is also descriptive metadata used for filtering and output context; it does not alter path cost.

## Graph Operations (`src/soc_climb/graph.py`)
- People:
  - `add_person(person, overwrite=False)`
  - `remove_person(person_id)` guarantees:
    - removal of all incident edges and edge contexts
    - removal of every remaining `family_friends_links` entry where `link.person_id == person_id`
- Edges:
  - `add_connection(source, target, weight_delta, contexts=None, symmetric=True)`
  - `remove_connection(source, target, symmetric=True)`
- Filtering:
  - `filter_people(**criteria)` supports list membership and dict key/submap matching.
- Safety:
  - no self-loops
  - finite numeric checks for edge/context deltas
  - non-positive cumulative tie weight drops the edge

## Pathfinding (`src/soc_climb/pathfinding.py`)
- `dijkstra_shortest_path(graph, start, goal)`.
- Base traversal cost is the edge distance itself.
- Person metadata does not modify cost.
- `PathResult` returns `nodes`, `edges`, `total_cost`, `total_strength`.
- Node payload includes `tier`, `dependency_weight`, and model metadata fields.

## Persistence (`src/soc_climb/storage.py`)
- JSON:
  - `save_graph_json` / `load_graph_json`
  - serializes full `PersonNode` shape + edges/contexts.
  - default web snapshot path is `data/graph.json` (set in `create_app`).
- CSV:
  - `save_graph_csv` / `load_graph_csv`
  - person columns:
    - `id,name,schools,employers,societies,location,tier,dependency_weight,decision_nodes,platforms,ecosystems,family_friends_links,notes`
  - `decision_nodes` and `family_friends_links` are JSON-encoded lists in cells.
  - `societies` encoding is explicit key/value rank pairs:
    - default list delimiter: `|`
    - default key/value delimiter: `=`
    - example cell: `ivy_club=1|book_society=3|board_circle=5`
  - `societies` values are parsed as ints and then validated by `PersonNode` (`1..5`).

## Societies Encoding Detail
- Canonical model type: `Dict[str, int]` where key is society identifier and value is rank (`1` strongest, `5` weakest).
- JSON payload shape (API + snapshot):
  - `"societies": {"ivy_club": 1, "book_society": 3}`
- CLI input:
  - repeatable flag `--society-rank key=rank`
  - example: `--society-rank ivy_club=1 --society-rank book_society=3`
- CSV node storage:
  - one string column `societies`
  - encoded as `key=rank` pairs joined by `|`
  - decoded by `_parse_int_map` in `src/soc_climb/storage.py`
- Filtering behavior:
  - graph-level filter accepts dict-key matching for societies
  - CLI `--filter-society ivy_club` checks presence of that key in the `societies` map.

## CLI (`src/soc_climb/cli.py`)
Run with:
```bash
python -m soc_climb.cli <command> [options]
```

Supported commands:
- `add-person`
- `remove-person`
- `add-connection`
- `remove-connection`
- `shortest-path`
- `filter`

Selected add-person options:
- `--id`, `--name`, `--school`, `--employer`, `--location`
- `--tier`, `--dependency-weight`
- `--society-rank key=rank`
- `--decision-node '{...json...}'`
- `--platform key=value`
- `--ecosystem`
- `--family-friends-link '{...json...}'`
- `--notes`

Persistence flags:
- `--json <path>`
- or `--nodes-csv <path> --edges-csv <path>`

## Web API (`src/soc_climb/web.py`)
- `GET /api/graph`
- `POST /api/people`
- `POST /api/extract-person` (accepts image upload and/or `name_query`; extracts person form fields with optional web search enrichment)
- `DELETE /api/people/{person_id}`
- `POST /api/connections` (deprecated; returns HTTP `410 Gone` while manual add-connection is disabled)
- `DELETE /api/connections` (deprecated; returns HTTP `410 Gone` while manual delete-connection is disabled)
- `GET /api/path?source=&target=`

Notes:
- People endpoint now validates `tier`, `dependency_weight`, and `societies` ranks.
- Quality endpoints were removed as part of schema migration.
- `POST /api/extract-person` accepts:
  - `image` (optional image upload)
  - `name_query` (optional string, e.g. `Peter Thiel`)
  - `web_search` form flag (default `false`)
- Extraction behavior:
  - if `web_search=false`: returns image-only (or name-only fallback if no image)
  - if `web_search=true`: uses web search enrichment and name-based retry when needed
- Manual add/delete connection flows are currently deprecated and disabled; these endpoints may be reopened in a future update.

## Run Web App
- Install web dependencies in the same interpreter you run the server with:
```bash
py -3.12 -m pip install -e .[web]
```
- Start server from repo root (Python 3.12):
```bash
py -3.12 -m uvicorn soc_climb.web:app --reload --app-dir src
```
- Open site:
  - `http://127.0.0.1:8000/`
- API docs:
  - `http://127.0.0.1:8000/docs`
- Troubleshooting:
  - `Form data requires "python-multipart"`:
    run `py -3.12 -m pip install python-multipart` (or rerun `py -3.12 -m pip install -e .[web]`).
  - `No module named 'soc_climb'`:
    ensure `--app-dir src` is exactly `src` (not `sr`).

## Web Client (`src/soc_climb/static/`)
- `index.html`, `app.js`, `styles.css`.
- Supports:
  - viewing graph
  - tier-based neon node colors:
    - tier `1` = red
    - tier `2` = orange
    - tier `3` = yellow
    - tier `4` = green
  - add/update person (current schema subset)
  - paste/drop/select image and extract visible person fields into add-person form
  - page-level paste support for images (not only dropzone-focused paste)
  - optional name query field in extract panel for direct web-search extraction
  - `Web Search` toggle in extract panel is off by default
  - extracted values populate standard editable form fields; user can modify before save
  - add/delete connection controls are currently deprecated/disabled in the UI and may be reopened later
  - delete person
  - inspect selected node summary

## Ingestion (`src/soc_climb/ingestion.py`)
- Batch and manual application of:
  - `PersonEvent`
  - `EdgeEvent`

## Tests
- Coverage files:
  - `tests/test_graph.py`
  - `tests/test_pathfinding.py`
  - `tests/test_storage.py`
  - `tests/test_cli.py`
  - `tests/test_ingestion.py`
- Includes explicit tests that:
  - `remove_person` cleans dangling `family_friends_links` references
  - `tier` / `dependency_weight` do not influence pathfinding cost

Run:
```bash
pytest -q
```


