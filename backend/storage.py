from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any


SOURCE_ID = "demo-upload"


def _defaults() -> dict[str, Any]:
    return {
        "sources": [
            {
                "id": SOURCE_ID,
                "displayName": "Uploaded Demo Video",
                "sourceType": "file",
                "connectionLabel": "Local browser upload",
                "status": "online",
                "lastSeenAt": None,
                "hasZoneConfigured": False,
                "hasWallConfigured": False,
            }
        ],
        "zones": {SOURCE_ID: {"sourceId": SOURCE_ID, "points": [], "updatedAt": None}},
        "walls": {SOURCE_ID: {"sourceId": SOURCE_ID, "points": [], "updatedAt": None}},
        "settings": {
            SOURCE_ID: {
                "sourceId": SOURCE_ID,
                "monitoringStartTime": "00:00",
                "monitoringEndTime": "23:59",
                "loiteringDurationSeconds": 30,
                "confidenceThreshold": 0.35,
                "alertCutoffScore": 30,
            }
        },
        "incidents": [],
    }


class JsonStore:
    """Small, thread-safe persistent store suitable for the single-machine demo."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _defaults()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            defaults = _defaults()
            defaults.update(loaded)
            return defaults
        except (json.JSONDecodeError, OSError):
            return _defaults()

    def _persist(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def get_sources(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._data["sources"])

    def save_source(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            source = {**payload, "id": source_id}
            current = self._data["sources"]
            self._data["sources"] = [source if item["id"] == source_id else item for item in current]
            if not any(item["id"] == source_id for item in current):
                self._data["sources"].append(source)
            self._persist()
            return deepcopy(source)

    def get_configuration(self, kind: str, source_id: str) -> dict[str, Any]:
        with self._lock:
            values = self._data[kind]
            if source_id in values:
                return deepcopy(values[source_id])
            if kind == "settings":
                return {**_defaults()["settings"][SOURCE_ID], "sourceId": source_id}
            return {"sourceId": source_id, "points": [], "updatedAt": None}

    def save_configuration(self, kind: str, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = {**payload, "sourceId": source_id}
            if kind in {"zones", "walls"}:
                value["updatedAt"] = datetime.now(timezone.utc).isoformat()
            self._data[kind][source_id] = value
            for source in self._data["sources"]:
                if source["id"] != source_id:
                    continue
                if kind == "zones":
                    source["hasZoneConfigured"] = len(value.get("points", [])) >= 3
                elif kind == "walls":
                    source["hasWallConfigured"] = len(value.get("points", [])) >= 2
            self._persist()
            return deepcopy(value)

    def add_incidents(self, incidents: list[dict[str, Any]]) -> None:
        if not incidents:
            return
        with self._lock:
            known = {item["id"] for item in self._data["incidents"]}
            self._data["incidents"].extend(item for item in incidents if item["id"] not in known)
            self._persist()

    def get_incidents(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._data["incidents"])

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self._lock:
            incident = next((item for item in self._data["incidents"] if item["id"] == incident_id), None)
            return deepcopy(incident) if incident else None

    def save_feedback(self, incident_id: str, feedback: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            incident = next((item for item in self._data["incidents"] if item["id"] == incident_id), None)
            if incident is None:
                return None
            incident["feedback"] = {
                "status": feedback.get("status", "unreviewed"),
                "note": feedback.get("note"),
                "reviewedAt": datetime.now(timezone.utc).isoformat(),
            }
            self._persist()
            return deepcopy(incident)
