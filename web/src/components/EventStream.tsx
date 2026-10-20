import { useMemo, useState } from "react";
import { api, eur, Ev, human, pct } from "../api";

type Group = { key: string; kind: "single" | "rules" | "jev"; events: Ev[] };

const TECHNICAL = new Set(["fnol.field_extracted", "evidence.normalized"]);

function group(evs: Ev[], technical: boolean): Group[] {
  const out: Group[] = [];
  for (const e of evs) {
    if (!technical && TECHNICAL.has(e.type)) continue;
    const prev = out[out.length - 1];
    if (e.type === "rule.evaluated" && prev?.kind === "rules") { prev.events.push(e); continue; }
    if (e.type === "jev.answered" && prev?.kind === "jev" && prev.events[0].payload.question_set === e.payload.question_set) {
      prev.events.push(e); continue;
    }
    out.push({ key: e.event_id, kind: e.type === "rule.evaluated" ? "rules" : e.type === "jev.answered" ? "jev" : "single", events: [e] });
  }
  return out.reverse();
}

export function EventStream({ events, all }: { events: Ev[]; all: Ev[] }) {
  const [technical, setTechnical] = useState(false);
  const groups = useMemo(() => group(events, technical), [events, technical]);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-sm text-muted">
        <span>{events.length} events in the claim file</span>
        <label className="flex items-center gap-1 ml-auto cursor-pointer">
          <input type="checkbox" checked={technical} onChange={(e) => setTechnical(e.target.checked)} /> technical
        </label>
      </div>
      {groups.map((g) => <GroupCard key={g.key} g={g} all={all} />)}
    </div>
  );
}

