import csv
import io
import json
import os
import re
import uuid
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

from src.errors import ArchiveError
from src.sampling import Sample

SAMPLE_FIELDS = [f.name for f in fields(Sample)]
INDEX_KEYS = ("run_id", "ammeter", "status", "started_at", "count", "mean", "std_dev", "cv", "error_rate")


def new_id(name: str = "") -> str:
    """Sorts by time and is unique, e.g. 20261026T120000Z_greenlee_3f9a1c."""
    parts = [f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", name, uuid.uuid4().hex[:6]]
    return "_".join(p for p in parts if p)


def write_atomic(path: Path, text: str):
    """Writes to a temporary file first, so a crash never leaves half a file behind."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


class ResultStore:
    """Each run goes to runs/<run_id>/, and index.jsonl keeps one line per run for quick listing."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_path = self.root / "index.jsonl"

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[\w-]+", run_id):  # keeps an id like "../x" inside the archive
            raise ArchiveError(f"not a run id: {run_id!r}")
        return self.root / "runs" / run_id

    def save(self, run: dict, samples: list[Sample]) -> Path:
        folder = self.run_dir(run["run_id"])
        folder.mkdir(parents=True, exist_ok=True)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=SAMPLE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(s) for s in samples)
        write_atomic(folder / "samples.csv", buffer.getvalue())
        write_atomic(folder / "run.json", json.dumps(run, indent=2))

        stats = run["statistics"]
        entry = {
            "run_id": run["run_id"],
            "ammeter": run["ammeter"]["name"],
            "status": run["status"],
            "started_at": run["started_at"],
            "count": stats["count"],
            "mean": stats.get("mean"),
            "std_dev": stats.get("std_dev"),
            "cv": stats.get("cv"),
            "error_rate": run["error_rate"],
        }
        with open(self.index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return folder

    def write_file(self, run_id: str, name: str, text: str) -> Path:
        path = self.run_dir(run_id) / name
        write_atomic(path, text)
        return path

    def save_comparison(self, comparison: dict, report_text: str) -> Path:
        folder = self.root / "comparisons" / new_id()
        folder.mkdir(parents=True)
        write_atomic(folder / "comparison.json", json.dumps(comparison, indent=2))
        write_atomic(folder / "comparison.md", report_text)
        return folder

    def list_runs(self, ammeter: str | None = None, status: str | None = None) -> list[dict]:
        if not self.index_path.exists():
            return []
        runs = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or any(key not in entry for key in INDEX_KEYS):
                continue
            if ammeter and entry["ammeter"] != ammeter.lower():
                continue
            if status and entry["status"] != status.upper():
                continue
            runs.append(entry)
        return runs

    def latest(self, ammeter: str) -> dict | None:
        runs = self.list_runs(ammeter)
        return self.load(runs[-1]["run_id"]) if runs else None

    def load(self, run_id: str) -> dict:
        path = self.run_dir(run_id) / "run.json"
        if not path.is_file():
            raise ArchiveError(f"no run {run_id!r} in {self.root}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ArchiveError(f"run {run_id!r} is damaged: {path} can't be read ({e})") from None

    def load_samples(self, run_id: str) -> list[Sample]:
        path = self.run_dir(run_id) / "samples.csv"
        if not path.is_file():
            raise ArchiveError(f"no samples for run {run_id!r} in {self.root}")
        try:
            return self._read_samples(path)
        except (KeyError, ValueError) as e:
            raise ArchiveError(f"run {run_id!r} is damaged: {path} can't be read ({e})") from None

    @staticmethod
    def _read_samples(path: Path) -> list[Sample]:
        with open(path, encoding="utf-8", newline="") as f:
            return [
                Sample(
                    index=int(row["index"]),
                    time_s=float(row["time_s"]),
                    lag_s=float(row["lag_s"]),
                    latency_s=float(row["latency_s"]),
                    value=float(row["value"]) if row["value"] else None,
                    error=row["error"] or None,
                )
                for row in csv.DictReader(f)
            ]
