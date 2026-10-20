import { useEffect, useState } from "react";
import { api, eur, human } from "../api";
import { Empty } from "./ReportView";

export function ReviewInbox({ onOpen, current }: { onOpen: (cid: string) => void; current: string | null }) {
  const [items, setItems] = useState<any[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    const load = () => api.inbox().then(setItems).catch(() => {});
    load();
    const h = setInterval(load, 2000);
    return () => clearInterval(h);
  }, []);
  useEffect(() => { if (current && items.some((i) => i.claim_id === current)) setSel(current); }, [current, items]);
  const item = items.find((i) => i.claim_id === sel);

  return (
    <div className="grid grid-cols-[300px_1fr] gap-3">
      <div className="space-y-2">
        {items.length === 0 && <Empty text="Inbox is empty." />}
        {items.map((i) => (
          <button key={i.claim_id} onClick={() => { setSel(i.claim_id); onOpen(i.claim_id); }}
            className={`w-full text-left rounded-xl border p-3 bg-white ${sel === i.claim_id ? "border-brand ring-2 ring-brand/20" : "border-line"}`}>
            <div className="flex items-center gap-2"><span className="font-semibold">{i.claim_id}</span>
              <span className={`ml-auto text-xs rounded-full px-2 py-0.5 text-white ${i.queue === "siu" ? "bg-red-600" : "bg-amber-500"}`}>{i.queue === "siu" ? "SIU" : human(i.approver)}</span></div>
            <div className="text-sm">{i.customer} · proposed {eur(i.proposed_payout)}</div>
            <div className="text-xs text-muted truncate">{i.reasons.join(", ")}</div>
          </button>
        ))}
      </div>
      {item ? <Decide item={item} onDone={() => setSel(null)} /> : <Empty text="Select a claim to review. The Live and Report tabs show its full file." />}
    </div>
  );
}

function Decide({ item, onDone }: { item: any; onDone: () => void }) {
  const [action, setAction] = useState<"approve" | "override" | "request_info" | "escalate_siu">("approve");
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState<string>(String(item.proposed_payout ?? 0));
  const [ask, setAsk] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setErr(null); setBusy(true);
    try {
      await api.review(item.claim_id, {
        action, reviewer_id: "presenter", reviewer_role: human(item.approver) || "claims_handler",
        reason: reason || null, payout_override: action === "override" ? Number(amount) : null,
        info_needed: action === "request_info" ? [ask] : [],
      });
      onDone();
    } catch (e: any) { setErr(String(e.message ?? e)); } finally { setBusy(false); }
  }

  return (
    <div className="bg-white rounded-xl border border-line p-4 space-y-3">
      <h3 className="font-semibold text-lg">{item.claim_id} · {item.customer}</h3>
      <div className="flex flex-wrap gap-1">{item.reasons.map((r: string) => <span key={r} className="bg-amber-100 text-amber-900 rounded px-1.5 py-0.5 text-xs">{r}</span>)}</div>
      <div className="text-sm">Proposed payout <b>{eur(item.proposed_payout)}</b> · required approver: {human(item.approver)}</div>
      <div className="flex gap-2">
        {(["approve", "override", "request_info", "escalate_siu"] as const).map((a) => (
          <button key={a} onClick={() => setAction(a)} className={`px-3 py-1.5 rounded-full text-sm border ${action === a ? "bg-brand text-white border-brand" : "border-line"}`}>{human(a)}</button>
        ))}
      </div>
      {action === "override" && <label className="block text-sm">New payout (EUR) <input value={amount} onChange={(e) => setAmount(e.target.value)} className="border border-line rounded px-2 py-1 ml-2 w-32" /></label>}
      {action === "request_info" && <label className="block text-sm">Question for the customer <input value={ask} onChange={(e) => setAsk(e.target.value)} className="border border-line rounded px-2 py-1 w-full mt-1" placeholder="e.g. Can you send a photo of the floor?" /></label>}
      <label className="block text-sm">Reason {action === "override" || action === "escalate_siu" ? <span className="text-red-600">(mandatory)</span> : "(optional)"}
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="border border-line rounded px-2 py-1 w-full mt-1" /></label>
      {err && <div className="text-red-700 text-sm">{err}</div>}
      <button onClick={submit} disabled={busy} className="bg-brand text-white rounded-full px-5 py-2 disabled:opacity-50">Submit decision</button>
      <p className="text-xs text-muted">Your decision is recorded as a human.decision event with your id and role - part of the audit trail.</p>
    </div>
  );
}
