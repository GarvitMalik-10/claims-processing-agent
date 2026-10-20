import { Ev, Status } from "./api";

export type NodeState = "pending" | "active" | "done" | "warn" | "fail" | "skipped";
export type MapNode = { id: string; label: string; sub: string; state: NodeState; detail?: string };

const last = (evs: Ev[], type: string, pred: (e: Ev) => boolean = () => true) =>
  [...evs].reverse().find((e) => e.type === type && pred(e));

export function buildMap(evs: Ev[], status: Status | null, revealComplete: boolean): MapNode[] {
  const busy = !!status?.busy || !revealComplete;
  const has = (t: string, p?: (e: Ev) => boolean) => !!last(evs, t, p);
  const finding = (agent: string) => last(evs, "finding.created", (e) => e.payload?.agent === agent);
  const incident = has("claim.recorded_as_incident");
  const registered = has("claim.registered");
  const comp = last(evs, "fnol.completeness_evaluated");
  const route = last(evs, "routing.decided");
  const cov = last(evs, "coverage.resolved");
  const pay = last(evs, "payout.calculated");
  const risk = last(evs, "risk.scored", (e) => e.payload?.stage === "join") ?? last(evs, "risk.scored");
  const waitingCustomer = status?.waiting_for === "awaiting_customer_info";
  const waitingHuman = status?.waiting_for === "awaiting_human_review";

  // "active" = the first unfinished step while the backend is working
  const n = (id: string, label: string, sub: string, done: boolean, extra: Partial<MapNode> = {}): MapNode =>
    ({ id, label, sub, state: done ? "done" : "pending", ...extra });

  const nodes: MapNode[] = [
    n("intake", "Intake", "text · photo · quote", has("evidence.received")),
    n("extract", "Extract facts", "Sonnet + quote check", !!finding("fnol_extractor")),
    n("classify", "Peril & intent", "Jev", has("jev.answered", (e) => e.payload?.question_set?.startsWith("fnol"))),
    n("complete", "Complete?", "rules", !!comp || incident, comp && !comp.payload.complete ? { state: "warn", detail: `missing: ${comp.payload.missing.join(", ")}` } : {}),
    n("register", "Policy & register", "rules", registered, incident ? { state: "skipped", detail: "incident only" } : {}),
    n("damage", "Damage", "vision + Jev + rules", !!finding("damage_agent")),
    n("policy", "Policy", "clauses + rules", !!finding("policy_agent")),
    n("risk", "Risk", "signals + Jev", !!finding("risk_agent")),
    n("coverage", "Coverage", "join · rules", !!cov,
      cov && ["not_covered", "partially_covered"].includes(cov.payload.status) ? { state: "fail", detail: cov.payload.status } :
      cov && cov.payload.status === "unresolved" ? { state: "warn", detail: "unresolved" } : cov ? { detail: "covered" } : {}),
    n("payout", "Payout", "benchmark · depreciation · deductible", !!pay,
      pay?.payload?.recommendation ? { detail: `€ ${pay.payload.recommendation.payout.toFixed(2)}` } : {}),
    n("route", "Decision gate", "rules", !!route, route ? {
      detail: route.payload.route.replace("_", " "),
      state: route.payload.route === "stp" ? "done" : route.payload.route === "siu" ? "fail" : "warn",
    } : {}),
  ];

  if (risk && nodes[7].state === "done") nodes[7].detail = `score ${(risk.payload.score ?? 0).toFixed(2)}`;
  const dmg = finding("damage_agent");
  if (dmg) {
    const c = dmg.payload.finding.consistency;
    nodes[5].detail = c.replaceAll("_", " ");
    if (c !== "consistent") nodes[5].state = c === "partially_consistent" ? "warn" : "fail";
  }

  if (incident) nodes.slice(4).forEach((x) => { if (x.state === "pending") x.state = "skipped"; });

  // Mark the frontier
  if (busy) {
    const first = nodes.find((x) => x.state === "pending");
    if (first) {
      first.state = "active";
      if (["damage", "policy", "risk"].includes(first.id))
        nodes.filter((x) => ["damage", "policy", "risk"].includes(x.id) && x.state === "pending").forEach((x) => (x.state = "active"));
    }
  }
  if (waitingCustomer) {
    const at = route ? nodes[10] : nodes[3];
    at.detail = `${at.detail ? at.detail + " · " : ""}waiting for customer`;
  }
  if (waitingHuman) nodes[10].detail = `${nodes[10].detail ?? ""} · waiting for reviewer`;
  return nodes;
}

export function outcome(evs: Ev[], status: Status | null): { label: string; tone: string } | null {
  if (last(evs, "claim.closed")) {
    const paid = last(evs, "payment.instructed");
    return paid ? { label: `Paid € ${paid.payload.amount.toFixed(2)}`, tone: "bg-emerald-600" } : { label: "Closed – no payment", tone: "bg-slate-600" };
  }
  if (last(evs, "claim.recorded_as_incident")) return { label: "Recorded as incident", tone: "bg-slate-600" };
  if (status?.waiting_for === "awaiting_human_review") {
    const q = last(evs, "human.review_requested")?.payload?.queue;
    return q === "siu" ? { label: "Special investigations", tone: "bg-red-600" } : { label: "Human review", tone: "bg-amber-500" };
  }
  if (status?.waiting_for === "awaiting_customer_info") return { label: "Waiting for customer", tone: "bg-sky-600" };
  return null;
}
