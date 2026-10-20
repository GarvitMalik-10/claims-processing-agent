import { MapNode, NodeState } from "../processMap";

const tone: Record<NodeState, string> = {
  pending: "bg-white border-slate-300 text-slate-400",
  active: "bg-blue-50 border-blue-500 text-blue-900 node-active",
  done: "bg-emerald-50 border-emerald-500 text-emerald-900",
  warn: "bg-amber-50 border-amber-500 text-amber-900",
  fail: "bg-red-50 border-red-500 text-red-900",
  skipped: "bg-slate-50 border-slate-200 text-slate-300 line-through",
};

function Box({ n }: { n: MapNode }) {
  return (
    <div className={`flex-1 min-w-0 rounded-lg border-2 px-2 py-1.5 transition-colors ${tone[n.state]}`} title={`${n.label} · ${n.sub}`}>
      <div className="font-semibold text-[12.5px] leading-tight truncate">{n.label}</div>
      <div className="text-[10px] opacity-70 leading-tight truncate">{n.sub}</div>
      {n.detail && <div className="text-[11px] font-medium mt-0.5 leading-tight truncate" title={n.detail}>{n.detail}</div>}
    </div>
  );
}

const Arrow = () => <div className="text-slate-400 text-sm shrink-0">›</div>;

export function ProcessMap({ nodes, outcome }: { nodes: MapNode[]; outcome: { label: string; tone: string } | null }) {
  const by = (id: string) => nodes.find((n) => n.id === id)!;
  return (
    <div className="bg-white rounded-2xl border border-line p-3">
      <div className="flex items-center gap-1">
        <Box n={by("intake")} /><Arrow />
        <Box n={by("extract")} /><Arrow />
        <Box n={by("classify")} /><Arrow />
        <Box n={by("complete")} /><Arrow />
        <Box n={by("register")} /><Arrow />
        <div className="flex-[1.15] min-w-0 flex flex-col gap-1 border-x-2 border-dashed border-slate-300 px-1.5 rounded">
          <div className="text-[9.5px] text-center text-slate-500 font-semibold tracking-wide">IN PARALLEL</div>
          <Box n={by("damage")} /><Box n={by("policy")} /><Box n={by("risk")} />
        </div>
        <Arrow />
        <Box n={by("coverage")} /><Arrow />
        <Box n={by("payout")} /><Arrow />
        <Box n={by("route")} />
      </div>
      {outcome && (
        <div className="mt-2 flex justify-end">
          <div className={`${outcome.tone} text-white rounded-full px-5 py-1.5 font-semibold shadow card-in`}>{outcome.label}</div>
        </div>
      )}
    </div>
  );
}
