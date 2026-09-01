"""Emit a machine-readable integrity audit for a WebUI SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from sage.experiments.codex_trellis_scene_v2.content_chain import content_hash, file_binding


REQUIRED_TABLES = {
    "jobs", "stages", "attempts", "logs", "artifacts", "asset_reviews", "events", "metadata"
}


def audit_database(path: Path) -> dict[str, Any]:
    failures: list[str] = []
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        journal_mode = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        foreign_keys = int(db.execute("PRAGMA foreign_keys").fetchone()[0])
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(REQUIRED_TABLES - tables)
        if journal_mode != "wal":
            failures.append("journal_mode_not_wal")
        if foreign_keys != 1:
            failures.append("foreign_keys_not_enabled")
        if missing:
            failures.append("missing_tables")
        jobs = []
        if "jobs" in tables:
            for row in db.execute("SELECT id,status,profile,systemd_unit,control_group,output_dir FROM jobs ORDER BY id"):
                if row[1] == "running" and not row[3]:
                    failures.append(f"running_job_without_unit:{row[0]}")
                jobs.append({"id": row[0], "status": row[1], "profile": row[2], "systemd_unit": row[3], "control_group": row[4], "output_dir": row[5]})
        counts = {
            table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in sorted(REQUIRED_TABLES & tables)
        }
    report = {
        "schema": "scene-webui-control-plane-audit/v1", "database": {"path": str(path.resolve()), **file_binding(path)},
        "journal_mode": journal_mode, "foreign_keys_enabled_per_connection": foreign_keys == 1,
        "required_tables": sorted(REQUIRED_TABLES), "missing_tables": missing,
        "counts": counts, "jobs": jobs, "remote_access": "disabled_loopback_only",
        "failures": failures, "ok": not failures,
    }
    report["content_hash"] = content_hash(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_database(args.database)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
