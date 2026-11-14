import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import type { Draft } from '../lib/types';
import { useToast } from '../components/Toast';
import { Search, CheckSquare, Square, CheckCircle2, Trash2, CalendarClock, Inbox, Clock, Check, Download, Edit3, Loader2, Copy, ExternalLink } from 'lucide-react';

// Where to send the user to compose a post on each platform (manual posting)
const PLATFORM_COMPOSE: Record<string, { label: string; url: string; prefills?: boolean }> = {
  X:         { label: 'X / Twitter', url: 'https://x.com/intent/post?text=', prefills: true },
  LinkedIn:  { label: 'LinkedIn',    url: 'https://www.linkedin.com/feed/?shareActive=true' },
  Facebook:  { label: 'Facebook',    url: 'https://www.facebook.com/' },
  Instagram: { label: 'Instagram',   url: 'https://www.instagram.com/' },
  YouTube:   { label: 'YouTube',     url: 'https://studio.youtube.com/' },
  GitHub:    { label: 'GitHub',      url: 'https://github.com/' },
  General:   { label: 'Platform',    url: '' },
};

function composeUrl(platform: string, body: string): string {
  const target = PLATFORM_COMPOSE[platform] || PLATFORM_COMPOSE.General;
  if (!target.url) return '';
  if (target.prefills) return target.url + encodeURIComponent((body || '').slice(0, 280));
  return target.url;
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for older browsers / non-secure contexts
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

export default function Queue() {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'active' | 'published'>('active');
  const [schedulingId, setSchedulingId] = useState<number | null>(null);
  const [scheduleDate, setScheduleDate] = useState('');
  const [publishingId, setPublishingId] = useState<number | null>(null);
  const { toast } = useToast();

  const handleExport = (id: number) => {
    window.open(`/api/export-markdown?id=${id}`, '_blank');
    toast('Exporting markdown…', 'info');
  };

  const handleExportAll = async () => {
    try {
      await api.exportAllMarkdown();
      toast('Exported all drafts to markdown', 'success');
    } catch {
      toast('Export failed', 'error');
    }
  };

  const load = () => {
    setLoading(true);
    api.getDrafts().then((d) => setDrafts(d)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const filtered = drafts.filter((d) => {
    if (tab === 'active' && d.status === 'Published') return false;
    if (tab === 'published' && d.status !== 'Published') return false;
    if (query && !(d.title + ' ' + d.body).toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });
  // Deduplicate by source_url (or title+platform fallback) — keep the most recent
  const deduped = filtered.reduce((acc, d) => {
    const key = d.source_url || `${d.title}||${d.platform}`;
    const existing = acc.get(key);
    if (!existing || d.id > existing.id) acc.set(key, d);
    return acc;
  }, new Map<string, Draft>()).values();

  const toggle = (id: number) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };

  const bulkApprove = async () => {
    const ids = [...selected];
    if (!ids.length) { toast('Select drafts first', 'info'); return; }
    await api.bulkApprove(ids);
    toast(`Approved ${ids.length} posts`, 'success');
    setSelected(new Set()); load();
  };
  const handleSchedule = async (id: number) => {
    if (!scheduleDate) { toast('Pick a date/time first', 'error'); return; }
    try {
      await api.scheduleDraft(id, scheduleDate);
      toast(`Scheduled for ${scheduleDate}`, 'success');
      setSchedulingId(null);
      load();
    } catch {
      toast('Failed to schedule', 'error');
    }
  };

  const handlePublish = async (id: number) => {
    setPublishingId(id);
    try {
      const res = await api.publishDraft(id);
      if (res.ok) {
        toast('Published successfully!', 'success');
        load();
      } else {
        toast(res.error || 'Publish failed', 'error');
      }
    } catch (e: any) {
      toast(e?.message || 'Publish failed', 'error');
    } finally {
      setPublishingId(null);
    }
  };

  const handleMarkPublished = async (id: number) => {
    try {
      await api.markPublished(id);
      toast('Marked as published', 'success');
      load();
    } catch {
      toast('Failed to mark as published', 'error');
    }
  };
  const bulkDelete = async () => {
    const ids = [...selected];
    if (!ids.length) { toast('Select drafts first', 'info'); return; }
    await api.bulkDelete(ids);
    toast(`Deleted ${ids.length} posts`, 'success');
    setSelected(new Set()); load();
  };

  return (
    <div className="flex flex-col h-full bg-canvas animate-fade-up">
      {/* Top Header */}
      <div className="flex h-16 items-center justify-between px-8 border-b border-edge bg-surface">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-brand-600">
          <Inbox size={13} /> Review Queue
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={bulkApprove}
            className="flex items-center gap-1.5 rounded-lg border border-emerald-300 bg-emerald-50 text-emerald-700 px-3 py-1.5 text-[12px] font-semibold hover:bg-emerald-100 transition-colors"
          >
            <CheckCircle2 size={13} /> Approve Selected
          </button>
          <button
            onClick={bulkDelete}
            className="flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 text-red-600 px-3 py-1.5 text-[12px] font-semibold hover:bg-red-100 transition-colors"
          >
            <Trash2 size={13} /> Delete
          </button>
        </div>
      </div>

      {/* Tabs & Search Toolbar */}
      <div className="flex items-center gap-3 px-8 py-3 border-b border-edge bg-raised">
        <button
          onClick={() => setTab('active')}
          className={`rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${
            tab === 'active' ? 'bg-surface text-brand-700 shadow-sm border border-edge' : 'text-sub hover:text-ink'
          }`}
        >
          Active Queue ({drafts.filter((d) => d.status !== 'Published').length})
        </button>
        <button
          onClick={() => setTab('published')}
          className={`rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${
            tab === 'published' ? 'bg-surface text-brand-700 shadow-sm border border-edge' : 'text-sub hover:text-ink'
          }`}
        >
          Published ({drafts.filter((d) => d.status === 'Published').length})
        </button>

        <div className="relative flex-1 max-w-sm ml-auto">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter queue by headline or content…"
            className="w-full rounded-lg border border-edge bg-surface pl-9 pr-3 py-1.5 text-[13px] text-ink placeholder-faint focus:outline-none focus:border-brand-500 shadow-card"
          />
        </div>

        <button
          onClick={handleExportAll}
          className="flex items-center gap-1.5 rounded-lg border border-edge bg-surface text-sub px-3 py-1.5 text-[12px] font-semibold hover:text-ink hover:bg-raised transition-colors"
        >
          <Download size={13} /> Export All
        </button>
      </div>

      {/* Queue items */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="space-y-3 max-w-4xl mx-auto">
          {Array.from(deduped).map((d) => (
            <div key={d.id} className="card p-5 flex gap-4 hover:border-edgehover transition-all">
              <button onClick={() => toggle(d.id)} className="mt-0.5 text-faint hover:text-brand-600">
                {selected.has(d.id) ? (
                  <CheckSquare size={19} className="text-brand-500" />
                ) : (
                  <Square size={19} />
                )}
              </button>

              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-[15px] font-semibold text-ink leading-snug">{d.title}</h3>
                  <span
                    className={`flex-shrink-0 text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full border ${
                      d.status === 'Published'
                        ? 'border-blue-200 text-blue-700 bg-blue-50'
                        : d.status === 'Approved'
                        ? 'border-emerald-200 text-emerald-700 bg-emerald-50'
                        : 'border-edge text-sub bg-raised'
                    }`}
                  >
                    {d.status}
                  </span>
                </div>

                <p className="text-[13px] text-sub mt-2 line-clamp-2 leading-relaxed">{d.body}</p>

                <div className="flex items-center gap-3 mt-3 text-[11px] text-faint">
                  <span className="font-semibold text-sub">{d.platform}</span>
                  {d.tags && <span>· {d.tags}</span>}
                  {d.scheduled_for && (
                    <span className="flex items-center gap-1 text-brand-600 font-medium">
                      <CalendarClock size={12} /> {d.scheduled_for}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex flex-col gap-2">
                {schedulingId === d.id ? (
                  <div className="flex flex-col gap-2 p-2 rounded-lg bg-raised border border-brand-200">
                    <input
                      type="datetime-local"
                      value={scheduleDate}
                      onChange={(e) => setScheduleDate(e.target.value)}
                      className="rounded-lg border border-edge bg-surface px-2 py-1.5 text-[12px] text-ink focus:outline-none focus:border-brand-500"
                    />
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleSchedule(d.id)}
                        className="flex-1 rounded-md bg-brand-500 text-white px-2 py-1 text-[11px] font-semibold hover:bg-brand-600"
                      >
                        <Check size={11} /> Schedule
                      </button>
                      <button
                        onClick={() => { setSchedulingId(null); setScheduleDate(''); }}
                        className="rounded-md border border-edge bg-surface px-2 py-1 text-[11px] text-sub hover:text-ink"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    {d.status !== 'Approved' && d.status !== 'Published' && (
                      <button
                        onClick={() => api.approveDraft(d.id).then(load)}
                        title="Approve post"
                        className="rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 p-2 hover:bg-emerald-100 transition-colors"
                      >
                        <CheckCircle2 size={16} />
                      </button>
                    )}
                    <button
                      onClick={() => { setSchedulingId(d.id); setScheduleDate(''); }}
                      title="Schedule post"
                      className="rounded-lg border border-edge bg-surface text-sub p-2 hover:text-brand-600 hover:border-brand-200 transition-colors"
                    >
                      <CalendarClock size={16} />
                    </button>
                  </>
                )}

                {/* ── Manual post helpers (no API needed) ── */}
                <button
                  onClick={async () => {
                    const ok = await copyToClipboard(d.body || '');
                    toast(ok ? 'Copied to clipboard — paste into your platform' : 'Copy failed — select text manually', ok ? 'success' : 'error');
                  }}
                  title="Copy post text to clipboard"
                  className="rounded-lg border border-edge bg-surface text-sub p-2 hover:text-brand-600 hover:border-brand-200 transition-colors"
                >
                  <Copy size={16} />
                </button>
                {composeUrl(d.platform, d.body) && (
                  <a
                    href={composeUrl(d.platform, d.body)}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Open compose window on platform"
                    className="rounded-lg border border-edge bg-surface text-sub p-2 hover:text-brand-600 hover:border-brand-200 transition-colors flex items-center justify-center"
                  >
                    <ExternalLink size={16} />
                  </a>
                )}

                <button
                  onClick={() => handlePublish(d.id)}
                  disabled={publishingId === d.id}
                  title="Publish now (requires platform credentials)"
                  className="rounded-lg border border-edge bg-surface text-sub p-2 hover:text-ink hover:bg-raised transition-colors disabled:opacity-50"
                >
                  {publishingId === d.id ? <Loader2 size={16} className="animate-spin" /> : <Clock size={16} />}
                </button>
                {d.status !== 'Published' && (
                  <button
                    onClick={() => handleMarkPublished(d.id)}
                    title="Mark as published (manual post)"
                    className="rounded-lg border border-dashed border-edge bg-surface text-faint p-2 hover:text-brand-600 hover:border-brand-200 transition-colors text-[10px] font-semibold"
                  >
                    ✓
                  </button>
                )}
                <button
                  onClick={() => navigate('/', { state: { editId: d.id } })}
                  title="Edit draft"
                  className="rounded-lg border border-edge bg-surface text-sub p-2 hover:text-brand-600 hover:border-brand-200 transition-colors"
                >
                  <Edit3 size={16} />
                </button>
                <button
                  onClick={() => handleExport(d.id)}
                  title="Export as Markdown"
                  className="rounded-lg border border-edge bg-surface text-sub p-2 hover:text-brand-600 hover:border-brand-200 transition-colors"
                >
                  <Download size={16} />
                </button>
              </div>
            </div>
          ))}

          {!loading && filtered.length === 0 && (
            <div className="card p-12 text-center">
              <Inbox size={36} className="text-faint mx-auto mb-3" />
              <h3 className="text-ink font-semibold text-base">Your queue is clear</h3>
              <p className="text-[13px] text-sub mt-1">Generate content in the Studio or discover stories from RSS feeds.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}