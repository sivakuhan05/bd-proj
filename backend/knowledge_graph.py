import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.bias_terms import LEFT_LEAN_TERMS, RIGHT_LEAN_TERMS
from backend.bias_utils import clamp, score_to_three_class_label, utc_now
from dotenv import load_dotenv

try:
    from backend.spark_jobs.bias_batch import SparkBiasAnalyzer
except Exception:  # pragma: no cover - keep core scorer importable without Spark extras
    SparkBiasAnalyzer = None

try:
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover - handled gracefully at runtime
    GraphDatabase = None


ALLSIDES_LABEL_TO_SCORE = {
    "left": -1.0,
    "lean left": -0.5,
    "center": 0.0,
    "centre": 0.0,
    "lean right": 0.5,
    "right": 1.0,
}

ENTITY_TYPE_TO_LABEL = {
    "author": "Author",
    "publisher": "Publisher",
    "publisher_house": "PublisherHouse",
    "organization": "Organization",
    "think_tank": "ThinkTank",
    "topic": "Topic",
}

ENTITY_TYPE_IMPORTANCE = {
    "author": 0.42,
    "publisher": 0.23,
    "publisher_house": 0.15,
    "organization": 0.10,
    "think_tank": 0.05,
    "topic": 0.05,
}

DEFAULT_NODE_IMPORTANCE = {
    "Author": 1.00,
    "Publisher": 0.95,
    "PublisherHouse": 0.85,
    "Organization": 0.70,
    "ThinkTank": 0.70,
    "Topic": 0.45,
}

ALLOWED_RELATIONSHIPS = {
    "WRITES_FOR",
    "OWNED_BY",
    "AFFILIATED_WITH",
    "ADVOCATES_FOR",
    "COVERS",
    "PUBLISHED_BY",
    "BELONGS_TO",
    "ASSOCIATED_WITH",
}

GRAPH_SCHEMA_QUERIES = [
    "CREATE CONSTRAINT author_key IF NOT EXISTS FOR (n:Author) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT publisher_key IF NOT EXISTS FOR (n:Publisher) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT publisher_house_key IF NOT EXISTS FOR (n:PublisherHouse) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT organization_key IF NOT EXISTS FOR (n:Organization) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT think_tank_key IF NOT EXISTS FOR (n:ThinkTank) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT topic_key IF NOT EXISTS FOR (n:Topic) REQUIRE n.key IS UNIQUE",
]
def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def unique_non_empty(values: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        token = value.strip()
        if not token:
            continue
        key = normalize_text(token)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return ordered


def parse_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, (float, int)):
        return float(value)
    token = str(value).strip()
    if not token:
        return default
    try:
        return float(token)
    except ValueError:
        return default

def bias_label_to_score(label: Optional[str]) -> Optional[float]:
    if not label:
        return None
    normalized = normalize_text(label.replace("_", " "))
    return ALLSIDES_LABEL_TO_SCORE.get(normalized)

def score_to_allsides_label(score: float) -> str:
    if score <= -0.75:
        return "Left"
    if score <= -0.25:
        return "Lean Left"
    if score < 0.25:
        return "Center"
    if score < 0.75:
        return "Lean Right"
    return "Right"


def sanitize_relationship_type(value: str) -> str:
    token = value.strip().upper().replace(" ", "_")
    token = re.sub(r"[^A-Z_]", "", token)
    if token in ALLOWED_RELATIONSHIPS:
        return token
    return "ASSOCIATED_WITH"


