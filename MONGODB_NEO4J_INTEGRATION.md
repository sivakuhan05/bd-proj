# MongoDB and Neo4j Integration Documentation
## Political News Bias Detection System

---

## Table of Contents
1. [System Architecture Overview](#system-architecture-overview)
2. [MongoDB: Primary Data Store](#mongodb-primary-data-store)
3. [Neo4j: Knowledge Graph](#neo4j-knowledge-graph)
4. [Data Flow Architecture](#data-flow-architecture)
5. [Integration Patterns](#integration-patterns)
6. [Data Migration and Synchronization](#data-migration-and-synchronization)
7. [Data Storage Decisions](#data-storage-decisions)
8. [Workflow Examples](#workflow-examples)

---

## System Architecture Overview

### Dual-Database Design

The system uses **MongoDB** and **Neo4j** for different, complementary purposes:

```
User Input Article
        ↓
    [FastAPI Endpoint]
        ↓
    [MongoDB] ← Stores: Article, Author, Publisher records
        +
    [Neo4j] ← Queries: Knowledge graph for bias calculation
        ↓
    [Bias Classification Results]
        ↓
    [Both DBs] ← Store: Final classification, signals, inferred nodes
```

### Design Philosophy

**MongoDB is optimized for:**
- **Document storage**: Articles with rich metadata
- **Query flexibility**: Text search, filtering by bias/category/author
- **Transactional consistency**: Article creation/update/deletion
- **Relationship representation by reference**: author_id, publisher_id foreign keys

**Neo4j is optimized for:**
- **Graph traversal**: Finding bias through entity relationships
- **Path analysis**: Discovering connections between entities (1-2 hops)
- **Weighted propagation**: Bias flowing through relationships with decay
- **Dynamic inference**: Creating and updating nodes from article analysis

---

## MongoDB: Primary Data Store

### Database Name
```
Database: "data"
```

### Collections

#### 1. Articles Collection
**Purpose**: Store article content, metadata, and classification results

**Schema**:
```json
{
  "_id": ObjectId("..."),
  "title": "Climate Policy Debate Heats Up",
  "content": "Full article text here...",
  "published_date": "2024-01-15",
  "category": "Politics",
  
  // References to Author and Publisher
  "author_id": ObjectId("..."),
  "publisher_id": ObjectId("..."),
  
  // Direct metadata (also in Neo4j)
  "source": "CNN",
  "publisher_house": "Warner Media",
  "organizations": ["Sierra Club", "Heritage Foundation"],
  "think_tanks": [],
  "keywords": ["climate", "policy", "environment"],
  
  // Topic scoring
  "topic_scores": {
    "climate": -0.7,
    "policy": -0.4
  },
  
  // Engagement metrics
  "engagement": {
    "likes": 150,
    "shares": 45,
    "views": 2500
  },
  
  // User comments
  "comments": [
    {
      "user": "user123",
      "comment": "Great article",
      "likes": 10,
      "timestamp": "2024-01-15T11:00:00Z",
      "flags": []
    }
  ],
  
  // Bias Classification Results (from Neo4j + ML)
  "classification": {
    "label": "Left",
    "score": -0.506,
    "confidence": 0.744,
    "model_version": "hybrid-ml-graph-v1"
  },
  
  // ML Component Results
  "ml_signal": {
    "label": "Left",
    "score": -0.45,
    "confidence": 0.72,
    "model_version": "internal-lexical-v1",
    "diagnostics": {
      "left_hits": 5,
      "right_hits": 2,
      "total_hits": 7
    }
  },
  
  // Graph Component Results
  "graph_signal": {
    "label": "Left",
    "score": -0.55,
    "confidence": 0.78,
    "coverage_ratio": 0.95,
    "available_weight": 0.85,
    "requested_weight": 0.92,
    "status": "ok",
    "inferred_unknown_nodes": 2,
    "evidence": [
      {
        "source_entity": "Anderson Cooper",
        "source_type": "author",
        "matched_node": "CNN",
        "bias_score": -0.45,
        "confidence": 0.80,
        "contribution_weight": 0.207,
        "weighted_contribution": -0.0932
      }
    ]
  },
  
  // Metadata
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:15Z"
}
```

**Key Points**:
- Full article text stored for future re-analysis or search
- Classification results permanently stored for retrieval
- Evidence from graph signal cached for display
- Engagement and comments for comprehensive article record
- All bias/confidence metrics denormalized for API responses

**Indexes**:
```python
articles.create_index([("author_id", ASCENDING)])
articles.create_index([("publisher_id", ASCENDING)])
articles.create_index([("classification.label", ASCENDING)])
articles.create_index([("publisher_house", ASCENDING)])
articles.create_index([("organizations", ASCENDING)])
articles.create_index([("think_tanks", ASCENDING)])
articles.create_index([("keywords", ASCENDING)])
articles.create_index(
    [("title", TEXT), ("content", TEXT), ("keywords", TEXT)],
    name="article_text_index"
)
```

---

#### 2. Authors Collection
**Purpose**: Normalize author data and avoid duplication

**Schema**:
```json
{
  "_id": ObjectId("..."),
  "name": "Anderson Cooper",
  "affiliation": "CNN",
  "aliases": ["A. Cooper", "Andy Cooper"],
  
  // Unique key for deduplication
  "author_key": "anderson cooper::cnn",
  
  // Timestamps
  "created_at": "2024-01-10T08:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Purpose**:
- Deduplicates authors across multiple articles
- Stores normalized name for matching
- Captures author affiliation and aliases
- Used via foreign key (author_id) in articles collection
- Separate from Neo4j Author node (different purposes)

**Indexes**:
```python
authors.create_index([("author_key", ASCENDING)], unique=True)
authors.create_index([("name", ASCENDING)])
```

**Difference from Neo4j Author Node**:
```
MongoDB Author:
  - Article author metadata (name, affiliation, aliases)
  - Used for article storage and retrieval
  - Normalized to avoid duplication in articles
  
Neo4j Author:
  - Entity in knowledge graph with bias information
  - Has bias_score, confidence, importance_weight
  - Connected to publishers and other entities
  - Used for bias inference
```

---

#### 3. Publishers Collection
**Purpose**: Normalize publisher data

**Schema**:
```json
{
  "_id": ObjectId("..."),
  "name": "CNN",
  "website": "https://www.cnn.com",
  "country": "USA",
  "aliases": ["CNN International", "CNN US"],
  
  // Unique key for deduplication
  "publisher_key": "cnn",
  
  // Timestamps
  "created_at": "2024-01-10T08:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Purpose**:
- Deduplicates publishers across articles
- Stores publisher metadata (website, country)
- Used via foreign key (publisher_id) in articles
- Separate from Neo4j Publisher node

**Indexes**:
```python
publishers.create_index([("publisher_key", ASCENDING)], unique=True)
publishers.create_index([("name", ASCENDING)])
```

---

### MongoDB Data Characteristics

| Aspect | Details |
|--------|---------|
| **Primary Key** | MongoDB ObjectId (_id) |
| **Storage Model** | Document-based (JSON-like) |
| **Article Lifespan** | Created, read, updated, deleted |
| **Relationships** | Via ObjectId foreign keys (author_id, publisher_id) |
| **Search** | Full-text search, filtering, aggregation |
| **Consistency** | ACID transactions per document |
| **Bias Data** | Cached results from Neo4j calculations |

---

## Neo4j: Knowledge Graph

### Graph Database Instance

**Connection Details**:
```
URI: $NEO4J_URI (typically neo4j+ssc://xxxx.databases.neo4j.io:7687)
Authentication: $NEO4J_USERNAME, $NEO4J_PASSWORD
Database: $NEO4J_DATABASE (default: "neo4j")
```

### Node Types and Properties

Nodes store bias information for different entity types:

```
Node Types:
  - Author (bias_score: float, importance: 1.00)
  - Publisher (bias_score: float, importance: 0.95)
  - PublisherHouse (bias_score: float, importance: 0.85)
  - Organization (bias_score: float, importance: 0.70)
  - ThinkTank (bias_score: float, importance: 0.70)
  - Topic (bias_score: float, importance: 0.45)
```

### Data Sources for Neo4j

Neo4j data comes from **three sources**, in order of priority:

#### 1. Seed Data (AllSides CSV)
```python
# Command to load seed data
python -m backend.scripts.seed_neo4j --seed-path sample_data/allsides_seed_template.csv
```

**Who executes**: System administrator during initial setup
**Source**: AllSides political bias database
**What's loaded**: 
- Pre-classified publishers, organizations, think tanks
- Known bias scores from AllSides
- Established relationships

**Neo4j Result**:
```cypher
MERGE (n:Publisher {key: "cnn"})
SET
  n.name = "CNN",
  n.bias_score = -0.45,
  n.bias_confidence = 0.85,
  n.bias_label = "Lean Left",
  n.source = "allsides.com",
  n.importance_weight = 0.95
```

#### 2. Article Metadata (User Input)
```python
# When user creates/updates article via API
POST /articles

{
  "title": "...",
  "author": "Anderson Cooper",
  "publisher": "CNN",
  "organizations": ["Sierra Club"],
  "keywords": ["climate"],
  ...
}
```

**Who executes**: User via frontend UI or API
**When**: Each article upload
**What's created**:
- New Author nodes (if not exist)
- New Organization/ThinkTank nodes (if not exist)
- New Topic nodes (from keywords)
- Relationships between these entities

**Neo4j Result**:
```cypher
MERGE (n:Author {key: "anderson cooper"})
ON CREATE SET
  n.created_at = datetime(),
  n.source = "article_metadata"
SET
  n.name = "Anderson Cooper",
  n.importance_weight = 1.00

MERGE (a:Author {key: "anderson cooper"})
MERGE (b:Publisher {key: "cnn"})
MERGE (a)-[r:WRITES_FOR]->(b)
SET r.weight = 0.95, r.source = "article_metadata"
```

#### 3. Inferred Bias (Calculated from Graph)
```python
# During article bias calculation
def evaluate_graph_signal(metadata):
    # ... fetch node neighbors and calculate bias ...
    # For unknown candidates, calculate inferred score
    inferred_score = weighted_sum / weight_sum
    inferred_confidence = 0.20 + 0.55 * (confidence_sum / weight_sum)
    
    # Persist back to Neo4j
    _persist_unknown_inference(unknown_candidates, per_candidate_rollup, default_score)
```

**Who executes**: System automatically during bias calculation
**When**: Article is created/updated
**What's created/updated**:
- Existing nodes WITHOUT bias_score get inferred scores
- Nodes marked as `inferred_from_articles: true`
- Inference model version recorded

**Neo4j Result**:
```cypher
MATCH (n:Organization {key: "sierra club"})
WHERE n.bias_score IS NULL
SET
  n.bias_score = -0.518,
  n.bias_confidence = 0.617,
  n.bias_label = "Lean Left",
  n.inferred_from_articles = true,
  n.inference_model = "graph-inference-v1",
  n.source = coalesce(n.source, "article_inference")
```

### Key Question: Is Neo4j Data Migrated from MongoDB?

**Answer: NO - Not at all. 100% Separate.**

```
MongoDB contains:              Neo4j contains:
  - Article records             - Entity nodes
  - Author references           - Relationships between entities
  - Publisher references        - Bias scores for entities
  - Engagement data             - Inferred knowledge
  - Comments                    - No article content
  - Full article text           - No engagement data
  - Bias classification results - No comments
```

**Why no migration**:
1. **Different purposes**: MongoDB is transactional document store; Neo4j is graph analysis engine
2. **Different schemas**: Article documents ≠ entity nodes
3. **Different relationships**: MongoDB uses foreign keys; Neo4j uses graph edges
4. **Different access patterns**: MongoDB for retrieval; Neo4j for inference
5. **Performance**: Each optimized for its use case

**Data sourcing**:
- MongoDB: User uploads articles via API
- Neo4j: AllSides seed data + article metadata extraction + inference

---

## Data Flow Architecture

### Complete Article Lifecycle with Both Databases

```
STEP 1: USER INPUT
┌─────────────────────────────────────┐
│ User uploads article via frontend   │
│ - Title, content                    │
│ - Author, publisher                 │
│ - Organizations, keywords, etc.     │
└────────────────┬────────────────────┘
                 ↓
STEP 2: API ENDPOINT
┌─────────────────────────────────────┐
│ POST /articles (main.py)            │
├─────────────────────────────────────┤
│ Create article payload              │
│ Validate and normalize data         │
└────────────────┬────────────────────┘
                 ↓
STEP 3: MONGODB STORAGE - PHASE 1
┌─────────────────────────────────────┐
│ Resolve author in authors collection│
│ - Find or create author_id          │
│ - Store: name, affiliation, aliases │
└────────────────┬────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────┐
│ Resolve publisher in publishers col │
│ - Find or create publisher_id       │
│ - Store: name, website, country     │
└────────────────┬────────────────────┘
                 ↓
STEP 4: NEO4J - BIAS CALCULATION
┌─────────────────────────────────────┐
│ Build scoring context               │
│ - Author name (from author_id)      │
│ - Publisher name (from publisher_id)│
│ - Organizations, keywords, etc.     │
└────────────────┬────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│ kg_scorer.compute_article_bias()    │
├─────────────────────────────────────┤
│ 1. evaluate_graph_signal():         │
│    - Query Neo4j for entity nodes   │
│    - Fetch neighbors (1-2 hops)     │
│    - Calculate weighted bias        │
│    - Mark unknown candidates        │
│                                     │
│ 2. estimate_ml_signal():            │
│    - Count left/right keywords      │
│    - Calculate ML bias score        │
│                                     │
│ 3. combine_signals():               │
│    - Merge ML + graph scores        │
│    - Output final classification    │
└────────────────┬────────────────────┘
                 ↓
STEP 5: NEO4J - PERSISTENCE
┌─────────────────────────────────────┐
│ _persist_unknown_inference()        │
├─────────────────────────────────────┤
│ For each unknown candidate:         │
│ - Calculate inferred bias from      │
│   evidence collected during lookup  │
│ - UPDATE Neo4j node with:          │
│   * bias_score                      │
│   * bias_confidence                 │
│   * inferred_from_articles: true   │
│   * inference_model version         │
└────────────────┬────────────────────┘
                 ↓
STEP 6: MONGODB STORAGE - PHASE 2
┌─────────────────────────────────────┐
│ Insert article into articles        │
├─────────────────────────────────────┤
│ article_doc = {                     │
│   "title": ...,                     │
│   "content": ...,                   │
│   "author_id": ObjectId(...),       │
│   "publisher_id": ObjectId(...),    │
│   "organizations": [...],           │
│   "keywords": [...],                │
│   "engagement": {...},              │
│   "comments": [...],                │
│   "classification": {...},          │ ← From Neo4j
│   "ml_signal": {...},               │ ← From Neo4j
│   "graph_signal": {...},            │ ← From Neo4j
│   "created_at": ...,                │
│   "updated_at": ...                 │
│ }                                   │
│                                     │
│ collections["articles"].insert_one()│
└────────────────┬────────────────────┘
                 ↓
STEP 7: RESPONSE
┌─────────────────────────────────────┐
│ Return hydrated article to user     │
│ - Fetch author from authors table   │
│ - Fetch publisher from publishers   │
│ - Include all classification data   │
└─────────────────────────────────────┘
```

### Data Fields by Database

```
MongoDB (articles):
  ✓ _id, title, content
  ✓ published_date, category
  ✓ author_id, publisher_id (references)
  ✓ source, publisher_house
  ✓ organizations, think_tanks, keywords
  ✓ topic_scores, engagement, comments
  ✓ classification, ml_signal, graph_signal (RESULTS)
  ✓ created_at, updated_at

Neo4j (knowledge graph):
  ✓ Author nodes with bias_score, confidence
  ✓ Publisher nodes with bias_score
  ✓ Organization nodes with (inferred) bias_score
  ✓ ThinkTank nodes with bias_score
  ✓ Topic nodes with bias_score
  ✓ Relationships with weights
  ✓ Importance weights, source metadata
  ✓ inferred_from_articles flag
  ✗ Article content, engagement, comments
  ✗ Full article text, topic scores
```

---

## Integration Patterns

### Pattern 1: Direct Entity Lookup

**When**: Creating an article with known entities
**Flow**:
```python
# User provides: author="Anderson Cooper", publisher="CNN"

# Step 1: MongoDB lookup
author_doc = authors.find_one_and_update(
    {"author_key": "anderson cooper"},
    {"$set": {"name": "Anderson Cooper", ...}},
    upsert=True
)
author_id = author_doc["_id"]

# Step 2: Neo4j lookup (during bias calculation)
node_data = session.execute_read(
    self._fetch_node_with_neighbors,
    "Author",
    "anderson cooper",
    1.00
)
# Returns bias_score, related nodes, etc.

# Step 3: MongoDB storage
article_doc["author_id"] = author_id
article_doc["classification"] = bias_from_graph
articles.insert_one(article_doc)
```

### Pattern 2: Unknown Entity Resolution

**When**: User mentions an entity that doesn't exist in either DB
**Flow**:
```python
# User provides: organizations=["Sierra Club"]

# Step 1: MongoDB - no entry needed (stored in article doc)
article_doc["organizations"] = ["Sierra Club"]

# Step 2: Neo4j - entity created from article metadata
candidates = _build_candidate_entities(metadata)
# Creates candidate: {"label": "Organization", "key": "sierra club", ...}

# Step 3: Neo4j - node merged but has no bias_score yet
_merge_candidate_node(session, candidate)
# MERGE (n:Organization {key: "sierra club"})
# Returns has_bias: false

# Step 4: Bias calculated from related entities
# Graph signal calculation finds evidence from:
#   - Publisher CNN (known bias: -0.45)
#   - Topics in keywords (known bias)

# Step 5: Neo4j - inferred bias persisted
_update_inferred_node_bias(
    session,
    "Organization",
    "sierra club",
    inferred_score=-0.518,
    inferred_confidence=0.617
)

# Step 6: MongoDB - results stored
article_doc["graph_signal"]["inferred_unknown_nodes"] = 1
articles.insert_one(article_doc)

# FUTURE: Next article mentioning "Sierra Club"
# → Neo4j finds existing node with bias_score = -0.518
# → Uses cached value instead of inferring again
```

### Pattern 3: Article Update with Bias Recalculation

**When**: User edits article metadata
**Flow**:
```python
# User updates article: new organizations, keywords

# Step 1: MongoDB update
articles.update_one(
    {"_id": article_id},
    {"$set": {"organizations": new_orgs, "keywords": new_keywords}}
)

# Step 2: Recalculate bias using Neo4j
scoring_context = build_scoring_context(updated_article_doc, ...)
bias_bundle = kg_scorer.compute_article_bias(scoring_context)

# Step 3: Neo4j stores new inferred biases for previously unknown entities

# Step 4: MongoDB stores recalculated results
articles.update_one(
    {"_id": article_id},
    {
        "$set": {
            "classification": bias_bundle["classification"],
            "ml_signal": bias_bundle["ml_signal"],
            "graph_signal": bias_bundle["graph_signal"],
            "updated_at": now
        }
    }
)
```

### Pattern 4: Search with Bias Filter

**When**: User searches for articles with specific bias
**Flow**:
```python
# User searches: GET /articles?bias=Left

# Step 1: MongoDB aggregation
query = {"classification.label": "Left"}
pipeline = [
    {"$match": query},
    {"$sort": {"created_at": -1}},
    {"$skip": 0},
    {"$limit": 50},
    {
        "$lookup": {
            "from": "authors",
            "localField": "author_id",
            "foreignField": "_id",
            "as": "author"
        }
    },
    {
        "$lookup": {
            "from": "publishers",
            "localField": "publisher_id",
            "foreignField": "_id",
            "as": "publisher"
        }
    }
]

articles = collections["articles"].aggregate(pipeline)

# Neo4j not involved in search
# All classification results already cached in MongoDB
```

---

## Data Migration and Synchronization

### Migration Model: **NOT ONE-WAY** 

MongoDB and Neo4j are **NOT synchronized replicas**. They serve different purposes:

#### MongoDB Purpose
```
Transaction Log + Result Cache
↓
- Permanent record of all articles
- Cached classification results
- Search index for user queries
- Historical record of decisions
```

#### Neo4j Purpose
```
Dynamic Knowledge Graph
↓
- Entity relationship analysis
- Bias inference engine
- Learning system (infers unknown entities)
- Real-time graph traversal
```

### Why Not MongoDB → Neo4j?

✗ **No bulk synchronization from MongoDB to Neo4j**

Reasons:
1. **Different schemas**: Article document structure ≠ entity node structure
2. **Different relationships**: MongoDB uses IDs; Neo4j uses semantic edges
3. **Information loss**: Article content not needed in graph; entity links needed
4. **Performance**: Importing all article text to graph would be inefficient
5. **Purpose mismatch**: Graph analyzes entities, not article documents

### Why Not Neo4j → MongoDB?

✗ **No direct export of Neo4j nodes to MongoDB**

Reasons:
1. **Different use cases**: Graph nodes used for calculation, not document storage
2. **Already in MongoDB**: Results cached after calculation
3. **Risk of duplication**: Would create confusing parallel storage
4. **Real-time vs. analytical**: MongoDB needs current article view; Neo4j needs dynamic relationships

### What DOES Synchronize

**Only the Results**:
```
Neo4j Calculation
    ↓
MongoDB Storage

Specifically:
  - classification (final bias label, score, confidence)
  - ml_signal (lexical analysis results)
  - graph_signal (entity relationship results)
  - inferred_unknown_nodes (count of entities updated in Neo4j)
```

**Code Reference**:
```python
# In main.py create_article()
scoring_context = build_scoring_context(article_doc, author_doc, publisher_doc)
bias_bundle = kg_scorer.compute_article_bias(scoring_context)

# Results from Neo4j are stored in MongoDB
article_doc["classification"] = bias_bundle["classification"]
article_doc["ml_signal"] = bias_bundle["ml_signal"]
article_doc["graph_signal"] = bias_bundle["graph_signal"]

collections["articles"].insert_one(article_doc)
```

---

## Data Storage Decisions

### What Goes in MongoDB

| Data | Why | Storage |
|------|-----|---------|
| Article text | Need full text for display and search | Full text indexed |
| Engagement (likes, shares, views) | User interaction metrics | Denormalized |
| Comments | Discussion history | Arrays of comment objects |
| Author metadata (name, affiliation) | Normalize authors across articles | Separate collection |
| Publisher metadata (website, country) | Normalize publishers across articles | Separate collection |
| Topic scores | Article-specific topic analysis | In article doc |
| Classification results | Cached for fast retrieval | In article doc |
| ML signal | Detailed lexical analysis | In article doc |
| Graph signal | Evidence from Neo4j | In article doc (partial) |

### What Goes in Neo4j

| Data | Why | Storage |
|------|-----|---------|
| Entity nodes | Foundation of knowledge graph | Nodes (6 types) |
| Entity relationships | How entities connect | Relationships (8 types) |
| Bias scores | Calculated from graph structure | Node properties |
| Confidence values | How sure we are | Node properties |
| Importance weights | Entity type influence | Node properties |
| Inference metadata | Track how bias was learned | inferred_from_articles flag |
| Relationship weights | Path strength for propagation | Relationship properties |
| Known bias from AllSides | Seed knowledge | From seed CSV |

### What Does NOT Go Anywhere

| Data | Reason |
|------|--------|
| Raw article content in Neo4j | Unnecessary for graph analysis |
| User comments in Neo4j | Not relevant to entity bias |
| Engagement data in Neo4j | Orthogonal to knowledge graph |
| All Neo4j nodes in MongoDB | Results only, not full graph |
| User-generated article metadata in seed data | Dynamic, doesn't go to seed |

---

## Workflow Examples

### Example 1: Complete Article Upload Workflow

**User Action**: Upload new article about climate policy

**Input Data**:
```json
{
  "title": "New Climate Initiative Announced",
  "content": "The administration announced...",
  "author": "Sarah Mitchell",
  "publisher": "The Washington Post",
  "publisher_house": "Nash Holdings",
  "organizations": ["Sierra Club", "EarthJustice"],
  "keywords": ["climate", "environment", "policy"],
  "engagement": {"likes": 0, "shares": 0, "views": 0}
}
```

**Step 1: Resolve Author in MongoDB**
```python
# main.py: resolve_author()
author_doc = authors.find_one_and_update(
    {"author_key": "sarah mitchell"},
    {
        "$set": {"name": "Sarah Mitchell", "updated_at": now},
        "$setOnInsert": {"created_at": now}
    },
    upsert=True,
    return_document=ReturnDocument.AFTER
)
author_id = author_doc["_id"]  # e.g., ObjectId("507f1f77bcf86cd799439011")

# MongoDB result:
# authors collection now has:
# {
#   "_id": ObjectId("507f1f77bcf86cd799439011"),
#   "name": "Sarah Mitchell",
#   "author_key": "sarah mitchell",
#   "created_at": "2024-01-15T10:30:00Z",
#   "updated_at": "2024-01-15T10:30:00Z"
# }
```

**Step 2: Resolve Publisher in MongoDB**
```python
# main.py: resolve_publisher()
publisher_doc = publishers.find_one_and_update(
    {"publisher_key": "the washington post"},
    {
        "$set": {
            "name": "The Washington Post",
            "website": None,
            "country": None,
            "aliases": [],
            "updated_at": now
        },
        "$setOnInsert": {"created_at": now}
    },
    upsert=True,
    return_document=ReturnDocument.AFTER
)
publisher_id = publisher_doc["_id"]  # e.g., ObjectId("507f1f77bcf86cd799439012")

# MongoDB result:
# publishers collection now has:
# {
#   "_id": ObjectId("507f1f77bcf86cd799439012"),
#   "name": "The Washington Post",
#   "publisher_key": "the washington post",
#   "created_at": "2024-01-15T10:30:00Z"
# }
```

**Step 3: Build Scoring Context for Neo4j**
```python
# main.py: build_scoring_context()
scoring_context = {
    "title": "New Climate Initiative Announced",
    "content": "The administration announced...",
    "category": None,
    "author": "Sarah Mitchell",  # From author_doc
    "publisher": "The Washington Post",  # From publisher_doc
    "publisher_house": "Nash Holdings",
    "organizations": ["Sierra Club", "EarthJustice"],
    "think_tanks": [],
    "keywords": ["climate", "environment", "policy"],
    "topic_scores": {}
}
```

**Step 4: Calculate Bias in Neo4j**
```python
# knowledge_graph.py: compute_article_bias()

# 4A: Extract candidates
candidates = [
    {"label": "Author", "key": "sarah mitchell", "base_weight": 0.42},
    {"label": "Publisher", "key": "the washington post", "base_weight": 0.23},
    {"label": "PublisherHouse", "key": "nash holdings", "base_weight": 0.15},
    {"label": "Organization", "key": "sierra club", "base_weight": 0.05},
    {"label": "Organization", "key": "earthjustice", "base_weight": 0.05},
    {"label": "Topic", "key": "climate", "base_weight": 0.025},
    {"label": "Topic", "key": "environment", "base_weight": 0.025},
    {"label": "Topic", "key": "policy", "base_weight": 0.025}
]

# 4B: Merge candidates into Neo4j (creates nodes if missing)
# MERGE (n:Author {key: "sarah mitchell"}) ...
# MERGE (n:Publisher {key: "the washington post"}) ...
# etc.

# 4C: Fetch node data from Neo4j
# For each candidate, execute:
#   MATCH (n:Author {key: "sarah mitchell"})
#   OPTIONAL MATCH p=(n)-[rels*1..2]-(m)
#   WHERE m.bias_score IS NOT NULL
#   ... collect related nodes with bias ...

# 4D: Results from Neo4j:
# Note: Some entities have known bias (from AllSides seed),
#       Some are unknown (no bias_score yet)

Graph lookup results:
  ✓ Publisher "The Washington Post": bias = -0.40, confidence = 0.80
    Related: Nash Holdings (bias -0.35), Topic "climate" (bias -0.70)
  
  ✗ Author "Sarah Mitchell": No node exists yet (created but no bias)
    Evidence from: Publisher (via WRITES_FOR indirect)
  
  ✗ Organization "Sierra Club": Exists but NO bias_score yet
    Evidence from: Publisher CNN affiliates, climate topic
  
  ✓ Organization "EarthJustice": bias = -0.72, confidence = 0.75

unknown_candidates = ["sarah mitchell", "sierra club"]

# 4E: Calculate weighted bias
weighted_score_sum = -0.425  # From known entities
total_contribution_weight = 1.05
graph_score = -0.425 / 1.05 = -0.405 (Lean Left)
graph_confidence = 0.72

# 4F: Calculate ML signal (if enabled)
ml_score = -0.35  (few right-lean terms in "climate policy")
ml_confidence = 0.65

# 4G: Combine signals
final_score = (-0.405 × 0.3) + (-0.35 × 0.7) = -0.367 (Left-leaning)
final_confidence = 0.70

# 4H: Infer bias for unknown candidates
For "sarah mitchell":
  rollup evidence = publisher signal only
  inferred_score = -0.40 (inherited from publisher via WRITES_FOR)
  inferred_confidence = 0.64

For "sierra club":
  rollup evidence = publisher signal + topic evidence
  inferred_score = -0.52 (Lean Left)
  inferred_confidence = 0.68

# 4I: Persist inferred nodes back to Neo4j
MATCH (n:Author {key: "sarah mitchell"})
WHERE n.bias_score IS NULL
SET
  n.bias_score = -0.40,
  n.bias_confidence = 0.64,
  n.bias_label = "Lean Left",
  n.inferred_from_articles = true,
  n.inference_model = "graph-inference-v1"

MATCH (n:Organization {key: "sierra club"})
WHERE n.bias_score IS NULL
SET
  n.bias_score = -0.52,
  n.bias_confidence = 0.68,
  n.bias_label = "Lean Left",
  n.inferred_from_articles = true,
  n.inference_model = "graph-inference-v1"
```

**Step 5: Store Results in MongoDB**
```python
# main.py: create_article()
article_doc = {
    "title": "New Climate Initiative Announced",
    "content": "The administration announced...",
    "published_date": None,
    "category": None,
    "author_id": ObjectId("507f1f77bcf86cd799439011"),
    "publisher_id": ObjectId("507f1f77bcf86cd799439012"),
    "source": "The Washington Post",
    "publisher_house": "Nash Holdings",
    "organizations": ["Sierra Club", "EarthJustice"],
    "think_tanks": [],
    "keywords": ["climate", "environment", "policy"],
    "topic_scores": {},
    "engagement": {"likes": 0, "shares": 0, "views": 0},
    "comments": [],
    
    // FROM NEO4J CALCULATIONS:
    "classification": {
        "label": "Left",
        "score": -0.367,
        "confidence": 0.70,
        "model_version": "hybrid-ml-graph-v1"
    },
    "ml_signal": {
        "label": "Left",
        "score": -0.35,
        "confidence": 0.65,
        "model_version": "internal-lexical-v1",
        "diagnostics": {"left_hits": 1, "right_hits": 0, "total_hits": 1}
    },
    "graph_signal": {
        "label": "Left",
        "score": -0.405,
        "confidence": 0.72,
        "coverage_ratio": 0.90,
        "available_weight": 0.95,
        "requested_weight": 1.00,
        "status": "ok",
        "inferred_unknown_nodes": 2,
        "evidence": [...]
    },
    
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:15Z"
}

articles.insert_one(article_doc)
# MongoDB article now has _id: ObjectId("507f1f77bcf86cd799439013")
```

**Step 6: Return Hydrated Article to User**
```json
{
  "_id": "507f1f77bcf86cd799439013",
  "title": "New Climate Initiative Announced",
  "content": "The administration announced...",
  "author": {
    "_id": "507f1f77bcf86cd799439011",
    "name": "Sarah Mitchell",
    "affiliation": null,
    "author_key": "sarah mitchell"
  },
  "publisher": {
    "_id": "507f1f77bcf86cd799439012",
    "name": "The Washington Post",
    "website": null,
    "country": null,
    "publisher_key": "the washington post"
  },
  "publisher_house": "Nash Holdings",
  "organizations": ["Sierra Club", "EarthJustice"],
  "keywords": ["climate", "environment", "policy"],
  "engagement": {"likes": 0, "shares": 0, "views": 0},
  "classification": {
    "label": "Left",
    "score": -0.367,
    "confidence": 0.70
  },
  "graph_signal": {
    "label": "Left",
    "score": -0.405,
    "confidence": 0.72,
    "inferred_unknown_nodes": 2
  },
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Neo4j State After Upload**:
```
NEW NODES CREATED/UPDATED:
  Author "Sarah Mitchell"
    - bias_score: -0.40 (INFERRED)
    - confidence: 0.64 (INFERRED)
    - inferred_from_articles: true
    - Created from: Article metadata

  Organization "Sierra Club"
    - bias_score: -0.52 (INFERRED)
    - confidence: 0.68 (INFERRED)
    - inferred_from_articles: true
    - Created from: Article metadata

  Organization "EarthJustice"
    - Already existed with bias_score: -0.72 (from seed)
    - No change

  Publisher "The Washington Post"
    - Already existed with bias_score: -0.40 (from seed)
    - No change

  Topics: "climate", "environment", "policy"
    - Created from keywords with no bias (unknown)

NEW RELATIONSHIPS CREATED:
  (Sarah Mitchell)-[:WRITES_FOR]->(The Washington Post) weight: 0.95
  (The Washington Post)-[:OWNED_BY]->(Nash Holdings) weight: 0.90
  (The Washington Post)-[:COVERS]->(climate) weight: 0.62
  (Sierra Club)-[:ADVOCATES_FOR]->(climate) weight: 0.68
  (EarthJustice)-[:ADVOCATES_FOR]->(climate) weight: 0.70
```

---

### Example 2: Search Articles by Bias (MongoDB Only)

**User Action**: Search for "Left-leaning articles about climate"

**Steps**:
```python
# frontend/app.py or /search endpoint
# GET /articles?bias=Left&keyword=climate

# 1. Build MongoDB query
query = {
    "classification.label": "Left",
    "keywords": {"$all": ["climate"]}
}

# 2. Execute MongoDB aggregation
pipeline = [
    {"$match": query},
    {"$sort": {"created_at": -1}},
    {"$skip": 0},
    {"$limit": 50},
    # Join with authors and publishers collections
    {"$lookup": {...from authors...}},
    {"$lookup": {...from publishers...}},
]

articles = collections["articles"].aggregate(pipeline)

# 3. Return results (no Neo4j involved)
# Neo4j is NOT queried for search
# Classification already cached in MongoDB
```

**Key Point**: Search uses MongoDB only. Neo4j bias was calculated once during article creation and cached.

---

### Example 3: Updating Article and Recalculating Bias

**User Action**: Update article keywords from ["climate"] to ["climate", "economics", "policy"]

**Steps**:
```python
# main.py: update_article()

# 1. Update MongoDB article
articles.update_one(
    {"_id": ObjectId("507f1f77bcf86cd799439013")},
    {"$set": {
        "keywords": ["climate", "economics", "policy"],
        "updated_at": now
    }}
)

# 2. Fetch updated article
article = articles.find_one({"_id": ObjectId("507f1f77bcf86cd799439013")})

# 3. Recalculate bias in Neo4j
new_candidates = _build_candidate_entities({
    "keywords": ["climate", "economics", "policy"],
    ...
})
# Now includes: Topic "economics" (new)

# 4. Neo4j topics lookup
# - "climate": existing node with bias -0.70
# - "economics": new node created, no bias yet
# - "policy": existing node with bias None

# 5. New inferred score
# Previous: -0.405
# New:      -0.35  (economics is more neutral, pulls toward center)

# 6. Update MongoDB with new results
articles.update_one(
    {"_id": ObjectId("507f1f77bcf86cd799439013")},
    {"$set": {
        "classification": {
            "label": "Left",
            "score": -0.35,
            "confidence": 0.68
        },
        "graph_signal": {
            "score": -0.35,
            "inferred_unknown_nodes": 1
        },
        "updated_at": now
    }}
)

# 7. Neo4j state
# - Topic "economics" now has inferred bias: -0.15 (Lean Left, weakly)
# - Marked as inferred_from_articles: true
# - For future articles, "economics" bias reused
```

---

## Summary

### MongoDB + Neo4j Integration Summary

| Aspect | MongoDB | Neo4j |
|--------|---------|-------|
| **Primary Role** | Transactional data store | Bias inference engine |
| **Data Types** | Documents (articles, authors, publishers) | Entities (nodes, relationships) |
| **Data Sources** | User input via API | AllSides seed + article metadata + inference |
| **Lifecycle** | Create, read, update, delete | Create & infer, maintain growing graph |
| **Search** | Full-text, filtering, aggregation | Graph traversal, path analysis |
| **Results Storage** | Classification, signals, metrics | Inferred entity bias, relationships |
| **Migration Flow** | NO MongoDB → Neo4j | Results only: Neo4j → MongoDB |
| **Synchronization** | Async (after bias calculation) | N/A (separate systems) |
| **Query Pattern** | For articles & retrieval | For bias calculation |

### Key Takeaways

1. **Not Duplicated**: MongoDB and Neo4j store entirely different data structures
2. **Not Migrated**: No bulk data movement from one to the other
3. **Not Synchronized**: Results flow one direction (Neo4j → MongoDB)
4. **Complementary**: Each optimized for its specific purpose
5. **Flow**: User Input → MongoDB → Neo4j Calculation → Results Back to MongoDB

This hybrid architecture provides:
- Fast article retrieval and search (MongoDB)
- Sophisticated bias inference and learning (Neo4j)
- Scalable, fault-tolerant system with clear separation of concerns
