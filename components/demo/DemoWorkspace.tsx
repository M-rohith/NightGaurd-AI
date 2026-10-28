"use client";

import { forwardRef, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, MouseEvent } from "react";
import type {
  DemoAnalysisJob,
  DemoFrameAnnotation,
  DemoModelInfo,
  NormalizedPoint,
} from "@/types";
import { getDemoJob, getDemoModelInfo, startDemoAnalysis } from "@/lib/api/demo-client";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";

const MIN_ZONE_POINTS = 3;

function closestFrame(frames: DemoFrameAnnotation[], time: number): DemoFrameAnnotation | null {
  if (frames.length === 0) return null;
  let low = 0;
  let high = frames.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high + 1) / 2);
    if (frames[middle].time <= time) low = middle;
    else high = middle - 1;
  }
  return frames[low] ?? null;
}

export function DemoWorkspace() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<SVGSVGElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoDimensions, setVideoDimensions] = useState({ width: 16, height: 9 });
  const [zone, setZone] = useState<NormalizedPoint[]>([]);
  const [confidence, setConfidence] = useState(0.35);
  const [model, setModel] = useState<DemoModelInfo | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<DemoAnalysisJob | null>(null);
  const [currentTime, setCurrentTime] = useState(0);

  const locked =
    starting ||
    job?.status === "queued" ||
    job?.status === "processing" ||
    job?.status === "completed";
  const currentFrame = useMemo(
    () => closestFrame(job?.annotations ?? [], currentTime),
    [currentTime, job?.annotations],
  );

  useEffect(() => {
    getDemoModelInfo()
      .then((information) => {
        setModel(information);
        setBackendError(null);
      })
      .catch(() => setBackendError("FastAPI is not running on port 8000. Start it with npm run demo."));
  }, []);

  useEffect(() => {
    return () => {
      if (videoUrl) URL.revokeObjectURL(videoUrl);
    };
  }, [videoUrl]);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const next = await getDemoJob(jobId);
        if (cancelled) return;
        setJob(next);
        if (next.status === "queued" || next.status === "processing") {
          timer = setTimeout(poll, 800);
        }
      } catch (error) {
        if (!cancelled) {
          setJob((previous) =>
            previous
              ? {
                  ...previous,
                  status: "failed",
                  error: error instanceof Error ? error.message : "Could not read analysis progress.",
                }
              : previous,
          );
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  useEffect(() => {
    if (job?.status !== "completed") return;
    const timer = setInterval(() => {
      if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
    }, 50);
    return () => clearInterval(timer);
  }, [job?.status]);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0];
    if (!nextFile) return;
    setVideoUrl((previous) => {
      if (previous) URL.revokeObjectURL(previous);
      return URL.createObjectURL(nextFile);
    });
    setFile(nextFile);
    setZone([]);
    setJobId(null);
    setJob(null);
    setCurrentTime(0);
  };

  const handleOverlayClick = (event: MouseEvent<SVGSVGElement>) => {
    if (!file || locked) return;
    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return;
    setZone((points) => [
      ...points,
      {
        x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
      },
    ]);
  };

  const startAnalysis = async () => {
    if (!file || zone.length < MIN_ZONE_POINTS) return;
    setStarting(true);
    setBackendError(null);
    try {
      const created = await startDemoAnalysis(file, zone, confidence);
      setJob(created);
      setJobId(created.id);
      if (videoRef.current) {
        videoRef.current.pause();
        videoRef.current.currentTime = 0;
      }
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : "Could not start analysis.");
    } finally {
      setStarting(false);
    }
  };

  const reset = () => {
    setJobId(null);
    setJob(null);
    setZone([]);
    setCurrentTime(0);
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.currentTime = 0;
    }
  };

  const seekToIncident = (time: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, time - 0.5);
    setCurrentTime(video.currentTime);
    void video.play();
  };

  return (
    <div className="flex flex-col gap-5">
      <ModelStatus model={model} backendError={backendError} />

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.7fr)] gap-5">
        <Card padded={false} className="overflow-hidden">
          <div className="px-5 py-4 border-b border-hairline">
            <h2 className="font-display text-lg text-ink">1. Upload and mark the zone</h2>
            <p className="text-sm text-ink-muted mt-1">
              Choose a video, then click around the restricted area. Entry is based on the person&apos;s bottom-centre point.
            </p>
          </div>

          <div className="p-4 md:p-5">
            {!videoUrl ? (
              <label className="flex min-h-80 cursor-pointer flex-col items-center justify-center rounded-[4px] border border-dashed border-hairline-strong bg-[#050708] px-6 text-center hover:border-signal-info">
                <span className="font-display text-xl text-ink">Select a demonstration video</span>
                <span className="mt-2 max-w-md text-sm text-ink-muted">
                  MP4, MOV, AVI, MKV, WebM, or M4V. Use a short clip for the fastest classroom demo.
                </span>
                <span className="mt-4 rounded-[3px] bg-signal-info px-4 py-2 text-sm font-medium text-ground">
                  Browse video
                </span>
                <input className="sr-only" type="file" accept="video/*" onChange={handleFileChange} />
              </label>
            ) : (
              <>
                <div
                  className="relative overflow-hidden rounded-[4px] border border-hairline bg-black"
                  style={{ aspectRatio: `${videoDimensions.width}/${videoDimensions.height}` }}
                >
                  <video
                    ref={videoRef}
                    src={videoUrl}
                    muted
                    playsInline
                    preload="auto"
                    controls={job?.status === "completed"}
                    className="absolute inset-0 h-full w-full object-fill"
                    onLoadedMetadata={(event) => {
                      const video = event.currentTarget;
                      setVideoDimensions({ width: video.videoWidth || 16, height: video.videoHeight || 9 });
                      video.currentTime = 0.001;
                    }}
                    onSeeked={(event) => setCurrentTime(event.currentTarget.currentTime)}
                  />
                  <DetectionOverlay
                    ref={overlayRef}
                    zone={zone}
                    frame={currentFrame}
                    drawing={!locked}
                    onClick={handleOverlayClick}
                  />
                  {job?.status === "completed" && currentFrame?.alert && (
                    <div className="pointer-events-none absolute left-0 right-0 top-0 z-30 bg-signal-high/95 px-4 py-2 text-center text-sm font-bold tracking-wide text-white">
                      RESTRICTED ZONE ENTRY DETECTED
                    </div>
                  )}
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm text-ink">{file?.name}</p>
                    <p className="mt-0.5 text-xs font-data text-ink-muted">
                      {zone.length} zone point{zone.length === 1 ? "" : "s"}
                      {zone.length > 0 && zone.length < MIN_ZONE_POINTS ? " · add at least 3" : ""}
                    </p>
                  </div>
                  {!locked && (
                    <div className="flex flex-wrap gap-2">
                      <Button variant="ghost" onClick={() => setZone((points) => points.slice(0, -1))} disabled={zone.length === 0}>
                        Undo point
                      </Button>
                      <Button variant="ghost" onClick={() => setZone([])} disabled={zone.length === 0}>
                        Clear zone
                      </Button>
                      <label className="inline-flex cursor-pointer items-center rounded-[3px] border border-hairline-strong bg-panel-raised px-3.5 py-2 text-sm text-ink hover:border-ink-muted">
                        Replace video
                        <input className="sr-only" type="file" accept="video/*" onChange={handleFileChange} />
                      </label>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </Card>

        <div className="flex flex-col gap-5">
          <Card>
            <CardHeader title="2. Run the model" description="FastAPI processes the upload with Ultralytics YOLO and ByteTrack." />
            <label className="block text-xs font-data uppercase tracking-wide text-ink-muted" htmlFor="confidence">
              Confidence threshold · {Math.round(confidence * 100)}%
            </label>
            <input
              id="confidence"
              type="range"
              min="0.15"
              max="0.8"
              step="0.05"
              value={confidence}
              disabled={locked}
              onChange={(event) => setConfidence(Number(event.target.value))}
              className="mt-3 w-full accent-signal-info"
            />
            <p className="mt-2 text-xs text-ink-faint">35% is a practical starting point for low-light footage.</p>

            <div className="mt-5 border-t border-hairline pt-4">
              {job && <JobProgress job={job} />}
              <div className="mt-4 flex flex-wrap gap-2">
                {!job || job.status === "failed" ? (
                  <Button
                    variant="primary"
                    onClick={startAnalysis}
                    disabled={!file || zone.length < MIN_ZONE_POINTS || starting || Boolean(backendError)}
                  >
                    {starting ? "Uploading…" : "Analyze video"}
                  </Button>
                ) : null}
                {job?.status === "completed" && (
                  <Button variant="secondary" onClick={reset}>Run another zone</Button>
                )}
              </div>
            </div>
          </Card>

          {job?.status === "completed" && job.summary && (
            <ResultSummary job={job} onSeek={seekToIncident} />
          )}
        </div>
      </div>
    </div>
  );
}

function ModelStatus({ model, backendError }: { model: DemoModelInfo | null; backendError: string | null }) {
  if (backendError) {
    return (
      <div className="rounded-[4px] border border-signal-high/40 bg-signal-high-dim px-4 py-3 text-sm text-signal-high" role="alert">
        {backendError}
      </div>
    );
  }
  if (!model) {
    return <div className="rounded-[4px] border border-hairline bg-panel px-4 py-3 text-sm text-ink-muted">Checking inference backend…</div>;
  }
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 rounded-[4px] border px-4 py-3 ${model.customModelLoaded ? "border-signal-low/30 bg-signal-low-dim" : "border-signal-medium/30 bg-signal-medium-dim"}`}>
      <div>
        <p className={`text-sm font-medium ${model.customModelLoaded ? "text-signal-low" : "text-signal-medium"}`}>
          {model.customModelLoaded ? "Custom NightGuard model ready" : "Pretrained person-detector fallback selected"}
        </p>
        <p className="mt-0.5 break-all text-xs font-data text-ink-muted">{model.selectedModel}</p>
      </div>
      <span className="rounded-[3px] bg-black/20 px-2 py-1 text-xs font-data text-ink-muted">{model.deviceName}</span>
    </div>
  );
}

const DetectionOverlay = forwardRef<
  SVGSVGElement,
  {
    zone: NormalizedPoint[];
    frame: DemoFrameAnnotation | null;
    drawing: boolean;
    onClick: (event: MouseEvent<SVGSVGElement>) => void;
  }
>(function DetectionOverlay({ zone, frame, drawing, onClick }, ref) {
  const polygon = zone.map((point) => `${point.x * 1000},${point.y * 1000}`).join(" ");
  return (
    <svg
      ref={ref}
      viewBox="0 0 1000 1000"
      preserveAspectRatio="none"
      onClick={onClick}
      className={`absolute inset-0 z-20 h-full w-full ${drawing ? "cursor-crosshair" : "pointer-events-none"}`}
      aria-label="Video detection overlay and restricted zone editor"
    >
      {zone.length >= 3 ? (
        <polygon points={polygon} fill="rgba(217,154,61,0.16)" stroke="rgb(217,154,61)" strokeWidth="4" vectorEffect="non-scaling-stroke" />
      ) : zone.length > 0 ? (
        <polyline points={polygon} fill="none" stroke="rgb(217,154,61)" strokeWidth="4" vectorEffect="non-scaling-stroke" />
      ) : null}
      {zone.map((point, index) => (
        <g key={`${point.x}-${point.y}-${index}`}>
          <circle cx={point.x * 1000} cy={point.y * 1000} r="9" fill="rgb(217,154,61)" />
          <text x={point.x * 1000 + 14} y={point.y * 1000 - 12} fill="white" fontSize="24">{index + 1}</text>
        </g>
      ))}
      {frame?.boxes.map((box) => {
        const color = box.inside ? "rgb(226,85,90)" : "rgb(63,185,138)";
        return (
          <g key={box.trackId}>
            <rect
              x={box.x * 1000}
              y={box.y * 1000}
              width={box.width * 1000}
              height={box.height * 1000}
              fill="none"
              stroke={color}
              strokeWidth="4"
              vectorEffect="non-scaling-stroke"
            />
            <rect x={box.x * 1000} y={Math.max(0, box.y * 1000 - 38)} width="205" height="38" fill="rgba(0,0,0,0.8)" />
            <text x={box.x * 1000 + 8} y={Math.max(28, box.y * 1000 - 10)} fill={color} fontSize="25" fontWeight="700">
              Person #{box.trackId} · {Math.round(box.confidence * 100)}%
            </text>
          </g>
        );
      })}
    </svg>
  );
});

function JobProgress({ job }: { job: DemoAnalysisJob }) {
  const label =
    job.status === "queued"
      ? "Waiting for the model"
      : job.status === "processing"
        ? "Tracking people"
        : job.status === "completed"
          ? "Analysis complete"
          : "Analysis failed";
  return (
    <div role="status" aria-live="polite">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className={job.status === "failed" ? "text-signal-high" : "text-ink"}>{label}</span>
        <span className="font-data text-ink-muted">{job.progress}%</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ground">
        <div className={`h-full transition-[width] ${job.status === "failed" ? "bg-signal-high" : "bg-signal-info"}`} style={{ width: `${job.progress}%` }} />
      </div>
      <p className="mt-2 text-xs font-data text-ink-faint">
        {job.processedFrames.toLocaleString()}{job.totalFrames ? ` / ${job.totalFrames.toLocaleString()}` : ""} frames
      </p>
      {job.error && <p className="mt-3 text-sm text-signal-high">{job.error}</p>}
    </div>
  );
}

function ResultSummary({ job, onSeek }: { job: DemoAnalysisJob; onSeek: (time: number) => void }) {
  const summary = job.summary;
  if (!summary) return null;
  return (
    <Card>
      <CardHeader title="Detection result" description="Click an entry to jump to the crossing in the uploaded video." />
      <div className="grid grid-cols-2 gap-3">
        <Metric label="People tracked" value={summary.uniquePeopleTracked} />
        <Metric label="Zone entries" value={summary.restrictedZoneEntries} danger={summary.restrictedZoneEntries > 0} />
        <Metric label="Frames" value={summary.framesProcessed.toLocaleString()} />
        <Metric label="Video FPS" value={summary.fps} />
      </div>
      <div className="mt-4 border-t border-hairline pt-4">
        {job.incidents.length === 0 ? (
          <p className="text-sm text-ink-muted">No tracked person crossed into the selected restricted zone.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {job.incidents.map((incident) => (
              <li key={incident.id}>
                <button
                  type="button"
                  onClick={() => onSeek(incident.videoTimeSeconds)}
                  className="w-full rounded-[3px] border border-signal-high/30 bg-signal-high-dim px-3 py-2.5 text-left hover:brightness-110"
                >
                  <span className="block text-sm font-medium text-signal-high">Person #{incident.trackId} entered the zone</span>
                  <span className="mt-0.5 block text-xs font-data text-ink-muted">
                    {incident.videoTimeSeconds.toFixed(1)}s · risk {incident.score} · {incident.severity}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function Metric({ label, value, danger = false }: { label: string; value: string | number; danger?: boolean }) {
  return (
    <div className="rounded-[3px] border border-hairline bg-ground px-3 py-2.5">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={`mt-0.5 font-data text-lg ${danger ? "text-signal-high" : "text-ink"}`}>{value}</p>
    </div>
  );
}
