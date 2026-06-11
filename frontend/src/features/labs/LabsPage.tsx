"use client";

const labItems = [
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
        <div className="mt-6 flex flex-wrap gap-2">
          <a href="/ops" className="inline-flex rounded border border-cyan-300 bg-cyan-300 px-4 py-2 text-sm font-black text-slate-950">
            Command center
          </a>
          <a href="/venue-profile" className="inline-flex rounded border border-lime-300 bg-lime-300 px-4 py-2 text-sm font-black text-slate-950">
            Venue Profile
          </a>
          <a href="/experience-studio" className="inline-flex rounded border border-slate-700 bg-slate-950 px-4 py-2 text-sm font-black text-slate-100">
            Experience Studio
          </a>
        </div>
      </div>
    </main>
  );
}
