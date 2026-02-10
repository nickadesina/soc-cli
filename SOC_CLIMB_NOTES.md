# Soc-Climb Codebase Notes (Current)

## Overview
- Core package: `src/soc_climb`.
- In-memory directed weighted graph (`SocGraph`) with JSON/CSV persistence.
- FastAPI web API (`src/soc_climb/web.py`) and static Cytoscape client (`src/soc_climb/static/`).
- Main pathfinding algorithm is Dijkstra with edge-strength cost only.

## Data Model
- `PersonNode` in `src/soc_climb/models.py` now uses:
  - `id: str`
  - `name: str`
  - `family: str`
  - `schools: List[str]`
  - `employers: List[str]`
  - `location: str`
  - `tier: int | None` (`1` highest, `4` lowest; descriptive only)
  - `dependency_weight: int` (`1` strongest, `5` weakest; descriptive only)
  - `decision_nodes: List[DecisionNode]`
  - `platforms: Dict[str, str]`
  - `societies: Dict[str, int]` (membership strength rank, `1..5`, `1` strongest)
  - `ecosystems: List[str]`
  - `close_connections: List[str]`
  - `family_links: List[FamilyLink]`
  - `notes: str`
- Nested types:
  - `DecisionNode { org, role, scope, start, end }`, where `start/end` are ISO date strings or `None`.
  - `FamilyLink { person_id, relationship, alliance_signal }`.
- Validation enforced in model:
  - `tier` in `1..4` when present.
  - `dependency_weight` in `1..5`.
  - each `societies[...]` rank in `1..5` and int.
  - decision node dates must parse with `date.fromisoformat`.

## Schema vs Algorithm Separation
- `tier` and `dependency_weight` are fully descriptive person attributes (like `notes`).
- They are serialized, validated, filterable, and included in path output metadata.
- They do not affect path scoring or traversal decisions.
- Pathfinding cost is computed only from edge weight (`1 / weight`).
- `societies` is also descriptive metadata used for filtering and output context; it does not alter path cost.

## Graph Operations (`src/soc_climb/graph.py`)
- People:
  - `add_person(person, overwrite=False)`
  - `remove_person(person_id)` guarantees:
    - removal of all incident edges and edge contexts
    - removal of `person_id` from every remaining node's `close_connections`
    - removal of every remaining `family_links` entry where `family_link.person_id == person_id`
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
- Base tie traversal cost: `1 / weight`.
- Person metadata does not modify cost.
- `PathResult` returns `nodes`, `edges`, `total_cost`, `total_strength`.
- Node payload includes `tier`, `dependency_weight`, and model metadata fields.

## Persistence (`src/soc_climb/storage.py`)
- JSON:
  - `save_graph_json` / `load_graph_json`
  - serializes full `PersonNode` shape + edges/contexts.
- CSV:
  - `save_graph_csv` / `load_graph_csv`
  - person columns:
    - `id,name,family,schools,employers,societies,location,tier,dependency_weight,decision_nodes,platforms,ecosystems,close_connections,family_links,notes`
  - `decision_nodes` and `family_links` are JSON-encoded lists in cells.
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
- `--id`, `--name`, `--family`, `--school`, `--employer`, `--location`
- `--tier`, `--dependency-weight`
- `--society-rank key=rank`
- `--decision-node '{...json...}'`
- `--platform key=value`
- `--ecosystem`, `--close-connection`
- `--family-link '{...json...}'`
- `--notes`

Persistence flags:
- `--json <path>`
- or `--nodes-csv <path> --edges-csv <path>`

## Web API (`src/soc_climb/web.py`)
- `GET /api/graph`
- `POST /api/people`
- `DELETE /api/people/{person_id}`
- `POST /api/connections`
- `DELETE /api/connections?source=&target=&symmetric=`
- `GET /api/path?source=&target=`

Notes:
- People endpoint now validates `tier`, `dependency_weight`, and `societies` ranks.
- Quality endpoints were removed as part of schema migration.

## Web Client (`src/soc_climb/static/`)
- `index.html`, `app.js`, `styles.css`.
- Supports:
  - viewing graph
  - add/update person (current schema subset)
  - add/delete connections
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
  - `remove_person` cleans dangling `close_connections` and `family_links` references
  - `tier` / `dependency_weight` do not influence pathfinding cost

Run:
```bash
pytest -q
```
