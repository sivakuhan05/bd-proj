from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ASCENDING, MongoClient, ReturnDocument, TEXT

app = FastAPI(title="Political News Bias API")

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
_INDEXES_READY = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def normalize_keywords(keywords: List[str]) -> List[str]:
    cleaned = {normalize_text(keyword) for keyword in keywords if keyword.strip()}
    return sorted(cleaned)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value


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


def get_collections():
    if not MONGO_URI:
        raise HTTPException(status_code=500, detail="MONGO_URI is not configured")

    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
        retryWrites=True,
    )
    db = client["data"]
    collections = {
        "articles": db["articles"],
        "authors": db["authors"],
        "publishers": db["publishers"],
    }
    ensure_indexes(collections)
    return collections, client


def ensure_indexes(collections):
    global _INDEXES_READY
    if _INDEXES_READY:
        return

    collections["authors"].create_index([("author_key", ASCENDING)], unique=True)
    collections["authors"].create_index([("name", ASCENDING)])

    collections["publishers"].create_index([("publisher_key", ASCENDING)], unique=True)
    collections["publishers"].create_index([("name", ASCENDING)])

    collections["articles"].create_index([("author_id", ASCENDING)])
    collections["articles"].create_index([("publisher_id", ASCENDING)])
    collections["articles"].create_index([("classification.label", ASCENDING)])
    collections["articles"].create_index([("keywords", ASCENDING)])
    collections["articles"].create_index(
        [("title", TEXT), ("content", TEXT), ("keywords", TEXT)],
        name="article_text_index",
    )

    _INDEXES_READY = True


