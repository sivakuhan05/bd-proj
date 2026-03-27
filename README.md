# Political News Bias App

FastAPI + Streamlit app for uploading political articles and automatically computing article bias.

Current behavior (`ENABLE_ML_MODEL=false`):
- Final user-facing bias is computed only from the Neo4j knowledge graph.

Future behavior (`ENABLE_ML_MODEL=true`):
- Final user-facing bias is computed as weighted sum of ML score and graph score.

## What The Seed Script Is For

`python -m backend.scripts.seed_neo4j --seed-path sample_data/allsides_seed_template.csv`

This script:
1. Loads `.env` from project root.
2. Connects to your Neo4j Aura instance.
3. Ensures schema constraints exist.
4. Upserts initial nodes and relationships from CSV (AllSides-derived starter data).

It does not scrape AllSides directly. It loads what is in your CSV file.

## Why Aura May Look Empty In Browser

If script says data was inserted but browser looks empty, usually one of these is true:
1. You are viewing a different database than `NEO4J_DATABASE`.
2. Browser graph canvas has no query run yet.
3. You are connected to another Aura instance/project.

Run this in Neo4j Browser:

```cypher
SHOW DATABASES;
MATCH (n) RETURN labels(n) AS labels, count(*) AS cnt ORDER BY cnt DESC;
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt ORDER BY cnt DESC;
```

## Project Structure

- `backend/main.py` - API routes and MongoDB persistence
- `backend/knowledge_graph.py` - Neo4j scoring, unknown-node learning, hybrid combiner
- `backend/neo4j_schema.cypher` - constraints and schema notes
- `backend/scripts/seed_neo4j.py` - seed runner
- `frontend/app.py` - Streamlit UI
- `sample_data/allsides_seed_template.csv` - starter AllSides-based seed rows
- `sample_data/article_sample_known_graph.json` - sample upload payload with metadata already in graph
- `sample_data/article_sample_partial_graph.json` - sample upload payload with partial known/unknown metadata

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure `.env`:

```bash
MONGO_URI=...
NEO4J_URI=...
NEO4J_USERNAME=...
NEO4J_PASSWORD=...
NEO4J_DATABASE=...
ENABLE_ML_MODEL=false
ENABLE_SPARK_ML=true
HYBRID_ML_WEIGHT=0.7
HYBRID_GRAPH_WEIGHT=0.3
INTERNAL_ML_MODEL_VERSION=internal-lexical-v1
R_SCRIPT_BIN=Rscript
```

Notes:
- Keep `ENABLE_ML_MODEL=false` for graph-only output now.
- When your real ML model is ready, set `ENABLE_ML_MODEL=true`.
- `ENABLE_SPARK_ML=true` lets the ML signal use a local Spark session through R (`sparklyr`) when ML mode is enabled.
- If R/Spark is unavailable at runtime, the backend falls back to the existing lexical scorer automatically.

## Run

