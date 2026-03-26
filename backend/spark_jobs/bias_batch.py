import os
import re
from typing import Dict, Iterable, Optional

from backend.bias_terms import LEFT_LEAN_TERMS, RIGHT_LEAN_TERMS
from backend.bias_utils import clamp, score_to_three_class_label, utc_now

try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
except Exception:  # pragma: no cover - pyspark is optional at runtime
    SparkSession = None
    F = None


class SparkBiasAnalyzer:
    """Optional Spark-backed text scorer used by the existing ML-signal hook."""

    def __init__(self):
        self.app_name = os.getenv("SPARK_APP_NAME", "PoliticalNewsBiasSpark")
        self.master = os.getenv("SPARK_MASTER", "local[*]")
        self.driver_memory = os.getenv("SPARK_DRIVER_MEMORY", "1g")
        self._session: Optional["SparkSession"] = None
        self._init_error: Optional[str] = None

    def available(self) -> bool:
        return SparkSession is not None

    def get_error(self) -> Optional[str]:
        return self._init_error

    def close(self) -> None:
        if self._session is not None:
            self._session.stop()
            self._session = None

    def _get_session(self) -> Optional["SparkSession"]:
        if self._session is not None:
            return self._session
        if SparkSession is None:
            self._init_error = "pyspark is not installed."
            return None

        try:
            self._session = (
                SparkSession.builder.master(self.master)
                .appName(self.app_name)
                .config("spark.driver.memory", self.driver_memory)
                .config("spark.ui.showConsoleProgress", "false")
                .getOrCreate()
            )
            self._session.sparkContext.setLogLevel("ERROR")
            self._init_error = None
            return self._session
        except Exception as exc:
            self._init_error = f"{exc.__class__.__name__}: {exc}"
            return None

    @staticmethod
    def _build_text(metadata: Dict[str, object]) -> str:
        content = str(metadata.get("content", "") or "")
        category = str(metadata.get("category", "") or "")
        keywords = [str(item) for item in metadata.get("keywords", [])]
        organizations = [str(item) for item in metadata.get("organizations", [])]
        think_tanks = [str(item) for item in metadata.get("think_tanks", [])]
        return " ".join(
            [content, category, " ".join(keywords), " ".join(organizations), " ".join(think_tanks)]
        ).strip()

    @staticmethod
    def _count_occurrence_expr(text_column: str, term: str):
        escaped_term = re.escape(term.lower())
        return (
            (
                F.length(F.col(text_column))
                - F.length(F.regexp_replace(F.col(text_column), escaped_term, ""))
            )
            / max(len(term), 1)
        )

    def _aggregate_hits(self, normalized_text: str, terms: Iterable[str]) -> int:
        spark = self._get_session()
        if spark is None or F is None:
            raise RuntimeError(self._init_error or "Spark session is unavailable.")

        frame = spark.createDataFrame([(normalized_text,)], ["text"])
        aggregate_expr = None
        for term in terms:
            term_expr = self._count_occurrence_expr("text", term)
            aggregate_expr = term_expr if aggregate_expr is None else aggregate_expr + term_expr

        if aggregate_expr is None:
            return 0

        row = frame.select(F.round(aggregate_expr, 0).cast("int").alias("hits")).collect()[0]
        return max(int(row["hits"] or 0), 0)

    def score_article(self, metadata: Dict[str, object], model_version: str) -> Dict[str, object]:
        spark = self._get_session()
        if spark is None:
            raise RuntimeError(self._init_error or "Spark session is unavailable.")

        text = self._build_text(metadata).lower()
        token_count = 0
        if F is not None:
            row = (
                spark.createDataFrame([(text,)], ["text"])
                .select(
                    F.size(
                        F.array_remove(
                            F.split(F.regexp_replace(F.col("text"), r"[^a-z0-9\\s]", " "), r"\\s+"),
                            "",
                        )
                    ).alias("token_count")
                )
                .collect()[0]
            )
            token_count = int(row["token_count"] or 0)

        left_hits = self._aggregate_hits(text, LEFT_LEAN_TERMS)
        right_hits = self._aggregate_hits(text, RIGHT_LEAN_TERMS)
        total_hits = left_hits + right_hits

        score = 0.0
        if total_hits > 0:
            score = (right_hits - left_hits) / float(total_hits)
        score = clamp(score, -1.0, 1.0)

        confidence = clamp(
            0.48 + (0.30 * abs(score)) + min(total_hits * 0.025, 0.18),
            0.35,
            0.94,
        )

        return {
            "label": score_to_three_class_label(score),
            "score": round(score, 6),
            "confidence": round(confidence, 6),
            "model_version": model_version,
            "predicted_at": utc_now(),
            "diagnostics": {
                "engine": "spark",
                "left_hits": left_hits,
                "right_hits": right_hits,
                "total_hits": total_hits,
                "token_count": token_count,
            },
        }