def resolve_author(authors_collection, author: AuthorModel) -> ObjectId:
    key = f"{normalize_text(author.name)}::{normalize_text(author.affiliation or '')}"
    now = utc_now()
    author_doc = authors_collection.find_one_and_update(
        {"author_key": key},
        {
            "$set": {
                "name": author.name.strip(),
                "affiliation": author.affiliation,
                "aliases": author.aliases,
                "updated_at": now,
            },
            "$setOnInsert": {
                "author_key": key,
                "created_at": now,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return author_doc["_id"]


def resolve_publisher(
    publishers_collection,
    publisher: Optional[PublisherModel] = None,
    source: Optional[str] = None,
) -> Optional[ObjectId]:
    if publisher:
        name = publisher.name
        website = publisher.website
        country = publisher.country
        aliases = publisher.aliases
    elif source:
        name = source
        website = None
        country = None
        aliases = []
    else:
        return None

    key = normalize_text(name)
    now = utc_now()
    publisher_doc = publishers_collection.find_one_and_update(
        {"publisher_key": key},
        {
            "$set": {
                "name": name.strip(),
                "website": website,
                "country": country,
                "aliases": aliases,
                "updated_at": now,
            },
            "$setOnInsert": {
                "publisher_key": key,
                "created_at": now,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return publisher_doc["_id"]


def hydrate_article(doc: Dict[str, Any], collections) -> Dict[str, Any]:
    article = dict(doc)
    author = None
    publisher = None

    if article.get("author_id"):
        author = collections["authors"].find_one({"_id": article["author_id"]})
    if article.get("publisher_id"):
        publisher = collections["publishers"].find_one({"_id": article["publisher_id"]})

    article["author"] = author or {}
    article["publisher"] = publisher or {}
    article["source"] = (publisher or {}).get("name")
    article["bias"] = article.get("classification")
    return to_jsonable(article)


def get_search_query(
    collections,
    bias: Optional[str],
    keyword: Optional[str],
    author: Optional[str],
    publisher: Optional[str],
    source: Optional[str],
    category: Optional[str],
    q: Optional[str],
):
    query = {}

    if bias:
        query["classification.label"] = bias
    if category:
        query["category"] = category
    if q:
        query["$text"] = {"$search": q}

    if keyword:
        requested = normalize_keywords(keyword.split(","))
        if requested:
            query["keywords"] = {"$all": requested}

    if author:
        author_match = list(
            collections["authors"].find(
                {
                    "$or": [
                        {"name": {"$regex": author, "$options": "i"}},
                        {"aliases": {"$regex": author, "$options": "i"}},
                    ]
                },
                {"_id": 1},
            )
        )
        author_ids = [item["_id"] for item in author_match]
        if not author_ids:
            return {"_id": {"$exists": False}}
        query["author_id"] = {"$in": author_ids}

    publisher_name = publisher or source
    if publisher_name:
        publisher_match = list(
            collections["publishers"].find(
                {
                    "$or": [
                        {"name": {"$regex": publisher_name, "$options": "i"}},
                        {"aliases": {"$regex": publisher_name, "$options": "i"}},
                    ]
                },
                {"_id": 1},
            )
        )
        publisher_ids = [item["_id"] for item in publisher_match]
        if not publisher_ids:
            return {"_id": {"$exists": False}}
        query["publisher_id"] = {"$in": publisher_ids}

    return query


def resolve_classification(
    classification: Optional[ClassificationModel],
    bias: Optional[ClassificationModel],
):
    selected = classification or bias
    if not selected:
        return None
    doc = selected.model_dump(exclude_none=True)
    doc["predicted_at"] = utc_now()
    return doc


def resolve_classification_update(
    classification: Optional[ClassificationUpdateModel],
    bias: Optional[ClassificationUpdateModel],
    existing: Optional[Dict[str, Any]] = None,
):
    incoming = classification or bias
    if not incoming:
        return None
    merged = dict(existing or {})
    merged.update(incoming.model_dump(exclude_none=True))
    merged["predicted_at"] = utc_now()
    return merged


@app.get("/")
def root():
    return {"message": "Political News Bias API is running"}


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
    collections, client = get_collections()
    query = get_search_query(
        collections=collections,
        bias=bias,
        keyword=keyword,
        author=author,
        publisher=publisher,
        source=source,
        category=category,
        q=q,
    )

    pipeline = [
        {"$match": query},
        {"$sort": {"created_at": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "authors",
                "localField": "author_id",
                "foreignField": "_id",
                "as": "author",
            }
        },
        {
            "$lookup": {
                "from": "publishers",
                "localField": "publisher_id",
                "foreignField": "_id",
                "as": "publisher",
            }
        },
        {
            "$addFields": {
                "author": {"$ifNull": [{"$arrayElemAt": ["$author", 0]}, {}]},
                "publisher": {"$ifNull": [{"$arrayElemAt": ["$publisher", 0]}, {}]},
                "bias": "$classification",
            }
        },
        {"$addFields": {"source": "$publisher.name"}},
    ]

    results = list(collections["articles"].aggregate(pipeline))
    hydrated = [to_jsonable(doc) for doc in results]
    client.close()
    return hydrated


@app.post("/articles", status_code=201)
def create_article(payload: ArticleCreate):
    collections, client = get_collections()

    classification = resolve_classification(payload.classification, payload.bias)
    if not classification:
        client.close()
        raise HTTPException(
            status_code=400,
            detail="classification (or bias) is required with label and confidence",
        )

    author_id = resolve_author(collections["authors"], payload.author)
    publisher_id = resolve_publisher(
        collections["publishers"], publisher=payload.publisher, source=payload.source
    )

    now = utc_now()
    article_doc = {
        "title": payload.title.strip(),
        "content": payload.content.strip(),
        "published_date": payload.published_date,
        "category": payload.category,
        "author_id": author_id,
        "publisher_id": publisher_id,
        "classification": classification,
        "keywords": normalize_keywords(payload.keywords),
        "engagement": payload.engagement.model_dump(),
        "comments": [comment.model_dump() for comment in payload.comments],
        "topic_scores": payload.topic_scores,
        "created_at": now,
        "updated_at": now,
    }

    result = collections["articles"].insert_one(article_doc)
    article = collections["articles"].find_one({"_id": result.inserted_id})

    hydrated = hydrate_article(article, collections)
    client.close()
    return hydrated


@app.put("/articles/{article_id}")
def update_article(article_id: str, payload: ArticleUpdate):
    collections, client = get_collections()

    try:
        object_id = ObjectId(article_id)
    except Exception:
        client.close()
        raise HTTPException(status_code=400, detail="Invalid article_id")

    article = collections["articles"].find_one({"_id": object_id})
    if not article:
        client.close()
        raise HTTPException(status_code=404, detail="Article not found")

    update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not update_data:
        client.close()
        raise HTTPException(status_code=400, detail="No fields provided for update")

    set_fields: Dict[str, Any] = {"updated_at": utc_now()}

    direct_fields = ["title", "content", "published_date", "category", "topic_scores"]
    for field in direct_fields:
        if field in update_data:
            set_fields[field] = update_data[field]

    if "keywords" in update_data:
        set_fields["keywords"] = normalize_keywords(update_data["keywords"])

    if "engagement" in update_data:
        set_fields["engagement"] = update_data["engagement"]

    if "comments" in update_data:
        set_fields["comments"] = update_data["comments"]

    classification_update = resolve_classification_update(
        payload.classification,
        payload.bias,
        existing=article.get("classification"),
    )
    if classification_update:
        set_fields["classification"] = classification_update

    if payload.author:
        if not payload.author.name:
            client.close()
            raise HTTPException(
                status_code=400,
                detail="author.name is required when updating author reference",
            )
        author_doc = AuthorModel(
            name=payload.author.name,
            affiliation=payload.author.affiliation,
            aliases=payload.author.aliases or [],
        )
        set_fields["author_id"] = resolve_author(collections["authors"], author_doc)

    if payload.publisher or payload.source:
        publisher_doc = None
        if payload.publisher and not payload.publisher.name:
            client.close()
            raise HTTPException(
                status_code=400,
                detail="publisher.name is required when updating publisher reference",
            )
        if payload.publisher:
            publisher_doc = PublisherModel(
                name=payload.publisher.name,
                website=payload.publisher.website,
                country=payload.publisher.country,
                aliases=payload.publisher.aliases or [],
            )
        set_fields["publisher_id"] = resolve_publisher(
            collections["publishers"], publisher=publisher_doc, source=payload.source
        )

    collections["articles"].update_one({"_id": object_id}, {"$set": set_fields})

    updated = collections["articles"].find_one({"_id": object_id})
    hydrated = hydrate_article(updated, collections)
    client.close()
    return hydrated


@app.delete("/articles/{article_id}")
def delete_article(article_id: str):
    collections, client = get_collections()

    try:
        object_id = ObjectId(article_id)
    except Exception:
        client.close()
        raise HTTPException(status_code=400, detail="Invalid article_id")

    result = collections["articles"].delete_one({"_id": object_id})
    client.close()

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Article not found")

    return {
        "message": "Article deleted successfully",
        "article_id": article_id,
    }
