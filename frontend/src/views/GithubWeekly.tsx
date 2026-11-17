import { useState } from 'react';
import { api } from '../lib/api';
import { useToast } from '../components/Toast';
import { Github, Sparkles, Loader2, ExternalLink, Download, RefreshCw, Star, ArrowRight, AlertTriangle } from 'lucide-react';

interface Repo {
  full_name: string;
  url: string;
  description: string;
  stars: number;
  language: string;
  fetched_at?: string;
  sample?: boolean;
}

export default function GithubWeekly() {
  const [lang, setLang] = useState('python');
  const [platform, setPlatform] = useState('LinkedIn');
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [bundle, setBundle] = useState<{ title: string; body: string } | null>(null);
  const [usingSample, setUsingSample] = useState(false);
  const { toast } = useToast();

  const fetchTrending = async () => {
    setFetching(true);
    setBundle(null);
    try {
      const res = await api.getGithubTrending(lang);
      if (res.ok && res.repos) {
        setRepos(res.repos);
        setUsingSample(Boolean(res.sample));
        if (res.sample) {
          toast('GitHub API unavailable — showing sample data. Do not publish these numbers.', 'error');
        } else {
          toast(`Fetched top ${res.repos.length} live trending repos!`, 'success');
        }
      } else {
        toast('Failed to fetch trending repos', 'error');
      }
    } catch {
      toast('Fetch failed — check network', 'error');
    } finally {
      setFetching(false);
    }
  };

  const generate = async () => {
    if (usingSample) {
      toast('Cannot generate a post from sample data — fetch live repos first.', 'error');
      return;
    }
    setLoading(true);
    try {
      const data = await api.generateGithubWeekly('General', platform);
      setUsingSample(Boolean(data.sample));
      if (data.ok && data.title) {
        setBundle({ title: data.title, body: data.body || '' });
        if (data.sample) {
          toast('Generated from sample data — review star counts before publishing!', 'error');
        } else {
          toast('Weekly Top 10 post generated!', 'success');
        }
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
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-11 h-11 rounded-xl bg-raised border border-edge flex items-center justify-center">
            <Github size={24} className="text-ink" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-ink tracking-tight">
              GitHub Weekly <span className="text-brand-600">Top 10</span>
            </h1>
            <p className="text-[13px] text-sub">Fetch trending repos, view findings immediately, and generate your weekly summary post.</p>
          </div>
        </div>

        {/* Sample-data warning: never let fabricated star counts be published unnoticed */}
        {usingSample && (
          <div className="card p-4 mb-6 border-amber-300 bg-amber-50">
            <div className="flex items-start gap-3">
              <AlertTriangle size={18} className="text-amber-600 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-[13px] font-bold text-amber-800">Sample data — GitHub API unavailable</div>
                <p className="text-[12px] text-amber-700 mt-1">
                  These repositories and star counts are illustrative placeholders, not live data.
                  Check your network connection and fetch again before publishing a post.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Controls */}
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
              {fetching ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Fetch Trending Repos
            </button>

            {repos.length > 0 && (
              <button
                onClick={generate}
                disabled={loading}
                className="ml-auto flex items-center gap-2 rounded-lg bg-brand-500 text-white px-5 py-2.5 text-[13px] font-bold hover:bg-brand-600 transition-colors shadow-sm disabled:opacity-50"
              >
                {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} Generate {platform} Post
              </button>
            )}
          </div>
        </div>

        {/* Repos list preview directly after fetch */}
        {repos.length > 0 && !bundle && (
          <div className="space-y-4 mb-6">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-ink uppercase tracking-wider">Top {repos.length} Trending Repositories ({lang || 'All'})</h2>
              <button
                onClick={generate}
                disabled={loading}
                className="flex items-center gap-1.5 text-[12px] font-bold text-brand-600 hover:text-brand-700"
              >
                Compile into Post <ArrowRight size={14} />
              </button>
            </div>
            <div className="grid gap-3">
              {repos.map((r, idx) => (
                <div key={r.url} className="card p-4 flex items-start justify-between gap-4 hover:border-brand-300 transition-all">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] font-bold text-brand-600 w-5">#{idx + 1}</span>
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[14px] font-bold text-ink hover:text-brand-600 truncate flex items-center gap-1"
                      >
                        {r.full_name} <ExternalLink size={12} className="text-faint" />
                      </a>
                      {r.language && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-raised text-sub border border-edge">
                          {r.language}
                        </span>
                      )}
                    </div>
                    <p className="text-[12px] text-sub mt-1 line-clamp-2">{r.description || 'No description provided.'}</p>
                  </div>
                  <div className="flex items-center gap-1 text-[12px] font-bold text-amber-600 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg">
                    <Star size={13} fill="currentColor" /> {r.stars.toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Generated post bundle */}
        {bundle && (
          <div className="card overflow-hidden shadow-card">
            <div className="flex items-center justify-between px-5 py-4 border-b border-edge">
              <div>
                <div className="text-[15px] font-bold text-ink">{bundle.title}</div>
                <div className="text-[11px] text-faint">Formatted for {platform} · {repos.length} repos</div>
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
              </div>
            </div>
            <pre className="p-5 text-[12px] leading-relaxed text-sub whitespace-pre-wrap font-mono max-h-[480px] overflow-y-auto">
              {bundle.body}
            </pre>
          </div>
        )}

        {/* Empty State */}
        {repos.length === 0 && !bundle && (
          <div className="card p-16 text-center border-dashed">
            <Github size={40} className="text-faint mx-auto mb-3" />
            <h3 className="text-ink font-semibold text-base">Ready to discover trending repos</h3>
            <p className="text-[13px] text-sub mt-1 max-w-sm mx-auto">
              Select a programming language and click <strong>Fetch Trending Repos</strong>. Results will instantly appear here so you can review them before creating your post.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}