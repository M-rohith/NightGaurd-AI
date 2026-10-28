from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.analyzer import JobRegistry, MEDIA_DIR, RUNTIME_DIR, UPLOAD_DIR, model_information
from backend.storage import JsonStore, SOURCE_ID


RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

store = JsonStore(RUNTIME_DIR / "state.json")
jobs = JobRegistry(store)

app = FastAPI(title="NightGuard AI Demo API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model": model_information()}


@app.get("/api/model")
def model() -> dict[str, Any]:
    return model_information()


@app.post("/api/demo/analyze", status_code=202)
def analyze_video(
    file: UploadFile = File(...),
    zone: str = Form(...),
    confidence: float = Form(0.35),
) -> dict[str, Any]:
    try:
        points = json.loads(zone)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Zone must be valid JSON.") from exc
    if not isinstance(points, list) or len(points) < 3:
        raise HTTPException(status_code=422, detail="Draw a restricted zone with at least three points.")
    for point in points:
        if not isinstance(point, dict) or not {"x", "y"}.issubset(point):
            raise HTTPException(status_code=422, detail="Every zone point needs x and y coordinates.")
        if not 0 <= float(point["x"]) <= 1 or not 0 <= float(point["y"]) <= 1:
            raise HTTPException(status_code=422, detail="Zone coordinates must be normalized from 0 to 1.")
    if not 0.05 <= confidence <= 0.95:
        raise HTTPException(status_code=422, detail="Confidence must be between 0.05 and 0.95.")

    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}:
        raise HTTPException(status_code=415, detail="Upload an MP4, MOV, AVI, MKV, WebM, or M4V video.")

    upload_path = UPLOAD_DIR / f"{Path(file.filename or 'video').stem}-{id(file)}{suffix}"
    try:
        with upload_path.open("wb") as output:
            shutil.copyfileobj(file.file, output, length=1024 * 1024)
    finally:
        file.file.close()

    if upload_path.stat().st_size == 0:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="The uploaded video is empty.")

    store.save_configuration("zones", SOURCE_ID, {"sourceId": SOURCE_ID, "points": points})
    return jobs.create(upload_path, file.filename or upload_path.name, points, confidence)


@app.get("/api/demo/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return job


@app.get("/api/monitoring/status")
def monitoring_status() -> dict[str, Any]:
    return {
        "isRunning": jobs.any_running(),
        "activeSourceId": SOURCE_ID,
        "backendReachable": True,
        "lastEventAt": jobs.latest_event_at(),
    }


@app.get("/api/sources")
def sources() -> list[dict[str, Any]]:
    return store.get_sources()


@app.put("/api/sources/{source_id}")
def save_source(source_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return store.save_source(source_id, payload)


@app.post("/api/sources/{source_id}/test-connection")
def test_connection(source_id: str) -> dict[str, str]:
    if not any(source["id"] == source_id for source in store.get_sources()):
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"status": "ok", "message": "The local FastAPI service is ready."}


@app.get("/api/sources/{source_id}/zone")
def get_zone(source_id: str) -> dict[str, Any]:
    return store.get_configuration("zones", source_id)


@app.put("/api/sources/{source_id}/zone")
def save_zone(source_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return store.save_configuration("zones", source_id, payload)


@app.get("/api/sources/{source_id}/wall")
def get_wall(source_id: str) -> dict[str, Any]:
    return store.get_configuration("walls", source_id)


@app.put("/api/sources/{source_id}/wall")
def save_wall(source_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return store.save_configuration("walls", source_id, payload)


@app.get("/api/sources/{source_id}/settings")
def get_settings(source_id: str) -> dict[str, Any]:
    return store.get_configuration("settings", source_id)


@app.put("/api/sources/{source_id}/settings")
def save_settings(source_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return store.save_configuration("settings", source_id, payload)


@app.get("/api/incidents")
def incidents(
    severity: str | None = None,
    event_type: str | None = Query(None, alias="eventType"),
    from_time: str | None = Query(None, alias="from"),
    to_time: str | None = Query(None, alias="to"),
) -> list[dict[str, Any]]:
    values = store.get_incidents()
    if severity:
        values = [item for item in values if item["severity"] == severity]
    if event_type:
        values = [item for item in values if item["eventType"] == event_type]
    if from_time:
        values = [item for item in values if item["startedAt"] >= from_time]
    if to_time:
        values = [item for item in values if item["startedAt"] <= to_time]
    return sorted(values, key=lambda item: item["startedAt"], reverse=True)


@app.post("/api/incidents/{incident_id}/feedback")
def feedback(incident_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    incident = store.save_feedback(incident_id, payload)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return incident


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: str) -> dict[str, Any]:
    value = store.get_incident(incident_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return value
