import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
except Exception:  # pragma: no cover - pyspark is optional at runtime
    SparkSession = None
    F = None


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
        description="Run Spark analytics on political news articles stored in MongoDB."
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


def ensure_spark() -> "SparkSession":
    if SparkSession is None:
        raise RuntimeError(
            "pyspark is not installed. Run `pip install -r requirements.txt` first."
        )
    spark = (
        SparkSession.builder.master(os.getenv("SPARK_MASTER", "local[*]"))
        .appName(os.getenv("SPARK_APP_NAME", "PoliticalNewsAnalytics"))
        .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "1g"))
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def show_table(title: str, dataframe, num_rows: int = 20) -> None:
    print(f"\n=== {title} ===")
    dataframe.show(num_rows, truncate=False)


def write_report(dataframe, output_dir: Path, name: str) -> None:
    target = output_dir / name
    dataframe.coalesce(1).write.mode("overwrite").option("header", True).csv(str(target))


def run_analytics(rows: Iterable[Dict[str, Any]], output_dir: Path, save_source_json: bool) -> None:
    spark = ensure_spark()
    rows = list(rows)
    if not rows:
        spark.stop()
        raise RuntimeError("No articles found to analyze. Upload a few articles first.")

    output_dir.mkdir(parents=True, exist_ok=True)
    if save_source_json:
        source_path = output_dir / "flattened_articles.jsonl"
        with source_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(to_jsonable(row), ensure_ascii=True) + "\n")

    df = spark.createDataFrame(rows)
    keyword_df = df.select(F.explode_outer("keywords").alias("keyword")).where(
        F.col("keyword").isNotNull() & (F.trim(F.col("keyword")) != "")
    )

    publisher_counts = (
        df.groupBy("publisher_name")
        .agg(F.count("*").alias("article_count"))
        .orderBy(F.desc("article_count"), F.asc("publisher_name"))
    )
    category_counts = (
        df.groupBy("category")
        .agg(F.count("*").alias("article_count"))
        .orderBy(F.desc("article_count"), F.asc("category"))
    )
    bias_distribution = (
        df.groupBy("bias_label")
        .agg(F.count("*").alias("article_count"))
        .orderBy(F.desc("article_count"), F.asc("bias_label"))
    )
    engagement_by_category = (
        df.groupBy("category")
        .agg(
            F.round(F.avg("views"), 2).alias("avg_views"),
            F.round(F.avg("likes"), 2).alias("avg_likes"),
            F.round(F.avg("shares"), 2).alias("avg_shares"),
        )
        .orderBy(F.desc("avg_views"), F.asc("category"))
    )
    top_keywords = (
        keyword_df.groupBy("keyword")
        .agg(F.count("*").alias("keyword_count"))
        .orderBy(F.desc("keyword_count"), F.asc("keyword"))
    )
    publisher_bias = (
        df.groupBy("publisher_name", "bias_label")
        .agg(F.count("*").alias("article_count"))
        .orderBy(F.asc("publisher_name"), F.desc("article_count"), F.asc("bias_label"))
    )
    article_size = df.select(
        F.count("*").alias("total_articles"),
        F.round(F.avg("content_length"), 2).alias("avg_content_length"),
        F.max("content_length").alias("max_content_length"),
        F.round(F.avg("graph_confidence"), 4).alias("avg_graph_confidence"),
    )

    show_table("Publisher Article Counts", publisher_counts)
    show_table("Category Article Counts", category_counts)
    show_table("Bias Distribution", bias_distribution)
    show_table("Average Engagement By Category", engagement_by_category)
    show_table("Top Keywords", top_keywords)
    show_table("Publisher vs Bias Label", publisher_bias)
    show_table("Dataset Summary", article_size, num_rows=5)

    write_report(publisher_counts, output_dir, "publisher_counts")
    write_report(category_counts, output_dir, "category_counts")
    write_report(bias_distribution, output_dir, "bias_distribution")
    write_report(engagement_by_category, output_dir, "engagement_by_category")
    write_report(top_keywords, output_dir, "top_keywords")
    write_report(publisher_bias, output_dir, "publisher_bias")
    write_report(article_size, output_dir, "dataset_summary")

    print(f"\nSpark analytics reports written to: {output_dir}")
    spark.stop()


def main() -> None:
    args = parse_args()
    rows = load_article_rows(args.limit)
    run_analytics(rows, Path(args.output_dir), args.save_source_json)


if __name__ == "__main__":
    main()
