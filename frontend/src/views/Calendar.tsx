import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { Draft } from '../lib/types';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

export default function Calendar() {
  const [view, setView] = useState(new Date());
  const [drafts, setDrafts] = useState<Draft[]>([]);

  useEffect(() => { api.getDrafts().then(setDrafts).catch(() => {}); }, []);

  const year = view.getFullYear(), month = view.getMonth();
  const first = new Date(year, month, 1);
  const startDow = first.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayStr = new Date().toDateString();

  const scheduled = drafts.filter((d) => d.scheduled_for);
  // Deduplicate by source_url (or title+platform fallback) — keep the most recent
  const deduped = scheduled.reduce((acc, d) => {
    const key = d.source_url || `${d.title}||${d.platform}`;
    const existing = acc.get(key);
    if (!existing || d.id > existing.id) acc.set(key, d);
    return acc;
  }, new Map<string, Draft>()).values();
  const postsOn = (y: number, m: number, d: number) =>
    Array.from(deduped).filter((p) => {
      if (!p.scheduled_for) return false;
      const [date] = p.scheduled_for.split(' ');
      const [py, pm, pd] = date.split('-').map(Number);
      return py === y && pm === m + 1 && pd === d;
    });

  const cells: Array<{ day: number | null; today: boolean; posts: Draft[] }> = [];
  for (let i = 0; i < startDow; i++) cells.push({ day: null, today: false, posts: [] });
  for (let d = 1; d <= daysInMonth; d++) {
    const dt = new Date(year, month, d);
    cells.push({ day: d, today: dt.toDateString() === todayStr, posts: postsOn(year, month, d) });
  }

  return (
    <div className="h-full overflow-y-auto p-8 bg-canvas animate-fade-up">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-brand-50 border border-brand-200 flex items-center justify-center">
              <CalendarDays size={20} className="text-brand-600" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-ink">{MONTHS[month]} {year}</h1>
              <p className="text-[12px] text-sub">{scheduled.length} scheduled posts queued</p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setView(new Date(year, month - 1, 1))}
              className="p-2 rounded-lg border border-edge bg-surface text-sub hover:text-ink hover:bg-raised transition-colors shadow-card"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => setView(new Date())}
              className="px-3.5 py-2 rounded-lg border border-edge bg-surface text-[12px] font-semibold text-sub hover:text-ink hover:bg-raised transition-colors shadow-card"
            >
              Today
            </button>
            <button
              onClick={() => setView(new Date(year, month + 1, 1))}
              className="p-2 rounded-lg border border-edge bg-surface text-sub hover:text-ink hover:bg-raised transition-colors shadow-card"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-7 gap-2 mb-2 text-center text-[10px] font-bold text-faint uppercase tracking-widest">
          {['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map((d) => <div key={d} className="py-2">{d}</div>)}
        </div>

        <div className="grid grid-cols-7 gap-2">
          {cells.map((cell, i) => (
            <div
              key={i}
              className={`min-h-[110px] rounded-xl border p-2.5 transition-all ${
                cell.day === null
                  ? 'border-transparent'
                  : cell.today
                  ? 'border-brand-500 bg-brand-50/50 shadow-glow'
                  : 'border-edge bg-surface hover:border-edgehover shadow-card'
              }`}
            >
              {cell.day !== null && (
                <>
                  <div className={`text-[12px] font-bold mb-1.5 ${cell.today ? 'text-brand-600' : 'text-sub'}`}>
                    {cell.day}
                  </div>
                  <div className="space-y-1">
                    {cell.posts.map((p) => (
                      <div
                        key={p.id}
                        className="text-[10px] font-semibold rounded-md px-2 py-1 bg-brand-50 text-brand-700 border border-brand-200 truncate"
                        title={p.title}
                      >
                        {p.title.slice(0, 24)}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          ))}
        </div>

        <div className="mt-6 flex items-center gap-5 text-[12px] text-sub">
          <span className="flex items-center gap-2">
            <span className="w-3 h-3 rounded bg-brand-50 border border-brand-300" /> Scheduled Post
          </span>
          <span className="flex items-center gap-2">
            <span className="w-3 h-3 rounded border-2 border-brand-500 bg-brand-50" /> Today
          </span>
        </div>
      </div>
    </div>
  );
}