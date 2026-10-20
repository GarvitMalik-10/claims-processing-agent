export type Ev = {
  claim_id: string;
  seq: number;
  event_id: string;
  type: string;
  actor: { kind: string; id: string; role?: string | null };
  timestamp: string;
  payload: any;
  evidence_refs: string[];
  provenance: any;
  prev_hash: string;
  hash: string;
};

export type Status = {
  claim_id: string;
  stage: string | null;
  waiting: boolean;
  waiting_for: string | null;
  info_request_rounds: number;
  route_reasons: string[];
  busy: boolean;
};

export type Persona = {
  customer_id: string; name: string; language: "nl" | "en"; address: string; note: string;
  policy_id: string; product: string; extensions: string[]; start_date: string; deductible: number;
};

export type Gallery = {
  photos: { id: string; url: string; caption: string; caption_nl: string; trick: string | null }[];
  estimates: { id: string; contractor: string; total: number; lines: string[]; title: string }[];
  stories: { id: string; title: string; customer_id: string; images: string[]; texts: string[]; followup: string | null }[];
};

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

const post = (url: string, body?: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

export const api = {
  personas: () => fetch("/api/personas").then(j<Persona[]>),
  gallery: () => fetch("/api/gallery").then(j<Gallery>),
  claims: () => fetch("/api/claims").then(j<(Status & { customer_id: string })[]>),
  createClaim: (customer_id: string) => post("/api/claims", { customer_id }).then(j<{ claim_id: string }>),
  turn: (cid: string, body: { text?: string; gallery_images?: string[]; uploads?: { filename: string; data_b64: string }[]; gallery_estimate?: string | null }) =>
    post(`/api/claims/${cid}/turn`, body).then(j),
  events: (cid: string, after: number) => fetch(`/api/claims/${cid}/events?after=${after}`).then(j<{ events: Ev[]; status: Status }>),
  report: (cid: string) => fetch(`/api/claims/${cid}/report`).then(j<any>),
  inbox: () => fetch("/api/review/inbox").then(j<any[]>),
  review: (cid: string, decision: any) => post(`/api/claims/${cid}/review`, decision).then(j),
  verify: (cid: string) => fetch(`/api/claims/${cid}/audit/verify`).then(j<any>),
  tamper: (cid: string) => post(`/api/claims/${cid}/audit/tamper`).then(j<any>),
  replay: (cid: string) => fetch(`/api/claims/${cid}/audit/replay`).then(j<any>),
  resetDemo: () => post("/api/demo/reset").then(j<{ archived_to: string }>),
  exportUrl: (cid: string) => `/api/claims/${cid}/audit/export`,
  exportPdfUrl: (cid: string) => `/api/claims/${cid}/audit/export.pdf`,
  letterPdfUrl: (cid: string) => `/api/claims/${cid}/letter.pdf`,
  blobUrl: (digest: string) => `/api/blobs/${digest}`,
};

export const eur = (n: number | null | undefined) =>
  n == null ? "–" : new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" }).format(n);

export const pct = (p: number | null | undefined) => (p == null ? "–" : `${Math.round(p * 100)}%`);

export const human = (s: string | null | undefined) => (s ?? "").replaceAll("_", " ");