function Shell({ icon, title, who, tone = "border-line", children, raw }: {
  icon: string; title: React.ReactNode; who: string; tone?: string; children?: React.ReactNode; raw: Ev[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`bg-white rounded-xl border-l-4 ${tone} border border-line shadow-sm px-4 py-3 card-in`}>
      <div className="flex items-start gap-3">
        <span className="text-xl leading-none mt-0.5">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <div className="font-semibold">{title}</div>
            <span className="text-[11px] text-muted ml-auto whitespace-nowrap">{who} · #{raw[0].seq}{raw.length > 1 ? `–${raw[raw.length - 1].seq}` : ""}</span>
            <button onClick={() => setOpen(!open)} className="text-[11px] text-slate-400 hover:text-slate-700 font-mono">{open ? "hide" : "{ }"}</button>
          </div>
          {children && <div className="mt-1.5 text-[14px] text-slate-700">{children}</div>}
          {open && (
            <pre className="mt-2 text-[11px] bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto max-h-80 scroll-thin">
              {JSON.stringify(raw.length === 1 ? raw[0] : raw, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

const who = (e: Ev) => `${e.actor.kind}: ${e.actor.id}${e.provenance?.model ? ` (${e.provenance.model})` : ""}`;

function Bar({ p, label }: { p: number; label?: string }) {
  const color = p >= 0.75 ? "bg-emerald-500" : p <= 0.25 ? "bg-red-500" : "bg-amber-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-40 h-2.5 bg-slate-100 rounded-full overflow-hidden"><div className={`${color} h-full`} style={{ width: `${Math.round(p * 100)}%` }} /></div>
      <span className="font-mono text-[12px] w-10">{p.toFixed(2)}</span>
      {label && <span className="text-[12px] text-muted">{label}</span>}
    </div>
  );
}

const Badge = ({ source, value }: { source: string; value: number }) => {
  const c = source === "self_reported" ? "bg-slate-100 text-slate-600" : source === "measured" ? "bg-blue-100 text-blue-800" : "bg-emerald-100 text-emerald-800";
  return <span className={`text-[11px] rounded-full px-2 py-0.5 ${c}`}>confidence {value.toFixed(2)} · {human(source)}{source === "self_reported" ? " (not used for decisions)" : ""}</span>;
};

const Chips = ({ items, tone = "bg-slate-100" }: { items: string[]; tone?: string }) => (
  <div className="flex flex-wrap gap-1">{items.map((t, i) => <span key={i} className={`${tone} rounded px-1.5 py-0.5 text-[12px]`}>{human(t)}</span>)}</div>
);

function GroupCard({ g, all }: { g: Group; all: Ev[] }) {
  const e = g.events[0];
  const p = e.payload;

  if (g.kind === "rules") {
    return (
      <Shell icon="⚙️" title={`${g.events.length} rule${g.events.length > 1 ? "s" : ""} evaluated`} who="rules (plain code)" raw={g.events} tone="border-l-slate-400">
        <ul className="text-[13px] space-y-0.5">
          {g.events.slice(0, 12).map((r) => (
            <li key={r.seq} className="flex gap-2">
              <span className="font-mono text-[11.5px] text-slate-500 w-36 shrink-0 truncate">{r.payload.rule_id}</span>
              <span className="truncate">{ruleSummary(r)}</span>
            </li>
          ))}
          {g.events.length > 12 && <li className="text-muted">… {g.events.length - 12} more</li>}
        </ul>
      </Shell>
    );
  }
  if (g.kind === "jev") {
    return (
      <Shell icon="🎯" title={<>Jev answered {g.events.length} question{g.events.length > 1 ? "s" : ""} <span className="text-muted font-normal text-sm">({p.question_set})</span></>}
        who={`agent: ${e.actor.id} (${e.provenance.model})`} raw={g.events} tone="border-l-blue-500">
        <div className="space-y-1.5">
          {g.events.map((j) => {
            const a = j.payload.answer;
            const q = j.payload.question.instructions?.replace(/`/g, "") ?? j.payload.question_id;
            return (
              <div key={j.seq}>
                <div className="text-[13px] text-slate-600 truncate" title={q}>{q}</div>
                {a.type === "noul" ? <Bar p={a.noul} /> :
                  <div className="flex items-center gap-2"><span className="font-semibold text-[13px]">{human(a.choice)}</span><Bar p={a.confidence} label="confidence" /></div>}
              </div>
            );
          })}
        </div>
      </Shell>
    );
  }

  switch (e.type) {
    case "claim.notified":
      return <Shell icon="🔔" title="New notification opened" who={who(e)} raw={g.events}>Customer {p.customer_id} · policy {p.policy_hint} · {p.channel}</Shell>;
    case "evidence.received": {
      const norm = all.find((n) => n.type === "evidence.normalized" && n.payload.evidence_id === p.evidence_id)?.payload;
      if (p.kind === "image") return (
        <Shell icon="🖼️" title={`Photo received (${p.evidence_id})`} who={who(e)} raw={g.events}>
          <div className="flex gap-3 items-start">
            <img src={api.blobUrl(p.blob)} className="w-28 h-20 object-cover rounded" />
            {norm && <div className="text-[12.5px] space-y-0.5">
              <div>normalized {norm.size?.join("×")} px · fingerprint <span className="font-mono">{norm.phash}</span></div>
              <div>camera date {norm.exif?.DateTimeOriginal ?? "none"} {norm.exif?.GPS ? `· GPS ${norm.exif.GPS.lat.toFixed(3)}, ${norm.exif.GPS.lon.toFixed(3)}` : "· no GPS"}</div>
              {norm.exif_source === "synthetic_demo_metadata" && <div className="text-amber-700">camera data is synthetic demo metadata</div>}
            </div>}
          </div>
        </Shell>
      );
      if (p.kind === "document") return <Shell icon="📄" title={`Repair quote received (${p.evidence_id})`} who={who(e)} raw={g.events}>{p.estimate.contractor} · {p.estimate.lines.length} lines · {eur(p.estimate.total)}</Shell>;
      return <Shell icon="💬" title={`Customer message (${p.evidence_id})`} who={who(e)} raw={g.events}><span className="italic">“{p.text}”</span>{norm && <span className="text-muted text-xs"> · {norm.language}</span>}</Shell>;
    }
    case "evidence.normalized":
      return <Shell icon="🧹" title={`Normalized ${p.evidence_id}`} who={who(e)} raw={g.events} />;
    case "fnol.field_extracted":
      return <Shell icon="🔎" title={`Field ${p.field} = ${String(p.value)}`} who={who(e)} raw={g.events}>quote: “{p.quote}”</Shell>;
    case "finding.created":
      return <FindingCard e={e} />;
    case "fnol.completeness_evaluated":
      return p.complete
        ? <Shell icon="✅" title="Notification complete" who={who(e)} raw={g.events} tone="border-l-emerald-500">peril {human(p.peril)}; all required fields present</Shell>
        : <Shell icon="🧩" title="Information missing" who={who(e)} raw={g.events} tone="border-l-amber-500"><Chips items={p.missing} tone="bg-amber-100" /></Shell>;
    case "fnol.info_requested":
      return <Shell icon="❓" title={`Asking the customer (round ${p.round})`} who={who(e)} raw={g.events} tone="border-l-sky-500"><Chips items={p.missing} /></Shell>;
    case "fnol.info_received":
      return <Shell icon="📨" title="Customer answered" who={who(e)} raw={g.events}>new evidence: {p.new_evidence.join(", ") || "–"}</Shell>;
    case "message.sent":
      return <Shell icon="📤" title={`Message to customer (${p.kind})`} who={who(e)} raw={g.events}><span className="italic">“{p.text}”</span></Shell>;
    case "policy.matched":
      return <Shell icon="📑" title={p.matched ? `Policy ${p.policy_id} matched` : "Policy match failed"} who={who(e)} raw={g.events} tone={p.matched ? "border-l-emerald-500" : "border-l-red-500"}>
        {p.matched ? `${p.product}, ${p.days_since_policy_start} days since policy start` : <Chips items={p.reasons} tone="bg-red-100" />}</Shell>;
    case "claim.registered":
      return <Shell icon="🗂️" title={`Claim registered: ${p.claim_ref}`} who={who(e)} raw={g.events} tone="border-l-emerald-500">loss date {p.loss_date ?? "unknown"}</Shell>;
    case "claim.recorded_as_incident":
      return <Shell icon="📝" title="Recorded as incident only" who={who(e)} raw={g.events}>{human(p.reason)}</Shell>;
    case "vision.extracted": {
      const o = p.observation;
      const img = all.find((x) => x.type === "evidence.received" && x.payload.evidence_id === p.evidence_id)?.payload;
      return (
        <Shell icon="👁️" title={`Vision: ${p.evidence_id} shows ${human(o.room_type)}`} who={who(e)} raw={g.events} tone="border-l-violet-500">
          <div className="flex gap-3">
            {img && <img src={api.blobUrl(img.blob)} className="w-24 h-20 object-cover rounded" />}
            <div className="space-y-1 text-[13px]">
              <Chips items={o.damage_types} tone="bg-violet-100" />
              <div>quality {human(o.image_quality)}{o.long_term_signs_visible ? " · long-term signs visible" : ""}</div>
              {(o.visible_text.length > 0 || o.regional_indicators.length > 0) && <div className="text-amber-700">observed: {[...o.visible_text, ...o.regional_indicators].join("; ")}</div>}
              <div className="text-slate-500">{o.summary_en}</div>
            </div>
          </div>
        </Shell>
      );
    }
    case "risk.scored":
      return p.stage === "join"
        ? <Shell icon="🛡️" title={`Final risk ${p.score?.toFixed(2)}`} who={who(e)} raw={g.events} tone={p.score >= 0.7 || p.hard_flags.length ? "border-l-red-500" : p.score >= 0.3 ? "border-l-amber-500" : "border-l-emerald-500"}>
            base {p.base_score?.toFixed(2)}{p.added_signals.map((a: any) => ` + ${a.contribution} ${human(a.signal)} (${a.checks.join(", ")})`)}
            {p.hard_flags.length > 0 && <div className="text-red-700 font-semibold">hard flags: {p.hard_flags.join(", ")}</div>}
          </Shell>
        : <Shell icon="🛡️" title={`Risk score ${p.score.toFixed(2)} (${p.band})`} who={who(e)} raw={g.events}>
            <div className="space-y-0.5 text-[13px]">
              {[...p.signals].sort((a: any, b: any) => b.contribution - a.contribution).filter((s: any) => s.contribution > 0).slice(0, 5)
                .map((s: any) => <div key={s.signal} className="flex gap-2"><span className="w-56 truncate">{human(s.signal)}</span><span className="font-mono">+{s.contribution.toFixed(3)}</span><span className="text-muted truncate">{s.detail}</span></div>)}
              {p.hard_flags.length > 0 && <div className="text-red-700 font-semibold">hard flags: {p.hard_flags.join(", ")}</div>}
            </div>
          </Shell>;
    case "coverage.resolved":
      return <Shell icon="⚖️" title={`Coverage: ${human(p.status)}`} who={who(e)} raw={g.events}
        tone={p.status === "covered" ? "border-l-emerald-500" : p.status === "unresolved" ? "border-l-amber-500" : "border-l-red-500"}>
        {p.reasons.length > 0 ? <Chips items={p.reasons} /> : "all relevant clauses resolved in the customer's favour"}
        {Object.keys(p.excluded_lines).length > 0 && <div className="text-[13px] mt-1">excluded lines: {Object.entries(p.excluded_lines).map(([c, cl]) => `${c} (${cl})`).join(", ")}</div>}
      </Shell>;
    case "depreciation.calculated":
      return <Shell icon="📉" title="Depreciation applied" who={who(e)} raw={g.events}>
        {p.lines.map((l: any) => <div key={l.code} className="text-[13px]">{l.description}: −{eur(l.depreciation)} ({l.reason})</div>)}</Shell>;
    case "payout.calculated": {
      const r = p.recommendation;
      if (!r) return <Shell icon="💶" title="No payout calculated" who={who(e)} raw={g.events}><Chips items={p.warnings.map((w: any) => w.code)} /></Shell>;
      return <Shell icon="💶" title={`Payout recommendation ${eur(r.payout)}`} who={who(e)} raw={g.events} tone="border-l-emerald-500">
        <table className="text-[12.5px] w-full mt-1">
          <thead className="text-muted"><tr><th className="text-left font-normal">item</th><th className="text-right font-normal">claimed</th><th className="text-right font-normal">validated</th><th className="text-right font-normal">depr.</th><th className="text-right font-normal">covered</th></tr></thead>
          <tbody>{r.lines.map((l: any) => <tr key={l.code}><td className="truncate max-w-48">{l.description}{l.reason ? <span className="text-muted"> · {l.reason}</span> : null}</td><td className="text-right">{eur(l.claimed)}</td><td className="text-right">{eur(l.validated)}</td><td className="text-right">{l.depreciation ? `−${eur(l.depreciation)}` : ""}</td><td className="text-right font-medium">{eur(l.covered)}</td></tr>)}</tbody>
        </table>
        <div className="text-[13px] mt-1">eligible {eur(r.eligible)} − deductible {eur(r.deductible)} = <b>{eur(r.payout)}</b>{r.caps_applied.length ? ` · caps: ${r.caps_applied.join(", ")}` : ""}</div>
        {p.warnings.length > 0 && <Chips items={p.warnings.map((w: any) => w.code)} tone="bg-amber-100" />}
      </Shell>;
    }
    case "routing.decided": {
      const tone = p.route === "stp" ? "bg-emerald-600" : p.route === "siu" ? "bg-red-600" : p.route === "info_request" ? "bg-sky-600" : "bg-amber-500";
      return <Shell icon="🚦" title={<span className="flex items-center gap-2">Decision gate <span className={`${tone} text-white rounded-full px-3 py-0.5 text-sm`}>{human(p.route).toUpperCase()}</span></span>} who={who(e)} raw={g.events} tone="border-l-slate-900">
        <Chips items={p.reasons} />{p.route !== "stp" && <div className="text-[13px] mt-1">approver: {human(p.approver)}</div>}
      </Shell>;
    }
    case "human.review_requested":
      return <Shell icon="🧑‍⚖️" title={`Sent to ${p.queue === "siu" ? "special investigations" : "human review"}`} who={who(e)} raw={g.events} tone="border-l-amber-500"><Chips items={p.reasons} /></Shell>;
    case "human.decision":
      return <Shell icon="✍️" title={`Reviewer ${e.actor.id} (${e.actor.role}): ${human(p.action)}`} who={who(e)} raw={g.events} tone="border-l-violet-500">
        {p.reason && <div>reason: {p.reason}</div>}{p.payout_override != null && <div>payout set to {eur(p.payout_override)}</div>}
        {p.info_needed?.length > 0 && <div>asked: {p.info_needed.join("; ")}</div>}
      </Shell>;
    case "payment.instructed":
      return <Shell icon="🏦" title={`Payment instructed ${eur(p.amount)}`} who={who(e)} raw={g.events} tone="border-l-emerald-600">{p.payment_ref} · authorised by {p.authorised_by}{p.mock ? " · mock" : ""}</Shell>;
    case "letter.generated":
      return <LetterCard e={e} />;
    case "report.generated":
      return <Shell icon="📊" title="Claim decision report generated" who={who(e)} raw={g.events}>stored as blob {p.report_blob.slice(0, 12)}…</Shell>;
    case "claim.closed":
      return <Shell icon="🏁" title="Claim closed" who={who(e)} raw={g.events} tone="border-l-slate-900">payout {eur(p.payout)}</Shell>;
    case "system.error":
      return <Shell icon="⚠️" title={`System error in ${p.node}`} who={who(e)} raw={g.events} tone="border-l-red-600"><span className="text-red-700">{p.error_type}: {p.message.slice(0, 200)}</span></Shell>;
    default:
      return <Shell icon="•" title={e.type} who={who(e)} raw={g.events} />;
  }
}

function FindingCard({ e }: { e: Ev }) {
  const p = e.payload;
  const raw = [e];
  const head = <><span>{p.summary}</span><div className="mt-1 flex flex-wrap gap-1 items-center"><Badge source={p.confidence.source} value={p.confidence.value} />
    {p.warnings.filter((w: any) => w.severity !== "info").map((w: any, i: number) => <span key={i} className={`text-[11px] rounded px-1.5 py-0.5 ${w.severity === "critical" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-900"}`}>{w.code}</span>)}</div></>;
  switch (p.agent) {
    case "fnol_extractor": {
      const f = p.finding;
      const fields = ["loss_date", "what_happened", "source", "location", "source_stopped", "police_report_ref", "fire_brigade_report_ref"]
        .filter((k) => f[k]).map((k) => ({ k, v: String(f[k].value), q: f[k].quote }));
      return <Shell icon="🔎" title="Facts extracted (each with the customer's own words)" who={who(e)} raw={raw} tone="border-l-violet-500">
        {head}
        <table className="text-[13px] mt-1.5"><tbody>{fields.map((x) => <tr key={x.k}><td className="pr-3 text-muted align-top whitespace-nowrap">{human(x.k)}</td><td className="pr-3 align-top font-medium">{x.v}</td><td className="italic text-slate-500 align-top">“{x.q}”</td></tr>)}</tbody></table>
      </Shell>;
    }
    case "damage_agent": {
      const f = p.finding;
      const tone = f.consistency === "consistent" ? "border-l-emerald-500" : f.consistency === "partially_consistent" ? "border-l-amber-500" : "border-l-red-500";
      return <Shell icon="🔬" title={`Damage agent: photos ${human(f.consistency)} with the claim`} who={who(e)} raw={raw} tone={tone}>
        {head}
        <ul className="text-[13px] mt-1.5 space-y-0.5">{f.checks.map((c: any) => (
          <li key={c.check} className="flex gap-2"><span>{c.result === "pass" ? "✅" : c.result === "fail" ? "❌" : c.result === "unresolved" ? "❔" : "➖"}</span>
            <span className="w-52 shrink-0">{human(c.check)}</span><span className="text-slate-500 truncate">{c.detail}</span></li>))}</ul>
      </Shell>;
    }
    case "policy_agent": {
      const f = p.finding;
      return <Shell icon="📜" title={`Policy agent: ${f.clauses.length} clauses for ${human(f.peril)}`} who={who(e)} raw={raw} tone="border-l-indigo-500">
        {head}
        <ul className="text-[13px] mt-1.5 space-y-0.5">{f.clauses.filter((c: any) => c.status !== "not_applicable").map((c: any) => (
          <li key={c.clause_id} className="flex gap-2"><span className="font-mono w-14 shrink-0">{c.clause_id}</span>
            <span className={`w-24 shrink-0 ${c.status === "excluded" ? "text-red-700" : c.status === "conditional" ? "text-amber-700" : c.status === "unresolved" ? "text-amber-700" : "text-emerald-700"}`}>{c.status}</span>
            <span className="text-slate-600 truncate">{c.reason}</span><span className="text-[11px] text-muted ml-auto whitespace-nowrap">{c.selected_by.join("+")}</span></li>))}</ul>
      </Shell>;
    }
    case "risk_agent":
      return <Shell icon="🕵️" title={`Risk agent: ${p.finding.band} (${p.finding.score.toFixed(2)})`} who={who(e)} raw={raw}>{head}</Shell>;
    default:
      return <Shell icon="🧠" title={`Finding by ${p.agent}`} who={who(e)} raw={raw}>{p.summary ? head : null}</Shell>;
  }
}

function LetterCard({ e }: { e: Ev }) {
  const [open, setOpen] = useState(false);
  return (
    <Shell icon="✉️" title="Decision letter written (Sonnet, from the decision record only)" who={who(e)} raw={[e]} tone="border-l-violet-500">
      <button onClick={() => setOpen(!open)} className="text-sm text-brand underline">{open ? "hide letter" : "show letter"}</button>
      {open && <pre className="whitespace-pre-wrap font-sans text-[13.5px] bg-slate-50 rounded-lg p-3 mt-2">{e.payload.letter}</pre>}
    </Shell>
  );
}

function ruleSummary(r: Ev): string {
  const o = r.payload.output ?? {};
  const line = r.payload.inputs?.line;
  if (o.status) return `${o.status}${o.reason ? " – " + o.reason : ""}`;
  if ("validated" in o) return `${line}: validated ${eur(o.validated)}${o.trimmed ? " (trimmed to benchmark)" : ""}`;
  if ("depreciation" in o) return `${line}: depreciation ${pct(o.depreciation_pct)} = ${eur(o.depreciation)}`;
  if ("payout" in o) return `payout ${eur(o.payout)}`;
  if ("eligible" in o) return `eligible ${eur(o.eligible)}`;
  if ("covered" in o) return `${line}: excluded by ${o.clause}`;
  if ("consistency" in o) return `consistency ${human(o.consistency)}`;
  if ("complete" in o) return o.complete ? "complete" : `missing ${o.missing.join(", ")}`;
  if ("incident_only" in o) return "incident only";
  if ("reduced_by" in o) return `sublimit: reduced by ${eur(o.reduced_by)}`;
  return JSON.stringify(o).slice(0, 80);
}
