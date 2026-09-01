"""Durable SQLite state for the Scene V2 control plane."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sage.experiments.codex_trellis_scene_v2.content_chain import file_binding


SCHEMA_VERSION = 1
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "blocked", "orphaned"})


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise RuntimeError("SQLite WAL mode is required")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY, status TEXT NOT NULL, mode TEXT NOT NULL,
                  profile TEXT NOT NULL, output_dir TEXT NOT NULL,
                  payload_json TEXT NOT NULL, plan_json TEXT NOT NULL,
                  warnings_json TEXT NOT NULL, resource_gate_json TEXT NOT NULL,
                  systemd_unit TEXT, control_group TEXT, main_pid INTEGER, return_code INTEGER,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  started_at TEXT, finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS stages(
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  name TEXT NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL,
                  input_key TEXT, output_key TEXT, updated_at REAL NOT NULL,
                  PRIMARY KEY(job_id, name)
                );
                CREATE TABLE IF NOT EXISTS attempts(
                  job_id TEXT NOT NULL, stage_name TEXT NOT NULL, attempt INTEGER NOT NULL,
                  status TEXT NOT NULL, started_at REAL, finished_at REAL,
                  input_key TEXT, output_key TEXT, resource_json TEXT NOT NULL,
                  PRIMARY KEY(job_id, stage_name, attempt),
                  FOREIGN KEY(job_id, stage_name) REFERENCES stages(job_id, name) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS logs(
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  stream TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER, sha256 TEXT,
                  updated_at TEXT NOT NULL, PRIMARY KEY(job_id, stream)
                );
                CREATE TABLE IF NOT EXISTS artifacts(
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  name TEXT NOT NULL, stage_name TEXT, path TEXT NOT NULL,
                  bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, kind TEXT NOT NULL,
                  approval_status TEXT NOT NULL DEFAULT 'not_required',
                  updated_at TEXT NOT NULL, PRIMARY KEY(job_id, name)
                );
                CREATE TABLE IF NOT EXISTS asset_reviews(
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  candidate_id TEXT NOT NULL, category TEXT, asset_path TEXT,
                  generation_status TEXT NOT NULL, approval_status TEXT NOT NULL,
                  reviewer TEXT, notes TEXT, updated_at TEXT NOT NULL,
                  PRIMARY KEY(job_id, candidate_id)
                );
                CREATE TABLE IF NOT EXISTS events(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                  at TEXT NOT NULL, event TEXT NOT NULL, detail_json TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "control_group" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN control_group TEXT")
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    def create_job(self, job: dict[str, Any]) -> None:
        now = str(job["createdAt"])
        plan = job.get("plan", {})
        payload = job.get("payload", {})
        with self.transaction() as db:
            db.execute(
                """INSERT INTO jobs(id,status,mode,profile,output_dir,payload_json,plan_json,
                   warnings_json,resource_gate_json,systemd_unit,control_group,main_pid,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job["id"], job["status"], plan.get("mode", payload.get("mode", "unknown")),
                    plan.get("profile", payload.get("deliveryProfile", "diagnostic")),
                    plan.get("outputDir", ""), _json(payload), _json(plan),
                    _json(job.get("warnings", [])), _json(job.get("resourceGate", {})),
                    job.get("systemdUnit"), job.get("controlGroup"), job.get("pid"), now, now,
                ),
            )
            self._event(db, job["id"], "created", {"status": job["status"]})

    def update_job(self, job_id: str, **values: Any) -> None:
        mapping = {
            "status": "status", "resourceGate": "resource_gate_json", "systemdUnit": "systemd_unit",
            "controlGroup": "control_group", "pid": "main_pid", "returnCode": "return_code", "startedAt": "started_at", "finishedAt": "finished_at",
            "warnings": "warnings_json",
        }
        assignments: list[str] = []
        parameters: list[Any] = []
        for key, value in values.items():
            column = mapping.get(key)
            if column is None:
                raise KeyError(f"unsupported job update: {key}")
            if key in {"resourceGate", "warnings"}:
                value = _json(value)
            assignments.append(f"{column}=?")
            parameters.append(value)
        if not assignments:
            return
        assignments.append("updated_at=?")
        parameters.append(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        parameters.append(job_id)
        with self.transaction() as db:
            db.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id=?", parameters)
            self._event(db, job_id, "updated", values)

    def claim_launch(self, job_id: str, *, heavy: bool, max_running: int = 4) -> tuple[bool, str | None]:
        """Atomically reserve a queue slot before invoking systemd-run."""

        with self.transaction() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in {"created", "queued", "waiting_for_resources"}:
                return False, f"job_not_launchable:{row['status']}"
            active_rows = db.execute(
                "SELECT id,plan_json FROM jobs WHERE id<>? AND status IN ('launching','running','reattaching')",
                (job_id,),
            ).fetchall()
            if len(active_rows) >= max_running:
                return False, "webui_concurrency_limit"
            if heavy and any(_loads(item["plan_json"], {}).get("assetStrategy") == "generate_from_scratch" for item in active_rows):
                return False, "webui_heavy_job_active"
            db.execute(
                "UPDATE jobs SET status='launching',updated_at=? WHERE id=?",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), job_id),
            )
            self._event(db, job_id, "launch_claimed", {"heavy": heavy})
            return True, None

    @staticmethod
    def _event(db: sqlite3.Connection, job_id: str, event: str, detail: Any) -> None:
        db.execute(
            "INSERT INTO events(job_id,at,event,detail_json) VALUES(?,?,?,?)",
            (job_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), event, _json(detail)),
        )

    def _hydrate(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        job_id = str(row["id"])
        stages = []
        for item in db.execute("SELECT * FROM stages WHERE job_id=? ORDER BY ordinal", (job_id,)):
            stage = dict(item)
            stage["attempts"] = [
                dict(attempt) for attempt in db.execute(
                    "SELECT * FROM attempts WHERE job_id=? AND stage_name=? ORDER BY attempt",
                    (job_id, stage["name"]),
                )
            ]
            stages.append(stage)
        assets = [dict(item) for item in db.execute("SELECT * FROM asset_reviews WHERE job_id=? ORDER BY candidate_id", (job_id,))]
        artifacts = [dict(item) for item in db.execute("SELECT * FROM artifacts WHERE job_id=? ORDER BY name", (job_id,))]
        logs = {item["stream"]: item["path"] for item in db.execute("SELECT * FROM logs WHERE job_id=?", (job_id,))}
        return {
            "id": job_id, "status": row["status"], "mode": row["mode"], "profile": row["profile"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"], "startedAt": row["started_at"],
            "finishedAt": row["finished_at"], "pid": row["main_pid"], "returnCode": row["return_code"],
            "systemdUnit": row["systemd_unit"], "controlGroup": row["control_group"], "payload": _loads(row["payload_json"], {}),
            "plan": _loads(row["plan_json"], {}), "warnings": _loads(row["warnings_json"], []),
            "resourceGate": _loads(row["resource_gate_json"], {}), "logs": logs,
            "stages": stages, "artifacts": artifacts, "assetCandidates": assets,
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return self._hydrate(db, row) if row else None

    def list_jobs(self, limit: int = 80) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
            return [self._hydrate(db, row) for row in rows]

    def record_log(self, job_id: str, stream: str, path: Path) -> None:
        binding = file_binding(path) if path.is_file() else {"bytes": 0, "sha256": ""}
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.transaction() as db:
            db.execute(
                """INSERT INTO logs(job_id,stream,path,bytes,sha256,updated_at) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(job_id,stream) DO UPDATE SET path=excluded.path,bytes=excluded.bytes,
                   sha256=excluded.sha256,updated_at=excluded.updated_at""",
                (job_id, stream, str(path), binding["bytes"], binding["sha256"], now),
            )

    def sync_v2_output(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        output_dir = Path(job["plan"].get("outputDir") or "").resolve()
        dag_path = output_dir / "run_dag.json"
        if dag_path.is_file():
            dag = json.loads(dag_path.read_text(encoding="utf-8"))
            with self.transaction() as db:
                for ordinal, stage_name in enumerate(dag.get("stage_order", [])):
                    attempts = dag.get("stages", {}).get(stage_name, {}).get("attempts", [])
                    latest = attempts[-1] if attempts else {}
                    db.execute(
                        """INSERT INTO stages(job_id,name,ordinal,status,input_key,output_key,updated_at)
                           VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id,name) DO UPDATE SET status=excluded.status,
                           input_key=excluded.input_key,output_key=excluded.output_key,updated_at=excluded.updated_at""",
                        (job_id, stage_name, ordinal, latest.get("status", "pending"), latest.get("input_key"), latest.get("output_key"), time.time()),
                    )
                    for attempt in attempts:
                        number = int(attempt["attempt"])
                        db.execute(
                            """INSERT INTO attempts(job_id,stage_name,attempt,status,started_at,finished_at,input_key,output_key,resource_json)
                               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,stage_name,attempt) DO UPDATE SET
                               status=excluded.status,finished_at=excluded.finished_at,output_key=excluded.output_key,
                               resource_json=excluded.resource_json""",
                            (job_id, stage_name, number, attempt.get("status", "unknown"), attempt.get("started_at"), attempt.get("completed_at"), attempt.get("input_key"), attempt.get("output_key"), _json(attempt.get("resource_peak", {}))),
                        )
                        for name, artifact in attempt.get("outputs", {}).items():
                            path = Path(str(artifact.get("path") or "")).resolve()
                            if output_dir not in path.parents and path != output_dir:
                                continue
                            declared = {"bytes": int(artifact.get("bytes", 0)), "sha256": str(artifact.get("sha256", ""))}
                            actual = file_binding(path) if path.is_file() else declared
                            kind = "stage_output" if path.is_file() and actual == declared else (
                                "stage_output_invalid_binding" if path.is_file() else "stage_output_missing"
                            )
                            db.execute(
                                """INSERT INTO artifacts(job_id,name,stage_name,path,bytes,sha256,kind,updated_at)
                                   VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(job_id,name) DO UPDATE SET path=excluded.path,
                                   bytes=excluded.bytes,sha256=excluded.sha256,stage_name=excluded.stage_name,updated_at=excluded.updated_at""",
                                (job_id, f"{stage_name}:{name}", stage_name, str(path), actual["bytes"], actual["sha256"], kind, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                            )
        assets_path = output_dir / "asset_resolution.json"
        if assets_path.is_file():
            document = json.loads(assets_path.read_text(encoding="utf-8"))
            with self.transaction() as db:
                for item in document.get("results", []):
                    candidate_id = str(item.get("asset_id") or item.get("object_id"))
                    status = str(item.get("status") or "unknown")
                    default_approval = "pending" if status in {"generated", "generated_for_run", "scene_specific_approved"} else "not_required"
                    db.execute(
                        """INSERT INTO asset_reviews(job_id,candidate_id,category,asset_path,generation_status,approval_status,updated_at)
                           VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id,candidate_id) DO UPDATE SET category=excluded.category,
                           asset_path=excluded.asset_path,generation_status=excluded.generation_status,updated_at=excluded.updated_at""",
                        (job_id, candidate_id, item.get("category"), item.get("staged"), status, default_approval, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                    )

    def review_asset(self, job_id: str, candidate_id: str, status: str, reviewer: str, notes: str) -> None:
        if status not in {"approved", "rejected", "pending"}:
            raise ValueError("asset approval status must be approved, rejected, or pending")
        with self.transaction() as db:
            result = db.execute(
                "UPDATE asset_reviews SET approval_status=?,reviewer=?,notes=?,updated_at=? WHERE job_id=? AND candidate_id=?",
                (status, reviewer, notes, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), job_id, candidate_id),
            )
            if result.rowcount != 1:
                raise KeyError(candidate_id)
            self._event(db, job_id, "asset_review", {"candidate_id": candidate_id, "status": status, "reviewer": reviewer})
