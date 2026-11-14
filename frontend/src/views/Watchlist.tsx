import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Rss, Plus, Search, Trash2, Edit3, Save, X, ExternalLink, RefreshCw, Loader2 } from 'lucide-react';
import { api } from '../lib/api';
import { useToast } from '../components/Toast';
import type { WatchlistItem } from '../lib/types';

const DEFAULT_CATEGORIES = ['Tech News', 'AI', 'Official', 'Aggregators', 'Research', 'Other'];

const PRESET_FEEDS = [
  { label: 'TechCrunch — Breaking News', url: 'https://techcrunch.com/feed/', category: 'Tech News' },
  { label: 'The Verge — Gadgets & Culture', url: 'https://www.theverge.com/rss/index.xml', category: 'Tech News' },
  { label: 'WIRED — Deep Tech & Science', url: 'https://www.wired.com/feed/rss', category: 'Tech News' },
  { label: 'Ars Technica', url: 'https://feeds.arstechnica.com/arstechnica/index', category: 'Tech News' },
  { label: 'Hacker News', url: 'https://news.ycombinator.com/rss', category: 'Aggregators' },
  { label: 'Techmeme', url: 'https://www.techmeme.com/feed.xml', category: 'Aggregators' },
  { label: 'MIT Technology Review — AI', url: 'https://www.technologyreview.com/topic/artificial-intelligence/feed/', category: 'AI' },
  { label: 'Apple Developer News', url: 'https://developer.apple.com/news/rss/news.rss', category: 'Official' },
  { label: 'Google AI Blog', url: 'https://blog.google/technology/ai/rss/', category: 'Official' },
  { label: 'OpenAI News', url: 'https://openai.com/news/rss.xml', category: 'AI' },
];

