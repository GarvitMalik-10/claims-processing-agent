import { useState } from "react";
import { eur, Gallery, Persona } from "../api";

export function GalleryModal({ gallery, persona, onClose, onPick }: {
  gallery: Gallery; persona: Persona | null; onClose: () => void;
  onPick: (sel: { photos: string[]; estimate: string | null; text: string | null }) => void;
}) {
  const [tab, setTab] = useState<"photos" | "quotes" | "stories">("photos");
  const [photos, setPhotos] = useState<string[]>([]);
  const [estimate, setEstimate] = useState<string | null>(null);
  const nl = persona?.language === "nl";
  const toggle = (id: string) => setPhotos((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  return (
    <div className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-6" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[88vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-5 py-3">
          <h2 className="text-lg font-semibold mr-4">Sample gallery</h2>
          {(["photos", "quotes", "stories"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-full text-sm ${tab === t ? "bg-brand text-white" : "hover:bg-slate-100"}`}>
              {t === "photos" ? "Photos" : t === "quotes" ? "Repair quotes" : "Example stories"}
            </button>
          ))}
          <div className="flex-1" />
          <button onClick={onClose} className="text-2xl text-slate-500 px-2">×</button>
        </div>

        <div className="overflow-y-auto p-5 scroll-thin">
          {tab === "photos" && (
            <div className="grid grid-cols-4 gap-3">
              {gallery.photos.map((p) => (
                <button key={p.id} onClick={() => toggle(p.id)}
                  className={`text-left rounded-xl overflow-hidden border-2 ${photos.includes(p.id) ? "border-brand ring-2 ring-brand/30" : "border-transparent"} bg-slate-50 hover:shadow`}>
                  <img src={p.url} className="w-full h-36 object-cover" />
                  <div className="p-2 text-xs leading-snug">
                    <span className="font-semibold">{p.id}</span> · {nl ? p.caption_nl : p.caption}
                    {p.trick && <div className="mt-1 inline-block bg-amber-100 text-amber-900 rounded px-1.5 py-0.5">trick: {p.trick}</div>}
                  </div>
                </button>
              ))}
            </div>
          )}
          {tab === "quotes" && (
            <div className="grid grid-cols-2 gap-3">
              {gallery.estimates.map((e) => (
                <button key={e.id} onClick={() => setEstimate(estimate === e.id ? null : e.id)}
                  className={`text-left rounded-xl border-2 p-3 ${estimate === e.id ? "border-brand bg-brand-soft/40" : "border-line hover:bg-slate-50"}`}>
                  <div className="flex justify-between"><span className="font-semibold">📄 {e.contractor}</span><span className="font-semibold">{eur(e.total)}</span></div>
                  <div className="text-xs text-muted mt-0.5">{e.id} · {e.title}</div>
                  <ul className="text-sm mt-2 list-disc pl-5 text-slate-700">{e.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
                </button>
              ))}
            </div>
          )}
          {tab === "stories" && (
            <div className="space-y-2">
              {gallery.stories.map((s) => (
                <div key={s.id} className="border border-line rounded-xl p-3">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{s.id}</span><span className="text-sm text-muted">{s.title}</span>
                    <div className="flex-1" />
                    <button className="text-sm bg-brand text-white rounded-full px-3 py-1"
                      onClick={() => onPick({ photos: s.images, estimate: gallery.estimates.some((e) => e.id === s.id) ? s.id : null, text: s.texts.join("\n") })}>
                      Use story + photos + quote
                    </button>
                  </div>
                  <p className="text-sm mt-1 text-slate-700">{s.texts[0]}</p>
                  {s.customer_id !== persona?.customer_id && <p className="text-xs text-amber-700 mt-1">Written for {s.customer_id}; works with any persona.</p>}
                </div>
              ))}
            </div>
          )}
        </div>

        {tab !== "stories" && (
          <div className="border-t border-line px-5 py-3 flex items-center gap-3">
            <span className="text-sm text-muted">{photos.length} photo(s){estimate ? " · 1 quote" : ""} selected · gallery photos get synthetic camera data (taken now, at the persona's home)</span>
            <div className="flex-1" />
            <button onClick={() => onPick({ photos, estimate, text: null })} className="bg-brand text-white rounded-full px-5 py-2">Attach</button>
          </div>
        )}
      </div>
    </div>
  );
}
