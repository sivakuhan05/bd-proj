from fastapi import FastAPI, Query
from pymongo import MongoClient
from typing import Optional
import os
from dotenv import load_dotenv

app = FastAPI(title="Political News Bias API")

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")


def get_collection():
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
        retryWrites=True
    )
    db = client["data"]
    return db["news_articles"], client


def serialize(doc):
    doc["_id"] = str(doc["_id"])
    return doc


@app.get("/search")
def search_articles(
    bias: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
):
    collection, client = get_collection()

    query = {}

    if bias:
        query["bias.label"] = bias
    if source:
        query["source"] = source
    if keyword:
        query["keywords"] = keyword

    results = list(collection.find(query).limit(10))

    client.close()  

    return [serialize(doc) for doc in results]
