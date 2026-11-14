import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import type { DashboardStats, Draft } from '../lib/types';
import { TrendingUp, FileText, CheckCircle2, Zap, ArrowRight, Flame, Rss } from 'lucide-react';
import Studio from './Studio';

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    api.getDashboardStats().then(setStats).catch(() => {});
    api.getDrafts().then(setDrafts).catch(() => {});
  }, []);

  const s = stats;
  const activeDrafts = drafts.filter((d) => d.status !== 'Published');

  const cards = [
    { label: 'Total Drafts', value: s?.total ?? 0, icon: FileText, color: 'text-ink', navigate: '/queue' },
    { label: 'Active Queue', value: s?.active ?? 0, icon: Zap, color: 'text-brand-600', navigate: '/queue' },
    { label: 'Published', value: s?.published ?? 0, icon: CheckCircle2, color: 'text-emerald-600', navigate: '/queue' },
    { label: 'This Week', value: s?.recent_7days ?? 0, icon: TrendingUp, color: 'text-violet-600', navigate: '/queue' },
  ];

  return (
    <div className="h-full overflow-y-auto p-8 bg-canvas animate-fade-up">
      <div className="max-w-6xl mx-auto">
        <div className="mb-6">
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-brand-600 mb-2">
            <Flame size={13} /> Command Center
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-ink">Good Morning, Creator 👋</h1>
          <p className="text-sub mt-1">Generate → Review → Publish. All in one place.</p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          {cards.map(({ label, value, icon: Icon, color, navigate: nav }) => (
            <button
              key={label}
              onClick={() => navigate(nav)}
              className="card p-4 hover:border-brand-300 hover:bg-brand-50/50 transition-all text-left group"
            >
              <Icon size={18} className={color} strokeWidth={1.8} />
              <div className="mt-3 text-2xl font-bold text-ink group-hover:text-brand-700 transition-colors">{value}</div>
              <div className="text-[11px] text-faint mt-0.5">{label}</div>
            </button>
          ))}
        </div>

        <div className="grid lg:grid-cols-3 gap-4">
          <div className="card p-5">
            <h2 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
              <Zap size={16} className="text-brand-500" /> Quick Actions
            </h2>
            <div className="space-y-2">
              <button
                onClick={() => navigate('/queue')}
                className="w-full flex items-center justify-between rounded-lg border border-edge bg-surface px-4 py-3 text-left hover:border-brand-300 hover:bg-raised transition-all group"
              >
                <span className="flex items-center gap-2 text-[13px] text-ink font-medium">
                  <CheckCircle2 size={15} className="text-emerald-500" /> Review queue ({activeDrafts.length})
                </span>
                <ArrowRight size={15} className="text-faint group-hover:text-brand-500 transition-colors" />
              </button>
              <button
                onClick={() => navigate('/discover')}
                className="w-full flex items-center justify-between rounded-lg border border-edge bg-surface px-4 py-3 text-left hover:border-brand-300 hover:bg-raised transition-all group"
              >
                <span className="flex items-center gap-2 text-[13px] text-ink font-medium">
                  <Rss size={15} className="text-brand-500" /> Discover stories
                </span>
                <ArrowRight size={15} className="text-faint group-hover:text-brand-500 transition-colors" />
              </button>
            </div>
          </div>

          <div className="card p-5">
            <h2 className="text-sm font-bold text-ink mb-4">Platform Split</h2>
            {s?.platform_breakdown && Object.keys(s.platform_breakdown).length > 0 ? (
              <div className="space-y-3">
                {Object.entries(s.platform_breakdown).sort((a, b) => b[1] - a[1]).map(([platform, count]) => {
                  const max = Math.max(...Object.values(s.platform_breakdown));
                  const widthPct = (count / max) * 100;
                  return (
                    <div key={platform}>
                      <div className="flex justify-between text-[12px] text-sub mb-1">
                        <span>{platform}</span>
                        <span className="font-semibold">{count}</span>
                      </div>
                      <div className="h-2 rounded-full bg-raised overflow-hidden">
                        <div className="h-full bg-brand-500 rounded-full" style={{ width: `${widthPct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-[13px] text-sub">No active drafts yet.</p>
            )}
          </div>

          <div className="card p-5">
            <h2 className="text-sm font-bold text-ink mb-4">Top Tags</h2>
            {s?.tag_counts && Object.keys(s.tag_counts).length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {Object.entries(s.tag_counts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([tag, count]) => (
                  <span key={tag} className="rounded-full border border-edge bg-raised px-3 py-1 text-[11px] text-sub font-medium">
                    {tag} <span className="text-brand-600 font-bold">{count}</span>
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-[13px] text-sub">No tags yet.</p>
            )}
          </div>
        </div>

        <div className="mt-6">
          <Studio embedded />
        </div>
      </div>
    </div>
  );
}