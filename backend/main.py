from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
import requests

app = FastAPI(title="Political News Bias API")

load_dotenv()
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
_SCHEMA_READY = False


class AuthorModel(BaseModel):
    name: str
    affiliation: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)


class AuthorUpdateModel(BaseModel):
    name: Optional[str] = None
    affiliation: Optional[str] = None
    aliases: Optional[List[str]] = None


class PublisherModel(BaseModel):
    name: str
    website: Optional[str] = None
    country: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)


class PublisherUpdateModel(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    country: Optional[str] = None
    aliases: Optional[List[str]] = None


class ClassificationModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    label: str = Field(..., examples=["Left", "Right", "Center"])
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_version: Optional[str] = "prototype-v1"


class ClassificationUpdateModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    label: Optional[str] = Field(None, examples=["Left", "Right", "Center"])
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    model_version: Optional[str] = None


class EngagementModel(BaseModel):
    likes: int = 0
    shares: int = 0
    views: int = 0


class EngagementUpdateModel(BaseModel):
    likes: Optional[int] = None
    shares: Optional[int] = None
    views: Optional[int] = None


class CommentModel(BaseModel):
    user: str
    comment: str
    likes: int = 0
    timestamp: str
    flags: List[str] = Field(default_factory=list)


class ArticleCreate(BaseModel):
    title: str
    content: str
    published_date: Optional[str] = None
    category: Optional[str] = None
    author: AuthorModel
    publisher: Optional[PublisherModel] = None
    source: Optional[str] = None
    classification: Optional[ClassificationModel] = None
    bias: Optional[ClassificationModel] = None
    keywords: List[str] = Field(default_factory=list)
    engagement: EngagementModel = Field(default_factory=EngagementModel)
    comments: List[CommentModel] = Field(default_factory=list)
    topic_scores: Dict[str, float] = Field(default_factory=dict)


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    published_date: Optional[str] = None
    category: Optional[str] = None
    author: Optional[AuthorUpdateModel] = None
    publisher: Optional[PublisherUpdateModel] = None
    source: Optional[str] = None
    classification: Optional[ClassificationUpdateModel] = None
    bias: Optional[ClassificationUpdateModel] = None
    keywords: Optional[List[str]] = None
    engagement: Optional[EngagementUpdateModel] = None
    comments: Optional[List[CommentModel]] = None
    topic_scores: Optional[Dict[str, float]] = None


class Neo4jConfigError(RuntimeError):
    pass


class Neo4jQueryError(RuntimeError):
    pass


class Neo4jDataError(RuntimeError):
    pass


SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT article_id_unique IF NOT EXISTS FOR (a:Article) REQUIRE a.article_id IS UNIQUE",
    "CREATE CONSTRAINT author_key_unique IF NOT EXISTS FOR (a:Author) REQUIRE a.author_key IS UNIQUE",
    "CREATE CONSTRAINT publisher_key_unique IF NOT EXISTS FOR (p:Publisher) REQUIRE p.publisher_key IS UNIQUE",
    "CREATE CONSTRAINT keyword_name_unique IF NOT EXISTS FOR (k:Keyword) REQUIRE k.name IS UNIQUE",
    "CREATE CONSTRAINT topic_name_unique IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT category_name_unique IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT comment_id_unique IF NOT EXISTS FOR (c:Comment) REQUIRE c.comment_id IS UNIQUE",
    "CREATE INDEX article_created_at IF NOT EXISTS FOR (a:Article) ON (a.created_at)",
    "CREATE INDEX article_bias_label IF NOT EXISTS FOR (a:Article) ON (a.bias_label)",
    "CREATE INDEX article_category IF NOT EXISTS FOR (a:Article) ON (a.category)",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def normalize_keywords(keywords: List[str]) -> List[str]:
    cleaned = {normalize_text(keyword) for keyword in keywords if keyword.strip()}
    return sorted(cleaned)


def clean_topic_scores(topic_scores: Dict[str, float]) -> Dict[str, float]:
    cleaned: Dict[str, float] = {}
    for name, score in topic_scores.items():
        topic_name = normalize_text(name)
        if topic_name:
            cleaned[topic_name] = float(score)
    return cleaned


def get_http_endpoint() -> str:
    if not NEO4J_URI or not NEO4J_USERNAME or not NEO4J_PASSWORD:
        raise Neo4jConfigError(
            "NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be configured"
        )

    parsed = urlparse(NEO4J_URI)
    host = parsed.netloc or parsed.path
    if not host:
        raise Neo4jConfigError("NEO4J_URI is invalid")

    scheme = "https" if parsed.scheme.endswith("s") else "http"
    return f"{scheme}://{host}/db/{NEO4J_DATABASE}/tx/commit"


def extract_records(payload: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    errors = payload.get("errors", []) or []
    if errors:
        first_error = errors[0]
        raise Neo4jQueryError(first_error.get("message", "Neo4j query failed"))

    extracted: List[List[Dict[str, Any]]] = []
    for result in payload.get("results", []):
        columns = result.get("columns", []) or []
        result_records = []
        for data_entry in result.get("data", []) or []:
            row = data_entry.get("row", []) or []
            result_records.append(
                {column: row[index] if index < len(row) else None for index, column in enumerate(columns)}
            )
        extracted.append(result_records)
    return extracted


def run_cypher_batch(
    statements: List[Dict[str, Any]], *, ensure_schema_ready: bool = True
) -> List[List[Dict[str, Any]]]:
    if ensure_schema_ready:
        ensure_schema()

    payload = {
        "statements": [
            {
                "statement": item["statement"],
                "parameters": item.get("parameters", {}),
                "resultDataContents": ["row"],
            }
            for item in statements
        ]
    }

    session = requests.Session()
    session.trust_env = False

    try:
        response = session.post(
            get_http_endpoint(),
            json=payload,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise Neo4jQueryError(f"Neo4j request failed: {exc}") from exc
    finally:
        session.close()

    try:
        return extract_records(response.json())
    except ValueError as exc:
        raise Neo4jQueryError("Neo4j returned a non-JSON response") from exc


def run_cypher(statement: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return run_cypher_batch(
        [{"statement": statement, "parameters": parameters or {}}]
    )[0]


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    run_cypher_batch(
        [{"statement": statement, "parameters": {}} for statement in SCHEMA_STATEMENTS],
        ensure_schema_ready=False,
    )
    _SCHEMA_READY = True


def resolve_author_payload(author: AuthorModel | AuthorUpdateModel) -> Dict[str, Any]:
    name = (author.name or "").strip()
    if not name:
        raise Neo4jDataError("author.name is required")

    affiliation = author.affiliation.strip() if author.affiliation else None
    aliases = [alias.strip() for alias in (author.aliases or []) if alias.strip()]
    return {
        "author_key": f"{normalize_text(name)}::{normalize_text(affiliation or '')}",
        "name": name,
        "affiliation": affiliation,
        "aliases": aliases,
    }


def resolve_publisher_payload(
    publisher: Optional[PublisherModel | PublisherUpdateModel] = None,
    source: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if publisher:
        name = (publisher.name or "").strip()
        if not name:
            raise Neo4jDataError("publisher.name is required")
        website = publisher.website.strip() if publisher.website else None
        country = publisher.country.strip() if publisher.country else None
        aliases = [alias.strip() for alias in (publisher.aliases or []) if alias.strip()]
    elif source and source.strip():
        name = source.strip()
        website = None
        country = None
        aliases = []
    else:
        return None

    return {
        "publisher_key": normalize_text(name),
        "name": name,
        "website": website,
        "country": country,
        "aliases": aliases,
    }


def resolve_classification(
    classification: Optional[ClassificationModel],
    bias: Optional[ClassificationModel],
) -> Optional[Dict[str, Any]]:
    selected = classification or bias
    if not selected:
        return None
    doc = selected.model_dump(exclude_none=True)
    doc["predicted_at"] = utc_now_iso()
    return doc


def resolve_classification_update(
    classification: Optional[ClassificationUpdateModel],
    bias: Optional[ClassificationUpdateModel],
    existing: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    incoming = classification or bias
    if not incoming:
        return None
    merged = dict(existing or {})
    merged.update(incoming.model_dump(exclude_none=True))
    merged["predicted_at"] = utc_now_iso()
    return merged


def build_comment_payloads(comments: List[CommentModel]) -> List[Dict[str, Any]]:
    payloads = []
    for comment in comments:
        payloads.append(
            {
                "comment_id": str(uuid4()),
                "user": comment.user.strip(),
                "comment": comment.comment.strip(),
                "likes": int(comment.likes),
                "timestamp": comment.timestamp,
                "flags": [flag.strip() for flag in comment.flags if flag.strip()],
            }
        )
    return payloads


def article_projection_query(match_clause: str, where_clause: str = "") -> str:
    return f"""
    {match_clause}
    OPTIONAL MATCH (author:Author)-[:AUTHORED]->(article)
    OPTIONAL MATCH (article)-[:PUBLISHED_BY]->(publisher:Publisher)
    OPTIONAL MATCH (article)-[topicRel:HAS_TOPIC]->(topic:Topic)
    WITH article, author, publisher,
         collect(DISTINCT CASE WHEN topic IS NULL THEN NULL ELSE {{name: topic.name, score: topicRel.score}} END) AS topic_entries
    OPTIONAL MATCH (article)-[:HAS_COMMENT]->(comment:Comment)
    WITH article, author, publisher, topic_entries,
         collect(DISTINCT CASE WHEN comment IS NULL THEN NULL ELSE comment{{.comment_id, .user, .comment, .likes, .timestamp, .flags}} END) AS raw_comments
    {where_clause}
    RETURN {{
        _id: article.article_id,
        article_id: article.article_id,
        title: article.title,
        content: article.content,
        published_date: article.published_date,
        category: article.category,
        classification: CASE WHEN article.bias_label IS NULL THEN NULL ELSE {{
            label: article.bias_label,
            confidence: article.bias_confidence,
            model_version: article.bias_model_version,
            predicted_at: article.bias_predicted_at
        }} END,
        bias: CASE WHEN article.bias_label IS NULL THEN NULL ELSE {{
            label: article.bias_label,
            confidence: article.bias_confidence,
            model_version: article.bias_model_version,
            predicted_at: article.bias_predicted_at
        }} END,
        keywords: coalesce(article.keywords, []),
        engagement: {{
            likes: coalesce(article.likes, 0),
            shares: coalesce(article.shares, 0),
            views: coalesce(article.views, 0)
        }},
        comments: [item IN raw_comments WHERE item IS NOT NULL | item{{.user, .comment, .likes, .timestamp, .flags}}],
        topic_entries: [item IN topic_entries WHERE item IS NOT NULL | item],
        author: CASE WHEN author IS NULL THEN {{}} ELSE author{{.name, .affiliation, .aliases, .author_key, .created_at, .updated_at}} END,
        publisher: CASE WHEN publisher IS NULL THEN {{}} ELSE publisher{{.name, .website, .country, .aliases, .publisher_key, .created_at, .updated_at}} END,
        source: CASE WHEN publisher IS NULL THEN NULL ELSE publisher.name END,
        created_at: article.created_at,
        updated_at: article.updated_at
    }} AS article
    """


def normalize_article_record(record: Dict[str, Any]) -> Dict[str, Any]:
    article = dict(record.get("article") or {})
    topic_entries = article.pop("topic_entries", []) or []
    article["topic_scores"] = {
        entry["name"]: entry["score"]
        for entry in topic_entries
        if entry and entry.get("name") is not None and entry.get("score") is not None
    }
    return article


def fetch_article(article_id: str) -> Optional[Dict[str, Any]]:
    query = article_projection_query(
        "MATCH (article:Article {article_id: $article_id})",
        "",
    )
    rows = run_cypher(query, {"article_id": article_id})
    if not rows:
        return None
    return normalize_article_record(rows[0])


def fetch_existing_article_state(article_id: str) -> Optional[Dict[str, Any]]:
    rows = run_cypher(
        """
        MATCH (article:Article {article_id: $article_id})
        RETURN {
            classification: CASE WHEN article.bias_label IS NULL THEN NULL ELSE {
                label: article.bias_label,
                confidence: article.bias_confidence,
                model_version: article.bias_model_version,
                predicted_at: article.bias_predicted_at
            } END,
            engagement: {
                likes: coalesce(article.likes, 0),
                shares: coalesce(article.shares, 0),
                views: coalesce(article.views, 0)
            }
        } AS article_state
        """,
        {"article_id": article_id},
    )
    if not rows:
        return None
    return rows[0]["article_state"]


def upsert_author_statement(author_payload: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    return {
        "statement": """
        MERGE (author:Author {author_key: $author_key})
        ON CREATE SET author.created_at = $now
        SET author.name = $name,
            author.affiliation = $affiliation,
            author.aliases = $aliases,
            author.updated_at = $now
        """,
        "parameters": {**author_payload, "now": now_iso},
    }


def upsert_publisher_statement(publisher_payload: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    return {
        "statement": """
        MERGE (publisher:Publisher {publisher_key: $publisher_key})
        ON CREATE SET publisher.created_at = $now
        SET publisher.name = $name,
            publisher.website = $website,
            publisher.country = $country,
            publisher.aliases = $aliases,
            publisher.updated_at = $now
        """,
        "parameters": {**publisher_payload, "now": now_iso},
    }


def create_article_statements(
    article_properties: Dict[str, Any],
    author_payload: Dict[str, Any],
    publisher_payload: Optional[Dict[str, Any]],
    category: Optional[str],
    keywords: List[str],
    topic_scores: Dict[str, float],
    comments: List[Dict[str, Any]],
    now_iso: str,
) -> List[Dict[str, Any]]:
    statements: List[Dict[str, Any]] = [upsert_author_statement(author_payload, now_iso)]
    if publisher_payload:
        statements.append(upsert_publisher_statement(publisher_payload, now_iso))

    statements.extend(
        [
            {
                "statement": """
                CREATE (article:Article {
                    article_id: $article_id,
                    title: $title,
                    content: $content,
                    published_date: $published_date,
                    category: $category,
                    bias_label: $bias_label,
                    bias_confidence: $bias_confidence,
                    bias_model_version: $bias_model_version,
                    bias_predicted_at: $bias_predicted_at,
                    keywords: $keywords,
                    likes: $likes,
                    shares: $shares,
                    views: $views,
                    created_at: $created_at,
                    updated_at: $updated_at
                })
                """,
                "parameters": article_properties,
            },
            {
                "statement": """
                MATCH (author:Author {author_key: $author_key})
                MATCH (article:Article {article_id: $article_id})
                MERGE (author)-[:AUTHORED]->(article)
                """,
                "parameters": {
                    "author_key": author_payload["author_key"],
                    "article_id": article_properties["article_id"],
                },
            },
        ]
    )

    if publisher_payload:
        statements.append(
            {
                "statement": """
                MATCH (publisher:Publisher {publisher_key: $publisher_key})
                MATCH (article:Article {article_id: $article_id})
                MERGE (article)-[:PUBLISHED_BY]->(publisher)
                """,
                "parameters": {
                    "publisher_key": publisher_payload["publisher_key"],
                    "article_id": article_properties["article_id"],
                },
            }
        )

    if category:
        statements.append(
            {
                "statement": """
                MATCH (article:Article {article_id: $article_id})
                MERGE (category:Category {name: $category})
                MERGE (category)-[:IN_CATEGORY]->(article)
                """,
                "parameters": {"article_id": article_properties["article_id"], "category": category},
            }
        )

    if keywords:
        statements.append(
            {
                "statement": """
                MATCH (article:Article {article_id: $article_id})
                UNWIND $keywords AS keyword_name
                MERGE (keyword:Keyword {name: keyword_name})
                MERGE (article)-[:HAS_KEYWORD]->(keyword)
                """,
                "parameters": {"article_id": article_properties["article_id"], "keywords": keywords},
            }
        )

    if topic_scores:
        topic_rows = [{"name": name, "score": score} for name, score in topic_scores.items()]
        statements.append(
            {
                "statement": """
                MATCH (article:Article {article_id: $article_id})
                UNWIND $topics AS topic_data
                MERGE (topic:Topic {name: topic_data.name})
                MERGE (article)-[rel:HAS_TOPIC]->(topic)
                SET rel.score = topic_data.score
                """,
                "parameters": {"article_id": article_properties["article_id"], "topics": topic_rows},
            }
        )

    if comments:
        statements.append(
            {
                "statement": """
                MATCH (article:Article {article_id: $article_id})
                UNWIND $comments AS comment_data
                CREATE (comment:Comment {
                    comment_id: comment_data.comment_id,
                    user: comment_data.user,
                    comment: comment_data.comment,
                    likes: comment_data.likes,
                    timestamp: comment_data.timestamp,
                    flags: comment_data.flags
                })
                MERGE (article)-[:HAS_COMMENT]->(comment)
                """,
                "parameters": {"article_id": article_properties["article_id"], "comments": comments},
            }
        )

    return statements


def replace_relationships_statements(
    article_id: str,
    *,
    author_payload: Optional[Dict[str, Any]] = None,
    publisher_payload: Optional[Dict[str, Any]] = None,
    category: Optional[str] = None,
    replace_category: bool = False,
    keywords: Optional[List[str]] = None,
    topic_scores: Optional[Dict[str, float]] = None,
    comments: Optional[List[Dict[str, Any]]] = None,
    now_iso: Optional[str] = None,
) -> List[Dict[str, Any]]:
    statements: List[Dict[str, Any]] = []

    if author_payload:
        statements.append(upsert_author_statement(author_payload, now_iso or utc_now_iso()))
        statements.append(
            {
                "statement": "MATCH (:Author)-[rel:AUTHORED]->(:Article {article_id: $article_id}) DELETE rel",
                "parameters": {"article_id": article_id},
            }
        )
        statements.append(
            {
                "statement": """
                MATCH (author:Author {author_key: $author_key})
                MATCH (article:Article {article_id: $article_id})
                MERGE (author)-[:AUTHORED]->(article)
                """,
                "parameters": {"author_key": author_payload["author_key"], "article_id": article_id},
            }
        )

    if publisher_payload is not None:
        statements.append(
            {
                "statement": "MATCH (:Publisher)-[rel:PUBLISHED_BY]->(:Article {article_id: $article_id}) DELETE rel",
                "parameters": {"article_id": article_id},
            }
        )
        if publisher_payload:
            statements.append(upsert_publisher_statement(publisher_payload, now_iso or utc_now_iso()))
            statements.append(
                {
                    "statement": """
                    MATCH (publisher:Publisher {publisher_key: $publisher_key})
                    MATCH (article:Article {article_id: $article_id})
                    MERGE (article)-[:PUBLISHED_BY]->(publisher)
                    """,
                    "parameters": {
                        "publisher_key": publisher_payload["publisher_key"],
                        "article_id": article_id,
                    },
                }
            )

    if replace_category:
        statements.append(
            {
                "statement": "MATCH (:Category)-[rel:IN_CATEGORY]->(:Article {article_id: $article_id}) DELETE rel",
                "parameters": {"article_id": article_id},
            }
        )
        if category:
            statements.append(
                {
                    "statement": """
                    MATCH (article:Article {article_id: $article_id})
                    MERGE (category:Category {name: $category})
                    MERGE (category)-[:IN_CATEGORY]->(article)
                    """,
                    "parameters": {"article_id": article_id, "category": category},
                }
            )

    if keywords is not None:
        statements.append(
            {
                "statement": "MATCH (article:Article {article_id: $article_id})-[rel:HAS_KEYWORD]->(:Keyword) DELETE rel",
                "parameters": {"article_id": article_id},
            }
        )
        if keywords:
            statements.append(
                {
                    "statement": """
                    MATCH (article:Article {article_id: $article_id})
                    UNWIND $keywords AS keyword_name
                    MERGE (keyword:Keyword {name: keyword_name})
                    MERGE (article)-[:HAS_KEYWORD]->(keyword)
                    """,
                    "parameters": {"article_id": article_id, "keywords": keywords},
                }
            )

    if topic_scores is not None:
        statements.append(
            {
                "statement": "MATCH (article:Article {article_id: $article_id})-[rel:HAS_TOPIC]->(:Topic) DELETE rel",
                "parameters": {"article_id": article_id},
            }
        )
        if topic_scores:
            statements.append(
                {
                    "statement": """
                    MATCH (article:Article {article_id: $article_id})
                    UNWIND $topics AS topic_data
                    MERGE (topic:Topic {name: topic_data.name})
                    MERGE (article)-[rel:HAS_TOPIC]->(topic)
                    SET rel.score = topic_data.score
                    """,
                    "parameters": {
                        "article_id": article_id,
                        "topics": [{"name": name, "score": score} for name, score in topic_scores.items()],
                    },
                }
            )

    if comments is not None:
        statements.append(
            {
                "statement": "MATCH (article:Article {article_id: $article_id})-[:HAS_COMMENT]->(comment:Comment) DETACH DELETE comment",
                "parameters": {"article_id": article_id},
            }
        )
        if comments:
            statements.append(
                {
                    "statement": """
                    MATCH (article:Article {article_id: $article_id})
                    UNWIND $comments AS comment_data
                    CREATE (comment:Comment {
                        comment_id: comment_data.comment_id,
                        user: comment_data.user,
                        comment: comment_data.comment,
                        likes: comment_data.likes,
                        timestamp: comment_data.timestamp,
                        flags: comment_data.flags
                    })
                    MERGE (article)-[:HAS_COMMENT]->(comment)
                    """,
                    "parameters": {"article_id": article_id, "comments": comments},
                }
            )

    return statements


@app.get("/")
def root():
    return {"message": "Political News Bias API is running on Neo4j"}


@app.get("/search")
def search_articles(
    bias: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    publisher: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Full text query on title/content"),
    skip: int = Query(0, ge=0),
):
    return read_articles(
        bias=bias,
        source=source,
        keyword=keyword,
        author=author,
        publisher=publisher,
        category=category,
        q=q,
        skip=skip,
        limit=50,
    )


@app.get("/articles")
def read_articles(
    bias: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    publisher: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Full text query on title/content"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    requested_keywords = normalize_keywords(keyword.split(",")) if keyword else []
    publisher_name = publisher or source
    query = article_projection_query(
        "MATCH (article:Article)",
        """
        WHERE ($bias IS NULL OR article.bias_label = $bias)
          AND ($category IS NULL OR article.category = $category)
          AND (
                $q IS NULL OR
                toLower(coalesce(article.title, '')) CONTAINS toLower($q) OR
                toLower(coalesce(article.content, '')) CONTAINS toLower($q) OR
                ANY(term IN coalesce(article.keywords, []) WHERE term CONTAINS toLower($q))
          )
          AND (
                $author IS NULL OR (
                    author IS NOT NULL AND (
                        toLower(coalesce(author.name, '')) CONTAINS toLower($author) OR
                        ANY(alias IN coalesce(author.aliases, []) WHERE toLower(alias) CONTAINS toLower($author))
                    )
                )
          )
          AND (
                $publisher IS NULL OR (
                    publisher IS NOT NULL AND (
                        toLower(coalesce(publisher.name, '')) CONTAINS toLower($publisher) OR
                        ANY(alias IN coalesce(publisher.aliases, []) WHERE toLower(alias) CONTAINS toLower($publisher))
                    )
                )
          )
          AND ALL(requested IN $requested_keywords WHERE requested IN coalesce(article.keywords, []))
        WITH article, author, publisher, topic_entries, raw_comments
        ORDER BY article.created_at DESC
        SKIP $skip
        LIMIT $limit
        """,
    )

    try:
        rows = run_cypher(
            query,
            {
                "bias": bias,
                "category": category,
                "q": q.strip() if q else None,
                "author": author.strip() if author else None,
                "publisher": publisher_name.strip() if publisher_name else None,
                "requested_keywords": requested_keywords,
                "skip": skip,
                "limit": limit,
            },
        )
        return [normalize_article_record(row) for row in rows]
    except (Neo4jConfigError, Neo4jQueryError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/articles", status_code=201)
def create_article(payload: ArticleCreate):
    classification = resolve_classification(payload.classification, payload.bias)
    if not classification:
        raise HTTPException(
            status_code=400,
            detail="classification (or bias) is required with label and confidence",
        )

    try:
        now_iso = utc_now_iso()
        article_id = str(uuid4())
        author_payload = resolve_author_payload(payload.author)
        publisher_payload = resolve_publisher_payload(payload.publisher, payload.source)
        keywords = normalize_keywords(payload.keywords)
        topic_scores = clean_topic_scores(payload.topic_scores)
        comments = build_comment_payloads(payload.comments)

        article_properties = {
            "article_id": article_id,
            "title": payload.title.strip(),
            "content": payload.content.strip(),
            "published_date": payload.published_date,
            "category": payload.category,
            "bias_label": classification["label"],
            "bias_confidence": classification["confidence"],
            "bias_model_version": classification.get("model_version"),
            "bias_predicted_at": classification["predicted_at"],
            "keywords": keywords,
            "likes": payload.engagement.likes,
            "shares": payload.engagement.shares,
            "views": payload.engagement.views,
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        run_cypher_batch(
            create_article_statements(
                article_properties,
                author_payload,
                publisher_payload,
                payload.category,
                keywords,
                topic_scores,
                comments,
                now_iso,
            )
        )
        article = fetch_article(article_id)
        if not article:
            raise Neo4jQueryError("Article was created but could not be reloaded")
        return article
    except Neo4jDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (Neo4jConfigError, Neo4jQueryError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/articles/{article_id}")
def update_article(article_id: str, payload: ArticleUpdate):
    update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    try:
        existing = fetch_existing_article_state(article_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Article not found")

        now_iso = utc_now_iso()
        set_clauses = ["article.updated_at = $updated_at"]
        params: Dict[str, Any] = {"article_id": article_id, "updated_at": now_iso}

        direct_fields = ["title", "content", "published_date", "category"]
        for field in direct_fields:
            if field in update_data:
                params[field] = update_data[field]
                set_clauses.append(f"article.{field} = ${field}")

        if payload.classification or payload.bias:
            classification_update = resolve_classification_update(
                payload.classification,
                payload.bias,
                existing=existing.get("classification"),
            )
            params.update(
                {
                    "bias_label": classification_update["label"],
                    "bias_confidence": classification_update["confidence"],
                    "bias_model_version": classification_update.get("model_version"),
                    "bias_predicted_at": classification_update["predicted_at"],
                }
            )
            set_clauses.extend(
                [
                    "article.bias_label = $bias_label",
                    "article.bias_confidence = $bias_confidence",
                    "article.bias_model_version = $bias_model_version",
                    "article.bias_predicted_at = $bias_predicted_at",
                ]
            )

        if payload.engagement:
            engagement = dict(existing.get("engagement") or {})
            engagement.update(payload.engagement.model_dump(exclude_none=True))
            params.update(engagement)
            set_clauses.extend(
                [
                    "article.likes = $likes",
                    "article.shares = $shares",
                    "article.views = $views",
                ]
            )

        if payload.keywords is not None:
            params["keywords"] = normalize_keywords(payload.keywords)
            set_clauses.append("article.keywords = $keywords")

        statements: List[Dict[str, Any]] = [
            {
                "statement": f"""
                MATCH (article:Article {{article_id: $article_id}})
                SET {', '.join(set_clauses)}
                """,
                "parameters": params,
            }
        ]

        if payload.author:
            statements.extend(
                replace_relationships_statements(
                    article_id,
                    author_payload=resolve_author_payload(payload.author),
                    now_iso=now_iso,
                )
            )

        if payload.publisher or payload.source:
            statements.extend(
                replace_relationships_statements(
                    article_id,
                    publisher_payload=resolve_publisher_payload(payload.publisher, payload.source),
                    now_iso=now_iso,
                )
            )

        if "category" in update_data:
            statements.extend(
                replace_relationships_statements(
                    article_id,
                    category=update_data.get("category"),
                    replace_category=True,
                )
            )

        if payload.keywords is not None:
            statements.extend(
                replace_relationships_statements(
                    article_id,
                    keywords=normalize_keywords(payload.keywords),
                )
            )

        if payload.topic_scores is not None:
            statements.extend(
                replace_relationships_statements(
                    article_id,
                    topic_scores=clean_topic_scores(payload.topic_scores),
                )
            )

        if payload.comments is not None:
            statements.extend(
                replace_relationships_statements(
                    article_id,
                    comments=build_comment_payloads(payload.comments),
                )
            )

        run_cypher_batch(statements)
        article = fetch_article(article_id)
        if not article:
            raise Neo4jQueryError("Article was updated but could not be reloaded")
        return article
    except HTTPException:
        raise
    except Neo4jDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (Neo4jConfigError, Neo4jQueryError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/articles/{article_id}")
def delete_article(article_id: str):
    try:
        existing = fetch_existing_article_state(article_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Article not found")

        run_cypher_batch(
            [
                {
                    "statement": "MATCH (article:Article {article_id: $article_id})-[:HAS_COMMENT]->(comment:Comment) DETACH DELETE comment",
                    "parameters": {"article_id": article_id},
                },
                {
                    "statement": "MATCH (article:Article {article_id: $article_id}) DETACH DELETE article",
                    "parameters": {"article_id": article_id},
                },
            ]
        )
        return {"message": "Article deleted successfully", "article_id": article_id}
    except HTTPException:
        raise
    except (Neo4jConfigError, Neo4jQueryError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
