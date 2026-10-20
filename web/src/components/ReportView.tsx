import { Fragment, useEffect, useState } from "react";
import { api, eur, Ev, human, pct } from "../api";

export function ReportView({ cid, events }: { cid: string | null; events: Ev[] }) {
  const [report, setReport] = useState<any>(null);
  const [why, setWhy] = useState<string | null>(null);
  const n = events.length;
  useEffect(() => { if (cid) api.report(cid).then(setReport).catch(() => setReport(null)); }, [cid, n]);
  if (!cid) return <Empty text="No claim selected." />;
  if (!report) return <Empty text="Loading report…" />;

  const s = report.claim_summary;
  const rules = (code?: string) => events.filter((e) => e.type === "rule.evaluated" && (!code || e.payload.inputs?.line === code));
  const routing = [...events].reverse().find((e) => e.type === "routing.decided");

  return (
    <div className="space-y-3">
      <Section title="Claim summary">
        <Grid rows={[["Claim", s.claim_id], ["Customer", s.customer_id], ["Policy", s.policy_id ?? "–"], ["Peril", human(s.peril)],
          ["Loss date", s.loss_date ?? "–"], ["Location", s.location ?? "–"], ["Channels", s.channels.join(", ")], ["Language", s.language]]} />
        {s.text?.en && <p className="text-sm text-slate-600 mt-2">{s.text.en}</p>}
      </Section>

      {report.image_assessment.length > 0 && (
        <Section title="Image damage assessment">
          <div className="grid grid-cols-2 gap-2">{report.image_assessment.map((a: any) => (
            <div key={a.evidence_id} className="border border-line rounded-lg p-2 text-sm">
              <div className="font-semibold">{a.evidence_id} · {human(a.room_type)}</div>
              <div>severity: {human(a.severity)}</div>
              <div className="text-slate-600">{a.damage_types.map(human).join(", ")}</div>
            </div>))}</div>
        </Section>
      )}

      {report.image_claim_consistency && (
        <Section title={`Image–claim consistency: ${human(report.image_claim_consistency.result)}`}>
          <ul className="text-sm space-y-0.5">{report.image_claim_consistency.checks.map((c: any) => (
            <li key={c.check}>{c.passed === true ? "✅" : c.passed === false ? "❌" : "❔"} {human(c.check)} <span className="text-muted">({c.source}) {c.detail}</span></li>))}</ul>
        </Section>
      )}

      {report.coverage_decision && (
        <Section title={`Coverage decision: ${human(report.coverage_decision.status)}`}>
          <ul className="text-sm space-y-0.5">{report.coverage_decision.clauses.filter((c: any) => c.status !== "not_applicable").map((c: any) => (
            <li key={c.clause_id}><span className="font-mono">{c.clause_id}</span> {c.status}{c.condition ? <span className="text-muted"> · if {c.condition}</span> : null}
              {Object.keys(c.facts_used).length > 0 && <span className="text-muted"> · facts {Object.entries(c.facts_used).map(([k, v]) => `${k}=${v}`).join(", ")}</span>}</li>))}</ul>
        </Section>
      )}

      {report.risk_score && (
        <Section title={`Risk score: ${report.risk_score.score.toFixed(2)}`}>
          {report.risk_score.hard_flags.length > 0 && <div className="text-red-700 font-semibold text-sm">hard flags: {report.risk_score.hard_flags.join(", ")}</div>}
          <ul className="text-sm">{report.risk_score.signals.filter((x: any) => x.contribution > 0).map((x: any) => (
            <li key={x.signal}>{human(x.signal)}: {x.strength.toFixed(2)} × {x.weight} = <b>{x.contribution.toFixed(3)}</b> <span className="text-muted">({x.source})</span></li>))}</ul>
        </Section>
      )}

      {report.payout_recommendation && (
        <Section title={`Payout recommendation: ${eur(report.payout_recommendation.payout)}`}>
          <table className="w-full text-sm">
            <thead className="text-muted"><tr><th className="text-left font-normal">item</th><th className="text-right font-normal">claimed</th><th className="text-right font-normal">validated</th><th className="text-right font-normal">depr.</th><th className="text-right font-normal">covered</th><th /></tr></thead>
            <tbody>{report.payout_recommendation.lines.map((l: any) => (<Fragment key={l.code}>
              <tr className="border-t border-line">
                <td>{l.description}</td><td className="text-right">{eur(l.claimed)}</td><td className="text-right">{eur(l.validated)}</td>
                <td className="text-right">{l.depreciation ? `−${eur(l.depreciation)}` : ""}</td><td className="text-right font-semibold">{eur(l.covered)}</td>
                <td className="text-right"><button onClick={() => setWhy(why === l.code ? null : l.code)} className="text-brand text-xs underline ml-2">Why?</button></td>
              </tr>
              {why === l.code && <tr><td colSpan={6}><WhyLine events={rules(l.code)} /></td></tr>}
            </Fragment>))}</tbody>
          </table>
          <div className="text-sm mt-2">eligible {eur(report.payout_recommendation.eligible)} − deductible {eur(report.payout_recommendation.deductible)} = <b>{eur(report.payout_recommendation.payout)}</b>
            <button onClick={() => setWhy(why === "_total" ? null : "_total")} className="text-brand text-xs underline ml-2">Why?</button></div>
          {why === "_total" && <WhyLine events={rules().filter((r) => ["PAY-CAP-01", "PAY-DEDUCT-01", "PAY-SUBLIMIT-01"].includes(r.payload.rule_id))} />}
        </Section>
      )}

      <Section title={`Route: ${report.route ? human(report.route).toUpperCase() : "–"}`}>
        <div className="flex flex-wrap gap-1">{report.route_reasons.map((r: string) => <span key={r} className="bg-slate-100 rounded px-1.5 py-0.5 text-xs">{r}</span>)}</div>
        {routing && <div className="text-xs text-muted mt-1">rule {routing.provenance.rule_id} · source {routing.provenance.rule_source} · config {Object.entries(routing.provenance.config_versions).map(([k, v]) => `${k}@${v}`).join(", ")}</div>}
      </Section>

      <Section title={`Human approval: ${human(report.human_approval.status)}`}>
        {report.human_approval.reviewer_id && <div className="text-sm">{report.human_approval.reviewer_id} ({report.human_approval.reviewer_role}) · {report.human_approval.reason ?? "no reason given"}</div>}
      </Section>

      {report.audit_trail && (
        <Section title="Audit trail">
          <div className="text-sm">{report.audit_trail.event_count} events · chain {report.audit_trail.chain_intact ? <span className="text-emerald-700 font-semibold">intact</span> : <span className="text-red-700 font-semibold">BROKEN at #{report.audit_trail.first_broken_seq}</span>}</div>
          <div className="text-xs text-muted">config versions: {Object.entries(report.audit_trail.config_versions).map(([k, v]) => `${k}@${v}`).join(", ")}</div>
        </Section>
      )}
    </div>
  );
}

function WhyLine({ events }: { events: Ev[] }) {
  return (
    <div className="bg-slate-50 rounded-lg p-2 my-1 text-xs space-y-1">
      {events.map((r) => (
        <div key={r.seq}><span className="font-mono font-semibold">{r.payload.rule_id}</span> <span className="text-muted">({r.provenance.rule_source})</span>
          <div className="font-mono">in: {JSON.stringify(r.payload.inputs)} → out: {JSON.stringify(r.payload.output)}</div></div>))}
      {events.length === 0 && <div className="text-muted">no rule events</div>}
    </div>
  );
}

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="bg-white rounded-xl border border-line p-4"><h3 className="font-semibold mb-2">{title}</h3>{children}</div>
);
const Grid = ({ rows }: { rows: [string, string][] }) => (
  <div className="grid grid-cols-4 gap-x-4 gap-y-1 text-sm">{rows.map(([k, v]) => <div key={k}><div className="text-muted text-xs">{k}</div><div>{v}</div></div>)}</div>
);
export const Empty = ({ text }: { text: string }) => <div className="text-center text-muted py-16">{text}</div>;
export { pct };
