import type { DemoAnalysisJob, DemoModelInfo, NormalizedPoint } from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || `Request failed (${response.status}).`;
  } catch {
    return `Request failed (${response.status}).`;
  }
}

export async function getDemoModelInfo(): Promise<DemoModelInfo> {
  const response = await fetch(`${BASE_URL}/api/model`);
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as DemoModelInfo;
}

export async function startDemoAnalysis(
  file: File,
  zone: NormalizedPoint[],
  confidence: number,
): Promise<DemoAnalysisJob> {
  const body = new FormData();
  body.append("file", file);
  body.append("zone", JSON.stringify(zone));
  body.append("confidence", confidence.toString());
  const response = await fetch(`${BASE_URL}/api/demo/analyze`, { method: "POST", body });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as DemoAnalysisJob;
}

export async function getDemoJob(jobId: string): Promise<DemoAnalysisJob> {
  const response = await fetch(`${BASE_URL}/api/demo/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as DemoAnalysisJob;
}
