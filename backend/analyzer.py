from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

import cv2
from dotenv import load_dotenv
import numpy as np
import torch
from ultralytics import YOLO

from backend.geometry import ZoneCrossingState, normalized_polygon, point_inside_polygon
from backend.storage import JsonStore, SOURCE_ID
from risk_engine import assess_risk


LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")
RUNTIME_DIR = ROOT / "runtime"
MEDIA_DIR = RUNTIME_DIR / "media"
UPLOAD_DIR = RUNTIME_DIR / "uploads"
API_ORIGIN = os.getenv("NIGHTGUARD_API_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
FALLBACK_MODEL = os.getenv("NIGHTGUARD_FALLBACK_MODEL", "yolo26n.pt")

MODEL_CANDIDATES = (
    ROOT / "runs" / "detect" / "train-3" / "weights" / "best.pt",
    ROOT / "weights" / "best.pt",
    ROOT / "best.pt",
)


def resolve_model() -> tuple[str, bool]:
    configured = os.getenv("NIGHTGUARD_MODEL_PATH")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.exists():
            return str(configured_path.resolve()), True
    for candidate in MODEL_CANDIDATES:
        if candidate.exists():
            return str(candidate), True
    return FALLBACK_MODEL, False


def model_information() -> dict[str, Any]:
    selected, custom = resolve_model()
    local_fallback = (ROOT / FALLBACK_MODEL).exists() if not Path(FALLBACK_MODEL).is_absolute() else Path(FALLBACK_MODEL).exists()
    return {
        "selectedModel": selected,
        "customModelLoaded": custom,
        "customModelExpectedAt": str(MODEL_CANDIDATES[0]),
        "fallbackModelAvailableLocally": custom or local_fallback,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "deviceName": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
    }


class JobRegistry:
    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = Lock()
        self._analysis_lock = Lock()
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        video_path: Path,
        original_name: str,
        zone: list[dict[str, float]],
        confidence: float,
    ) -> dict[str, Any]:
        job_id = uuid4().hex
        job = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "processedFrames": 0,
            "totalFrames": 0,
            "fileName": original_name,
            "zone": zone,
            "confidenceThreshold": confidence,
            "model": model_information(),
            "summary": None,
            "annotations": [],
            "incidents": [],
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job
        Thread(
            target=self._run,
            args=(job_id, video_path, original_name, zone, confidence),
            name=f"nightguard-job-{job_id[:8]}",
            daemon=True,
        ).start()
        return self.get(job_id) or job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def any_running(self) -> bool:
        with self._lock:
            return any(job["status"] in {"queued", "processing"} for job in self._jobs.values())

    def latest_event_at(self) -> str | None:
        incidents = self.store.get_incidents()
        if not incidents:
            return None
        return max(item["startedAt"] for item in incidents)

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(changes)

    def _run(
        self,
        job_id: str,
        video_path: Path,
        original_name: str,
        zone: list[dict[str, float]],
        confidence: float,
    ) -> None:
        try:
            with self._analysis_lock:
                self._process_video(job_id, video_path, original_name, zone, confidence)
        except Exception as exc:  # pragma: no cover - exercised by real model/runtime failures
            LOGGER.exception("Video analysis failed for job %s", job_id)
            self._update(job_id, status="failed", error=str(exc), progress=100)

    def _process_video(
        self,
        job_id: str,
        video_path: Path,
        original_name: str,
        zone: list[dict[str, float]],
        confidence: float,
    ) -> None:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError("OpenCV could not open the uploaded video.")
        total_frames = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        capture.release()
        if width <= 0 or height <= 0:
            raise ValueError("The uploaded video does not contain a readable frame.")

        polygon = normalized_polygon(zone, width, height)
        selected_model, custom_model = resolve_model()
        model = YOLO(selected_model)
        device: int | str = 0 if torch.cuda.is_available() else "cpu"

        output_dir = MEDIA_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        source_suffix = video_path.suffix.lower() or ".mp4"
        media_source = output_dir / f"uploaded-source{source_suffix}"
        if media_source != video_path:
            video_path.replace(media_source)
        else:
            media_source = video_path

        self._update(
            job_id,
            status="processing",
            totalFrames=total_frames,
            model={**model_information(), "selectedModel": selected_model, "customModelLoaded": custom_model},
        )

        crossing_state = ZoneCrossingState()
        annotations: list[dict[str, Any]] = []
        incidents: list[dict[str, Any]] = []
        unique_tracks: set[int] = set()
        frame_number = 0

        results = model.track(
            source=str(media_source),
            stream=True,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            conf=confidence,
            imgsz=640,
            device=device,
            verbose=False,
        )

        for result in results:
            frame_number += 1
            frame = result.orig_img.copy()
            boxes_for_frame: list[dict[str, Any]] = []
            entries_this_frame: list[tuple[int, float]] = []

            boxes = result.boxes
            if boxes is not None and len(boxes) > 0:
                coordinates = boxes.xyxy.cpu().numpy()
                confidences = boxes.conf.cpu().numpy()
                track_ids = boxes.id.int().cpu().tolist() if boxes.id is not None else list(range(1, len(boxes) + 1))
                for track_id, coordinates_xyxy, detection_confidence in zip(track_ids, coordinates, confidences):
                    x1, y1, x2, y2 = [float(value) for value in coordinates_xyxy]
                    track_id = int(track_id)
                    unique_tracks.add(track_id)
                    ground_point = (int(round((x1 + x2) / 2)), int(round(y2)))
                    inside = point_inside_polygon(polygon, ground_point)
                    if crossing_state.update(track_id, inside):
                        entries_this_frame.append((track_id, float(detection_confidence)))
                    boxes_for_frame.append(
                        {
                            "trackId": track_id,
                            "confidence": round(float(detection_confidence), 4),
                            "inside": inside,
                            "x": round(max(0.0, x1 / width), 6),
                            "y": round(max(0.0, y1 / height), 6),
                            "width": round(min(1.0, (x2 - x1) / width), 6),
                            "height": round(min(1.0, (y2 - y1) / height), 6),
                        }
                    )

            annotated = _annotate_frame(frame, polygon, boxes_for_frame, entries_this_frame)
            for track_id, detection_confidence in entries_this_frame:
                incident = _build_incident(
                    job_id=job_id,
                    track_id=track_id,
                    confidence=detection_confidence,
                    event_time=(frame_number - 1) / fps,
                    clip_url=f"{API_ORIGIN}/media/{job_id}/{media_source.name}",
                )
                snapshot_name = f"incident-{incident['id']}.jpg"
                if not cv2.imwrite(str(output_dir / snapshot_name), annotated):
                    raise OSError("Could not write the incident snapshot.")
                incident["evidence"]["snapshotUrl"] = f"{API_ORIGIN}/media/{job_id}/{snapshot_name}"
                incidents.append(incident)

            annotations.append(
                {
                    "time": round((frame_number - 1) / fps, 4),
                    "boxes": boxes_for_frame,
                    "alert": bool(entries_this_frame),
                }
            )

            if frame_number == 1 or frame_number % 5 == 0:
                progress = round(frame_number / total_frames * 100) if total_frames else 0
                self._update(
                    job_id,
                    progress=min(progress, 99),
                    processedFrames=frame_number,
                    incidents=deepcopy(incidents),
                )

        self.store.add_incidents(incidents)
        summary = {
            "framesProcessed": frame_number,
            "durationSeconds": round(frame_number / fps, 2),
            "fps": round(fps, 2),
            "frameWidth": width,
            "frameHeight": height,
            "uniquePeopleTracked": len(unique_tracks),
            "restrictedZoneEntries": len(incidents),
        }
        self._update(
            job_id,
            status="completed",
            progress=100,
            processedFrames=frame_number,
            summary=summary,
            annotations=annotations,
            incidents=incidents,
        )


