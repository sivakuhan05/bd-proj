# Political News Bias Detector

A FastAPI + Streamlit project for exploring and managing political news articles stored in MongoDB.

## Features

- Filter/query articles by:
  - bias label (`Left`, `Right`, `Center`)
  - source/publisher
  - keyword
- Full CRUD for articles:
  - Create new articles
  - Read/query existing articles
  - Update article fields
  - Delete articles
- Nested article schema support (author, bias confidence, engagement, comments).

## Project Structure

- `backend/main.py` — FastAPI app and MongoDB CRUD/query logic.
- `frontend/app.py` — Streamlit UI for query + CRUD interactions.
- `requirements.txt` — Python dependencies.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set environment variable for MongoDB connection:

```bash
export MONGO_URI="your-mongodb-uri"
```

(You can also place it in a `.env` file as `MONGO_URI=...`.)

## Run the Backend (FastAPI)

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend base URL: `http://localhost:8000`

## Run the Frontend (Streamlit)

```bash
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501
```

Frontend URL: `http://localhost:8501`

## Swagger / API Docs

Once the backend is running, open:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

That’s where you can see all available APIs and test them directly.

## Main API Endpoints

- `GET /search` — query endpoint (compatibility route)
- `GET /articles` — read/query articles with filters
- `POST /articles` — create article
- `PUT /articles/{article_id}` — update article
- `DELETE /articles/{article_id}` — delete article

## Example: Create Payload Shape

```json
{
  "title": "Government announces new economic reforms",
  "source": "National News",
  "author": {
    "name": "Jane Doe",
    "affiliation": "Political Desk"
  },
  "published_date": "2025-01-10",
  "category": "Politics",
  "bias": {
    "label": "Left",
    "confidence": 0.82
  },
  "content": "The government announced a new set of economic reforms...",
  "keywords": ["economy", "reforms", "government", "tax"],
  "engagement": {
    "likes": 850,
    "shares": 230
  },
  "comments": [
    {
      "user": "Alex",
      "comment": "These reforms are long overdue.",
      "likes": 25,
      "timestamp": "2025-01-10T14:30:00"
    }
  ]
}
```
