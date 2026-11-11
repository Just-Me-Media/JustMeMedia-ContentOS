import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import type { SourceItem } from '../lib/types';
import { useToast } from '../components/Toast';
import {
  Rss, Filter, Sparkles, X, ExternalLink, ChevronDown, Loader2, Plus, Zap,
} from 'lucide-react';

const FEEDS = [
  { label: 'TechCrunch — Breaking News', url: 'https://techcrunch.com/feed/', group: 'Tech News' },
  { label: 'The Verge — Gadgets & Culture', url: 'https://www.theverge.com/rss/index.xml', group: 'Tech News' },
  { label: 'WIRED — Deep Tech & Science', url: 'https://www.wired.com/feed/rss', group: 'Tech News' },
  { label: 'Ars Technica', url: 'https://feeds.arstechnica.com/arstechnica/index', group: 'Tech News' },
  { label: 'Hacker News', url: 'https://news.ycombinator.com/rss', group: 'Aggregators' },
  { label: 'Techmeme', url: 'https://www.techmeme.com/feed.xml', group: 'Aggregators' },
  { label: 'MIT Technology Review', url: 'https://www.technologyreview.com/topic/artificial-intelligence/feed/', group: 'AI' },
  { label: 'Apple Developer News', url: 'https://developer.apple.com/news/rss/news.rss', group: 'Official' },
  { label: 'Google AI Blog', url: 'https://blog.google/technology/ai/rss/', group: 'Official' },
  { label: 'OpenAI News', url: 'https://openai.com/news/rss.xml', group: 'AI Labs' },
];

const PLATFORMS = ['LinkedIn', 'X', 'YouTube', 'Facebook', 'Instagram', 'General'];

