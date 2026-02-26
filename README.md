# Political News Bias App

FastAPI + Streamlit project for manually uploading, classifying, searching, and deleting political news articles in MongoDB.

## Features

- Manual article upload (text input)
- Store article classification (`Left`/`Right`/`Center`) with confidence
- Search by author, publisher, keywords, category, bias, and full-text query
- Update any already uploaded article by Article ID
- Delete article by ID
- Demonstrates MongoDB patterns:
  - Embedded documents
  - Array of embedded documents
  - Document references across collections
  - Arrays and dictionary/map fields

## Project Structure

- `backend/main.py` - FastAPI API + MongoDB schema/query logic
- `frontend/app.py` - Streamlit UI for upload/search/delete
- `requirements.txt` - dependencies
- `sample_data/` - sample article text and example form inputs

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set MongoDB URI:

```bash
export MONGO_URI="your-mongodb-uri"
```

(Or place `MONGO_URI=...` in `.env`.)

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

## MongoDB Schema Map

Database: `data`

Collections used:
- `articles`
- `authors`
- `publishers`

Relationship map:

```text
authors (_id) 1 ----- * articles.author_id
publishers (_id) 1 -- * articles.publisher_id
```

Document structure summary:

1. `authors`
- `_id` (ObjectId)
- `author_key` (string, unique)
- `name` (string)
- `affiliation` (string|null)
- `aliases` (array[string])
- `created_at`, `updated_at` (datetime)

2. `publishers`
- `_id` (ObjectId)
- `publisher_key` (string, unique)
- `name` (string)
- `website` (string|null)
- `country` (string|null)
- `aliases` (array[string])
- `created_at`, `updated_at` (datetime)

3. `articles`
- `_id` (ObjectId)
- `title` (string)
- `content` (string)
- `published_date` (string|null)
- `category` (string|null)
- `author_id` (ObjectId ref -> `authors._id`)
- `publisher_id` (ObjectId ref -> `publishers._id`)
- `classification` (embedded document):
  - `label` (enum string: `Left` | `Right` | `Center`)
  - `confidence` (float from `0.0` to `1.0`)
  - `model_version` (string|null)
  - `predicted_at` (datetime)
- `keywords` (array[string], normalized to lowercase/trimmed)
- `engagement` (embedded document):
  - `likes` (int)
  - `shares` (int)
  - `views` (int)
- `comments` (array of embedded documents):
  - each comment has `user` (string), `comment` (string), `likes` (int), `timestamp` (string), `flags` (array[string])
- `topic_scores` (dict/map string -> float)
- `created_at`, `updated_at` (datetime)

## Upload + Classify: Input Types and Meaning

In Streamlit tab `Upload + Classify`:

- `Title`: string
- `Published Date (YYYY-MM-DD)`: string (recommended format `YYYY-MM-DD`)
- `Category`: string
- `Author Name`: string (required)
- `Author Affiliation`: string (optional)
- `Author Aliases`: comma-separated string -> array of strings
- `Publisher Name`: string (required)
- `Publisher Website`: string URL/text (optional)
- `Publisher Country`: string (optional)
- `Publisher Aliases`: comma-separated string -> array of strings
- `Article Content`: string text (required)
- `Label`: enum (`Left`, `Right`, `Center`)
- `Confidence`: float in `[0.0, 1.0]`
- `Model Version`: string
- `Keywords`: comma-separated string -> array of strings
- `Topic Scores`: comma-separated `key:value` pairs -> dict of float values
  - Example: `economy:0.8,health:0.1`
- `Likes`, `Shares`, `Views`: integers
- `Comments`: one per line
  - Format: `user|comment|likes|timestamp|flag1,flag2`
  - Last flags section is optional

## Search Tab: Input and Query Behavior

Search fields:
- `Full-text Query` (`q`): string, mapped to MongoDB `$text` search over title/content/keywords
- `Author`: string, regex match against author `name` or `aliases`
- `Publisher`: string, regex match against publisher `name` or `aliases`
- `Keywords`: comma-separated string; normalized values are matched with `$all`
- `Category`: string exact match
- `Bias`: enum (`Left`, `Right`, `Center`) exact match on `classification.label`
- `Limit`: integer `1..200`
- `Skip`: integer `>= 0` (offset/pagination)

### Does search use limit?

Yes.
- `GET /articles` uses `limit` (default `100`, max `200`).
- `GET /search` internally calls `GET /articles` with `limit=50`.

### Does search use sort / aggregate / skip?

- `sort`: Yes, by `created_at` descending (newest first).
- `aggregate`: Yes, `GET /articles` uses aggregation pipeline with `$match`, `$sort`, `$skip`, `$limit`, and `$lookup`.
- `skip`: Yes, exposed in API and frontend.

## Update Tab: Input and Behavior

- Input: `Article ID` (required)
- All other update fields are optional.
- You can update:
  - basic fields (`title`, `content`, `published_date`, `category`)
  - author details (`name`, `affiliation`, `aliases`)
  - publisher details (`name`, `website`, `country`, `aliases`)
  - classification (`label`, `confidence`, `model_version`)
  - `keywords`, `topic_scores`, `engagement`, and full `comments` list
- API used: `PUT /articles/{article_id}`
- On success, UI shows `Article updated successfully.`

## Delete Tab: Input and Behavior

- Input: `Article ID` (MongoDB ObjectId string)
- Action: `DELETE /articles/{article_id}`
- Effect: deletes article from `articles`

## Existing Old Collection (`news_articles`)

Older prototype may have used `news_articles`.
Current app writes to `articles`, `authors`, and `publishers`.

Recommendation:
- Keep old collection as backup first.
- Test new flow by uploading at least one article.
- Delete old `news_articles` only after validation if no migration is needed.

## Main Endpoints

- `GET /articles` - search/query articles
- `GET /search` - compatibility route to `GET /articles` with default limit 50
- `POST /articles` - create article
- `PUT /articles/{article_id}` - update article
- `DELETE /articles/{article_id}` - delete article
