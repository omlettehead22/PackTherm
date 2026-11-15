// Calls to the PackTherm API. The app is served by the API server, so every
// path is same-origin.
import type { CellCheck, JobStatus, LibraryCell, Limits, Results, Schema, Study, StudyCheck, Submitted } from "./types";

/** An error the API reported, with its list of specific problems if it gave one. */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public problems: string[] = [],
    public retryAfterS?: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("Could not reach the PackTherm server. Check your connection and try again.", 0);
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const b = (body ?? {}) as { error?: string; errors?: string[]; retry_after_s?: number };
    throw new ApiError(b.error ?? `The server answered ${res.status}`, res.status, b.errors ?? [], b.retry_after_s);
  }
  return body as T;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  schema: () => call<Schema>("/schema"),
  limits: () => call<Limits>("/limits"),
  cells: () => call<Record<string, LibraryCell>>("/cells"),
  checkCell: (cell: unknown) => call<CellCheck>("/cells/check", post(cell)),
  checkStudy: (study: Study) => call<StudyCheck>("/studies/check", post(study)),
  submit: (study: Study) => call<Submitted>("/studies", post(study)),
  status: (id: string) => call<JobStatus>(`/studies/${encodeURIComponent(id)}`),
  results: (id: string) => call<Results>(`/studies/${encodeURIComponent(id)}/results`),
  cancel: (id: string) => call<{ id: string; result: string }>(`/studies/${encodeURIComponent(id)}`, { method: "DELETE" }),
  csvUrl: (id: string) => `/studies/${encodeURIComponent(id)}/designs.csv`,
  chartUrl: (id: string) => `/studies/${encodeURIComponent(id)}/chart.png`,
  resultsUrl: (id: string) => `/studies/${encodeURIComponent(id)}/results`,
};
