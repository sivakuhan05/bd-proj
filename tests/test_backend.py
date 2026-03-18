import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.main import (
    ArticleCreate,
    ArticleUpdate,
    AuthorModel,
    ClassificationModel,
    EngagementModel,
    PublisherModel,
    create_article,
    normalize_article_record,
    read_articles,
    update_article,
)


class BackendApiTests(unittest.TestCase):
    def test_create_article_requires_classification(self):
        payload = ArticleCreate(
            title="Sample",
            content="Text",
            author=AuthorModel(name="Author"),
            publisher=PublisherModel(name="Publisher"),
        )

        with self.assertRaises(HTTPException) as exc:
            create_article(payload)

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("classification", exc.exception.detail)

    @patch("backend.main.fetch_article")
    @patch("backend.main.run_cypher_batch")
    def test_create_article_returns_hydrated_article(self, mock_run_batch, mock_fetch_article):
        mock_fetch_article.return_value = {
            "_id": "article-1",
            "article_id": "article-1",
            "title": "Sample",
            "content": "Text",
            "published_date": "2026-03-18",
            "category": "Policy",
            "classification": {"label": "Center", "confidence": 0.9, "model_version": "prototype-v1", "predicted_at": "2026-03-18T00:00:00+00:00"},
            "bias": {"label": "Center", "confidence": 0.9, "model_version": "prototype-v1", "predicted_at": "2026-03-18T00:00:00+00:00"},
            "keywords": ["policy"],
            "engagement": {"likes": 1, "shares": 2, "views": 3},
            "comments": [],
            "topic_scores": {"policy": 0.9},
            "author": {"name": "Author", "affiliation": None, "aliases": []},
            "publisher": {"name": "Publisher", "website": None, "country": None, "aliases": []},
            "source": "Publisher",
            "created_at": "2026-03-18T00:00:00+00:00",
            "updated_at": "2026-03-18T00:00:00+00:00",
        }

        payload = ArticleCreate(
            title="Sample",
            content="Text",
            published_date="2026-03-18",
            category="Policy",
            author=AuthorModel(name="Author"),
            publisher=PublisherModel(name="Publisher"),
            classification=ClassificationModel(label="Center", confidence=0.9),
            keywords=["policy"],
            engagement=EngagementModel(likes=1, shares=2, views=3),
            topic_scores={"policy": 0.9},
        )

        response = create_article(payload)

        self.assertEqual(response["_id"], "article-1")
        self.assertTrue(mock_run_batch.called)
        self.assertTrue(mock_fetch_article.called)

    @patch("backend.main.run_cypher")
    def test_read_articles_transforms_topic_entries(self, mock_run_cypher):
        mock_run_cypher.return_value = [
            {
                "article": {
                    "_id": "article-1",
                    "article_id": "article-1",
                    "title": "Sample",
                    "topic_entries": [
                        {"name": "policy", "score": 0.7},
                        {"name": "budget", "score": 0.4},
                    ],
                    "comments": [],
                    "engagement": {"likes": 0, "shares": 0, "views": 0},
                    "keywords": ["policy"],
                    "author": {},
                    "publisher": {},
                }
            }
        ]

        response = read_articles(bias=None, source=None, keyword=None, author=None, publisher=None, category=None, q=None, limit=50, skip=0)

        self.assertEqual(response[0]["topic_scores"], {"policy": 0.7, "budget": 0.4})

    @patch("backend.main.fetch_article")
    @patch("backend.main.run_cypher_batch")
    @patch("backend.main.fetch_existing_article_state")
    def test_update_article_merges_partial_engagement(self, mock_existing, mock_run_batch, mock_fetch_article):
        mock_existing.return_value = {
            "classification": {"label": "Left", "confidence": 0.6, "model_version": "v1", "predicted_at": "2026-03-18T00:00:00+00:00"},
            "engagement": {"likes": 10, "shares": 5, "views": 100},
        }
        mock_fetch_article.return_value = {"_id": "article-1", "engagement": {"likes": 10, "shares": 99, "views": 100}}

        payload = ArticleUpdate(engagement={"shares": 99})
        response = update_article("article-1", payload)

        self.assertEqual(response["_id"], "article-1")
        statements = mock_run_batch.call_args.args[0]
        update_statement = statements[0]
        self.assertEqual(update_statement["parameters"]["likes"], 10)
        self.assertEqual(update_statement["parameters"]["shares"], 99)
        self.assertEqual(update_statement["parameters"]["views"], 100)


class BackendHelpersTests(unittest.TestCase):
    def test_normalize_article_record_converts_topic_entries_to_topic_scores(self):
        normalized = normalize_article_record(
            {
                "article": {
                    "_id": "article-1",
                    "article_id": "article-1",
                    "topic_entries": [{"name": "economy", "score": 0.8}],
                }
            }
        )

        self.assertEqual(normalized["topic_scores"], {"economy": 0.8})
        self.assertNotIn("topic_entries", normalized)


if __name__ == "__main__":
    unittest.main()