Backend:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501
```

## R + Spark Setup

The app itself is still Python, but the Spark pieces now run through R.

Install these system tools:

1. Python dependencies:

```bash
pip install -r requirements.txt
```

2. R:
- Install R on your machine so `Rscript` is available on your PATH.

3. Java:
- Install Java 11 or newer.
- Confirm with:

```bash
java -version
Rscript --version
```

4. R packages and local Spark runtime:

```bash
export R_LIBS_USER=~/R/library
export SPARK_VERSION=3.5.1
Rscript backend/spark_jobs/install_packages.R
```

Optional:
- If `Rscript` is not on your PATH, set `R_SCRIPT_BIN` in `.env` to the full executable path.
- If you want a different Spark build for `sparklyr`, set `SPARK_VERSION` before running the installer.

Troubleshooting on Ubuntu:
- If you see package build errors for `curl`, `xml2`, `openssl`, or `httr`, install:

```bash
sudo apt-get update
sudo apt-get install -y r-base-dev libcurl4-openssl-dev libssl-dev libxml2-dev
```

- If you see `Java 11 is only supported for Spark 3.0.0+`, you are pointing to an old Spark runtime.
  Reinstall Spark 3.5.1 for `sparklyr`:

```bash
export R_LIBS_USER=~/R/library
export SPARK_VERSION=3.5.1
Rscript backend/spark_jobs/install_packages.R
```

## Spark Analytics Demo

To demonstrate Spark without changing the app workflow, run the standalone analytics job after you have uploaded a few articles.

Run the Spark job:

```bash
python3 -m backend.spark_jobs.article_analytics --limit 1000 --save-source-json
```

What it does:
- Reads article data from the existing MongoDB collections.
- Hands the dataset to an R `sparklyr` job and builds Spark DataFrames there.
- Prints analytics such as publisher counts, category counts, bias distribution, average engagement, and top keywords.
- Writes CSV reports under `sample_data/spark_reports/`.

## Neo4j Schema

Node labels:
- `Author`
- `Publisher`
- `PublisherHouse`
- `Organization`
- `ThinkTank`
- `Topic`

Important node properties:
- `key` (normalized unique key)
- `name`
- `bias_label` (`Left`, `Lean Left`, `Center`, `Lean Right`, `Right`)
- `bias_score` (`-1..1`)
- `bias_confidence` (`0..1`)
- `importance_weight`

Relationship types used:
- `WRITES_FOR`
- `OWNED_BY`
- `ADVOCATES_FOR`
- `COVERS`
- `AFFILIATED_WITH`

## AllSides Seed Flow

1. Put AllSides-derived values in `sample_data/allsides_seed_template.csv`.
2. Run:

```bash
python -m backend.scripts.seed_neo4j --seed-path sample_data/allsides_seed_template.csv
```

3. Verify in Neo4j Browser:

```cypher
MATCH (n) RETURN count(n) AS nodes;
MATCH ()-[r]->() RETURN count(r) AS relationships;
```

4. Verify from app UI:
- Open `Graph Status` tab in Streamlit.
- Click `Refresh Graph Stats`.
- This calls `GET /graph/stats` and shows node/relationship counts, inferred node count, and type breakdown.

You can also verify by API:

```bash
curl http://localhost:8000/graph/stats
```

## Sample Upload Payloads

Use these ready payloads:
- `sample_data/article_sample_known_graph.json` (all major metadata already present in graph)
- `sample_data/article_sample_partial_graph.json` (mix of known and unknown metadata)

### Comment Input Format In Frontend

In Upload/Update forms, `Comments (one per line)` accepts:
- `user|comment`
- `user|comment|likes|timestamp`
- `user|comment|likes|timestamp|flag1,flag2`

Example:

```text
alex|Good summary
ravi|Need more sources|2|2026-03-23T10:40:00Z
nina|Clear framing|5|2026-03-23T11:10:00Z|insightful
```

Example upload command:

```bash
curl -X POST http://localhost:8000/articles \
  -H "Content-Type: application/json" \
  -d @sample_data/article_sample_known_graph.json
