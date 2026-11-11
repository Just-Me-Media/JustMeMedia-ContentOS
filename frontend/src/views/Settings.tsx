import { Settings as SettingsIcon, Shield, Database, Moon, Globe } from 'lucide-react';

export default function Settings() {
  return (
    <div className="h-full overflow-y-auto p-8 bg-canvas animate-fade-up">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-11 h-11 rounded-xl bg-brand-50 border border-brand-200 flex items-center justify-center">
            <SettingsIcon size={20} className="text-brand-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-ink">Settings</h1>
            <p className="text-[13px] text-sub">Configure your ContentOS workspace.</p>
          </div>
        </div>

        <div className="space-y-5">
          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Shield size={14} /> Security
            </h2>
            <div className="space-y-4">
              <label className="flex items-center justify-between text-[13px] text-sub cursor-pointer">
                <span>Require human approval before any post publishes</span>
                <input type="checkbox" defaultChecked className="accent-brand-500 w-4 h-4" />
              </label>
              <label className="flex items-center justify-between text-[13px] text-sub cursor-pointer">
                <span>Localhost-only host guard (127.0.0.1)</span>
                <input type="checkbox" defaultChecked className="accent-brand-500 w-4 h-4" />
              </label>
              <label className="flex items-center justify-between text-[13px] text-sub cursor-pointer">
                <span>Enable content notifications</span>
                <input type="checkbox" className="accent-brand-500 w-4 h-4" />
              </label>
            </div>
          </section>

          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Database size={14} /> Storage
            </h2>
            <p className="text-[13px] text-sub leading-relaxed">
              Database is stored locally in your OS application-data folder. Nothing is uploaded to the cloud by default.
            </p>
          </section>

          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Moon size={14} /> Appearance
            </h2>
            <div className="flex items-center gap-3">
              <span className="text-[13px] text-sub">Theme</span>
              <div className="flex items-center gap-2">
                <span className="rounded-lg border border-brand-500 bg-brand-50 text-brand-700 px-3 py-1.5 text-[12px] font-semibold">Light</span>
                <span className="rounded-lg border border-edge bg-surface text-sub px-3 py-1.5 text-[12px] font-medium">Dark</span>
              </div>
            </div>
          </section>

          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Globe size={14} /> About
            </h2>
            <div className="text-[13px] text-sub space-y-1">
              <div className="flex justify-between"><span>Version</span><span className="font-medium text-ink">1.0.0</span></div>
              <div className="flex justify-between"><span>Engine</span><span className="font-medium text-ink">Python 3 + SQLite</span></div>
              <div className="flex justify-between"><span>Frontend</span><span className="font-medium text-ink">React + Vite + Tailwind</span></div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}