import { useEffect, useMemo, useRef, useState } from "react";
import { api, eur, Ev, Gallery, Persona, Status } from "../api";
import { GalleryModal } from "./GalleryModal";

type Pending = { photos: string[]; uploads: { filename: string; data_b64: string; preview: string }[]; estimate: string | null };

export function Chat({ cid, persona, events, status, gallery, onNewClaim }: {
  cid: string | null; persona: Persona | null; events: Ev[]; status: Status | null; gallery: Gallery | null;
  onNewClaim: () => void;
}) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Pending>({ photos: [], uploads: [], estimate: null });
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const bubbles = useMemo(() => {
    const out: { side: "me" | "bot"; seq: number; time: string; node: JSX.Element }[] = [];
    for (const e of events) {
      const time = new Date(e.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      if (e.type === "evidence.received") {
        const p = e.payload;
        if (p.kind === "text") out.push({ side: "me", seq: e.seq, time, node: <p className="whitespace-pre-wrap">{p.text}</p> });
        if (p.kind === "image") out.push({ side: "me", seq: e.seq, time, node: <img src={api.blobUrl(p.blob)} className="rounded-md max-h-56" /> });
        if (p.kind === "document") out.push({
          side: "me", seq: e.seq, time, node: (
            <div className="flex items-center gap-2"><span className="text-2xl">📄</span>
              <div><div className="font-medium">Offerte · {p.estimate.contractor}</div>
                <div className="text-sm text-slate-600">{p.estimate.lines.length} regels · {eur(p.estimate.total)}</div></div></div>),
        });
      }
      if (e.type === "message.sent") {
        const withLetter = e.payload.kind === "decision" && cid && events.some((x) => x.type === "letter.generated");
        out.push({
          side: "bot", seq: e.seq, time, node: (
            <div>
              <p className="whitespace-pre-wrap">{e.payload.text}</p>
              {withLetter && (
                <a href={api.letterPdfUrl(cid!)} target="_blank" rel="noreferrer"
                  className="mt-2 flex items-center gap-2 bg-slate-50 border border-line rounded-md px-2 py-1.5 hover:bg-slate-100">
                  <span className="text-xl">📄</span>
                  <span className="text-sm font-medium">{e.payload.language === "nl" ? "Besluit (PDF)" : "Decision letter (PDF)"}</span>
                </a>
              )}
            </div>),
        });
      }
    }
    return out;
  }, [events, cid]);

  const typing = !!status?.busy || sending;
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [bubbles.length, typing]);

  async function send() {
    if (!cid || (!text.trim() && !pending.photos.length && !pending.uploads.length && !pending.estimate)) return;
    setSending(true);
    try {
      await api.turn(cid, {
        text: text.trim() || undefined, gallery_images: pending.photos,
        uploads: pending.uploads.map(({ filename, data_b64 }) => ({ filename, data_b64 })), gallery_estimate: pending.estimate,
      });
      setText(""); setPending({ photos: [], uploads: [], estimate: null });
    } finally { setSending(false); }
  }

  function onFiles(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((f) => {
      const r = new FileReader();
      r.onload = () => {
        const url = String(r.result);
        setPending((p) => ({ ...p, uploads: [...p.uploads, { filename: f.name, data_b64: url.split(",")[1], preview: url }] }));
      };
      r.readAsDataURL(f);
    });
  }

  const nl = persona?.language === "nl";
  return (
    <div className="h-full flex flex-col rounded-[2rem] border-[10px] border-slate-900 bg-white shadow-2xl overflow-hidden">
      <div className="bg-brand text-white px-4 py-3 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-white/20 grid place-items-center font-bold">T</div>
        <div className="flex-1 leading-tight">
          <div className="font-semibold">Tecto Schadeservice</div>
          <div className="text-xs text-white/80">{typing ? (nl ? "typt…" : "typing…") : "online"}</div>
        </div>
        <button onClick={onNewClaim} className="text-xs bg-white/15 hover:bg-white/25 rounded-full px-3 py-1">{nl ? "Nieuwe melding" : "New claim"}</button>
      </div>

      <div className="flex-1 overflow-y-auto chat-wallpaper p-3 space-y-2 scroll-thin">
        {!cid && <div className="text-center text-sm text-slate-600 mt-10">Pick a persona to start a claim.</div>}
        {cid && bubbles.length === 0 && (
          <div className="mx-auto max-w-[85%] bg-amber-50 text-amber-900 text-sm rounded-lg px-3 py-2 text-center shadow">
            {nl ? "Meld je schade: vertel wat er gebeurd is en stuur foto's of een offerte." : "Report your damage: tell us what happened and send photos or a quote."}
          </div>
        )}
        {bubbles.map((b) => (
          <div key={b.seq} className={`flex ${b.side === "me" ? "justify-end" : "justify-start"} card-in`}>
            <div className={`max-w-[82%] rounded-lg px-3 py-2 shadow-sm text-[15px] ${b.side === "me" ? "bg-bubble-me" : "bg-white"}`}>
              {b.node}
              <div className="text-[11px] text-slate-500 text-right mt-1">{b.time}</div>
            </div>
          </div>
        ))}
        {typing && <div className="flex"><div className="bg-white rounded-lg px-3 py-2 shadow-sm text-slate-500 text-sm">● ● ●</div></div>}
        <div ref={bottomRef} />
      </div>

      {(pending.photos.length > 0 || pending.uploads.length > 0 || pending.estimate) && (
        <div className="bg-slate-50 border-t border-line px-3 py-2 flex gap-2 flex-wrap items-center">
          {pending.photos.map((id) => (
            <Chip key={id} onRemove={() => setPending((p) => ({ ...p, photos: p.photos.filter((x) => x !== id) }))}>
              <img src={`/api/gallery/images/${id}`} className="w-10 h-10 object-cover rounded" />
            </Chip>
          ))}
          {pending.uploads.map((u, i) => (
            <Chip key={i} onRemove={() => setPending((p) => ({ ...p, uploads: p.uploads.filter((_, k) => k !== i) }))}>
              <img src={u.preview} className="w-10 h-10 object-cover rounded" />
            </Chip>
          ))}
          {pending.estimate && (
            <Chip onRemove={() => setPending((p) => ({ ...p, estimate: null }))}>
              <span className="text-sm px-1">📄 {gallery?.estimates.find((e) => e.id === pending.estimate)?.contractor}</span>
            </Chip>
          )}
        </div>
      )}

      <div className="border-t border-line p-2 flex items-end gap-2 bg-slate-50">
        <button title="Sample gallery" disabled={!cid} onClick={() => setGalleryOpen(true)} className="w-10 h-10 rounded-full hover:bg-slate-200 text-xl disabled:opacity-40">📎</button>
        <button title="Upload a photo" disabled={!cid} onClick={() => fileRef.current?.click()} className="w-10 h-10 rounded-full hover:bg-slate-200 text-xl disabled:opacity-40">📷</button>
        <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => onFiles(e.target.files)} />
        <textarea
          value={text} disabled={!cid} rows={1}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder={nl ? "Typ een bericht" : "Type a message"}
          className="flex-1 resize-none rounded-2xl border border-line px-4 py-2 max-h-32 focus:outline-none focus:ring-2 focus:ring-brand/40"
        />
        <button onClick={send} disabled={!cid || sending} className="w-10 h-10 rounded-full bg-brand text-white disabled:opacity-40">➤</button>
      </div>

      {galleryOpen && gallery && (
        <GalleryModal gallery={gallery} persona={persona} onClose={() => setGalleryOpen(false)}
          onPick={(sel) => {
            setPending((p) => ({ ...p, photos: [...new Set([...p.photos, ...sel.photos])], estimate: sel.estimate ?? p.estimate }));
            if (sel.text) setText((t) => (t ? t + "\n" : "") + sel.text);
            setGalleryOpen(false);
          }} />
      )}
    </div>
  );
}

function Chip({ children, onRemove }: { children: React.ReactNode; onRemove: () => void }) {
  return (
    <span className="relative inline-flex items-center bg-white border border-line rounded-lg p-1">
      {children}
      <button onClick={onRemove} className="absolute -top-2 -right-2 bg-slate-700 text-white rounded-full w-5 h-5 text-xs">×</button>
    </span>
  );
}
