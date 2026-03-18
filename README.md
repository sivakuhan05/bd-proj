# Political News Bias App

FastAPI + Streamlit project for manually uploading, classifying, searching, updating, and deleting political news articles in a Neo4j graph database.

## Features

- Manual article upload (text input)
- Store article classification (`Left`/`Right`/`Center`) with confidence
- Search by author, publisher, keywords, category, bias, and full-text query
- Update any already uploaded article by Article ID
- Delete article by Article ID
- Demonstrates Neo4j graph patterns:
  - `(:Author)-[:AUTHORED]->(:Article)`
  - `(:Article)-[:PUBLISHED_BY]->(:Publisher)`
  - `(:Article)-[:HAS_KEYWORD]->(:Keyword)`
  - `(:Article)-[:HAS_TOPIC {score}]->(:Topic)`
  - `(:Category)-[:IN_CATEGORY]->(:Article)`
  - `(:Article)-[:HAS_COMMENT]->(:Comment)`

## Project Structure

- `backend/main.py` - FastAPI API + Neo4j schema/query logic
- `frontend/app.py` - Streamlit UI for upload/search/update/delete
- `requirements.txt` - dependencies
- `sample_data/` - sample article text and example form inputs

The backend connects to Neo4j Aura over its HTTPS transactional endpoint using `requests`, so no separate Neo4j Python driver is required.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set Neo4j connection variables:

```bash
export NEO4J_URI="neo4j+s://<host>"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="<password>"
export NEO4J_DATABASE="neo4j"
```

(Or place them in `.env`.)

## Run

Backend:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open backend at:
- `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

Frontend:

```bash
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501
```

Open frontend at:
- `http://127.0.0.1:8501`

Note:
- `0.0.0.0` is the bind address for the server process.
- Use `127.0.0.1` or `localhost` in the browser.

## Neo4j Graph Model

Primary nodes:
- `Article`
- `Author`
- `Publisher`
- `Keyword`
- `Topic`
- `Category`
- `Comment`

Primary relationships:

```text
(:Author)-[:AUTHORED]->(:Article)
(:Article)-[:PUBLISHED_BY]->(:Publisher)
(:Article)-[:HAS_KEYWORD]->(:Keyword)
(:Article)-[:HAS_TOPIC {score}]->(:Topic)
(:Category)-[:IN_CATEGORY]->(:Article)
(:Article)-[:HAS_COMMENT]->(:Comment)
```

## Stored Article Properties

Each `Article` node stores:
- `article_id` (UUID string)
- `title`
- `content`
- `published_date`
- `category`
- classification fields:
  - `bias_label`
  - `bias_confidence`
  - `bias_model_version`
  - `bias_predicted_at`
- `keywords` (normalized lowercase list for API/search compatibility)
- engagement fields:
  - `likes`
  - `shares`
  - `views`
- `created_at`
- `updated_at`

## Search Behavior

`GET /articles` supports:
- `q` for simple text contains search over title/content/keywords
- `author` against author name or aliases
- `publisher` or `source` against publisher name or aliases
- `keyword` as comma-separated normalized terms that must all be present
- `category` exact match
- `bias` exact match
- `skip` and `limit`

Sorting is by `created_at` descending.

## Main Endpoints

- `GET /articles` - search/query articles
- `GET /search` - compatibility route to `GET /articles` with default limit 50
- `POST /articles` - create article
- `PUT /articles/{article_id}` - update article
- `DELETE /articles/{article_id}` - delete article

## Neo4j Browser Notes

If you want to inspect the graph manually in Neo4j Browser after creating data, these are useful starter queries:

```cypher
MATCH (n) RETURN n LIMIT 100;
```

```cypher
MATCH p=(:Author)-[:AUTHORED]->(:Article)-[:PUBLISHED_BY]->(:Publisher)
RETURN p LIMIT 50;
```

```cypher
MATCH (a:Article)-[r:HAS_TOPIC]->(t:Topic)
RETURN a.article_id, a.title, t.name, r.score
ORDER BY a.created_at DESC;
```
