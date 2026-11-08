import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import results
from src.errors import ArchiveError
from src.results import ResultStore, new_id
from src.sampling import Sample


def _run(run_id, ammeter="entes", status="PASS"):
    return {
        "run_id": run_id,
        "status": status,
        "ammeter": {"name": ammeter},
        "started_at": "2026-10-26T10:00:00+00:00",
        "statistics": {"count": 2, "mean": 1.5, "std_dev": 0.7, "cv": 0.47},
        "error_rate": 0.5,
    }


def test_save_and_load_keep_full_detail(tmp_path):
    """A saved run and its samples load back exactly, with every digit, and the index keeps the full start
    time. Comparisons are saved as JSON and Markdown in folders that sort by time."""
    store = ResultStore(tmp_path)
    samples = [Sample(0, 0.0, 0.0, 0.001, value=1.5), Sample(1, 0.1, 0.002, 2.0, error="AmmeterTimeoutError: slow")]
    folder = store.save(_run("r1"), samples)
    assert {p.name for p in folder.iterdir()} == {"run.json", "samples.csv"}
    assert store.load("r1") == _run("r1")
    assert store.load_samples("r1") == samples

    run = _run("r2")
    run["statistics"]["median"] = 1.2
    store.save(run, [Sample(0, 0.0, 0.0, 0.001, value=0.004912345678912)])
    assert store.load_samples("r2")[0].value == 0.004912345678912
    entry = store.list_runs()[-1]
    assert (entry["mean"], entry["std_dev"], entry["cv"], entry["count"]) == (1.5, 0.7, 0.47, 2)
    assert entry["started_at"] == "2026-10-26T10:00:00+00:00"

    folder = store.save_comparison({"most_reliable": "entes"}, "## Comparison\n")
    assert re.fullmatch(r"\d{8}T\d{6}Z_[0-9a-f]{6}", folder.name)  # sorts by time, like the runs
    assert json.loads((folder / "comparison.json").read_text(encoding="utf-8")) == {"most_reliable": "entes"}
    assert (folder / "comparison.md").read_text(encoding="utf-8") == "## Comparison\n"


def test_listing_filters_exactly_and_skips_broken_lines(tmp_path):
    """Listing filters by ammeter and status with exact names, and skips broken or incomplete index lines."""
    store = ResultStore(tmp_path)
    store.save(_run("r1", "entes"), [])
    store.save(_run("r2", "greenlee", "FAIL"), [])
    with open(store.index_path, "a", encoding="utf-8") as f:
        f.write("{not json\n")
        f.write('{"run_id": "half"}\n')
        f.write("[1, 2]\n")
        f.write('{"run_id": "c", "ammeter": "entes", "status": "PASS"}\n')  # incomplete
    store.save(_run("r3", "entes", "FAIL"), [])
    store.save(_run("r4", "entes_b"), [])

    assert [e["run_id"] for e in store.list_runs()] == ["r1", "r2", "r3", "r4"]
    assert [e["run_id"] for e in store.list_runs(ammeter="ENTES")] == ["r1", "r3"]
    assert [e["run_id"] for e in store.list_runs(status="fail")] == ["r2", "r3"]
    assert store.list_runs("e") == []
    assert store.latest("entes")["run_id"] == "r3"
    assert store.latest("circutor") is None


class _October5(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 5, 9, 3, 7, tzinfo=timezone.utc)


def test_run_ids_are_unique_and_sort_by_time(monkeypatch):
    """Run ids are unique, have a fixed format with a zero-padded UTC time, and sort by time."""
    ids = [new_id("entes") for _ in range(100)]
    assert len(set(ids)) == 100
    assert all(re.fullmatch(r"\d{8}T\d{6}Z_entes_[0-9a-f]{6}", i) for i in ids)
    assert sorted(ids, key=lambda i: i.split("_")[0]) == ids
    stamp = datetime.strptime(ids[0].split("_")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 5
    monkeypatch.setattr(results, "datetime", _October5)
    assert new_id("entes").startswith("20261005T090307Z_entes_")  # zero-padded, so 5 October sorts before 26


def test_unknown_damaged_and_unsafe_runs_are_reported_clearly(tmp_path):
    """Unknown, unsafe ('../x', '..') or damaged runs give a clear ArchiveError, never a traceback or a read
    outside the archive."""
    store = ResultStore(tmp_path)
    with pytest.raises(ArchiveError, match="no run 'missing'"):
        store.load("missing")
    with pytest.raises(ArchiveError, match=re.escape(str(tmp_path))):
        store.load("missing")
    for unsafe in ("../../etc", "..\\..\\x", ".."):
        with pytest.raises(ArchiveError, match="not a run id"):
            store.load(unsafe)

    store.save(_run("r1"), [])
    (store.run_dir("r1") / "run.json").write_text("{half a file", encoding="utf-8")
    (store.run_dir("r1") / "samples.csv").write_text("index,value\n1,abc\n", encoding="utf-8")
    with pytest.raises(ArchiveError, match="damaged"):
        store.load("r1")
    with pytest.raises(ArchiveError, match="damaged"):
        store.load_samples("r1")
    (store.run_dir("r1") / "run.json").write_bytes(b'{"run_id": "\xff"}')  # not UTF-8
    with pytest.raises(ArchiveError, match="damaged"):
        store.load("r1")
    with pytest.raises(ArchiveError, match="no samples for run 'missing'"):
        store.load_samples("missing")
    (store.run_dir("r1") / "run.json").unlink()  # as if a crash happened while saving
    with pytest.raises(ArchiveError, match="no run 'r1'"):
        store.load("r1")


def test_writes_are_atomic_and_failures_are_not_hidden(tmp_path, monkeypatch):
    """Every file is written to its own temporary file next to it and then renamed, so a crash never leaves half a
    file. A full disk raises an error and leaves the index as it was."""
    store = ResultStore(tmp_path)
    moves, real_replace = [], os.replace
    monkeypatch.setattr(results.os, "replace", lambda src, dst: (moves.append((Path(src), Path(dst))), real_replace(src, dst)))
    store.save(_run("ok"), [])
    store.save_comparison({"most_reliable": "entes"}, "## Comparison\n")
    assert moves and all(src.parent == dst.parent and src != dst for src, dst in moves)  # a temp file next to it
    assert {"run.json", "comparison.json", "comparison.md"} <= {dst.name for _, dst in moves}
    assert len({src for src, _ in moves}) == len({dst for _, dst in moves})  # a temp file of its own for each file
    assert not list(tmp_path.rglob("*.tmp"))
    assert json.loads(store.index_path.read_text(encoding="utf-8"))["run_id"] == "ok"

    def disk_full(path, text):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(results, "write_atomic", disk_full)
    with pytest.raises(OSError):
        store.save(_run("lost"), [])
    with pytest.raises(OSError):
        store.save_comparison({}, "")
    assert [e["run_id"] for e in store.list_runs()] == ["ok"]
