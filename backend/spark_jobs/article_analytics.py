import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient


def to_jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Spark analytics on political news articles stored in MongoDB using R."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of articles to analyze.",
    )
    parser.add_argument(
        "--output-dir",
        default="sample_data/spark_reports",
        help="Directory where CSV analytics reports should be written.",
    )
    parser.add_argument(
        "--save-source-json",
        action="store_true",
        help="Also export the flattened source dataset used by Spark as JSON lines.",
    )
    return parser.parse_args()


def load_article_rows(limit: int) -> List[Dict[str, Any]]:
    load_dotenv()
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI is not configured in your .env file.")

    client = MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
        retryWrites=True,
    )
    db = client["data"]
    articles = db["articles"]
    authors = db["authors"]
    publishers = db["publishers"]

    author_map = {
        doc["_id"]: doc.get("name", "Unknown Author")
        for doc in authors.find({}, {"name": 1})
    }
    publisher_map = {
        doc["_id"]: doc.get("name", "Unknown Publisher")
        for doc in publishers.find({}, {"name": 1})
    }

    cursor = articles.find({}).sort("created_at", -1).limit(limit)
    rows: List[Dict[str, Any]] = []
    for article in cursor:
        engagement = article.get("engagement") or {}
        classification = article.get("classification") or {}
        graph_signal = article.get("graph_signal") or {}
        rows.append(
            {
                "article_id": str(article.get("_id")),
                "title": article.get("title", ""),
                "content": article.get("content", ""),
                "content_length": len(article.get("content", "") or ""),
                "published_date": article.get("published_date"),
                "category": article.get("category") or "Uncategorized",
                "author_name": author_map.get(article.get("author_id"), "Unknown Author"),
                "publisher_name": publisher_map.get(
                    article.get("publisher_id"),
                    article.get("source") or "Unknown Publisher",
                ),
                "publisher_house": article.get("publisher_house") or "Unknown House",
                "bias_label": classification.get("label") or "Unknown",
                "bias_score": float(classification.get("score") or 0.0),
                "graph_confidence": float(graph_signal.get("confidence") or 0.0),
                "likes": int(engagement.get("likes") or 0),
                "shares": int(engagement.get("shares") or 0),
                "views": int(engagement.get("views") or 0),
                "keywords": article.get("keywords") or [],
                "organizations": article.get("organizations") or [],
                "think_tanks": article.get("think_tanks") or [],
            }
        )

    client.close()
    return rows


def ensure_rscript() -> tuple[str, Path]:
    rscript_bin = os.getenv("R_SCRIPT_BIN", "Rscript")
    if shutil.which(rscript_bin) is None:
        raise RuntimeError(
            f"{rscript_bin} was not found on PATH. Install R first, then rerun this command."
        )

    script_path = Path(__file__).with_name("article_analytics.R")
    if not script_path.exists():
        raise RuntimeError(f"R analytics script not found: {script_path}")

    return rscript_bin, script_path


def run_analytics(rows: List[Dict[str, Any]], output_dir: Path, save_source_json: bool) -> None:
    if not rows:
        raise RuntimeError("No articles found to analyze. Upload a few articles first.")

    rscript_bin, script_path = ensure_rscript()
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as handle:
            input_path = handle.name
            for row in rows:
                handle.write(json.dumps(to_jsonable(row), ensure_ascii=True) + "\n")

        if save_source_json:
            source_path = output_dir / "flattened_articles.jsonl"
            with source_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(to_jsonable(row), ensure_ascii=True) + "\n")

        result = subprocess.run(
            [
                rscript_bin,
                str(script_path),
                "--input-jsonl",
                input_path,
                "--output-dir",
                str(output_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(message or "R Spark analytics job failed.")

        if result.stdout.strip():
            print(result.stdout.strip())

        print(f"\nSpark analytics reports written to: {output_dir}")
    finally:
        if input_path and os.path.exists(input_path):
            os.unlink(input_path)


def main() -> None:
    args = parse_args()
    rows = load_article_rows(args.limit)
    run_analytics(rows, Path(args.output_dir), args.save_source_json)


if __name__ == "__main__":
    main()
