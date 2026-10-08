"""Write a benchmark (and its Forms questionnaire) from a pollster's crosstab workbook.

    python -m app.services.kits.build_benchmark <workbook.xlsx> <benchmark_id>

Reads app/data/kits/benchmarks/<benchmark_id>/qmap.json and writes benchmark.json and
form.json next to it. Re-run whenever the workbook or the question map changes."""
from __future__ import annotations

import json
import os
import sys

from app.services.kits import benchmark


def main(xlsx: str, benchmark_id: str) -> None:
    folder = os.path.join(benchmark.DATA_DIR, benchmark_id)
    with open(os.path.join(folder, "qmap.json")) as f:
        qmap = json.load(f)
    bench, form = benchmark.build(xlsx, qmap["questions"], qmap["meta"])
    with open(os.path.join(folder, "benchmark.json"), "w") as f:
        json.dump(bench, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(folder, "form.json"), "w") as f:
        json.dump(form, f, ensure_ascii=False, indent=2)
    print(f"{benchmark_id}: {len(bench['questions'])} questions, {len(bench['columns'])} banner columns → {folder}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
