import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

from backend.bias_terms import LEFT_LEAN_TERMS, RIGHT_LEAN_TERMS


class SparkBiasAnalyzer:
    """R-backed Spark scorer used by the existing ML-signal hook."""

    def __init__(self):
        self.app_name = os.getenv("SPARK_APP_NAME", "PoliticalNewsBiasSparkR")
        self.master = os.getenv("SPARK_MASTER", "local[*]")
        self.driver_memory = os.getenv("SPARK_DRIVER_MEMORY", "1g")
        self.rscript_bin = os.getenv("R_SCRIPT_BIN", "Rscript")
        self._init_error: Optional[str] = None
        self._script_path = Path(__file__).with_name("bias_batch.R")

    def available(self) -> bool:
        if shutil.which(self.rscript_bin) is None:
            self._init_error = f"{self.rscript_bin} was not found on PATH."
            return False
        if not self._script_path.exists():
            self._init_error = f"R Spark scorer script is missing: {self._script_path}"
            return False
        self._init_error = None
        return True

    def get_error(self) -> Optional[str]:
        return self._init_error

    def close(self) -> None:
        return None

    def score_article(self, metadata: Dict[str, object], model_version: str) -> Dict[str, object]:
        if not self.available():
            raise RuntimeError(self._init_error or "R Spark scorer is unavailable.")

        payload = {
            "metadata": metadata,
            "model_version": model_version,
            "spark_master": self.master,
            "spark_app_name": self.app_name,
            "spark_driver_memory": self.driver_memory,
            "spark_version": os.getenv("SPARK_VERSION", "3.5.1"),
            "left_terms": sorted(LEFT_LEAN_TERMS),
            "right_terms": sorted(RIGHT_LEAN_TERMS),
        }

        input_path = None
        output_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as input_handle:
                json.dump(payload, input_handle, ensure_ascii=True)
                input_path = input_handle.name

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output_handle:
                output_path = output_handle.name

            result = subprocess.run(
                [self.rscript_bin, str(self._script_path), "--input", input_path, "--output", output_path],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                message = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(message or "R Spark scorer failed.")

            with open(output_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as exc:
            self._init_error = f"{self.rscript_bin} was not found on PATH."
            raise RuntimeError(self._init_error) from exc
        finally:
            for path in [input_path, output_path]:
                if path and os.path.exists(path):
                    os.unlink(path)