class KnowledgeGraphScorer:
    def __init__(self):
        load_dotenv()
        self.neo4j_uri = os.getenv("NEO4J_URI")
        self.neo4j_username = os.getenv("NEO4J_USERNAME")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD")
        self.neo4j_database = os.getenv("NEO4J_DATABASE")
        self._active_database: Optional[str] = None
        self._connection_error: Optional[str] = None

        self.ml_weight = self._read_weight("HYBRID_ML_WEIGHT", 0.7)
        self.graph_weight = self._read_weight("HYBRID_GRAPH_WEIGHT", 0.3)
        self.enable_ml_model = (
            os.getenv("ENABLE_ML_MODEL", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.neo4j_connection_timeout_seconds = max(
            1.0,
            parse_float(os.getenv("NEO4J_CONNECTION_TIMEOUT_SECONDS"), 8.0) or 8.0,
        )

        if self.ml_weight + self.graph_weight <= 0:
            self.ml_weight = 0.7
            self.graph_weight = 0.3
        else:
            total = self.ml_weight + self.graph_weight
            self.ml_weight = self.ml_weight / total
            self.graph_weight = self.graph_weight / total

        self.ml_model_version = os.getenv("INTERNAL_ML_MODEL_VERSION", "internal-lexical-v1")
        self.enable_spark_ml = (
            os.getenv("ENABLE_SPARK_ML", "true").strip().lower() in {"1", "true", "yes", "on"}
        )
        self._driver = None
        self._schema_ready = False
        self._spark_bias_analyzer = SparkBiasAnalyzer() if SparkBiasAnalyzer is not None else None

    @staticmethod
    def _read_weight(env_name: str, fallback: float) -> float:
        value = parse_float(os.getenv(env_name), fallback)
        if value is None:
            return fallback
        return max(0.0, value)

    def _get_driver(self):
        if self._driver is not None:
            return self._driver

        if GraphDatabase is None:
            self._connection_error = "neo4j package is not installed."
            return None
        missing = []
        if not self.neo4j_uri:
            missing.append("NEO4J_URI")
        if not self.neo4j_username:
            missing.append("NEO4J_USERNAME")
        if not self.neo4j_password:
            missing.append("NEO4J_PASSWORD")
        if missing:
            self._connection_error = f"Missing Neo4j env vars: {', '.join(missing)}"
            return None

        try:
            try:
                driver = GraphDatabase.driver(
                    self.neo4j_uri,
                    auth=(self.neo4j_username, self.neo4j_password),
                    connection_timeout=self.neo4j_connection_timeout_seconds,
                    max_transaction_retry_time=5,
                )
            except TypeError:
                driver = GraphDatabase.driver(
                    self.neo4j_uri,
                    auth=(self.neo4j_username, self.neo4j_password),
                )
        except Exception as exc:
            self._connection_error = (
                f"Failed creating Neo4j driver for URI '{self.neo4j_uri}': "
                f"{exc.__class__.__name__}: {exc}"
            )
            return None

        last_exc: Optional[Exception] = None
        for database in self._database_candidates():
            try:
                with driver.session(database=database) as session:
                    session.run("RETURN 1 AS ok").single()
                self._driver = driver
                self._active_database = database
                self._connection_error = None
                return self._driver
            except Exception as exc:
                last_exc = exc

        driver.close()
        labels = [db if db is not None else "<default>" for db in self._database_candidates()]
        self._connection_error = (
            f"Unable to open Neo4j session. Tried databases {labels}. "
            f"Last error: {last_exc.__class__.__name__ if last_exc else 'UnknownError'}: {last_exc}"
        )
        return None

    def _database_candidates(self) -> List[Optional[str]]:
        candidates: List[Optional[str]] = []
        configured = (self.neo4j_database or "").strip()
        if configured:
            candidates.append(configured)
        if "neo4j" not in candidates:
            candidates.append("neo4j")
        candidates.append(None)
        unique: List[Optional[str]] = []
        for candidate in candidates:
            if candidate not in unique:
                unique.append(candidate)
        return unique

    def _session_database(self) -> Optional[str]:
        if self._active_database is not None:
            return self._active_database
        configured = (self.neo4j_database or "").strip()
        return configured or None

    def get_connection_error(self) -> Optional[str]:
        return self._connection_error

    def get_active_database(self) -> Optional[str]:
        return self._active_database

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            self._schema_ready = False
            self._active_database = None
        if self._spark_bias_analyzer is not None:
            self._spark_bias_analyzer.close()

    def _estimate_lexical_ml_signal(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        content = str(metadata.get("content", ""))
        category = str(metadata.get("category", ""))
        keywords = [str(item) for item in metadata.get("keywords", [])]
        text = " ".join([content, category, " ".join(keywords)]).lower()

        left_hits = 0
        right_hits = 0

        for term in LEFT_LEAN_TERMS:
            if term in text:
                left_hits += text.count(term)
        for term in RIGHT_LEAN_TERMS:
            if term in text:
                right_hits += text.count(term)

        total_hits = left_hits + right_hits
        score = 0.0
        if total_hits > 0:
            score = (right_hits - left_hits) / float(total_hits)
        score = clamp(score, -1.0, 1.0)

        confidence = clamp(0.45 + (0.35 * abs(score)) + min(total_hits * 0.03, 0.2), 0.35, 0.92)

        return {
            "label": score_to_three_class_label(score),
            "score": round(score, 6),
            "confidence": round(confidence, 6),
            "model_version": self.ml_model_version,
            "predicted_at": utc_now(),
            "diagnostics": {
                "engine": "lexical",
                "left_hits": left_hits,
                "right_hits": right_hits,
                "total_hits": total_hits,
            },
        }

    def ensure_schema(self):
        if self._schema_ready:
            return

        driver = self._get_driver()
        if driver is None:
            return

        with driver.session(database=self._session_database()) as session:
            for query in GRAPH_SCHEMA_QUERIES:
                session.run(query)
        self._schema_ready = True

    def bootstrap_from_csv(self, seed_path: str) -> Dict[str, Any]:
        driver = self._get_driver()
        if driver is None:
            raise RuntimeError(
                "Neo4j is not reachable. "
                f"{self._connection_error or 'Check Neo4j URI/credentials in .env.'} "
                "If this is Aura, database is commonly named 'neo4j'."
            )

        self.ensure_schema()

        project_root = Path(__file__).resolve().parents[1]
        path = Path(seed_path)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
        if not path.exists():
            raise FileNotFoundError(f"Seed CSV not found: {path}")

        stats = {
            "seed_file": str(path),
            "rows_read": 0,
            "rows_skipped": 0,
            "nodes_upserted": 0,
            "relationships_upserted": 0,
        }

        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            with driver.session(database=self._session_database()) as session:
                for row in reader:
                    stats["rows_read"] += 1
                    result = session.execute_write(self._seed_row, row)
                    stats["rows_skipped"] += result.get("rows_skipped", 0)
                    stats["nodes_upserted"] += result.get("nodes_upserted", 0)
                    stats["relationships_upserted"] += result.get("relationships_upserted", 0)

        return stats

    @staticmethod
    def _read_graph_stats(tx) -> Dict[str, Any]:
        node_count_record = tx.run("MATCH (n) RETURN count(n) AS total").single()
        rel_count_record = tx.run("MATCH ()-[r]->() RETURN count(r) AS total").single()
        node_type_records = tx.run(
            """
            MATCH (n)
            RETURN head(labels(n)) AS node_type, count(*) AS count
            ORDER BY count DESC, node_type ASC
            """
        ).data()
        rel_type_records = tx.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) AS relationship_type, count(*) AS count
            ORDER BY count DESC, relationship_type ASC
            """
        ).data()
        inferred_node_record = tx.run(
            "MATCH (n {inferred_from_articles: true}) RETURN count(n) AS total"
        ).single()
        unknown_bias_record = tx.run(
            "MATCH (n) WHERE n.bias_score IS NULL RETURN count(n) AS total"
        ).single()

        node_count = int(node_count_record.get("total") or 0) if node_count_record else 0
        relationship_count = int(rel_count_record.get("total") or 0) if rel_count_record else 0
        inferred_nodes = int(inferred_node_record.get("total") or 0) if inferred_node_record else 0
        nodes_without_bias = int(unknown_bias_record.get("total") or 0) if unknown_bias_record else 0

        node_types = []
        for row in node_type_records:
            node_types.append(
                {
                    "node_type": row.get("node_type") or "Unknown",
                    "count": int(row.get("count") or 0),
                }
            )

        relationship_types = []
        for row in rel_type_records:
            relationship_types.append(
                {
                    "relationship_type": row.get("relationship_type") or "UNKNOWN_REL",
                    "count": int(row.get("count") or 0),
                }
            )

        return {
            "node_count": node_count,
            "relationship_count": relationship_count,
            "inferred_node_count": inferred_nodes,
            "nodes_without_bias_count": nodes_without_bias,
            "node_types": node_types,
            "relationship_types": relationship_types,
        }

    def get_graph_stats(self) -> Dict[str, Any]:
        driver = self._get_driver()
        if driver is None:
            raise RuntimeError(
                "Neo4j is not reachable. "
                f"{self._connection_error or 'Check Neo4j URI/credentials in .env.'}"
            )

        with driver.session(database=self._session_database()) as session:
            stats = session.execute_read(self._read_graph_stats)

        return {
            "database": self._session_database(),
            "uri": self.neo4j_uri,
            "stats": stats,
        }

    @staticmethod
    def _seed_row(tx, row: Dict[str, Any]) -> Dict[str, int]:
        entity_type = normalize_text(row.get("entity_type", ""))
        name = str(row.get("name", "")).strip()
        if not entity_type or not name:
            return {"rows_skipped": 1, "nodes_upserted": 0, "relationships_upserted": 0}

        label = ENTITY_TYPE_TO_LABEL.get(entity_type)
        if not label:
            return {"rows_skipped": 1, "nodes_upserted": 0, "relationships_upserted": 0}

        bias_score = parse_float(row.get("bias_score"))
        if bias_score is None:
            bias_score = bias_label_to_score(row.get("bias_label"))
        if bias_score is None:
            bias_score = 0.0

        bias_confidence = clamp(parse_float(row.get("bias_confidence"), 0.75) or 0.75, 0.0, 1.0)
        importance_weight = parse_float(
            row.get("importance_weight"),
            DEFAULT_NODE_IMPORTANCE.get(label, 0.5),
        ) or DEFAULT_NODE_IMPORTANCE.get(label, 0.5)

        source = str(row.get("source", "allsides.com")).strip() or "allsides.com"
        source_url = str(row.get("source_url", "")).strip() or None
        key = normalize_text(name)

        merge_node_query = f"""
        MERGE (n:{label} {{key: $key}})
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
        """
        tx.run(
            merge_node_query,
            key=key,
            name=name,
            bias_label=score_to_allsides_label(bias_score),
            bias_score=clamp(bias_score, -1.0, 1.0),
            bias_confidence=bias_confidence,
            importance_weight=importance_weight,
            source=source,
            source_url=source_url,
        )

        relationships_upserted = 0
        target_type = normalize_text(row.get("target_type", ""))
        target_name = str(row.get("target_name", "")).strip()
        if target_type and target_name and target_type in ENTITY_TYPE_TO_LABEL:
            target_label = ENTITY_TYPE_TO_LABEL[target_type]
            relationship_type = sanitize_relationship_type(
                str(row.get("relationship_type", "ASSOCIATED_WITH"))
            )
            relationship_weight = clamp(
                parse_float(row.get("relationship_weight"), 0.8) or 0.8,
                0.0,
                2.0,
            )

            merge_rel_query = f"""
            MERGE (target:{target_label} {{key: $target_key}})
            ON CREATE SET target.name = $target_name, target.created_at = datetime()
            SET target.updated_at = datetime()

            WITH target
            MATCH (source:{label} {{key: $source_key}})
            MERGE (source)-[r:{relationship_type}]->(target)
            SET
                r.weight = $relationship_weight,
                r.source = $source,
                r.updated_at = datetime()
            """
            tx.run(
                merge_rel_query,
                source_key=key,
                target_key=normalize_text(target_name),
                target_name=target_name,
                relationship_weight=relationship_weight,
                source=source,
            )
            relationships_upserted = 1

        return {"rows_skipped": 0, "nodes_upserted": 1, "relationships_upserted": relationships_upserted}

    def _fetch_node_with_neighbors(self, tx, label: str, key: str, default_importance: float):
        if label not in set(ENTITY_TYPE_TO_LABEL.values()):
            return None

        query = f"""
        MATCH (n:{label} {{key: $key}})
        OPTIONAL MATCH p=(n)-[rels*1..2]-(m)
        WHERE m.bias_score IS NOT NULL
        WITH n,
             collect({{
               node_name: m.name,
               node_type: head(labels(m)),
               bias_score: m.bias_score,
               bias_confidence: coalesce(m.bias_confidence, 0.55),
               importance_weight: coalesce(m.importance_weight, 0.35),
               relationship_weight: reduce(w = 1.0, rel IN rels | w * coalesce(rel.weight, 0.75)),
               hops: size(rels)
             }}) AS related_nodes
        RETURN {{
          node_name: n.name,
          node_type: head(labels(n)),
          bias_score: n.bias_score,
          bias_confidence: coalesce(n.bias_confidence, 0.65),
          importance_weight: coalesce(n.importance_weight, $default_importance),
          related: related_nodes
        }} AS node_data
        """
        record = tx.run(query, key=key, default_importance=default_importance).single()
        if not record:
            return None
        return record.get("node_data")

    def _build_candidate_entities(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        author_name = str(metadata.get("author", "")).strip()
        publisher_name = str(metadata.get("publisher", "")).strip()
        publisher_house = str(metadata.get("publisher_house", "")).strip()

        organizations = unique_non_empty([str(item) for item in metadata.get("organizations", [])])
        think_tanks = unique_non_empty([str(item) for item in metadata.get("think_tanks", [])])

        topic_scores = metadata.get("topic_scores", {}) or {}
        topic_keys = [str(topic) for topic in topic_scores.keys()]
        keywords = [str(item) for item in metadata.get("keywords", [])]
        category = str(metadata.get("category", "")).strip()
        topics = unique_non_empty(keywords + topic_keys + ([category] if category else []))

        entities: List[Dict[str, Any]] = []
        if author_name:
            entities.append(
                {
                    "entity_type": "author",
                    "label": ENTITY_TYPE_TO_LABEL["author"],
                    "name": author_name,
                    "key": normalize_text(author_name),
                    "base_weight": ENTITY_TYPE_IMPORTANCE["author"],
                }
            )
        if publisher_name:
            entities.append(
                {
                    "entity_type": "publisher",
                    "label": ENTITY_TYPE_TO_LABEL["publisher"],
                    "name": publisher_name,
                    "key": normalize_text(publisher_name),
                    "base_weight": ENTITY_TYPE_IMPORTANCE["publisher"],
                }
            )
        if publisher_house:
            entities.append(
                {
                    "entity_type": "publisher_house",
                    "label": ENTITY_TYPE_TO_LABEL["publisher_house"],
                    "name": publisher_house,
                    "key": normalize_text(publisher_house),
                    "base_weight": ENTITY_TYPE_IMPORTANCE["publisher_house"],
                }
            )

        if organizations:
            per_org_weight = ENTITY_TYPE_IMPORTANCE["organization"] / len(organizations)
            for name in organizations:
                entities.append(
                    {
                        "entity_type": "organization",
                        "label": ENTITY_TYPE_TO_LABEL["organization"],
                        "name": name,
                        "key": normalize_text(name),
                        "base_weight": per_org_weight,
                    }
                )

        if think_tanks:
            per_tank_weight = ENTITY_TYPE_IMPORTANCE["think_tank"] / len(think_tanks)
            for name in think_tanks:
                entities.append(
                    {
                        "entity_type": "think_tank",
                        "label": ENTITY_TYPE_TO_LABEL["think_tank"],
                        "name": name,
                        "key": normalize_text(name),
                        "base_weight": per_tank_weight,
                    }
                )

        if topics:
            top_topics = topics[:5]
            per_topic_weight = ENTITY_TYPE_IMPORTANCE["topic"] / len(top_topics)
            for name in top_topics:
                entities.append(
                    {
                        "entity_type": "topic",
                        "label": ENTITY_TYPE_TO_LABEL["topic"],
                        "name": name,
                        "key": normalize_text(name),
                        "base_weight": per_topic_weight,
                    }
                )

        return entities

    @staticmethod
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
        record = tx.run(
            query,
            key=candidate["key"],
            name=candidate["name"],
            importance_weight=DEFAULT_NODE_IMPORTANCE.get(label, 0.5),
        ).single()
        return {"has_bias": bool(record and record.get("has_bias"))}

    @staticmethod
    def _merge_relationship(
        tx,
        from_label: str,
        from_key: str,
        to_label: str,
        to_key: str,
        relationship_type: str,
        weight: float,
    ) -> None:
        rel = sanitize_relationship_type(relationship_type)
        query = f"""
        MATCH (a:{from_label} {{key: $from_key}})
        MATCH (b:{to_label} {{key: $to_key}})
        MERGE (a)-[r:{rel}]->(b)
        SET
            r.weight = coalesce(r.weight, $weight),
            r.source = coalesce(r.source, "article_metadata"),
            r.updated_at = datetime()
        """
        tx.run(
            query,
            from_key=from_key,
            to_key=to_key,
            weight=weight,
        )

    def _build_article_relationships(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for candidate in candidates:
            by_type.setdefault(candidate["entity_type"], []).append(candidate)

        relationships: List[Dict[str, Any]] = []
        for author in by_type.get("author", []):
            for publisher in by_type.get("publisher", []):
                relationships.append(
                    {
                        "from": author,
                        "to": publisher,
                        "type": "WRITES_FOR",
                        "weight": 0.95,
                    }
                )

        for publisher in by_type.get("publisher", []):
            for publisher_house in by_type.get("publisher_house", []):
                relationships.append(
                    {
                        "from": publisher,
                        "to": publisher_house,
                        "type": "OWNED_BY",
                        "weight": 0.90,
                    }
                )

        topics = by_type.get("topic", [])
        for publisher in by_type.get("publisher", []):
            for topic in topics:
                relationships.append(
                    {
                        "from": publisher,
                        "to": topic,
                        "type": "COVERS",
                        "weight": 0.62,
                    }
                )
        for organization in by_type.get("organization", []):
            for topic in topics:
                relationships.append(
                    {
                        "from": organization,
                        "to": topic,
                        "type": "ADVOCATES_FOR",
                        "weight": 0.68,
                    }
                )
        for think_tank in by_type.get("think_tank", []):
            for topic in topics:
                relationships.append(
                    {
                        "from": think_tank,
                        "to": topic,
                        "type": "ADVOCATES_FOR",
                        "weight": 0.70,
                    }
                )

        return relationships

    def _ensure_article_context(
        self, session, candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        known_bias_keys = set()
        unknown_candidates: List[Dict[str, Any]] = []

        for candidate in candidates:
            result = session.execute_write(self._merge_candidate_node, candidate)
            if result.get("has_bias"):
                known_bias_keys.add(candidate["key"])
            else:
                unknown_candidates.append(candidate)

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

    @staticmethod
    def _update_inferred_node_bias(
        tx,
        label: str,
        key: str,
        score: float,
        confidence: float,
        bias_label: str,
    ) -> int:
        query = f"""
        MATCH (n:{label} {{key: $key}})
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
        """
        record = tx.run(
            query,
            key=key,
            score=score,
            confidence=confidence,
            bias_label=bias_label,
        ).single()
        return int(record.get("updated_count") or 0) if record else 0

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

    def evaluate_graph_signal(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        candidates = self._build_candidate_entities(metadata)
        if not candidates:
            return {
                "label": "Center",
                "score": 0.0,
                "confidence": 0.2,
                "coverage_ratio": 0.0,
                "available_weight": 0.0,
                "requested_weight": 0.0,
                "status": "no_metadata",
                "model_version": "neo4j-knowledge-graph-v1",
                "predicted_at": utc_now(),
                "evidence": [],
                "inferred_unknown_nodes": 0,
            }

        driver = self._get_driver()
        if driver is None:
            return {
                "label": "Center",
                "score": 0.0,
                "confidence": 0.2,
                "coverage_ratio": 0.0,
                "available_weight": 0.0,
                "requested_weight": round(sum(item["base_weight"] for item in candidates), 4),
                "status": "neo4j_unavailable",
                "model_version": "neo4j-knowledge-graph-v1",
                "predicted_at": utc_now(),
                "evidence": [],
                "inferred_unknown_nodes": 0,
            }

        self.ensure_schema()

        requested_weight = sum(item["base_weight"] for item in candidates)
        available_weight = 0.0
        total_contribution_weight = 0.0
        weighted_score_sum = 0.0
        weighted_confidence_sum = 0.0
        evidence: List[Dict[str, Any]] = []
        per_candidate_rollup: Dict[str, Dict[str, float]] = {}
        graph_status = "ok"
        graph_score = 0.0
        graph_confidence = 0.2
        coverage_ratio = 0.0
        inferred_unknown_nodes = 0

        with driver.session(database=self._session_database()) as session:
            context = self._ensure_article_context(session, candidates)
            known_bias_keys = context["known_bias_keys"]
            unknown_candidates = context["unknown_candidates"]

            for candidate in candidates:
                node_data = session.execute_read(
                    self._fetch_node_with_neighbors,
                    candidate["label"],
                    candidate["key"],
                    DEFAULT_NODE_IMPORTANCE.get(candidate["label"], 0.5),
                )
                if not node_data:
                    continue

                candidate_key = candidate["key"]
                has_related_evidence = False

                node_score = parse_float(node_data.get("bias_score"))
                node_confidence = clamp(
                    parse_float(node_data.get("bias_confidence"), 0.65) or 0.65,
                    0.0,
                    1.0,
                )
                node_importance = max(
                    0.0,
                    parse_float(
                        node_data.get("importance_weight"),
                        DEFAULT_NODE_IMPORTANCE.get(candidate["label"], 0.5),
                    )
                    or DEFAULT_NODE_IMPORTANCE.get(candidate["label"], 0.5),
                )

                if node_score is not None:
                    available_weight += candidate["base_weight"]
                    contribution_weight = candidate["base_weight"] * node_importance
                    weighted_score = float(node_score) * contribution_weight
                    weighted_score_sum += weighted_score
                    weighted_confidence_sum += node_confidence * contribution_weight
                    total_contribution_weight += contribution_weight
                    has_related_evidence = True

                    rollup = per_candidate_rollup.setdefault(
                        candidate_key,
                        {"weight_sum": 0.0, "weighted_sum": 0.0, "confidence_weighted_sum": 0.0},
                    )
                    rollup["weight_sum"] += contribution_weight
                    rollup["weighted_sum"] += weighted_score
                    rollup["confidence_weighted_sum"] += node_confidence * contribution_weight

                    evidence.append(
                        {
                            "source_key": candidate_key,
                            "source_entity": candidate["name"],
                            "source_type": candidate["entity_type"],
                            "matched_node": node_data.get("node_name"),
                            "matched_type": node_data.get("node_type"),
                            "path_hops": 0,
                            "bias_score": float(node_score),
                            "confidence": node_confidence,
                            "contribution_weight": round(contribution_weight, 6),
                            "weighted_contribution": round(weighted_score, 6),
                        }
                    )

                for related in node_data.get("related", []):
                    related_score = parse_float(related.get("bias_score"))
                    if related_score is None:
                        continue

                    related_confidence = clamp(
                        parse_float(related.get("bias_confidence"), 0.55) or 0.55,
                        0.0,
                        1.0,
                    )
                    related_importance = max(
                        0.0,
                        parse_float(related.get("importance_weight"), 0.35) or 0.35,
                    )
                    relationship_weight = max(
                        0.0,
                        parse_float(related.get("relationship_weight"), 0.75) or 0.75,
                    )
                    hops = int(related.get("hops") or 1)
                    hop_decay = 0.55 if hops <= 1 else 0.35

                    contribution_weight = (
                        candidate["base_weight"]
                        * related_importance
                        * relationship_weight
                        * hop_decay
                    )
                    if contribution_weight <= 0:
                        continue

                    weighted_score = float(related_score) * contribution_weight
                    weighted_score_sum += weighted_score
                    weighted_confidence_sum += related_confidence * contribution_weight
                    total_contribution_weight += contribution_weight
                    has_related_evidence = True

                    rollup = per_candidate_rollup.setdefault(
                        candidate_key,
                        {"weight_sum": 0.0, "weighted_sum": 0.0, "confidence_weighted_sum": 0.0},
                    )
                    rollup["weight_sum"] += contribution_weight
                    rollup["weighted_sum"] += weighted_score
                    rollup["confidence_weighted_sum"] += related_confidence * contribution_weight

                    evidence.append(
                        {
                            "source_key": candidate_key,
                            "source_entity": candidate["name"],
                            "source_type": candidate["entity_type"],
                            "matched_node": related.get("node_name"),
                            "matched_type": related.get("node_type"),
                            "path_hops": hops,
                            "bias_score": float(related_score),
                            "confidence": related_confidence,
                            "relationship_weight": round(relationship_weight, 6),
                            "contribution_weight": round(contribution_weight, 6),
                            "weighted_contribution": round(weighted_score, 6),
                        }
                    )

                if candidate_key in known_bias_keys:
                    available_weight += 0.0
                elif has_related_evidence:
                    available_weight += candidate["base_weight"] * 0.6

            coverage_ratio = clamp(
                available_weight / requested_weight if requested_weight > 0 else 0.0,
                0.0,
                1.0,
            )

            if total_contribution_weight <= 0:
                graph_status = "no_graph_match"
                graph_score = 0.0
                graph_confidence = clamp(0.2 + 0.3 * coverage_ratio, 0.1, 0.5)
            else:
                graph_score = clamp(weighted_score_sum / total_contribution_weight, -1.0, 1.0)
                mean_confidence = clamp(weighted_confidence_sum / total_contribution_weight, 0.0, 1.0)
                graph_confidence = clamp(
                    0.15 + (0.45 * coverage_ratio) + (0.40 * mean_confidence),
                    0.05,
                    0.95,
                )

            inferred_unknown_nodes = self._persist_unknown_inference(
                session=session,
                unknown_candidates=unknown_candidates,
                per_candidate_rollup=per_candidate_rollup,
                default_score=graph_score,
                default_confidence=graph_confidence,
            )

        if total_contribution_weight <= 0:
            coverage_ratio = clamp(
                available_weight / requested_weight if requested_weight > 0 else 0.0,
                0.0,
                1.0,
            )
            return {
                "label": "Center",
                "score": 0.0,
                "confidence": clamp(0.2 + 0.3 * coverage_ratio, 0.1, 0.5),
                "coverage_ratio": round(coverage_ratio, 4),
                "available_weight": round(available_weight, 6),
                "requested_weight": round(requested_weight, 6),
                "status": "no_graph_match",
                "model_version": "neo4j-knowledge-graph-v1",
                "predicted_at": utc_now(),
                "evidence": [],
                "inferred_unknown_nodes": inferred_unknown_nodes,
            }

        top_evidence = sorted(
            evidence,
            key=lambda item: abs(item.get("weighted_contribution", 0.0)),
            reverse=True,
        )[:15]
        for item in top_evidence:
            item.pop("source_key", None)

        return {
            "label": score_to_three_class_label(graph_score),
            "score": round(graph_score, 6),
            "confidence": round(graph_confidence, 6),
            "coverage_ratio": round(coverage_ratio, 4),
            "available_weight": round(available_weight, 6),
            "requested_weight": round(requested_weight, 6),
            "status": graph_status,
            "model_version": "neo4j-knowledge-graph-v1",
            "predicted_at": utc_now(),
            "evidence": top_evidence,
            "inferred_unknown_nodes": inferred_unknown_nodes,
        }

    def estimate_ml_signal(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        if self.enable_spark_ml and self._spark_bias_analyzer is not None:
            try:
                return self._spark_bias_analyzer.score_article(metadata, self.ml_model_version)
            except Exception as exc:
                fallback = self._estimate_lexical_ml_signal(metadata)
                fallback["diagnostics"]["spark_fallback_reason"] = (
                    f"{exc.__class__.__name__}: {exc}"
                )
                return fallback

        return self._estimate_lexical_ml_signal(metadata)

    def combine_signals(self, ml_signal: Dict[str, Any], graph_signal: Dict[str, Any]) -> Dict[str, Any]:
        ml_score = parse_float(ml_signal.get("score"), 0.0) or 0.0
        ml_confidence = clamp(parse_float(ml_signal.get("confidence"), 0.5) or 0.5, 0.0, 1.0)
        graph_score = parse_float(graph_signal.get("score"), 0.0) or 0.0
        graph_confidence = clamp(parse_float(graph_signal.get("confidence"), 0.2) or 0.2, 0.0, 1.0)

        graph_status = str(graph_signal.get("status", "")).strip().lower()
        graph_quality = (
            clamp(parse_float(graph_signal.get("coverage_ratio"), 0.0) or 0.0, 0.0, 1.0)
            * graph_confidence
        )
        graph_weight = self.graph_weight
        if graph_status != "ok":
            graph_weight = 0.0
        else:
            graph_weight = graph_weight * clamp(graph_quality + 0.2, 0.2, 1.0)

        ml_weight = self.ml_weight
        if ml_weight + graph_weight <= 0:
            ml_weight = 1.0
            graph_weight = 0.0

        weight_total = ml_weight + graph_weight
        ml_ratio = ml_weight / weight_total
        graph_ratio = graph_weight / weight_total

        final_score = clamp((ml_score * ml_ratio) + (graph_score * graph_ratio), -1.0, 1.0)
        agreement = 1.0 - (min(2.0, abs(ml_score - graph_score)) / 2.0)
        blended_confidence = (ml_confidence * ml_ratio) + (graph_confidence * graph_ratio)
        final_confidence = clamp((0.8 * blended_confidence) + (0.2 * agreement), 0.05, 0.99)

        return {
            "label": score_to_three_class_label(final_score),
            "score": round(final_score, 6),
            "confidence": round(final_confidence, 6),
            "model_version": "hybrid-ml-graph-v1",
            "predicted_at": utc_now(),
            "components": {
                "ml": {
                    "score": round(ml_score, 6),
                    "confidence": round(ml_confidence, 6),
                    "weight": round(ml_ratio, 6),
                },
                "graph": {
                    "score": round(graph_score, 6),
                    "confidence": round(graph_confidence, 6),
                    "weight": round(graph_ratio, 6),
                    "coverage_ratio": round(
                        clamp(parse_float(graph_signal.get("coverage_ratio"), 0.0) or 0.0, 0.0, 1.0),
                        6,
                    ),
                },
            },
        }

    def graph_only_classification(self, graph_signal: Dict[str, Any]) -> Dict[str, Any]:
        graph_score = clamp(parse_float(graph_signal.get("score"), 0.0) or 0.0, -1.0, 1.0)
        graph_confidence = clamp(parse_float(graph_signal.get("confidence"), 0.2) or 0.2, 0.0, 1.0)
        return {
            "label": score_to_three_class_label(graph_score),
            "score": round(graph_score, 6),
            "confidence": round(graph_confidence, 6),
            "model_version": "graph-only-v1",
            "predicted_at": utc_now(),
            "components": {
                "ml": {
                    "status": "disabled",
                    "weight": 0.0,
                },
                "graph": {
                    "score": round(graph_score, 6),
                    "confidence": round(graph_confidence, 6),
                    "weight": 1.0,
                    "coverage_ratio": round(
                        clamp(parse_float(graph_signal.get("coverage_ratio"), 0.0) or 0.0, 0.0, 1.0),
                        6,
                    ),
                },
            },
        }

    @staticmethod
    def ml_disabled_signal() -> Dict[str, Any]:
        return {
            "status": "disabled",
            "label": None,
            "score": None,
            "confidence": None,
            "model_version": None,
            "predicted_at": utc_now(),
        }

    def compute_article_bias(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        graph_signal = self.evaluate_graph_signal(metadata)
        if self.enable_ml_model:
            ml_signal = self.estimate_ml_signal(metadata)
            classification = self.combine_signals(ml_signal, graph_signal)
        else:
            ml_signal = self.ml_disabled_signal()
            classification = self.graph_only_classification(graph_signal)
        return {
            "classification": classification,
            "ml_signal": ml_signal,
            "graph_signal": graph_signal,
        }
