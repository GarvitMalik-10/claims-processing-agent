import { useState } from "react";
import { api, human } from "../api";
import { Empty } from "./ReportView";

export function AuditPanel({ cid }: { cid: string | null }) {
  const [verify, setVerify] = useState<any>(null);
  const [replay, setReplay] = useState<any>(null);
  const [tampered, setTampered] = useState<any>(null);
  if (!cid) return <Empty text="No claim selected." />;

  return (
    <div className="space-y-3">
      <Card title="1 · Verify integrity" text="Recomputes the sha256 hash chain over every event in this claim file.">
        <button onClick={() => api.verify(cid).then(setVerify)} className="bg-brand text-white rounded-full px-5 py-2">Verify integrity</button>
        {verify && (verify.intact
          ? <div className="mt-3 text-2xl font-bold text-emerald-700">✔ Chain intact · {verify.event_count} events</div>
          : <div className="mt-3 text-2xl font-bold text-red-700">✘ Chain broken at event #{verify.first_broken_seq} <div className="text-base font-normal">{verify.problem}</div></div>)}
      </Card>

      <Card title="2 · Tamper (demo)" text="Plays an attacker with database access: edits the payout amount directly in SQLite, bypassing the application. Then verify again.">
        <button onClick={() => { if (confirm("Edit this claim's database record directly?")) api.tamper(cid).then((r) => { setTampered(r); setVerify(null); }); }}
          className="bg-red-600 text-white rounded-full px-5 py-2">Tamper with the database</button>
        {tampered && <div className="mt-2 text-sm text-red-700">Event #{tampered.tampered_seq} ({tampered.type}) was edited in the database. Click Verify integrity.</div>}
      </Card>

      <Card title="3 · Replay" text="Recomputes coverage, payout and route from the logged findings with the rules - no AI calls - and compares with what was decided.">
        <button onClick={() => api.replay(cid).then(setReplay)} className="bg-brand text-white rounded-full px-5 py-2">Replay decision</button>
        {replay && (!replay.replayable ? <div className="mt-2 text-muted">{replay.note}</div> : (
          <table className="mt-3 text-sm">
            <thead className="text-muted"><tr><th className="text-left pr-6 font-normal">item</th><th className="text-left pr-6 font-normal">logged</th><th className="text-left pr-6 font-normal">replayed</th><th /></tr></thead>
            <tbody>{replay.checks.map((c: any) => <tr key={c.item}><td className="pr-6">{c.item}</td><td className="pr-6">{human(String(c.logged))}</td><td className="pr-6">{human(String(c.replayed))}</td><td>{c.match ? "✅" : "❌"}</td></tr>)}</tbody>
          </table>))}
        {replay?.note && replay.replayable && <div className="text-xs text-amber-700 mt-1">{replay.note}</div>}
      </Card>

      <Card title="4 · Export audit file" text="One JSON bundle: every event, the decision report, chain verification, replay result and the raw model requests and responses.">
        <a href={api.exportUrl(cid)} className="inline-block bg-slate-800 text-white rounded-full px-5 py-2">Download {cid}-audit.json</a>
      </Card>
    </div>
  );
}

const Card = ({ title, text, children }: { title: string; text: string; children: React.ReactNode }) => (
  <div className="bg-white rounded-xl border border-line p-4"><h3 className="font-semibold text-lg">{title}</h3><p className="text-sm text-muted mb-3">{text}</p>{children}</div>
);