```

## Step-By-Step: How Graph Scoring Works

For every uploaded article, backend executes this sequence.

### Step 1: Build Candidate Entities

From upload metadata, candidate nodes are built for:
- author
- publisher
- publisher house
- organizations
- think tanks
- topics (keywords/category/topic_scores keys)

### Step 2: Ensure Context Nodes and Links Exist

Before scoring:
1. Each candidate node is `MERGE`d (created if missing).
2. Relationship context is `MERGE`d (for example author->publisher, publisher->house, entity->topic links).

This allows even new/unknown metadata to be connected into graph topology.

### Step 3: Traverse Relationships For Bias Evidence (Weighted Evidence Propagation)

For each candidate node:
1. Use direct node bias if available.
2. Traverse up to 2 hops to neighbors with bias (`MATCH (n)-[rels*1..2]-(m)`).
3. Compute contribution per evidence path:

```text
weighted_contribution = bias_score * base_weight * importance_weight * relationship_weight * hop_decay
```

4. Aggregate to graph score:

```text
graph_score = sum(weighted_contribution) / sum(contribution_weight)
```

Worked example (known metadata):
- Author node `Ben Shapiro`: `bias_score=+1.0`, `base_weight=0.42`, `importance=1.0`
- Publisher node `The Daily Wire`: `bias_score=+1.0`, `base_weight=0.23`, `importance=0.95`
- Related topic node `Tax Policy`: `bias_score=+0.5`, path weight produces contribution weight `0.06`

Contributions:
- Author contribution: `+1.0 * 0.42 * 1.0 = +0.42`
- Publisher contribution: `+1.0 * 0.23 * 0.95 = +0.2185`
- Topic contribution: `+0.5 * 0.06 = +0.03`

Graph score:
- Numerator `= 0.42 + 0.2185 + 0.03 = 0.6685`
- Denominator `= 0.42 + 0.2185 + 0.06 = 0.6985`
- `graph_score = 0.6685 / 0.6985 = 0.957`
- Label => `Right`

### Step 4: Compute Graph Confidence

Confidence uses:
- metadata coverage (how much requested metadata found usable evidence)
- weighted confidence of contributing nodes

### Step 5: Handle Unknown Nodes And Learn

If uploaded nodes were unknown (no stored `bias_score`):
1. Their bias/confidence is inferred from available evidence and graph result.
2. Those nodes are updated in Neo4j with inferred `bias_score`, `bias_confidence`, `bias_label`.
3. They are marked as inferred (`inferred_from_articles=true`) for traceability.

Result: future articles can directly use these learned nodes.

Worked example (partial unknown metadata):
- Known nodes:
  - Publisher `CNN` (`Lean Left`)
  - Topic `Climate Policy` (`Lean Left`)
- Unknown nodes in upload:
  - Author `Asha Verma`
  - Organization `Citizen Data Collective`

What happens:
1. Unknown nodes are created and linked to known context via relationships.
2. Graph evidence from known neighbors is aggregated (same weighted formula).
3. For each unknown node:
   - If it has evidence paths, inferred score is:

```text
inferred_score = unknown_weighted_sum / unknown_weight_sum
```

   - Inferred confidence is:

```text
inferred_confidence = clamp(0.20 + 0.55 * (confidence_weighted_sum / unknown_weight_sum), 0.15, 0.85)
```

4. Node is updated with:
   - `bias_score`
   - `bias_confidence`
   - `bias_label`
   - `inferred_from_articles=true`

So on next article upload, that node is no longer unknown and contributes directly.

## Current Final Output Logic (Graph Only)

With `ENABLE_ML_MODEL=false`:
- `classification` shown to user comes from graph signal only.
- UI shows final bias label + confidence from graph pipeline.

## Future Final Output Logic (ML + Graph Sum)

With `ENABLE_ML_MODEL=true`:
- ML model output and graph output are combined:

```text
final_score = (w_ml * ml_score) + (w_graph * graph_score)
```

Default base weights:
- `w_ml = 0.7`
- `w_graph = 0.3`

Graph weight is adjusted lower automatically when graph coverage/confidence is weak.

When ML is enabled:
- Final value shown to user is always the weighted sum of ML and graph scores.
- If graph quality is weak, graph weight is automatically reduced.

Final label mapping:
- `score <= -0.2` -> `Left`
- `score >= 0.2` -> `Right`
- otherwise -> `Center`

## MongoDB Stored Fields Per Article

Each article stores:
- `classification` (final user-facing label/confidence)
- `graph_signal`
- `ml_signal` (disabled now, active when enabled)

## API Endpoints

- `GET /articles`
- `GET /search`
- `GET /graph/stats`
- `POST /articles`
- `PUT /articles/{article_id}`
- `DELETE /articles/{article_id}`
- `POST /graph/bootstrap`