export default function Watchlist() {
  const navigate = useNavigate();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [newUrl, setNewUrl] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [newCategory, setNewCategory] = useState('Tech News');
  const [search, setSearch] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editData, setEditData] = useState<{ label: string; category: string; enabled: number }>({
    label: '', category: 'Tech News', enabled: 1,
  });
  const { toast } = useToast();

  const loadWatchlist = async () => {
    setLoading(true);
    try {
      const data = await api.getWatchlist();
      setItems(data.items || []);
    } catch (e: any) {
      toast('Failed to load watchlist', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadWatchlist(); }, []);

  const handleAdd = async () => {
    const url = newUrl.trim();
    if (!url) { toast('URL is required', 'error'); return; }
    try {
      const data = await api.addWatchlistItem(url, newLabel.trim() || undefined, newCategory);
      if (data.ok) {
        toast('Added to watchlist', 'success');
        setNewUrl('');
        setNewLabel('');
        setNewCategory('Tech News');
        loadWatchlist();
      } else {
        toast((data as any).error || 'Failed to add', 'error');
      }
    } catch (e: any) {
      toast(e.message || 'Failed to add feed', 'error');
    }
  };

  const handleRemove = async (url: string) => {
    try {
      const data = await api.removeWatchlistItem(url);
      if (data.ok) {
        toast('Removed from watchlist', 'success');
        setItems((prev) => prev.filter((i) => i.url !== url));
      }
    } catch {
      toast('Failed to remove', 'error');
    }
  };

  const handleToggle = async (item: WatchlistItem) => {
    try {
      await api.updateWatchlistItem(item.url, { enabled: item.enabled ? 0 : 1 });
      toast(item.enabled ? 'Disabled feed' : 'Enabled feed', 'success');
      loadWatchlist();
    } catch {
      toast('Failed to update', 'error');
    }
  };

  const startEdit = (item: WatchlistItem) => {
    setEditingId(item.id);
    setEditData({ label: item.label, category: item.category, enabled: item.enabled });
  };

  const saveEdit = async () => {
    if (editingId === null) return;
    const item = items.find((i) => i.id === editingId);
    if (!item) return;
    try {
      await api.updateWatchlistItem(item.url, editData);
      toast('Updated successfully', 'success');
      setEditingId(null);
      loadWatchlist();
    } catch {
      toast('Failed to update', 'error');
    }
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const handleAddPreset = async (feed: typeof PRESET_FEEDS[0]) => {
    try {
      const data = await api.addWatchlistItem(feed.url, feed.label, feed.category);
      if (data.ok) {
        toast(`Added ${feed.label}`, 'success');
        loadWatchlist();
      }
    } catch {
      toast('Failed to add feed', 'error');
    }
  };

  const filtered = items.filter((i) =>
    i.label.toLowerCase().includes(search.toLowerCase()) ||
    i.url.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="h-full overflow-y-auto p-8 bg-canvas animate-fade-up">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <div className="w-11 h-11 rounded-xl bg-brand-50 border border-brand-200 flex items-center justify-center">
            <Rss size={20} className="text-brand-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-ink">Source Watchlist</h1>
            <p className="text-[13px] text-sub">Add/remove RSS feeds you want to monitor for new content.</p>
          </div>
        </div>

        {/* Quick Add Section */}
        <section className="card p-5 mb-6">
          <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-3 flex items-center gap-2">
            <Plus size={14} /> Add New Feed
          </h2>
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="flex-1">
              <input
                type="url"
                placeholder="https://example.com/feed.rss"
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                className="w-full rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] text-ink placeholder-faint focus:border-brand-500 focus:outline-none"
              />
            </div>
            <div className="flex sm:flex-col md:flex-row gap-3">
              <input
                type="text"
                placeholder="Label (optional)"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                className="w-full sm:w-auto rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] text-ink placeholder-faint focus:border-brand-500 focus:outline-none"
              />
              <select
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
                className="w-full sm:w-auto rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] text-ink focus:border-brand-500 focus:outline-none cursor-pointer"
              >
                {DEFAULT_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <button
                onClick={handleAdd}
                className="flex items-center gap-2 rounded-lg bg-brand-500 text-white px-4 py-2 text-[13px] font-semibold hover:bg-brand-600 transition-colors"
              >
                <Plus size={14} /> Add Feed
              </button>
            </div>
          </div>
        </section>

        {/* Preset Feeds */}
        <section className="card p-5 mb-6">
          <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-3 flex items-center gap-2">
            Quick Add Popular Feeds
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {PRESET_FEEDS.map((f) => (
              <button
                key={f.url}
                onClick={() => handleAddPreset(f)}
                className="flex items-center justify-between rounded-lg border border-edge bg-surface px-3 py-2 text-left hover:border-brand-200 transition-colors"
              >
                <div>
                  <div className="text-[12px] font-medium text-ink">{f.label}</div>
                  <div className="text-[11px] text-sub">{f.category}</div>
                </div>
                <Plus size={12} className="text-brand-500" />
              </button>
            ))}
          </div>
        </section>

        {/* Watchlist Management */}
        <section className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-0 flex items-center gap-2">
              <RefreshCw size={14} /> Your Watchlist ({filtered.length})
            </h2>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
                <input
                  type="text"
                  placeholder="Search..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-6 pr-3 py-1.5 rounded-lg border border-edge bg-surface text-[12px] w-40 focus:border-brand-500 focus:outline-none"
                />
              </div>
              <button
                onClick={loadWatchlist}
                disabled={loading}
                className="p-1.5 rounded-lg border border-edge bg-surface hover:border-edgehover transition-colors"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              </button>
            </div>
          </div>

          {loading ? (
            <div className="text-center py-8">
              <Loader2 size={24} className="animate-spin text-brand-500 mx-auto mb-2" />
              <p className="text-[13px] text-sub">Loading watchlist...</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-[13px] text-sub">No feeds in your watchlist.</p>
              <p className="text-[12px] text-faint mt-1">Add feeds above or use the quick-add presets.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((item) => (
                <div key={item.id} className="border border-edge rounded-lg p-3 hover:border-edgehover transition-all">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      {editingId === item.id ? (
                        <div className="space-y-2">
                          <input
                            type="text"
                            value={editData.label}
                            onChange={(e) => setEditData({ ...editData, label: e.target.value })}
                            className="w-full rounded-lg border border-edge bg-surface px-2 py-1 text-[13px]"
                          />
                          <select
                            value={editData.category}
                            onChange={(e) => setEditData({ ...editData, category: e.target.value })}
                            className="w-full rounded-lg border border-edge bg-surface px-2 py-1 text-[13px] cursor-pointer"
                          >
                            {DEFAULT_CATEGORIES.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </select>
                        </div>
                      ) : (
                        <div>
                          <div className="text-[13px] font-medium text-ink">{item.label || item.url}</div>
                          <div className="text-[11px] text-sub mt-0.5">
                            <a href={item.url} target="_blank" rel="noopener noreferrer" className="hover:text-brand-600 transition-colors">
                              {item.url}
                            </a>
                            <ExternalLink size={10} className="inline ml-1" />
                          </div>
                          {item.last_checked && (
                            <div className="text-[11px] text-faint mt-1">Last checked: {item.last_checked}</div>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 ml-3">
                      {editingId === item.id ? (
                        <>
                          <button
                            onClick={saveEdit}
                            className="p-1 rounded-lg bg-brand-500 text-white hover:bg-brand-600 transition-colors"
                          >
                            <Save size={12} />
                          </button>
                          <button
                            onClick={cancelEdit}
                            className="p-1 rounded-lg border border-edge bg-surface hover:border-edgehover transition-colors"
                          >
                            <X size={12} />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => handleToggle(item)}
                            className={`p-1 rounded-lg border ${item.enabled ? 'border-green-300 bg-green-50' : 'border-edge bg-surface'} transition-colors`}
                            title={item.enabled ? 'Disable feed' : 'Enable feed'}
                          >
                            <div className={`w-2 h-2 rounded-full ${item.enabled ? 'bg-green-500' : 'bg-faint'}`} />
                          </button>
                          <button
                            onClick={() => startEdit(item)}
                            className="p-1 rounded-lg border border-edge bg-surface hover:border-edgehover transition-colors"
                          >
                            <Edit3 size={12} />
                          </button>
                          <button
                            onClick={() => handleRemove(item.url)}
                            className="p-1 rounded-lg border border-edge bg-surface hover:border-red-200 hover:text-red-600 transition-colors"
                          >
                            <Trash2 size={12} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* How It Works */}
        <section className="card p-5 mt-6">
          <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-3 flex items-center gap-2">
            How It Works
          </h2>
          <ol className="space-y-3 text-[13px] text-sub">
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-50 text-brand-700 text-[11px] font-bold flex items-center justify-center">1</span>
              Add RSS feeds you want to monitor. ContentOS checks them daily at 6:30 AM.
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-50 text-brand-700 text-[11px] font-bold flex items-center justify-center">2</span>
              Click <strong className="text-ink cursor-pointer hover:underline" onClick={() => navigate('/queue')}>Queue</strong> to see new stories queued for drafting.
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-50 text-brand-700 text-[11px] font-bold flex items-center justify-center">3</span>
              Use the feed dropdown in <strong className="text-ink cursor-pointer hover:underline" onClick={() => navigate('/')}>Discover</strong> to browse any feed in your watchlist.
            </li>
          </ol>
        </section>
      </div>
    </div>
  );
}