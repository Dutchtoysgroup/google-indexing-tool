"""Durable, incremental run reports independent of the application database."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config.settings import DATA_DIR

REQUIRED_PHASES = ("scan", "inspect", "snapshot")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class RunReport:
    def __init__(self, shops):
        run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex}"
        directory = Path(os.environ.get("PIPELINE_REPORT_DIR", DATA_DIR / "pipeline-runs"))
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{run_id}.json"
        self.data = {
            "schema_version": 1,
            "run_id": run_id,
            "started_at": timestamp(),
            "finished_at": None,
            # An interrupted run must never look successful.
            "status": "incomplete",
            "shops": {
                shop.shop_id: {
                    "name": shop.name,
                    "status": "incomplete",
                    "phases": {phase: {"status": "pending"} for phase in REQUIRED_PHASES},
                }
                for shop in shops
            },
            "errors": [],
        }
        self.save()

    def save(self):
        """Replace atomically and fsync both file and directory; errors propagate."""
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def phase(self, shop_id, phase, status, **details):
        phases = self.data["shops"][shop_id]["phases"]
        phases[phase] = {**phases[phase], "status": status, **details}
        if status == "running":
            phases[phase]["started_at"] = timestamp()
        else:
            phases[phase]["finished_at"] = timestamp()
        self.save()

    def error(self, phase, error):
        self.data["errors"].append({"phase": phase, "error": f"{type(error).__name__}: {error}"})
        self.save()

    def finish(self):
        for shop in self.data["shops"].values():
            statuses = [shop["phases"][phase]["status"] for phase in REQUIRED_PHASES]
            shop["status"] = (
                "success" if all(s == "success" for s in statuses)
                else "failed" if all(s == "failed" for s in statuses)
                else "incomplete"
            )
        statuses = [shop["status"] for shop in self.data["shops"].values()]
        if not statuses or self.data["errors"] or all(s == "failed" for s in statuses):
            self.data["status"] = "failed"
        elif all(s == "success" for s in statuses):
            self.data["status"] = "success"
        else:
            self.data["status"] = "incomplete"
        self.data["finished_at"] = timestamp()
        self.save()
        return 0 if self.data["status"] == "success" else 1
