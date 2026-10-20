import { useEffect, useRef, useState } from "react";
import { api, Ev, Status } from "./api";

export type Pace = "normal" | "slow" | "gate";

// Customer inputs and bookkeeping appear instantly; system work is revealed at the chosen pace.
const INSTANT = new Set(["claim.notified", "evidence.received", "evidence.normalized"]);

export function useClaimFeed(cid: string | null, pace: Pace) {
  const [all, setAll] = useState<Ev[]>([]);
  const [shown, setShown] = useState(0);
  const [status, setStatus] = useState<Status | null>(null);
  const [gateOpen, setGateOpen] = useState(false);
  const lastSeq = useRef(0);

  useEffect(() => {
    setAll([]); setShown(0); setStatus(null); lastSeq.current = 0; setGateOpen(false);
    if (!cid) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await api.events(cid, lastSeq.current);
        if (!alive) return;
        if (r.events.length) {
          lastSeq.current = r.events[r.events.length - 1].seq;
          setAll((prev) => [...prev, ...r.events]);
        }
        setStatus(r.status);
      } catch { /* backend restarting - keep polling */ }
    };
    tick();
    const h = setInterval(tick, 700);
    return () => { alive = false; clearInterval(h); };
  }, [cid]);

  // Reveal loop
  useEffect(() => {
    if (shown >= all.length) return;
    const next = all[shown];
    if (pace === "gate" && next.type === "routing.decided" && !gateOpen) return;
    if (pace === "normal" || INSTANT.has(next.type)) {
      // reveal everything up to the next gate in one go
      let n = shown;
      while (n < all.length) {
        if (pace === "gate" && all[n].type === "routing.decided" && !gateOpen) break;
        n++;
      }
      setShown(n);
      return;
    }
    const delay = pace === "slow" ? 650 : 120;
    const h = setTimeout(() => setShown((s) => s + 1), delay);
    return () => clearTimeout(h);
  }, [all, shown, pace, gateOpen]);

  // A new routing decision re-arms the gate
  useEffect(() => { if (pace !== "gate") setGateOpen(false); }, [pace]);

  const events = all.slice(0, shown);
  const heldAtGate = pace === "gate" && shown < all.length && all[shown]?.type === "routing.decided" && !gateOpen;
  return {
    events, all, status, heldAtGate,
    openGate: () => setGateOpen(true),
    rearmGate: () => setGateOpen(false),
  };
}
