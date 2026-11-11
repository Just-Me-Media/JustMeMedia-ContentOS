import { useState } from 'react';
import { api } from '../lib/api';
import { useToast } from '../components/Toast';
import { Github, Sparkles, Loader2, ExternalLink, Download, RefreshCw } from 'lucide-react';

export default function GithubWeekly() {
  const [lang, setLang] = useState('python');
  const [platform, setPlatform] = useState('LinkedIn');
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [bundle, setBundle] = useState<{ title: string; body: string } | null>(null);
  const { toast } = useToast();

  const fetchTrending = async () => {
    setFetching(true);
    try {
      const res = await api.githubFetch(lang, 'General', 7);
      if (res.ok) {
        toast(`Fetched ${res.fetched} repos, stored ${res.stored}`, 'success');
      }
    } catch {
      toast('Fetch failed', 'error');
    } finally {
      setFetching(false);
    }
  };

  const generate = async () => {
    setLoading(true);
    try {
      const data = await api.generateGithubWeekly('General', platform);
      if (data.ok && data.title) {
        setBundle({ title: data.title, body: data.body || '' });
        toast('Weekly Top 10 post generated!', 'success');
      } else {
        toast(data.error || 'Nothing cached — run a fetch first', 'error');
      }
    } catch {
      toast('Generation failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-8 bg-canvas animate-fade-up">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-11 h-11 rounded-xl bg-raised border border-edge flex items-center justify-center">
            <Github size={24} className="text-ink" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-ink tracking-tight">
              GitHub Weekly <span className="text-brand-600">Top 10</span>
            </h1>
            <p className="text-[13px] text-sub">Fetch trending repos, then auto-generate your weekly post.</p>
          </div>
        </div>

        <div className="card p-5 mb-6">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-[11px] font-bold uppercase tracking-widest text-faint">Language</label>
              <select
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] text-ink font-medium focus:outline-none focus:border-brand-500 shadow-card"
              >
                <option value="python">🐍 Python</option>
                <option value="javascript">📜 JavaScript</option>
                <option value="rust">⚙️ Rust</option>
                <option value="">All Languages</option>
              </select>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-[11px] font-bold uppercase tracking-widest text-faint">Platform</label>
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] text-ink font-medium focus:outline-none focus:border-brand-500 shadow-card"
              >
                <option>LinkedIn</option>
                <option>X</option>
                <option>Facebook</option>
              </select>
            </div>

            <button
              onClick={fetchTrending}
              disabled={fetching}
              className="flex items-center gap-2 rounded-lg border border-edge bg-surface px-4 py-2 text-[13px] font-semibold text-ink hover:bg-raised transition-colors disabled:opacity-50"
            >
              {fetching ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Fetch Trending
            </button>

            <button
              onClick={generate}
              disabled={loading}
              className="ml-auto flex items-center gap-2 rounded-lg bg-brand-500 text-white px-5 py-2.5 text-[13px] font-bold hover:bg-brand-600 transition-colors disabled:opacity-50"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} Generate Post
            </button>
          </div>
        </div>

        {bundle ? (
          <div className="card overflow-hidden shadow-card">
            <div className="flex items-center justify-between px-5 py-4 border-b border-edge">
              <div>
                <div className="text-[15px] font-bold text-ink">{bundle.title}</div>
                <div className="text-[11px] text-faint">Formatted for {platform} · 10 repos</div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    const blob = new Blob([bundle.body], { type: 'text/markdown' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${bundle.title.replace(/\s+/g, '_')}.md`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  className="flex items-center gap-1.5 text-[12px] text-brand-600 hover:text-brand-700 font-medium"
                >
                  <Download size={12} /> Export .md
                </button>
                <a
                  href="/studio"
                  className="flex items-center gap-1.5 text-[12px] text-brand-600 hover:text-brand-700 font-medium"
                >
                  Open in Studio <ExternalLink size={12} />
                </a>
              </div>
            </div>
            <pre className="p-5 text-[12px] leading-relaxed text-sub whitespace-pre-wrap font-mono max-h-[480px] overflow-y-auto">
              {bundle.body}
            </pre>
          </div>
        ) : (
          <div className="card p-16 text-center border-dashed">
            <Github size={40} className="text-faint mx-auto mb-3" />
            <h3 className="text-ink font-semibold text-base">Ready to generate</h3>
            <p className="text-[13px] text-sub mt-1 max-w-sm mx-auto">
              Pick a language and platform, hit Fetch Trending, then Generate. The post will be drafted with star counts and links.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}