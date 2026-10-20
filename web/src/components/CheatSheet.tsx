const ROWS: [string, string, string][] = [
  ["Paid straight through, with depreciation + Why?", "Sanne", "Story S14 (storm, chimney). Then Report → Why? on the roof tiles"],
  ["High deductible eats most of the claim", "Pieter", "Story S02 (washing machine hose)"],
  ["Glass cover, paid in seconds", "Emma", "Story S18 (football through the window). Try it as Pieter: no glass cover"],
  ["Tenant: burglary damage covered, contents depreciated", "James", "Story S19 (forced door, laptop stolen)"],
  ["Missing info loop", "anyone", "Type only “Mijn keuken is ondergelopen” and answer the questions"],
  ["Photo doesn't match the story", "Lotte / Sanne", "S04 (museum floor) or S06 (says kitchen, sends bathroom photo)"],
  ["Gradual damage exclusion", "Fatima / Pieter", "S07 (shower mould) or S09 (rusted wall)"],
  ["Policy decides, not the AI", "Henk vs Lotte", "S05 flood: excluded for Henk, covered under Lotte's flood extension"],
  ["Duplicate photo → special investigations", "Pieter", "S13 (photo already used on someone else's claim)"],
  ["Old photo + frequent claimer → SIU", "Henk", "S08 (photo dated 2024, 3 claims in 3 years)"],
  ["Authority limit → claims handler", "Emma", "S16 (tree on house, € 8.962). Approve it in the Review inbox"],
  ["Just reporting → incident only", "Ahmed", "S17 (tree in the garden, no damage)"],
  ["Unscripted: not a damage photo", "anyone", "Send IMG-20 (intact living room) or a photo of the meeting room"],
];

export function CheatSheet({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-6" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[88vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center mb-3"><h2 className="text-xl font-semibold">Presenter cheat sheet</h2><div className="flex-1" />
          <button onClick={onClose} className="text-2xl text-slate-500">×</button></div>
        <p className="text-sm text-muted mb-3">Let the prospect play the customer. Suggest one of these when you want to show a specific outcome. Stories are in 📎 → Example stories and work with any persona.</p>
        <table className="w-full text-sm">
          <thead className="text-left text-muted"><tr><th className="font-normal pb-1">To show</th><th className="font-normal pb-1">Persona</th><th className="font-normal pb-1">Suggest</th></tr></thead>
          <tbody>{ROWS.map(([a, b, c]) => <tr key={a} className="border-t border-line align-top"><td className="py-1.5 pr-3 font-medium">{a}</td><td className="py-1.5 pr-3">{b}</td><td className="py-1.5">{c}</td></tr>)}</tbody>
        </table>
        <div className="mt-4 text-sm grid grid-cols-2 gap-4">
          <div><div className="font-semibold mb-1">Hotkeys</div>
            <div><kbd>B</kbd> show/hide backstage · <kbd>1</kbd>–<kbd>4</kbd> tabs · <kbd>G</kbd> continue past the paused gate · <kbd>?</kbd> this sheet</div></div>
          <div><div className="font-semibold mb-1">Audit close (2 min)</div>
            <div>Audit tab → Verify integrity → Tamper → Verify again (red) → Replay → Download PDF</div></div>
        </div>
        <p className="text-xs text-muted mt-4">Before each session: Reset demo (archives earlier claims, nothing is deleted).</p>
      </div>
    </div>
  );
}