export default function Discover() {
  const [feedUrl, setFeedUrl] = useState(FEEDS[0].url);
  const [stories, setStories] = useState<SourceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState('');
  const [platform, setPlatform] = useState('LinkedIn');
  const [creatingUrl, setCreatingUrl] = useState<string | null>(null);
  const [runningAutopilot, setRunningAutopilot] = useState(false);
  const { toast } = useToast();

  const runAutopilot = async () => {
    setRunningAutopilot(true);
    try {
      const res = await api.autopilot(feedUrl, 'ollama:llama3.2');
      if (res.ok) {
        toast(`Autopilot drafted ${res.count} stories to your queue!`, 'success');
      } else {
        toast(res.error || 'Autopilot failed', 'error');
      }
    } catch {
      toast('Autopilot failed', 'error');
    } finally {
      setRunningAutopilot(false);
    }
  };

  const loadFeed = (url: string) => {
    setLoading(true);
    api.getSources(url)
      .then((data) => setStories(data))
      .catch(() => toast('Failed to load feed', 'error'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadFeed(feedUrl); }, [feedUrl]);

  const filtered = useMemo(() => {
    return stories.filter((s) => {
      if (query) {
        const q = query.toLowerCase();
        if (!s.title.toLowerCase().includes(q) && !s.snippet.toLowerCase().includes(q)) return false;
      }
      if (topic && !new RegExp(topic, 'i').test(s.title + ' ' + s.snippet)) return false;
      return true;
    }).slice(0, 40);
  }, [stories, query, topic]);

  const reject = (item: SourceItem) => {
    api.rejectSource(item.url, item.title).then(() => {
      setStories((prev) => prev.filter((s) => s.url !== item.url));
      toast('Story hidden from feed', 'success');
    }).catch(() => toast('Failed to reject', 'error'));
  };

  const createDraftFromStory = async (story: SourceItem) => {
    setCreatingUrl(story.url);
    try {
      const res = await api.oneClickDraft({
        title: story.title,
        url: story.url,
        snippet: story.snippet,
        platform,
        tone: 'thought_leadership',
        provider: 'ollama:llama3.2:3b',
      });
      if (res.ok) {
        toast(`Draft created for ${platform}!`, 'success');
        setStories((prev) => prev.filter((s) => s.url !== story.url));
      } else {
        toast(res.error || 'Failed to create draft', 'error');
      }
    } catch (e: any) {
      toast(e.message || 'Failed to create draft — check server logs', 'error');
    } finally {
      setCreatingUrl(null);
    }
  };

  const topics = [
    { label: 'All', value: '' },
    { label: 'AI', value: 'AI|LLM|agent' },
    { label: 'Apple', value: 'Apple|iOS|Mac' },
    { label: 'Google', value: 'Google|Gemini|Android' },
    { label: 'OpenAI', value: 'OpenAI|GPT' },
  ];

  return (
    <div className="flex h-full bg-canvas animate-fade-up">
      {/* Left: feed controls */}
      <div className="w-[360px] flex-shrink-0 border-r border-edge bg-raised flex flex-col">
        <div className="p-5 border-b border-edge">
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-brand-600 mb-3">
            <Rss size={13} /> Discovery Feed
          </div>

          <div className="relative">
            <select
              value={feedUrl}
              onChange={(e) => setFeedUrl(e.target.value)}
              className="w-full appearance-none rounded-lg border border-edge bg-surface px-3 py-2.5 pr-9 text-[13px] text-ink font-medium focus:border-brand-500 focus:outline-none cursor-pointer shadow-card"
            >
              {['Tech News', 'Aggregators', 'AI', 'AI Labs', 'Official'].map((group) => (
                <optgroup key={group} label={group}>
                  {FEEDS.filter((f) => f.group === group).map((f) => (
                    <option key={f.url} value={f.url}>{f.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            <ChevronDown size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-faint pointer-events-none" />
          </div>

          <div className="relative mt-3">
            <Filter size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search feed stories..."
              className="w-full rounded-lg border border-edge bg-surface pl-9 pr-3 py-2 text-[13px] text-ink placeholder-faint focus:border-brand-500 focus:outline-none shadow-card"
            />
          </div>

          <div className="flex flex-wrap gap-1.5 mt-3">
            {topics.map((t) => (
              <button
                key={t.label}
                onClick={() => setTopic(t.value)}
                className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  topic === t.value
                    ? 'border-brand-300 bg-brand-50 text-brand-700'
                    : 'border-edge bg-surface text-sub hover:border-edgehover'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Stories list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <div className="flex items-center justify-between px-1 mb-1">
            <span className="text-[10px] font-bold uppercase tracking-widest text-faint">{filtered.length} Stories</span>
            {loading && <Loader2 size={13} className="animate-spin text-brand-500" />}
          </div>

          {filtered.map((item) => (
            <div key={item.url} className="card p-3.5 hover:border-edgehover transition-all">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[13px] font-semibold text-ink leading-snug line-clamp-2 hover:text-brand-600 transition-colors"
              >
                {item.title}
              </a>
              <p className="text-[11px] text-sub mt-1.5 line-clamp-2 leading-relaxed">{item.snippet}</p>

              <div className="flex items-center justify-between mt-3 pt-2 border-t border-edge">
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => reject(item)}
                    className="flex items-center gap-1 rounded-md border border-edge bg-surface px-2 py-1 text-[10px] text-sub hover:text-red-600 hover:border-red-200 transition-colors"
                  >
                    <X size={11} /> Hide
                  </button>
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 rounded-md border border-edge bg-surface px-2 py-1 text-[10px] text-sub hover:text-ink transition-colors"
                  >
                    <ExternalLink size={11} /> Read
                  </a>
                </div>

                <button
                  onClick={() => createDraftFromStory(item)}
                  disabled={creatingUrl === item.url}
                  className="flex items-center gap-1 rounded-md bg-brand-500 text-white px-2.5 py-1 text-[11px] font-semibold hover:bg-brand-600 transition-colors disabled:opacity-50"
                >
                  {creatingUrl === item.url ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />} Create
                </button>
              </div>
            </div>
          ))}

          {!loading && filtered.length === 0 && (
            <div className="text-center py-12">
              <p className="text-[13px] text-sub">No stories match your filter.</p>
            </div>
          )}
        </div>
      </div>

      {/* Right side: overview + target platform selector */}
      <div className="flex-1 min-w-0 overflow-y-auto p-8 bg-canvas">
        <div className="max-w-2xl mx-auto">
          <div className="mb-6">
            <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-brand-600 mb-2">
              <Sparkles size={13} /> Discovery Engine
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-ink">Turn news into content</h1>
            <p className="text-sub text-sm mt-1">Pick your target platform, browse the feed, and click Create on any story.</p>
          </div>

          {/* Platform selector */}
          <div className="card p-5 mb-6">
            <label className="text-[11px] font-bold uppercase tracking-widest text-faint mb-2 block">
              Default Target Platform for 1-Click Drafts
            </label>
            <div className="flex flex-wrap gap-2">
              {PLATFORMS.map((p) => (
                <button
                  key={p}
                  onClick={() => setPlatform(p)}
                  className={`rounded-lg border px-3.5 py-2 text-[13px] font-semibold transition-all ${
                    platform === p
                      ? 'border-brand-500 bg-brand-50 text-brand-700 shadow-sm'
                      : 'border-edge bg-surface text-sub hover:border-edgehover'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Autopilot Card */}
          <div className="card p-6 border-brand-200 bg-brand-50/40">
            <h2 className="text-sm font-bold text-ink mb-2 flex items-center gap-2">
              <Zap size={16} className="text-brand-600" /> Autopilot Batch Engine
            </h2>
            <p className="text-[13px] text-sub mb-4 leading-relaxed">
              Run the Roundtable engine on the top 3 headlines from the selected feed — scrapes, analyzes, drafts, and queues them automatically.
            </p>
            <button
              onClick={runAutopilot}
              disabled={runningAutopilot}
              className="flex items-center gap-2 rounded-lg bg-brand-500 text-white px-4 py-2.5 text-[13px] font-bold hover:bg-brand-600 transition-colors shadow-sm disabled:opacity-50"
            >
              {runningAutopilot ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} Run Autopilot on Top 3
            </button>
          </div>
          <div className="card p-6">
            <h2 className="text-sm font-bold text-ink mb-3">How Discovery works</h2>
            <ol className="space-y-3 text-[13px] text-sub">
              <li className="flex gap-3">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-50 text-brand-700 text-[11px] font-bold flex items-center justify-center">1</span>
                Select RSS sources from the left dropdown (TechCrunch, Wired, Hacker News, OpenAI, etc.).
              </li>
              <li className="flex gap-3">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-50 text-brand-700 text-[11px] font-bold flex items-center justify-center">2</span>
                Hit <strong className="text-ink">Hide</strong> on stories you don't care about — ContentOS remembers and filters them out automatically.
              </li>
              <li className="flex gap-3">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-50 text-brand-700 text-[11px] font-bold flex items-center justify-center">3</span>
                Click <strong className="text-ink">Create</strong> to draft a custom post directly in your Review Queue.
              </li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}