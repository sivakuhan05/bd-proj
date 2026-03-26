# Neo4j Knowledge Graph Documentation
## Political News Bias Detection System

---

## Table of Contents
1. [Overview](#overview)
2. [Knowledge Graph Architecture](#knowledge-graph-architecture)
3. [Node Types and Properties](#node-types-and-properties)
4. [Relationship Types and Weights](#relationship-types-and-weights)
5. [Cypher Queries Used in the System](#cypher-queries-used-in-the-system)
6. [Bias Score Calculation Algorithm](#bias-score-calculation-algorithm)
7. [Bias Calculation for Unknown Nodes](#bias-calculation-for-unknown-nodes)
8. [Inferred Node Creation and Persistence](#inferred-node-creation-and-persistence)
9. [Example Workflows](#example-workflows)

---

## Overview

The system uses Neo4j as a knowledge graph to detect political bias in news articles. The knowledge graph stores:
- **Entities**: Authors, Publishers, Publisher Houses, Organizations, Think Tanks, and Topics
- **Relationships**: Connections between entities with weighted importance
- **Bias Metadata**: Bias scores and confidence values for each entity

The knowledge graph works in conjunction with an optional ML model to provide hybrid bias classification:
- ML Component: Uses keyword analysis to detect political lean from article content
- Graph Component: Uses entity relationships and known bias information to infer article bias
- Final Classification: Weighted combination of both signals (configurable via HYBRID_ML_WEIGHT and HYBRID_GRAPH_WEIGHT)

---

## Knowledge Graph Architecture

### Graph Structure
The knowledge graph is a directed, weighted graph where:
- **Nodes** represent entities in the news ecosystem
- **Edges** represent relationships with importance weights
- **Properties** on nodes store bias information and metadata

### Core Principles
1. **Entity-centric**: All bias information is associated with entities
2. **Evidence-based**: Bias values come from either seed data or graph inference
3. **Weighted propagation**: Bias information flows through relationships with decay
4. **Confidence tracking**: All scores include confidence metrics

### Default Importance Weights by Node Type
```
Author: 1.00 (highest importance - direct article creator)
Publisher: 0.95 (very high - direct content source)
PublisherHouse: 0.85 (high - ownership structure)
Organization: 0.70 (medium-high - associations)
ThinkTank: 0.70 (medium-high - advocacy sources)
Topic: 0.45 (lowest - subject matter)
```

---

## Node Types and Properties

### 1. Author Node
```
Label: Author
Key Property: key (unique normalized name identifier)

Properties:
- name: String (e.g., "John Smith")
- key: String (unique, normalized) [REQUIRED, UNIQUE]
- bias_score: Float (-1.0 to 1.0, where -1 = Left, 0 = Center, 1 = Right)
- bias_confidence: Float (0.0 to 1.0)
- bias_label: String ("Left", "Lean Left", "Center", "Lean Right", "Right")
- importance_weight: Float (0.0 to 1.0) [Default: 1.00]
- source: String (where data originated, e.g., "allsides.com")
- source_url: String (optional URL reference)
- inferred_from_articles: Boolean (true if bias was inferred from relationships)
- inference_model: String (e.g., "graph-inference-v1")
- created_at: DateTime
- updated_at: DateTime
```

### 2. Publisher Node
```
Label: Publisher
Key Property: key (unique normalized name identifier)

Properties:
- name: String (e.g., "CNN", "Fox News")
- key: String (unique, normalized) [REQUIRED, UNIQUE]
- bias_score: Float (-1.0 to 1.0)
- bias_confidence: Float (0.0 to 1.0)
- bias_label: String
- importance_weight: Float [Default: 0.95]
- source: String
- source_url: String (optional)
- inferred_from_articles: Boolean
- inference_model: String
- created_at: DateTime
- updated_at: DateTime
```

### 3. PublisherHouse Node
```
Label: PublisherHouse
Key Property: key (unique normalized name identifier)

Properties:
- name: String (e.g., "Rupert Murdoch's News Corp")
- key: String (unique, normalized) [REQUIRED, UNIQUE]
- bias_score: Float (-1.0 to 1.0)
- bias_confidence: Float (0.0 to 1.0)
- bias_label: String
- importance_weight: Float [Default: 0.85]
- source: String
- source_url: String
- inferred_from_articles: Boolean
- inference_model: String
- created_at: DateTime
- updated_at: DateTime
```

### 4. Organization Node
```
Label: Organization
Key Property: key (unique normalized name identifier)

Properties:
- name: String (e.g., "Planned Parenthood", "NRA")
- key: String (unique, normalized) [REQUIRED, UNIQUE]
- bias_score: Float (-1.0 to 1.0)
- bias_confidence: Float (0.0 to 1.0)
- bias_label: String
- importance_weight: Float [Default: 0.70]
- source: String
- source_url: String
- inferred_from_articles: Boolean
- inference_model: String
- created_at: DateTime
- updated_at: DateTime
```

### 5. ThinkTank Node
```
Label: ThinkTank
Key Property: key (unique normalized name identifier)

Properties:
- name: String (e.g., "Heritage Foundation", "Brookings Institution")
- key: String (unique, normalized) [REQUIRED, UNIQUE]
- bias_score: Float (-1.0 to 1.0)
- bias_confidence: Float (0.0 to 1.0)
- bias_label: String
- importance_weight: Float [Default: 0.70]
- source: String
- source_url: String
- inferred_from_articles: Boolean
- inference_model: String
- created_at: DateTime
- updated_at: DateTime
```

### 6. Topic Node
```
Label: Topic
Key Property: key (unique normalized name identifier)

Properties:
- name: String (e.g., "climate change", "gun rights")
- key: String (unique, normalized) [REQUIRED, UNIQUE]
- bias_score: Float (-1.0 to 1.0)
- bias_confidence: Float (0.0 to 1.0)
- bias_label: String
- importance_weight: Float [Default: 0.45]
- source: String
- source_url: String
- inferred_from_articles: Boolean
- inference_model: String
- created_at: DateTime
- updated_at: DateTime
```

---

## Relationship Types and Weights

### Schema Constraints
```cypher
CREATE CONSTRAINT author_key IF NOT EXISTS FOR (n:Author) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT publisher_key IF NOT EXISTS FOR (n:Publisher) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT publisher_house_key IF NOT EXISTS FOR (n:PublisherHouse) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT organization_key IF NOT EXISTS FOR (n:Organization) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT think_tank_key IF NOT EXISTS FOR (n:ThinkTank) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT topic_key IF NOT EXISTS FOR (n:Topic) REQUIRE n.key IS UNIQUE;
```

### Relationship Types

1. **WRITES_FOR** (Author → Publisher)
   - Meaning: Author writes for publisher
   - Default Weight: 0.95 (very strong signal of author-publisher alignment)

2. **OWNED_BY** (Publisher → PublisherHouse)
   - Meaning: Publisher is owned by publisher house
   - Default Weight: 0.90 (strong ownership signal)

3. **AFFILIATED_WITH** (Publisher → Organization)
   - Meaning: Publisher is affiliated with organization
   - Default Weight: 0.70 (moderate affiliation signal)

4. **ADVOCATES_FOR** (Organization/ThinkTank → Topic)
   - Meaning: Organization/Think Tank advocates for topic
   - Default Weight: 0.65-0.70 (advocacy relationship)

5. **COVERS** (Publisher → Topic)
   - Meaning: Publisher covers topic
   - Default Weight: 0.62 (coverage relationship)

6. **PUBLISHED_BY** (Not currently used in core logic)
   - Alternative to WRITES_FOR in some contexts
   - Default Weight: 0.95

7. **BELONGS_TO** (Not actively used in current version)
   - General membership relationship
   - Weight: Variable

8. **ASSOCIATED_WITH** (Fallback relationship)
   - Default relationship for uncategorized associations
   - Weight: 0.75 (default)

### Relationship Properties
```
Properties per relationship:
- weight: Float (0.0 to 2.0) [Default: 0.8]
- source: String (origin of relationship data)
- updated_at: DateTime
```

---

## Cypher Queries Used in the System

### 1. Schema Initialization Query
**Purpose**: Create unique constraints on all node types to ensure data integrity

```cypher
CREATE CONSTRAINT author_key IF NOT EXISTS FOR (n:Author) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT publisher_key IF NOT EXISTS FOR (n:Publisher) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT publisher_house_key IF NOT EXISTS FOR (n:PublisherHouse) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT organization_key IF NOT EXISTS FOR (n:Organization) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT think_tank_key IF NOT EXISTS FOR (n:ThinkTank) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT topic_key IF NOT EXISTS FOR (n:Topic) REQUIRE n.key IS UNIQUE;
```

**Usage in Code**: `KnowledgeGraphScorer.ensure_schema()` - Called before any graph operations

---

### 2. Seed Node Creation Query
**Purpose**: Create or update nodes from seed data (CSV imports)

```cypher
MERGE (n:<LABEL> {key: $key})
ON CREATE SET n.created_at = datetime()
SET
    n.name = $name,
    n.bias_label = $bias_label,
    n.bias_score = $bias_score,
    n.bias_confidence = $bias_confidence,
    n.importance_weight = $importance_weight,
    n.source = $source,
    n.source_url = $source_url,
    n.updated_at = datetime()
```

**Parameters**:
- `key`: Normalized entity name (unique identifier)
- `name`: Human-readable name
- `bias_label`: "Left", "Lean Left", "Center", "Lean Right", or "Right"
- `bias_score`: Float -1.0 to 1.0
- `bias_confidence`: Float 0.0 to 1.0
- `importance_weight`: Float 0.0 to 1.0
- `source`: Data source (e.g., "allsides.com")
- `source_url`: Optional URL

**Usage in Code**: `KnowledgeGraphScorer.bootstrap_from_csv()` - Called during initialization

**Example**:
```cypher
MERGE (n:Publisher {key: "cnn"})
ON CREATE SET n.created_at = datetime()
SET
    n.name = "CNN",
    n.bias_label = "Lean Left",
    n.bias_score = -0.45,
    n.bias_confidence = 0.85,
    n.importance_weight = 0.95,
    n.source = "allsides.com",
    n.source_url = "https://www.allsides.com/news-source/cnn",
    n.updated_at = datetime()
```

---

### 3. Seed Relationship Creation Query
**Purpose**: Create relationships between nodes during seed data import

```cypher
MERGE (target:<TARGET_LABEL> {key: $target_key})
ON CREATE SET target.name = $target_name, target.created_at = datetime()
SET target.updated_at = datetime()

WITH target
MATCH (source:<SOURCE_LABEL> {key: $source_key})
MERGE (source)-[r:<RELATIONSHIP_TYPE>]->(target)
SET
    r.weight = $relationship_weight,
    r.source = $source,
    r.updated_at = datetime()
```

**Parameters**:
- `source_key`: Key of source node
- `target_key`: Key of target node
- `target_name`: Name of target node (used if creating new)
- `relationship_weight`: Float 0.0 to 2.0
- `source`: Data source

**Usage in Code**: `KnowledgeGraphScorer._seed_row()` - Called for each CSV row

**Example**:
```cypher
MERGE (target:Publisher {key: "cnn"})
ON CREATE SET target.name = "CNN", target.created_at = datetime()
SET target.updated_at = datetime()

WITH target
MATCH (source:PublisherHouse {key: "warner media"})
MERGE (source)-[r:OWNED_BY]->(target)
SET
    r.weight = 0.90,
    r.source = "allsides.com",
    r.updated_at = datetime()
```

---

### 4. Fetch Node with Neighbors Query (Critical for Bias Calculation)
**Purpose**: Retrieve a node and all related nodes up to 2 hops away with bias information

```cypher
MATCH (n:<LABEL> {key: $key})
OPTIONAL MATCH p=(n)-[rels*1..2]-(m)
WHERE m.bias_score IS NOT NULL
WITH n,
     collect({
       node_name: m.name,
       node_type: head(labels(m)),
       bias_score: m.bias_score,
       bias_confidence: coalesce(m.bias_confidence, 0.55),
       importance_weight: coalesce(m.importance_weight, 0.35),
       relationship_weight: reduce(w = 1.0, rel IN rels | w * coalesce(rel.weight, 0.75)),
       hops: size(rels)
     }) AS related_nodes
RETURN {
  node_name: n.name,
  node_type: head(labels(n)),
  bias_score: n.bias_score,
  bias_confidence: coalesce(n.bias_confidence, 0.65),
  importance_weight: coalesce(n.importance_weight, $default_importance),
  related: related_nodes
} AS node_data
```

**Parameters**:
- `key`: Node key to look up
- `default_importance`: Default importance weight if not set on node

**Query Logic Explanation**:

1. **MATCH (n:<LABEL> {key: $key})**: Find the target node by label and key

2. **OPTIONAL MATCH p=(n)-[rels*1..2]-(m)**: Find all nodes within 1-2 hops:
   - Uses bidirectional relationship traversal (-[rels*1..2]-)
   - Matches paths of 1 or 2 relationships
   - OPTIONAL ensures query succeeds even if no related nodes exist

3. **WHERE m.bias_score IS NOT NULL**: Only include related nodes that have known bias scores

4. **reduce(w = 1.0, rel IN rels | w * coalesce(rel.weight, 0.75))**: Calculate cumulative relationship weight:
   - Starts with weight 1.0
   - Multiplies by each relationship weight along the path
   - If relationship lacks weight, defaults to 0.75
   - For 2-hop path: weight = rel1.weight × rel2.weight

5. **size(rels)**: Hop count (1 or 2)

**Usage in Code**: `KnowledgeGraphScorer._fetch_node_with_neighbors()` - Called for each article entity

**Example Query Execution**:
User analyzes article mentioning CNN (Publisher)

```cypher
MATCH (n:Publisher {key: "cnn"})
OPTIONAL MATCH p=(n)-[rels*1..2]-(m)
WHERE m.bias_score IS NOT NULL
WITH n,
     collect({
       node_name: m.name,
       node_type: head(labels(m)),
       bias_score: m.bias_score,
       bias_confidence: coalesce(m.bias_confidence, 0.55),
       importance_weight: coalesce(m.importance_weight, 0.35),
       relationship_weight: reduce(w = 1.0, rel IN rels | w * coalesce(rel.weight, 0.75)),
       hops: size(rels)
     }) AS related_nodes
RETURN {
  node_name: n.name,
  node_type: head(labels(n)),
  bias_score: n.bias_score,
  bias_confidence: coalesce(n.bias_confidence, 0.65),
  importance_weight: coalesce(n.importance_weight, 0.95),
  related: related_nodes
} AS node_data
```

**Expected Result**:
```json
{
  "node_data": {
    "node_name": "CNN",
    "node_type": "Publisher",
    "bias_score": -0.45,
    "bias_confidence": 0.85,
    "importance_weight": 0.95,
    "related": [
      {
        "node_name": "Warner Media",
        "node_type": "PublisherHouse",
        "bias_score": -0.35,
        "bias_confidence": 0.80,
        "importance_weight": 0.85,
        "relationship_weight": 0.90,
        "hops": 1
      },
      {
        "node_name": "Anderson Cooper",
        "node_type": "Author",
        "bias_score": -0.55,
        "bias_confidence": 0.75,
        "importance_weight": 1.00,
        "relationship_weight": 0.95,
        "hops": 1
      },
      {
        "node_name": "Climate Justice",
        "node_type": "Topic",
        "bias_score": -0.70,
        "bias_confidence": 0.65,
        "importance_weight": 0.45,
        "relationship_weight": 0.62 * 0.68,
        "hops": 2
      }
    ]
  }
}
```

---

### 5. Merge Candidate Node Query
**Purpose**: Create nodes from article metadata if they don't exist

```cypher
MERGE (n:<LABEL> {key: $key})
ON CREATE SET
    n.created_at = datetime(),
    n.source = "article_metadata"
SET
    n.name = $name,
    n.source = coalesce(n.source, "article_metadata"),
    n.importance_weight = coalesce(n.importance_weight, $importance_weight),
    n.updated_at = datetime()
RETURN n.bias_score IS NOT NULL AS has_bias
```

**Purpose**: This query:
1. Creates new node if it doesn't exist (from article metadata)
2. Updates name and importance_weight if it does exist
3. Returns whether the node already has bias information
4. Used to identify which entities need bias inference

**Usage in Code**: `KnowledgeGraphScorer._merge_candidate_node()` - Called for article entities

---

### 6. Merge Relationship Query
**Purpose**: Create or update relationships between nodes in article context

```cypher
MATCH (a:<FROM_LABEL> {key: $from_key})
MATCH (b:<TO_LABEL> {key: $to_key})
MERGE (a)-[r:<REL_TYPE>]->(b)
SET
    r.weight = coalesce(r.weight, $weight),
    r.source = coalesce(r.source, "article_metadata"),
    r.updated_at = datetime()
```

**Usage in Code**: `KnowledgeGraphScorer._merge_relationship()` - Called to link article entities

---

### 7. Update Inferred Node Bias Query
**Purpose**: Assign calculated bias to unknown nodes

```cypher
MATCH (n:<LABEL> {key: $key})
WHERE n.bias_score IS NULL
SET
    n.bias_score = $score,
    n.bias_confidence = $confidence,
    n.bias_label = $bias_label,
    n.inferred_from_articles = true,
    n.inference_model = "graph-inference-v1",
    n.source = coalesce(n.source, "article_inference"),
    n.updated_at = datetime()
RETURN count(n) AS updated_count
```

**Parameters**:
- `score`: Inferred bias score (-1.0 to 1.0)
- `confidence`: Confidence in inferred score (0.0 to 1.0)
- `bias_label`: Inferred label ("Left", "Lean Left", etc.)

**Purpose**: This query:
1. Finds nodes that have NO existing bias score
2. Assigns the calculated bias score and confidence
3. Marks the node as inferred with inference model version
4. Updates the source and timestamp
5. Returns count of updated nodes

**Usage in Code**: `KnowledgeGraphScorer._update_inferred_node_bias()` - Called during inference

---

### 8. Graph Statistics Queries
**Purpose**: Monitor graph state and coverage

```cypher
-- Total node count
MATCH (n) RETURN count(n) AS total

-- Total relationship count
MATCH ()-[r]->() RETURN count(r) AS total

-- Nodes by type
MATCH (n)
RETURN head(labels(n)) AS node_type, count(*) AS count
ORDER BY count DESC, node_type ASC

-- Relationships by type
MATCH ()-[r]->()
RETURN type(r) AS relationship_type, count(*) AS count
ORDER BY count DESC, relationship_type ASC

-- Inferred nodes
MATCH (n {inferred_from_articles: true}) RETURN count(n) AS total

-- Nodes without bias
MATCH (n) WHERE n.bias_score IS NULL RETURN count(n) AS total
```

**Usage in Code**: `KnowledgeGraphScorer.get_graph_stats()` - Called for monitoring

---

## Bias Score Calculation Algorithm

### Overview
The bias calculation uses a weighted aggregation algorithm that:
1. Identifies all relevant entities from article metadata
2. Fetches their bias scores and related entities from the graph
3. Calculates weighted contributions considering importance and relationships
4. Combines all evidence into a single bias score

### Step-by-Step Algorithm

#### Phase 1: Candidate Entity Extraction
```python
# From article metadata, extract entities:
candidates = {
    "author": author_name,
    "publisher": publisher_name,
    "publisher_house": publisher_house_name,
    "organizations": [org1, org2, ...],
    "think_tanks": [tank1, tank2, ...],
    "topics": keywords + topic_scores + category
}

# Assign base importance weights:
Base weights by type:
- author: 0.42
- publisher: 0.23
- publisher_house: 0.15
- organization: 0.10 / count(organizations)
- think_tank: 0.05 / count(think_tanks)
- topic: 0.05 / count(topics)
```

**Code Reference**:
```python
def _build_candidate_entities(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Returns list of candidate dicts with:
    # - entity_type: "author", "publisher", etc.
    # - label: Neo4j label ("Author", "Publisher", etc.)
    # - name: Human-readable name
    # - key: Normalized key for graph lookup
    # - base_weight: Initial importance weight
```

#### Phase 2: Graph Lookup and Evidence Collection
```python
For each candidate entity:
  1. Execute fetch_node_with_neighbors query
  2. Collect node's own bias score (if exists)
  3. Collect all related nodes' bias scores (up to 2 hops)
  4. Calculate contribution weights for each piece of evidence
```

**Code Reference**:
```python
node_data = session.execute_read(
    self._fetch_node_with_neighbors,
    candidate["label"],
    candidate["key"],
    DEFAULT_NODE_IMPORTANCE.get(candidate["label"], 0.5),
)
```

#### Phase 3: Weighted Score Aggregation

For **Direct Node Match** (0 hops):
```
contribution_weight = candidate.base_weight × node.importance_weight
weighted_score = node.bias_score × contribution_weight
total_contribution_weight += contribution_weight
weighted_score_sum += weighted_score
weighted_confidence_sum += node.bias_confidence × contribution_weight
```

**Example**: 
```
Article author: "John Smith" (base_weight=0.42)
Found in graph: Author node "john smith"
  - bias_score: -0.65 (Left-leaning)
  - bias_confidence: 0.80
  - importance_weight: 1.00

Calculation:
  contribution_weight = 0.42 × 1.00 = 0.42
  weighted_score = -0.65 × 0.42 = -0.273
  contribution to confidence sum = 0.80 × 0.42 = 0.336
```

For **Related Nodes** (1-2 hops away):
```
hop_decay = 0.55 (if 1 hop) or 0.35 (if 2+ hops)
contribution_weight = 
    candidate.base_weight 
    × related_node.importance_weight 
    × cumulative_relationship_weight 
    × hop_decay

weighted_score = related_node.bias_score × contribution_weight
```

**Example**:
```
Article mentions publisher: "CNN" (base_weight=0.23)
Found in graph: Publisher "CNN"
  - bias_score: -0.45
  - no direct match (null bias_score)
  - related node: "Anderson Cooper" (Author, 1 hop away)
    - bias_score: -0.55
    - importance_weight: 1.00
    - relationship weight (WRITES_FOR): 0.95

Calculation for "Anderson Cooper":
  hop_decay = 0.55 (1 hop)
  relationship_weight = 0.95
  contribution_weight = 0.23 × 1.00 × 0.95 × 0.55 = 0.12035
  weighted_score = -0.55 × 0.12035 = -0.0661925
```

#### Phase 4: Final Score Calculation
```
If total_contribution_weight > 0:
    graph_score = clamp(weighted_score_sum / total_contribution_weight, -1.0, 1.0)
    mean_confidence = weighted_confidence_sum / total_contribution_weight
    
    # Confidence combines:
    # - coverage_ratio: What percentage of requested weight was available
    # - mean_confidence: Average confidence of matched nodes
    graph_confidence = clamp(
        0.15 + (0.45 × coverage_ratio) + (0.40 × mean_confidence),
        0.05,
        0.95
    )
Else:
    graph_score = 0.0 (neutral)
    graph_confidence = low (0.1 to 0.5 depending on coverage)
```

#### Phase 5: Score to Label Conversion
```
score_to_three_class_label(score):
    if score <= -0.2: return "Left"
    if score >= 0.2: return "Right"
    return "Center"

score_to_allsides_label(score):
    if score <= -0.75: return "Left"
    if score <= -0.25: return "Lean Left"
    if score < 0.25: return "Center"
    if score < 0.75: return "Lean Right"
    return "Right"
```

**Example**:
```
graph_score = -0.45
→ score_to_three_class_label(-0.45) = "Left" (score <= -0.2)
→ score_to_allsides_label(-0.45) = "Lean Left" (-0.75 < -0.45 <= -0.25)
```

### Code Flow Summary
```python
def evaluate_graph_signal(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
    # 1. Extract candidates
    candidates = self._build_candidate_entities(metadata)
    
    # 2. Connect to graph
    driver = self._get_driver()
    
    # 3. Initialize tracking variables
    weighted_score_sum = 0.0
    weighted_confidence_sum = 0.0
    total_contribution_weight = 0.0
    evidence = []
    
    with driver.session() as session:
        # 4. Ensure article nodes exist in graph
        context = self._ensure_article_context(session, candidates)
        
        # 5. For each candidate, fetch from graph and calculate contribution
        for candidate in candidates:
            node_data = session.execute_read(
                self._fetch_node_with_neighbors,
                candidate["label"],
                candidate["key"],
                DEFAULT_NODE_IMPORTANCE.get(candidate["label"], 0.5),
            )
            if not node_data:
                continue
            
            # Process direct node match
            if node_data.bias_score is not None:
                contribution_weight = candidate.base_weight × node.importance_weight
                weighted_score_sum += node.bias_score × contribution_weight
                weighted_confidence_sum += node.bias_confidence × contribution_weight
                total_contribution_weight += contribution_weight
            
            # Process related nodes (1-2 hops)
            for related in node_data.related:
                if related.bias_score is None:
                    continue
                hop_decay = 0.55 if related.hops <= 1 else 0.35
                contribution_weight = (
                    candidate.base_weight 
                    × related.importance_weight 
                    × related.relationship_weight 
                    × hop_decay
                )
                weighted_score_sum += related.bias_score × contribution_weight
                weighted_confidence_sum += related.bias_confidence × contribution_weight
                total_contribution_weight += contribution_weight
        
        # 6. Persist inferred nodes
        inferred_unknown_nodes = self._persist_unknown_inference(
            session, unknown_candidates, per_candidate_rollup, graph_score, graph_confidence
        )
    
    # 7. Calculate final score
    if total_contribution_weight > 0:
        graph_score = weighted_score_sum / total_contribution_weight
        graph_confidence = 0.15 + (0.45 × coverage_ratio) + (0.40 × mean_confidence)
    else:
        graph_score = 0.0
        graph_confidence = 0.2
    
    return {
        "label": score_to_three_class_label(graph_score),
        "score": graph_score,
        "confidence": graph_confidence,
        "coverage_ratio": available_weight / requested_weight,
        "evidence": evidence,
        "inferred_unknown_nodes": inferred_unknown_nodes,
        "status": graph_status,
    }
```

---

## Bias Calculation for Unknown Nodes

### Problem Statement
When an article mentions an entity (author, publisher, organization, etc.) that:
1. Exists in the graph, OR
2. Doesn't exist in the graph yet

But the entity **has no bias score** (either never assigned or inferred), the system must:
1. Infer its bias from related entities
2. Persist this inference to the graph for future use

### Solution: Graph Inference Algorithm

#### Phase 1: Identify Unknown Candidates
During `_ensure_article_context`:
```python
unknown_candidates = []  # Entities with no bias_score
known_bias_keys = set()  # Entities with bias_score

for candidate in candidates:
    result = session.execute_write(self._merge_candidate_node, candidate)
    if result.get("has_bias"):
        known_bias_keys.add(candidate["key"])
    else:
        unknown_candidates.append(candidate)
```

**Code Reference**:
```python
def _ensure_article_context(self, session, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    known_bias_keys = set()
    unknown_candidates: List[Dict[str, Any]] = []

    for candidate in candidates:
        result = session.execute_write(self._merge_candidate_node, candidate)
        if result.get("has_bias"):
            known_bias_keys.add(candidate["key"])
        else:
            unknown_candidates.append(candidate)
    
    # Also create relationships between entities
    for rel in self._build_article_relationships(candidates):
        session.execute_write(
            self._merge_relationship,
            rel["from"]["label"],
            rel["from"]["key"],
            rel["to"]["label"],
            rel["to"]["key"],
            rel["type"],
            rel["weight"],
        )

    return {
        "known_bias_keys": known_bias_keys,
        "unknown_candidates": unknown_candidates,
    }
```

#### Phase 2: Collect Evidence for Unknown Entities
During main evidence collection loop, the `per_candidate_rollup` dictionary accumulates:
- Weight sum: Total weighted evidence for this candidate
- Weighted sum: Accumulated bias signal
- Confidence weighted sum: Accumulated confidence signal

```python
per_candidate_rollup = {}  # Key: candidate.key

for candidate in candidates:
    # ... fetch node_data from graph ...
    
    # Accumulate evidence in rollup
    rollup = per_candidate_rollup.setdefault(
        candidate_key,
        {
            "weight_sum": 0.0,
            "weighted_sum": 0.0,
            "confidence_weighted_sum": 0.0
        }
    )
    
    # Add direct node score to rollup
    if node_score is not None:
        rollup["weight_sum"] += contribution_weight
        rollup["weighted_sum"] += weighted_score
        rollup["confidence_weighted_sum"] += node_confidence × contribution_weight
    
    # Add related nodes to rollup
    for related in node_data.get("related", []):
        if related_score is not None:
            rollup["weight_sum"] += contribution_weight
            rollup["weighted_sum"] += weighted_score
            rollup["confidence_weighted_sum"] += related_confidence × contribution_weight
```

#### Phase 3: Calculate Inferred Bias
For each unknown candidate, compute estimated bias from its rollup:

```python
for candidate in unknown_candidates:
    rollup = per_candidate_rollup.get(candidate["key"], {})
    weight_sum = float(rollup.get("weight_sum", 0.0))
    weighted_sum = float(rollup.get("weighted_sum", 0.0))
    confidence_sum = float(rollup.get("confidence_weighted_sum", 0.0))

    if weight_sum > 0:
        # Has evidence: calculate inferred score from weighted average
        inferred_score = clamp(weighted_sum / weight_sum, -1.0, 1.0)
        inferred_confidence = clamp(
            0.20 + 0.55 * (confidence_sum / weight_sum),
            0.15,
            0.85,
        )
    else:
        # No evidence: use defaults with reduced confidence
        inferred_score = clamp(default_score, -1.0, 1.0)
        inferred_confidence = clamp(default_confidence * 0.7, 0.12, 0.65)
```

**Formula Explanation**:

**With Evidence (weight_sum > 0)**:
```
inferred_score = weighted_sum / weight_sum
  → Weighted average of all evidence scores
  → Clamped to [-1.0, 1.0]

inferred_confidence = 0.20 + 0.55 × (confidence_sum / weight_sum)
  → Base confidence: 0.20 (always trust some inferred data)
  → Additional confidence: 0.55 × average confidence of evidence sources
  → Clamped to [0.15, 0.85] (realistic range for inferred scores)
```

**Without Evidence (weight_sum = 0)**:
```
inferred_score = default_score (from article's overall graph signal)
  → Inherit article's calculated bias
  → Only justified if article itself had graph evidence

inferred_confidence = default_confidence × 0.7
  → Heavily reduced (0.7 multiplier)
  → Reflects uncertainty in inference
  → Clamped to [0.12, 0.65] (much lower than evidence-based)
```

**Example Scenario**:
```
Article mentions organization "Sierra Club" (no prior bias data)
Graph lookup finds:
  - Related to Publisher "Washington Post" (bias: -0.35, confidence: 0.80)
    weight: 0.68, contribution_weight = 0.68 × -0.35 = -0.238
  - Related to Topic "climate justice" (bias: -0.70, confidence: 0.75)
    weight: 0.45, contribution_weight = 0.45 × -0.70 = -0.315
  - Related to Topic "environmental protection" (bias: -0.60, confidence: 0.70)
    weight: 0.40, contribution_weight = 0.40 × -0.60 = -0.240

Rollup calculation:
  weight_sum = 0.68 + 0.45 + 0.40 = 1.53
  weighted_sum = -0.238 + (-0.315) + (-0.240) = -0.793
  confidence_sum = (0.80×0.68) + (0.75×0.45) + (0.70×0.40)
                 = 0.544 + 0.338 + 0.280 = 1.162

Inferred bias:
  inferred_score = -0.793 / 1.53 = -0.518 (Lean Left)
  inferred_confidence = 0.20 + 0.55 × (1.162 / 1.53)
                      = 0.20 + 0.55 × 0.759
                      = 0.20 + 0.417
                      = 0.617 (moderate-high confidence)
```

**Code Reference**:
```python
def _persist_unknown_inference(
    self,
    session,
    unknown_candidates: List[Dict[str, Any]],
    per_candidate_rollup: Dict[str, Dict[str, float]],
    default_score: float,
    default_confidence: float,
) -> int:
    updates = 0
    for candidate in unknown_candidates:
        rollup = per_candidate_rollup.get(candidate["key"], {})
        weight_sum = float(rollup.get("weight_sum", 0.0))
        weighted_sum = float(rollup.get("weighted_sum", 0.0))
        confidence_sum = float(rollup.get("confidence_weighted_sum", 0.0))

        if weight_sum > 0:
            inferred_score = clamp(weighted_sum / weight_sum, -1.0, 1.0)
            inferred_confidence = clamp(
                0.20 + 0.55 * (confidence_sum / weight_sum),
                0.15,
                0.85,
            )
        else:
            inferred_score = clamp(default_score, -1.0, 1.0)
            inferred_confidence = clamp(default_confidence * 0.7, 0.12, 0.65)

        updates += session.execute_write(
            self._update_inferred_node_bias,
            candidate["label"],
            candidate["key"],
            inferred_score,
            inferred_confidence,
            score_to_allsides_label(inferred_score),
        )
    return updates
```

---

## Inferred Node Creation and Persistence

### Overview
The system uses inferred nodes to:
1. Capture entities discovered from article metadata
2. Assign calculated bias values based on graph relationships
3. Enable faster lookups for future articles mentioning same entities
4. Provide an evolving knowledge graph that learns from articles

### Node Creation Strategy

#### Step 1: Article Analysis Creates Nodes
When article is analyzed:
```python
article_metadata = {
    "author": "John Smith",
    "publisher": "CNN",
    "organizations": ["Sierra Club", "NRDC"],
    "keywords": ["climate", "environment"],
}

# Candidate extraction creates nodes for all these entities
candidates = [
    {"label": "Author", "key": "john smith", "name": "John Smith", ...},
    {"label": "Publisher", "key": "cnn", "name": "CNN", ...},
    {"label": "Organization", "key": "sierra club", "name": "Sierra Club", ...},
    {"label": "Organization", "key": "nrdc", "name": "NRDC", ...},
    {"label": "Topic", "key": "climate", "name": "climate", ...},
    {"label": "Topic", "key": "environment", "name": "environment", ...},
]
```

#### Step 2: Nodes Merged into Graph
```python
def _merge_candidate_node(tx, candidate: Dict[str, Any]) -> Dict[str, Any]:
    label = candidate["label"]
    query = f"""
    MERGE (n:{label} {{key: $key}})
    ON CREATE SET
        n.created_at = datetime(),
        n.source = "article_metadata"
    SET
        n.name = $name,
        n.source = coalesce(n.source, "article_metadata"),
        n.importance_weight = coalesce(n.importance_weight, $importance_weight),
        n.updated_at = datetime()
    RETURN n.bias_score IS NOT NULL AS has_bias
    """
```

**Result**:
- If node exists: Updates name and importance_weight, returns whether it has a bias_score
- If node doesn't exist: Creates new node with source="article_metadata", returns has_bias=false

**Nodes Created in Neo4j**:
```cypher
MERGE (n:Author {key: "john smith"})
ON CREATE SET
    n.created_at = 2024-01-15T10:30:00Z,
    n.source = "article_metadata"
SET
    n.name = "John Smith",
    n.importance_weight = 1.00,
    n.updated_at = 2024-01-15T10:30:00Z
-- Node created with no bias_score (null)

MERGE (n:Organization {key: "sierra club"})
ON CREATE SET
    n.created_at = 2024-01-15T10:30:00Z,
    n.source = "article_metadata"
SET
    n.name = "Sierra Club",
    n.importance_weight = 0.10,
    n.updated_at = 2024-01-15T10:30:00Z
-- Node created with no bias_score (null)
```

#### Step 3: Relationships Created Between Article Entities
```python
def _build_article_relationships(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    relationships = []
    
    # Author → Publisher
    for author in candidates[author]:
        for publisher in candidates[publisher]:
            relationships.append({
                "from": author,
                "to": publisher,
                "type": "WRITES_FOR",
                "weight": 0.95,
            })
    
    # Publisher → PublisherHouse
    for publisher in candidates[publisher]:
        for publisher_house in candidates[publisher_house]:
            relationships.append({
                "from": publisher,
                "to": publisher_house,
                "type": "OWNED_BY",
                "weight": 0.90,
            })
    
    # Publisher/Org/ThinkTank → Topics
    topics = candidates[topics]
    for publisher in candidates[publisher]:
        for topic in topics:
            relationships.append({
                "from": publisher,
                "to": topic,
                "type": "COVERS",
                "weight": 0.62,
            })
    # ... similar for organizations and think tanks ...
    
    return relationships
```

**Relationships Created in Neo4j**:
```cypher
MATCH (a:Author {key: "john smith"})
MATCH (b:Publisher {key: "cnn"})
MERGE (a)-[r:WRITES_FOR]->(b)
SET
    r.weight = 0.95,
    r.source = "article_metadata",
    r.updated_at = 2024-01-15T10:30:00Z

MATCH (a:Publisher {key: "cnn"})
MATCH (b:Topic {key: "climate"})
MERGE (a)-[r:COVERS]->(b)
SET
    r.weight = 0.62,
    r.source = "article_metadata",
    r.updated_at = 2024-01-15T10:30:00Z
```

#### Step 4: Inference Calculation
Graph signal evaluation collects evidence and calculates scores:

```python
# For each candidate, fetch from graph
node_data = _fetch_node_with_neighbors(session, "Organization", "sierra club", 0.70)

# Process evidence
for candidate in candidates:
    if candidate.key == "sierra club":
        # Found evidence from:
        # - CNN Publisher (known bias: -0.45) connected via coverage
        # - Climate topic (known bias: -0.70) connected via advocacy
        # Calculate weighted contribution
```

#### Step 5: Persist Inferred Bias
Finally, update unknown nodes with calculated bias:

```python
# Query that executes for identified unknown candidates
MATCH (n:Organization {key: "sierra club"})
WHERE n.bias_score IS NULL
SET
    n.bias_score = -0.518,
    n.bias_confidence = 0.617,
    n.bias_label = "Lean Left",
    n.inferred_from_articles = true,
    n.inference_model = "graph-inference-v1",
    n.source = coalesce(n.source, "article_inference"),
    n.updated_at = 2024-01-15T10:30:15Z
RETURN count(n) AS updated_count
```

**Result Node After Inference**:
```json
{
  "name": "Sierra Club",
  "key": "sierra club",
  "bias_score": -0.518,
  "bias_confidence": 0.617,
  "bias_label": "Lean Left",
  "importance_weight": 0.10,
  "source": "article_metadata",
  "inferred_from_articles": true,
  "inference_model": "graph-inference-v1",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:15Z"
}
```

### Benefits of Inferred Node Persistence

1. **Learning Graph**: Graph becomes smarter over time as more articles are analyzed
2. **Faster Processing**: Future articles mentioning same entity use cached inference
3. **Traceability**: `inferred_from_articles` flag shows how nodes were created
4. **Quality Control**: Inference model version tracked for auditing
5. **Dynamic Bias**: As more evidence comes in, future inferences can improve

### Code Flow Summary
```python
def compute_article_bias(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
    graph_signal = self.evaluate_graph_signal(metadata)
    # Returns signal with inferred_unknown_nodes count
    
    # graph_signal contains:
    # {
    #   "label": "Left",
    #   "score": -0.45,
    #   "confidence": 0.75,
    #   "evidence": [...],
    #   "inferred_unknown_nodes": 3,  # Number of nodes updated with inference
    #   "status": "ok",
    # }
```

---

## Example Workflows

### Example 1: Analyzing an Article with Known Entities

**Input Article**:
```json
{
  "title": "Climate Policy Debate Heats Up",
  "content": "Anderson Cooper reports on climate policy debates...",
  "author": "Anderson Cooper",
  "publisher": "CNN",
  "publisher_house": "Warner Media",
  "organizations": ["Sierra Club", "Heritage Foundation"],
  "think_tanks": [],
  "keywords": ["climate", "policy"],
  "category": "Politics"
}
```

**Step 1: Extract Candidates**
```
Base Weights Assigned:
- Author: "Anderson Cooper" → weight = 0.42
- Publisher: "CNN" → weight = 0.23
- PublisherHouse: "Warner Media" → weight = 0.15
- Organization: "Sierra Club" → weight = 0.05 (0.10/2)
- Organization: "Heritage Foundation" → weight = 0.05 (0.10/2)
- Topic: "climate" → weight = 0.025 (0.05/2)
- Topic: "policy" → weight = 0.025 (0.05/2)

Requested Weight Total = 0.92
```

**Step 2: Graph Lookups**
```cypher
-- Lookup Author: Anderson Cooper
MATCH (n:Author {key: "anderson cooper"})
OPTIONAL MATCH p=(n)-[rels*1..2]-(m)
WHERE m.bias_score IS NOT NULL
...

Result:
{
  "node_name": "Anderson Cooper",
  "bias_score": -0.55,
  "bias_confidence": 0.75,
  "importance_weight": 1.00,
  "related": [
    {
      "node_name": "CNN",
      "bias_score": -0.45,
      "hops": 1,
      "relationship_weight": 0.95,
      ...
    },
    {
      "node_name": "Warner Media",
      "bias_score": -0.35,
      "hops": 2,
      "relationship_weight": 0.90 × rel_weight,
      ...
    }
  ]
}
```

**Step 3: Calculate Contributions**
```
Direct hit - Anderson Cooper:
  contribution_weight = 0.42 × 1.00 = 0.42
  weighted_score = -0.55 × 0.42 = -0.231
  weighted_confidence = 0.75 × 0.42 = 0.315
  
Related via WRITES_FOR (1 hop) - CNN:
  hop_decay = 0.55
  relationship_weight = 0.95
  contribution_weight = 0.42 × 0.95 × 0.95 × 0.55 = 0.207
  weighted_score = -0.45 × 0.207 = -0.0932
  weighted_confidence = 0.80 × 0.207 = 0.166

... (more related nodes processed) ...

Total:
  total_contribution_weight = 1.12
  weighted_score_sum = -0.567
  weighted_confidence_sum = 0.823
```

**Step 4: Calculate Final Score**
```
graph_score = -0.567 / 1.12 = -0.506 (Lean Left)
mean_confidence = 0.823 / 1.12 = 0.735
coverage_ratio = 0.92 / 0.92 = 1.0 (complete coverage)

graph_confidence = clamp(
    0.15 + (0.45 × 1.0) + (0.40 × 0.735),
    0.05,
    0.95
) = clamp(0.744, 0.05, 0.95) = 0.744
```

**Result**:
```json
{
  "classification": {
    "label": "Left",
    "score": -0.506,
    "confidence": 0.744,
    "model_version": "hybrid-ml-graph-v1"
  },
  "graph_signal": {
    "label": "Left",
    "score": -0.506,
    "confidence": 0.744,
    "coverage_ratio": 1.0,
    "requested_weight": 0.92,
    "available_weight": 0.92,
    "status": "ok",
    "inferred_unknown_nodes": 0,
    "evidence": [
      {
        "source_entity": "Anderson Cooper",
        "source_type": "author",
        "matched_node": "Anderson Cooper",
        "bias_score": -0.55,
        "confidence": 0.75,
        "contribution_weight": 0.42,
        "weighted_contribution": -0.231
      },
      {
        "source_entity": "Anderson Cooper",
        "source_type": "author",
        "matched_node": "CNN",
        "path_hops": 1,
        "bias_score": -0.45,
        "confidence": 0.80,
        "contribution_weight": 0.207,
        "weighted_contribution": -0.0932
      },
      ...
    ]
  }
}
```

---

### Example 2: Article with Unknown Entity (Inference)

**Input Article**:
```json
{
  "title": "New Green Energy Initiative",
  "content": "Environmental groups push for green energy policy...",
  "author": "Sarah Mitchell",  // Unknown author
  "publisher": "TheGuardian",  // Known publisher
  "organizations": ["EarthJustice"],  // Unknown organization
  "keywords": ["green energy", "environment", "sustainability"]
}
```

**Step 1: Merge Candidates**
```
Known: TheGuardian (Publisher) has bias_score = -0.40
Unknown: Sarah Mitchell (Author) has no bias_score
Unknown: EarthJustice (Organization) has no bias_score
```

**Step 2: Create Nodes and Relationships**
```cypher
MERGE (n:Author {key: "sarah mitchell"})
ON CREATE SET n.created_at = datetime(), n.source = "article_metadata"
SET n.name = "Sarah Mitchell", n.updated_at = datetime()
-- Returns has_bias = false

MERGE (n:Organization {key: "earthjustice"})
ON CREATE SET n.created_at = datetime(), n.source = "article_metadata"
SET n.name = "EarthJustice", n.updated_at = datetime()
-- Returns has_bias = false

MERGE (a:Author {key: "sarah mitchell"})
MERGE (b:Publisher {key: "theguardian"})
MERGE (a)-[r:WRITES_FOR]->(b) SET r.weight = 0.95
```

**Step 3: Evidence Collection**
```
For TheGuardian (known):
  - Direct bias: -0.40, confidence 0.80
  - Relationship weight: 1.0
  - Contribution: 0.23 × 1.0 = 0.23

unknown_candidates = [Sarah Mitchell, EarthJustice]
per_candidate_rollup = {
  "sarah mitchell": {
    "weight_sum": 0.23,
    "weighted_sum": -0.092,
    "confidence_weighted_sum": 0.184
  },
  "earthjustice": {
    "weight_sum": 0.0,
    "weighted_sum": 0.0,
    "confidence_weighted_sum": 0.0
  }
}
```

**Step 4: Calculate Inferred Bias**
```
For "sarah mitchell":
  weight_sum = 0.23 (has evidence from publisher)
  weighted_sum = -0.092
  confidence_sum = 0.184
  
  inferred_score = -0.092 / 0.23 = -0.4 (Lean Left)
  inferred_confidence = 0.20 + 0.55 × (0.184 / 0.23)
                      = 0.20 + 0.55 × 0.8
                      = 0.20 + 0.44 = 0.64

For "earthjustice":
  weight_sum = 0.0 (no direct evidence)
  
  inferred_score = default_score = -0.506 (from article's overall signal)
  inferred_confidence = default_confidence × 0.7
                      = 0.744 × 0.7 = 0.521
```

**Step 5: Persist Inferred Nodes**
```cypher
MATCH (n:Author {key: "sarah mitchell"})
WHERE n.bias_score IS NULL
SET
    n.bias_score = -0.4,
    n.bias_confidence = 0.64,
    n.bias_label = "Lean Left",
    n.inferred_from_articles = true,
    n.inference_model = "graph-inference-v1",
    n.source = coalesce(n.source, "article_inference"),
    n.updated_at = datetime()

MATCH (n:Organization {key: "earthjustice"})
WHERE n.bias_score IS NULL
SET
    n.bias_score = -0.506,
    n.bias_confidence = 0.521,
    n.bias_label = "Lean Left",
    n.inferred_from_articles = true,
    n.inference_model = "graph-inference-v1",
    n.source = coalesce(n.source, "article_inference"),
    n.updated_at = datetime()
```

**Result**:
```json
{
  "graph_signal": {
    "label": "Left",
    "score": -0.506,
    "confidence": 0.744,
    "status": "ok",
    "inferred_unknown_nodes": 2,  // Sarah Mitchell + EarthJustice
    "evidence": [...]
  }
}

// Nodes created in graph:
// Sarah Mitchell: bias_score = -0.4, confidence = 0.64, inferred = true
// EarthJustice: bias_score = -0.506, confidence = 0.521, inferred = true
```

**Future Impact**:
- Next article mentioning "Sarah Mitchell" → uses cached bias of -0.4 (confidence 0.64)
- Graph has evolved with new understanding of these entities
- Inference propagates pattern knowledge through the graph

---

### Example 3: ML + Graph Hybrid Classification

**Configuration**:
```env
ENABLE_ML_MODEL=true
HYBRID_ML_WEIGHT=0.7
HYBRID_GRAPH_WEIGHT=0.3
```

**Article**:
```
title: "Tax Cuts Boost Economy"
content: "Conservative economists argue tax cuts lead to job growth
and economic expansion. Traditional values of fiscal responsibility..."
author: "Robert Knight"
publisher: "Breitbart"
organizations: ["Heritage Foundation"]
keywords: ["economy", "tax", "conservative"]
```

**Step 1: Graph Signal Calculation**
```
All entities have bias scores:
- Robert Knight (Author): -0.3 (slight left)
- Breitbart (Publisher): 0.75 (right)
- Heritage Foundation (Org): 0.85 (right)

Graph Signal Result:
  score = 0.65  (Right-leaning)
  confidence = 0.82
  weight_ratio = 0.3 / (0.3 + 0.7) = 0.3
```

**Step 2: ML Signal Calculation**
```
Content analysis:
Text: "tax cuts boost economy conservative economists traditional values..."

Left-lean keywords found: 0
Right-lean keywords found:
  - "conservative": 2 occurrences
  - "tax cuts": 1 occurrence
  - "traditional values": 1 occurrence
  Total: 4 hits

left_hits = 0
right_hits = 4
total_hits = 4

score = (4 - 0) / 4 = 1.0 (fully right-leaning)
confidence = clamp(
    0.45 + (0.35 × 1.0) + min(4 × 0.03, 0.2),
    0.35,
    0.92
) = clamp(0.45 + 0.35 + 0.12, 0.35, 0.92) = 0.92

ML Signal Result:
  score = 1.0 (Right)
  confidence = 0.92
  weight_ratio = 0.7 / (0.3 + 0.7) = 0.7
```

**Step 3: Combine Signals**
```
ml_ratio = 0.7 / (0.3 + 0.7) = 0.7
graph_ratio = 0.3 / (0.3 + 0.7) = 0.3

final_score = (1.0 × 0.7) + (0.65 × 0.3) = 0.7 + 0.195 = 0.895
→ Strongly Right-leaning

agreement = 1.0 - (min(2.0, abs(1.0 - 0.65)) / 2.0)
          = 1.0 - (0.35 / 2.0)
          = 1.0 - 0.175
          = 0.825
→ High agreement between both signals

blended_confidence = (0.92 × 0.7) + (0.82 × 0.3)
                   = 0.644 + 0.246
                   = 0.890

final_confidence = clamp(
    (0.8 × 0.890) + (0.2 × 0.825),
    0.05,
    0.99
) = clamp(0.712 + 0.165, 0.05, 0.99)
  = clamp(0.877, 0.05, 0.99)
  = 0.877
```

**Final Result**:
```json
{
  "classification": {
    "label": "Right",
    "score": 0.895,
    "confidence": 0.877,
    "model_version": "hybrid-ml-graph-v1"
  },
  "components": {
    "ml": {
      "score": 1.0,
      "confidence": 0.92,
      "weight": 0.7
    },
    "graph": {
      "score": 0.65,
      "confidence": 0.82,
      "weight": 0.3,
      "coverage_ratio": 1.0
    }
  },
  "ml_signal": {
    "label": "Right",
    "score": 1.0,
    "confidence": 0.92,
    "diagnostics": {
      "left_hits": 0,
      "right_hits": 4,
      "total_hits": 4
    }
  },
  "graph_signal": {
    "label": "Right",
    "score": 0.65,
    "confidence": 0.82,
    ...
  }
}
```

---

## Summary

The Neo4j knowledge graph system provides:

1. **Entity-Centric Bias Tracking**: Stores bias information for authors, publishers, organizations, think tanks, and topics
2. **Relationship-Based Inference**: Propagates bias information through weighted relationships in the graph
3. **Evidence Tracking**: Captures detailed evidence of which entities and relationships contributed to bias classification
4. **Learning System**: Creates inferred nodes from article metadata, learning entity biases over time
5. **Hybrid Scoring**: Combines graph-based inference with optional ML signals for robust bias detection
6. **Confidence Metrics**: Provides confidence scores reflecting both coverage and consistency of evidence

The system enables fast, transparent bias classification that improves as more articles are analyzed and more entities are learned.
