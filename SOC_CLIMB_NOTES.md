# Soc-Climb Backend Toolkit

## Overview
- Pure Python module living under `src/soc_climb` with in-memory adjacency representation.
- Focused on strongly-typed people nodes (`PersonNode`) and weighted ties managed by `SocGraph`.
- Pathfinding utilities surface user-friendly payloads with per-hop metadata and cost/strength rollups.

## Data Model
- `PersonNode` captures id, label, affiliations (schools, employers, societies), location, grad year, social handles, and optional status score.
- `SocGraph` keeps adjacency as `Dict[node_id, Dict[neighbor_id, weight]]` plus context deltas per edge.
- Edge contexts store contributions (shared orgs, follows, etc.) that can grow via ingestion events.

## Pathfinding & Costs
- DFS with depth limit (default 23) for quick feasibility checks.
- Dijkstra-based weighted shortest path honours a configurable cost strategy: dynamic (max-weight inversion), inverse weight, or fixed-range normalisation.
- `PathResult` bundles node details (degree, metadata) and per-edge contexts to optimise UX rendering.

## Weight Handling
- Each context increment shifts the stored weight; non-positive updates prune the tie to keep traversal safe.
- `CostComputer` keeps cost conversion logic centralised so all algorithms behave consistently.

## Storage & Durability
- JSON snapshot: single file with `people` and `edges` collections, suitable for quick backups.
- CSV snapshot: two files (`nodes`, `edges`) with configurable delimiters for lists and key/value blobs.
- Loaders tolerate missing files and rebuild the graph in place.

## Ingestion
- `GraphIngestionService` applies `PersonEvent`/`EdgeEvent` batches for offline loaders.
- Helper methods (`apply_person`, `apply_edge`) support manual updates without any background threads.

## CLI
```
python -m soc_climb.cli <command> [options]
```
- `add-person`: upsert a person (supports repeated `--school`, `--platform`, etc.).
- `add-connection`: increment tie strength with optional context descriptors.
- `shortest-path`: choose DFS or Dijkstra and switch cost strategy to see different cost profiles.
- `filter`: slice people by school, employer, society, location, grad year, or name.
- Use `--json`, `--nodes-csv`, `--edges-csv` to load/persist snapshots (JSON preferred when both provided).

## Tests
- `pytest` suite exercises graph operations, pathfinding correctness, storage round-trips, ingestion helpers, and end-to-end CLI flows.
- Run `pytest` from the repo root (configured to auto-add `src` to `PYTHONPATH`).

## Scalability Notes
- Current design handles ~100k nodes comfortably in memory.
- For denser graphs, export to a NumPy adjacency matrix or a DuckDB edge list (hooks live in storage/ingestion layers).
- Cost strategies operate on current graph weights, so traversal semantics hold after incremental updates.

## Next Steps
- Hook scrapers into `GraphIngestionService` via manual batches and persist deltas.
- Explore DuckDB-backed loaders when snapshot size grows beyond comfortable JSON payloads.

## Usage Examples

### Python API
```python
from soc_climb import PersonNode, SocGraph, GraphIngestionService, dijkstra_shortest_path

graph = SocGraph()
ingestor = GraphIngestionService(graph)

ingestor.apply_person(PersonNode(id="alex", school=["Stanford"], grad_year=2022))
ingestor.apply_person(PersonNode(id="blake", employers=["OpenAI"]))
ingestor.apply_edge("alex", "blake", 4.0, contexts={"school": 1.0, "intro": 3.0})

path = dijkstra_shortest_path(graph, "alex", "blake")
if path:
    print(path.node_ids)              # ['alex', 'blake']
    print(path.total_strength)        # 4.0
    print(path.edges[0].contexts)     # {'school': 1.0, 'intro': 3.0}
```

### CLI Workflow
```bash
# Add two people and tie them together
python -m soc_climb.cli add-person --json data/graph.json --id alex --school Stanford --grad-year 2022
python -m soc_climb.cli add-person --json data/graph.json --id blake --employer OpenAI
python -m soc_climb.cli add-connection --json data/graph.json --source alex --target blake --weight 4 --context school=1 --context intro=3

# Query the strongest path between alex and blake using Dijkstra
python -m soc_climb.cli shortest-path --json data/graph.json --source alex --target blake --algorithm dijkstra

# Filter everyone who overlaps with Stanford
python -m soc_climb.cli filter --json data/graph.json --filter-school Stanford
```

### CSV Snapshot Round Trip
```bash
python -m soc_climb.cli add-person --nodes-csv data/nodes.csv --edges-csv data/edges.csv --id casey --society AlphaBeta
python -m soc_climb.cli add-connection --nodes-csv data/nodes.csv --edges-csv data/edges.csv --source casey --target alex --weight 2 --context society=1

# Back in Python
from soc_climb import load_graph_csv
snapshot = load_graph_csv("data/nodes.csv", "data/edges.csv")
print(snapshot.get_edge_weight("casey", "alex"))
```
