from fastapi import FastAPI, HTTPException, Query
from pymongo import MongoClient
from bson import ObjectId
from typing import List, Optional
from pydantic import BaseModel, Field
import os
from dotenv import load_dotenv

app = FastAPI(title="Political News Bias API")

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")


class AuthorModel(BaseModel):
    name: str
    affiliation: str


class AuthorUpdateModel(BaseModel):
    name: Optional[str] = None
    affiliation: Optional[str] = None


class BiasModel(BaseModel):
    label: str = Field(..., examples=["Left", "Right", "Center"])
    confidence: float


class BiasUpdateModel(BaseModel):
    label: Optional[str] = Field(None, examples=["Left", "Right", "Center"])
    confidence: Optional[float] = None


class EngagementModel(BaseModel):
    likes: int
    shares: int


class EngagementUpdateModel(BaseModel):
    likes: Optional[int] = None
    shares: Optional[int] = None


class CommentModel(BaseModel):
    user: str
    comment: str
    likes: int
    timestamp: str


class ArticleBase(BaseModel):
    title: str
    source: str
    author: AuthorModel
    published_date: str
    category: str
    bias: BiasModel
    content: str
    keywords: List[str] = Field(default_factory=list)
    engagement: EngagementModel
    comments: List[CommentModel] = Field(default_factory=list)


class ArticleCreate(ArticleBase):
    pass


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    source: Optional[str] = None
    author: Optional[AuthorUpdateModel] = None
    published_date: Optional[str] = None
    category: Optional[str] = None
    bias: Optional[BiasUpdateModel] = None
    content: Optional[str] = None
    keywords: Optional[List[str]] = None
    engagement: Optional[EngagementUpdateModel] = None
    comments: Optional[List[CommentModel]] = None


def get_collection():
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
    return db["news_articles"], client


def serialize(doc):
    doc["_id"] = str(doc["_id"])
    return doc


def build_query(bias: Optional[str], source: Optional[str], keyword: Optional[str]):
    query = {}

    if bias:
        query["bias.label"] = bias
    if source:
        query["source"] = source
    if keyword:
        query["keywords"] = keyword

    return query


@app.get("/search")
def search_articles(
    bias: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
):
    collection, client = get_collection()
    query = build_query(bias, source, keyword)
    results = list(collection.find(query).limit(50))
    client.close()
    return [serialize(doc) for doc in results]


@app.get("/articles")
def read_articles(
    bias: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
):
    collection, client = get_collection()
    query = build_query(bias, source, keyword)
    results = list(collection.find(query).limit(100))
    client.close()
    return [serialize(doc) for doc in results]


@app.post("/articles", status_code=201)
def create_article(payload: ArticleCreate):
    collection, client = get_collection()
    result = collection.insert_one(payload.model_dump())
    inserted = collection.find_one({"_id": result.inserted_id})
    client.close()
    return serialize(inserted)


@app.put("/articles/{article_id}")
def update_article(article_id: str, payload: ArticleUpdate):
    collection, client = get_collection()

    try:
        object_id = ObjectId(article_id)
    except Exception:
        client.close()
        raise HTTPException(status_code=400, detail="Invalid article_id")

    update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not update_data:
        client.close()
        raise HTTPException(status_code=400, detail="No fields provided for update")

    result = collection.update_one({"_id": object_id}, {"$set": update_data})
    if result.matched_count == 0:
        client.close()
        raise HTTPException(status_code=404, detail="Article not found")

    updated = collection.find_one({"_id": object_id})
    client.close()
    return serialize(updated)


@app.delete("/articles/{article_id}")
def delete_article(article_id: str):
    collection, client = get_collection()

    try:
        object_id = ObjectId(article_id)
    except Exception:
        client.close()
        raise HTTPException(status_code=400, detail="Invalid article_id")

    result = collection.delete_one({"_id": object_id})
    client.close()

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Article not found")

    return {"message": "Article deleted successfully", "article_id": article_id}
