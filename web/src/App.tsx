import { useEffect, useMemo, useState } from "react";
import { api, Gallery, Persona } from "./api";
import { AuditPanel } from "./components/AuditPanel";
import { Chat } from "./components/Chat";
import { EventStream } from "./components/EventStream";
import { ProcessMap } from "./components/ProcessMap";
import { ReportView } from "./components/ReportView";
import { ReviewInbox } from "./components/ReviewInbox";
import { buildMap, outcome } from "./processMap";
import { Pace, useClaimFeed } from "./useClaimFeed";

type Tab = "live" | "report" | "review" | "audit";

export default function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [gallery, setGallery] = useState<Gallery | null>(null);
  const [personaId, setPersonaId] = useState<string>("");
  const [cid, setCid] = useState<string | null>(null);
  const [claims, setClaims] = useState<any[]>([]);
  const [tab, setTab] = useState<Tab>("live");
  const [pace, setPace] = useState<Pace>("normal");
  const [backstage, setBackstage] = useState(true);
  const feed = useClaimFeed(cid, pace);

  useEffect(() => { api.personas().then(setPersonas); api.gallery().then(setGallery); }, []);
  useEffect(() => {
    const load = () => api.claims().then(setClaims).catch(() => {});
    load();
    const h = setInterval(load, 3000);
    return () => clearInterval(h);
  }, []);

  // Presenter hotkeys: B backstage, 1-4 tabs, G open the gate
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "TEXTAREA" || (e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "b") setBackstage((v) => !v);
      if (e.key === "g") feed.openGate();
      const tabs: Tab[] = ["live", "report", "review", "audit"];
      if (["1", "2", "3", "4"].includes(e.key)) { setTab(tabs[Number(e.key) - 1]); setBackstage(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [feed]);

  const currentClaim = claims.find((c) => c.claim_id === cid);
  const persona = personas.find((p) => p.customer_id === (currentClaim?.customer_id ?? personaId)) ?? null;
  const revealComplete = feed.events.length === feed.all.length;
  const nodes = useMemo(() => buildMap(feed.events, feed.status, revealComplete), [feed.events, feed.status, revealComplete]);
  const out = useMemo(() => (revealComplete ? outcome(feed.events, feed.status) : null), [feed.events, feed.status, revealComplete]);

  async function startClaim(id: string) {
    setPersonaId(id);
    if (!id) return;
    const r = await api.createClaim(id);
    setCid(r.claim_id); setTab("live");
  }

  return (
    <div className="h-full flex flex-col">
      <header className="bg-white border-b border-line px-5 py-2.5 flex items-center gap-4">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-lg bg-brand text-white grid place-items-center font-bold text-lg">T</div>
          <div className="leading-tight"><div className="font-bold text-lg">Tecto</div><div className="text-[11px] text-muted -mt-0.5">explainable claims STP · demo</div></div>
        </div>
        <select value={persona?.customer_id ?? ""} onChange={(e) => startClaim(e.target.value)} className="border border-line rounded-lg px-3 py-1.5 bg-white max-w-80"
          title={persona ? `${persona.note}\npolicy ${persona.policy_id} since ${persona.start_date} · deductible €${persona.deductible}${persona.extensions.length ? ` · +${persona.extensions.join(", ")}` : ""}` : ""}>
          <option value="">Choose a persona to start…</option>
          {personas.map((p) => <option key={p.customer_id} value={p.customer_id}>{p.name} · {p.product}{p.address.split(",").pop()}</option>)}
        </select>
        {persona && <div className="text-xs text-muted leading-tight whitespace-nowrap">policy {persona.policy_id} · €{persona.deductible} deductible{persona.extensions.length ? ` · +${persona.extensions.join(", ")}` : ""}</div>}
        <div className="flex-1" />
        <select value={cid ?? ""} onChange={(e) => setCid(e.target.value || null)} className="border border-line rounded-lg px-2 py-1.5 bg-white text-sm" title="Open an earlier claim">
          <option value="">Claims…</option>
          {claims.map((c) => <option key={c.claim_id} value={c.claim_id}>{c.claim_id} · {c.customer_id} · {c.stage}</option>)}
        </select>
        <div className="flex items-center gap-1 text-sm whitespace-nowrap" title="Pace of the backstage">
          {(["normal", "slow", "gate"] as Pace[]).map((p) => (
            <button key={p} onClick={() => setPace(p)} className={`px-2.5 py-1 rounded-full border ${pace === p ? "bg-slate-800 text-white border-slate-800" : "border-line"}`}>
              {p === "normal" ? "Normal" : p === "slow" ? "Slow-mo" : "Pause at gate"}</button>))}
        </div>
        <button onClick={() => setBackstage((v) => !v)} className="text-sm border border-line rounded-full px-3 py-1 whitespace-nowrap" title="Hotkey B">{backstage ? "Hide backstage" : "Show backstage"}</button>
        <button title="Archive all demo claims and start clean (use before each session)"
          onClick={async () => {
            if (!confirm("Archive all demo claims and start a clean session?")) return;
            try { await api.resetDemo(); setCid(null); setPersonaId(""); setClaims([]); } catch (e: any) { alert(e.message); }
          }}
          className="text-sm text-red-700 border border-red-200 rounded-full px-3 py-1 whitespace-nowrap">Reset demo</button>
      </header>

      <main className={`flex-1 min-h-0 grid gap-4 p-4 ${backstage ? "grid-cols-[minmax(360px,32%)_1fr]" : "grid-cols-[minmax(380px,460px)] justify-center"}`}>
        <div className="min-h-0 min-w-0">
          <Chat cid={cid} persona={persona} events={feed.events} status={feed.status} gallery={gallery}
            onNewClaim={() => persona && startClaim(persona.customer_id)} />
        </div>

        {backstage && (
          <section className="min-h-0 min-w-0 flex flex-col gap-3">
            <div className="flex items-center gap-1">
              {([["live", "Live"], ["report", "Report"], ["review", "Review inbox"], ["audit", "Audit"]] as [Tab, string][]).map(([t, label], i) => (
                <button key={t} onClick={() => setTab(t)} className={`px-4 py-1.5 rounded-full text-sm font-medium ${tab === t ? "bg-brand text-white" : "bg-white border border-line"}`}>
                  {label} <span className="opacity-50 text-xs">{i + 1}</span></button>))}
              {cid && <span className="ml-auto text-sm text-muted">{cid} · {feed.status?.stage ?? "–"}{feed.status?.busy ? " · working…" : ""}</span>}
            </div>
            {tab === "live" && <ProcessMap nodes={nodes} outcome={out} />}
            {tab === "live" && feed.heldAtGate && (
              <div className="bg-slate-900 text-white rounded-xl px-4 py-3 flex items-center gap-3">
                <span className="text-xl">⏸</span><span>Paused before the decision gate - explain the findings, then continue.</span>
                <button onClick={feed.openGate} className="ml-auto bg-white text-slate-900 rounded-full px-4 py-1.5 font-semibold">Continue (G)</button>
              </div>
            )}
            <div className="flex-1 min-h-0 overflow-y-auto scroll-thin pr-1">
              {tab === "live" && (cid ? <EventStream events={feed.events} all={feed.all} /> : <div className="text-center text-muted py-16">Choose a persona to open a claim. Everything the system does will appear here.</div>)}
              {tab === "report" && <ReportView cid={cid} events={feed.events} />}
              {tab === "review" && <ReviewInbox current={cid} onOpen={(c) => setCid(c)} />}
              {tab === "audit" && <AuditPanel cid={cid} />}
            </div>
          </section>
        )}
      </main>
      <footer className="text-[11px] text-muted px-5 pb-2">
        Demo with synthetic customers and policies. Photos: Wikimedia Commons contributors (CC BY / CC BY-SA / CC0 / public domain) - see data/synthetic/media/images/CREDITS.md.
      </footer>
    </div>
  );
}