def _annotate_frame(
    frame: np.ndarray,
    polygon: np.ndarray,
    boxes: list[dict[str, Any]],
    entries: list[tuple[int, float]],
) -> np.ndarray:
    overlay = frame.copy()
    cv2.fillPoly(overlay, [polygon], (0, 145, 255))
    cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
    cv2.polylines(frame, [polygon], True, (0, 180, 255), 3)
    triggered = {track_id for track_id, _ in entries}

    height, width = frame.shape[:2]
    for box in boxes:
        x1 = int(box["x"] * width)
        y1 = int(box["y"] * height)
        x2 = int((box["x"] + box["width"]) * width)
        y2 = int((box["y"] + box["height"]) * height)
        danger = box["inside"] or box["trackId"] in triggered
        color = (55, 75, 240) if danger else (75, 200, 120)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        cv2.circle(frame, (int((x1 + x2) / 2), y2), 5, color, -1)
        label = f"Person #{box['trackId']} {box['confidence']:.0%}"
        cv2.putText(frame, label, (x1, max(22, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    if entries:
        cv2.rectangle(frame, (0, 0), (width, 48), (35, 35, 190), -1)
        cv2.putText(
            frame,
            "RESTRICTED ZONE ENTRY DETECTED",
            (18, 33),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.82,
            (255, 255, 255),
            2,
        )
    return frame


def _build_incident(
    job_id: str,
    track_id: int,
    confidence: float,
    event_time: float,
    clip_url: str,
) -> dict[str, Any]:
    risk = assess_risk({"event_type": "zone_entry", "confidence": confidence})
    now = datetime.now(timezone.utc).isoformat()
    confidence_points = round(confidence * 30, 2)
    return {
        "id": uuid4().hex,
        "sourceId": SOURCE_ID,
        "sourceName": "Uploaded Demo Video",
        "eventType": "restricted_zone_entry",
        "severity": str(risk["risk_level"]).lower(),
        "score": risk["risk_score"],
        "trackId": track_id,
        "startedAt": now,
        "endedAt": now,
        "evidenceFactors": [
            {"label": "Restricted zone entered", "points": 40},
            {"label": f"Detection confidence {confidence:.0%}", "points": confidence_points},
        ],
        "explanation": (
            f"Person track #{track_id} crossed from outside into the restricted zone "
            f"at {event_time:.1f} seconds with {confidence:.0%} detector confidence."
        ),
        "evidence": {"snapshotUrl": None, "clipUrl": clip_url},
        "feedback": {"status": "unreviewed", "note": None, "reviewedAt": None},
        "demoJobId": job_id,
        "videoTimeSeconds": round(event_time, 2),
    }
