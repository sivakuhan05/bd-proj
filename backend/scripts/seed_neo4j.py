import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from backend.knowledge_graph import KnowledgeGraphScorer


def main():
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    parser = argparse.ArgumentParser(
        description="Seed Neo4j knowledge graph from AllSides CSV export/template."
    )
    parser.add_argument(
        "--seed-path",
        default="sample_data/allsides_seed_template.csv",
        help="Relative or absolute path to the seed CSV file.",
    )
    args = parser.parse_args()

    scorer = KnowledgeGraphScorer()
    try:
        stats = scorer.bootstrap_from_csv(args.seed_path)
        print(json.dumps({"status": "ok", "stats": stats}, indent=2))
    finally:
        scorer.close()


if __name__ == "__main__":
    main()
