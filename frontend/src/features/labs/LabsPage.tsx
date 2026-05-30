"use client";

const labItems = [
  "AutoDream and learned reruns",
  "Digital-twin benchmark gauntlets",
  "Industrial dossiers",
  "BigQuery priors",
  "Generated SOPs",
  "Reliability QA dashboards",
];

export default function LabsPage() {
  return (
    <main className="min-h-screen bg-slate-950 px-4 py-6 text-slate-200 lg:px-8">
      <div className="mx-auto max-w-5xl rounded-lg border border-slate-800 bg-slate-900 p-6">
        <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">ParkPulse labs</div>
        <h1 className="mt-2 text-3xl font-black text-slate-100">Advanced surfaces are parked here</h1>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
          The MVP command center owns the main story. Lab work should graduate back only when it strengthens the loop: state, findings, action, policy gate, dispatch, and receipt.
        </p>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {labItems.map((item) => (
            <div key={item} className="rounded border border-slate-800 bg-slate-950 p-4 text-sm font-black text-slate-100">
              {item}
            </div>
          ))}
        </div>
        <a href="/" className="mt-6 inline-flex rounded border border-cyan-300 bg-cyan-300 px-4 py-2 text-sm font-black text-slate-950">
          Back to command center
        </a>
      </div>
    </main>
  );
}

