const BASE = '';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000); // 3 min for AI ops
  try {
    const res = await fetch(BASE + path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      signal: controller.signal,
      ...options,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API ${res.status}: ${text || res.statusText}`);
    }
    return res.json() as Promise<T>;
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  getStatus: () => request<{ database: string; ollama: unknown }>('/api/status'),
  getProviders: () => request<{ providers: Array<{ id: string; name: string }> }>('/api/providers'),
  checkUpdate: () => request<{ ok: boolean; current_version: string; latest_version: string; up_to_date: boolean; changelog?: string[]; download_url?: string; note?: string }>('/api/update'),

  getDashboardStats: () => request<import('./types').DashboardStats>('/api/dashboard-stats'),
  getActivityLog: (limit = 100) => request<import('./types').ActivityItem[]>(`/api/activity-log?limit=${limit}`),

  getDrafts: () => request<import('./types').Draft[]>('/api/drafts'),
  createDraft: (data: Partial<import('./types').Draft>) =>
    request<{ ok: boolean; id: number }>('/api/drafts', { method: 'POST', body: JSON.stringify(data) }),
  approveDraft: (id: number) => request<{ ok: boolean }>(`/api/drafts/${id}/approve`, { method: 'POST' }),
  publishDraft: (id: number) => request<{ ok: boolean; error?: string }>(`/api/drafts/${id}/publish`, { method: 'POST' }),
  markPublished: (id: number) => request<{ ok: boolean }>(`/api/drafts/${id}/mark-published`, { method: 'POST' }),
  deleteDraft: (id: number) => request<{ ok: boolean }>(`/api/drafts/${id}`, { method: 'DELETE' }),
  updateBody: (id: number, body: string, tags?: string) =>
    request<{ ok: boolean }>(`/api/drafts/${id}/update-body`, { method: 'POST', body: JSON.stringify({ body, tags }) }),
  scheduleDraft: (id: number, scheduled_for: string) =>
    request<{ ok: boolean; auto_publish: number }>(`/api/drafts/${id}/schedule`, { method: 'POST', body: JSON.stringify({ scheduled_for }) }),
  updateDraft: (id: number, data: any) =>
    request<{ ok: boolean }>(`/api/drafts/${id}/update`, { method: 'POST', body: JSON.stringify(data) }),

  getSources: (url: string) => request<import('./types').SourceItem[]>(`/api/intake?url=${encodeURIComponent(url)}`),
  rejectSource: (url: string, title: string) =>
    request<{ ok: boolean }>('/api/reject-source', { method: 'POST', body: JSON.stringify({ url, title }) }),
  getRejectedCount: () => request<Array<{ id: number }>>('/api/rejected-sources'),
  clearRejected: () => request<{ ok: boolean }>('/api/rejected-sources/clear', { method: 'POST' }),

  getTemplates: () => request<import('./types').Template[]>('/api/templates'),
  saveTemplate: (data: Partial<import('./types').Template>) =>
    request<{ ok: boolean; id: number }>('/api/templates', { method: 'POST', body: JSON.stringify(data) }),

  bulkApprove: (ids: number[]) => request<{ ok: boolean; count: number }>('/api/drafts/bulk-approve', { method: 'POST', body: JSON.stringify({ ids }) }),
  bulkDelete: (ids: number[]) => request<{ ok: boolean; count: number }>('/api/drafts/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  bulkSchedule: (ids: number[], scheduled_for: string) =>
    request<{ ok: boolean; count: number }>('/api/drafts/bulk-schedule', { method: 'POST', body: JSON.stringify({ ids, scheduled_for }) }),

  generatePost: (data: { title: string; platform: string; tone: string; provider: string; url?: string; deep_research?: boolean; roundtable?: boolean; auto_image?: boolean }) =>
    request<{ ok: boolean; result?: string; final_post?: string; image_prompt?: string; media_url?: string; error?: string }>('/api/generate', { method: 'POST', body: JSON.stringify(data) }),

  oneClickDraft: (data: { title: string; url: string; snippet: string; platform: string; tone: string; provider: string; deep_research?: boolean }) =>
    request<{ ok: boolean; title?: string; body?: string; platform?: string; image_prompt?: string; media_url?: string; scheduled_for?: string; dedup?: boolean; verification?: import('./types').VerificationReport; error?: string }>('/api/one-click-draft', { method: 'POST', body: JSON.stringify(data) }),

  formatThread: (text: string) => request<{ ok: boolean; tweets: string[]; count: number }>('/api/format-thread', { method: 'POST', body: JSON.stringify({ text }) }),
  formatCarousel: (title: string, text: string) => request<{ ok: boolean; slides: Array<{ slide: number; title?: string; heading?: string; body: string }>; count: number }>('/api/format-carousel', { method: 'POST', body: JSON.stringify({ title, text }) }),
  formatX: (text: string) => request<{ ok: boolean; text: string; length: number }>('/api/format-x', { method: 'POST', body: JSON.stringify({ text }) }),

  // Autopilot: fetch top stories from a feed and auto-draft them
  autopilot: (feedUrl: string, provider: string) =>
    request<{ ok: boolean; count: number; error?: string }>(`/api/autopilot?feed_url=${encodeURIComponent(feedUrl)}&provider=${encodeURIComponent(provider)}`),

  // Draw Things image generation
  getDrawThingsStatus: () => request<{ available: boolean; url: string }>('/api/draw-things-status'),
  getImageProviders: () => request<{ providers: Array<{ id: string; name: string; available: boolean }>; active: string }>('/api/image-providers'),
  generateImage: (prompt: string, negativePrompt?: string, width?: number, height?: number, steps?: number) =>
    request<import('./types').ImageResult>('/api/generate-image', {
      method: 'POST',
      body: JSON.stringify({ prompt, negative_prompt: negativePrompt, width, height, steps })
    }),
  openMedia: (filename: string) =>
    request<{ ok: boolean }>('/api/open-media', { method: 'POST', body: JSON.stringify({ filename }) }),
  listMedia: (limit: number = 24) =>
    request<{ ok: boolean; files: Array<{ filename: string; url: string; size: number; modified: string }>; count: number; dir: string }>(`/api/media?limit=${limit}`),
  uploadImage: (dataUrl: string) =>
    request<{ ok: boolean; filename: string; url: string }>('/api/upload-image', {
      method: 'POST',
      body: JSON.stringify({ data_url: dataUrl }),
    }),

  // Studio AI assistant
  chat: (data: {
    message: string;
    title?: string;
    body?: string;
    platform?: string;
    image_prompt?: string;
    provider?: string;
    history?: Array<{ role: 'user' | 'assistant'; content: string }>;
  }) =>
    request<{
      ok: boolean;
      reply: string;
      suggested_body?: string;
      image_prompt?: string;
      sources?: Array<{ title: string; url: string; snippet: string }>;
      error?: string;
    }>('/api/chat', { method: 'POST', body: JSON.stringify(data) }),
  getVersions: (id: number) => request<Array<any>>(`/api/drafts/${id}/versions`),
  revertVersion: (id: number, version_id: number) =>
    request<{ ok: boolean; version: number }>(`/api/drafts/${id}/revert`, {
      method: 'POST',
      body: JSON.stringify({ version_id }),
    }),

  getGithubTrending: (lang: string) => request<{ ok: boolean; repos: Array<{ full_name: string; url: string; description: string; stars: number; language: string; sample?: boolean }>; count: number; sample?: boolean }>(`/api/github/trending?language=${encodeURIComponent(lang)}`),
  githubFetch: (lang: string, category: string, days: number) =>
    request<{ ok: boolean; fetched: number; stored: number; sample?: boolean }>(`/api/github/fetch?language=${encodeURIComponent(lang)}&category=${encodeURIComponent(category)}&days=${days}`),
  githubTop10: (category: string, platform: string) =>
    request<{ ok: boolean; title?: string; body?: string; image_prompt?: string; sample?: boolean; error?: string }>(`/api/github/top10?category=${encodeURIComponent(category)}&platform=${encodeURIComponent(platform)}`),
  generateGithubWeekly: (category: string, platform: string) =>
    request<{ ok: boolean; title?: string; body?: string; image_prompt?: string; sample?: boolean; error?: string }>('/api/github/weekly', { method: 'POST', body: JSON.stringify({ category, platform }) }),
  githubRepos: (category: string, limit: number = 10) =>
    request<{ ok: boolean; repos: Array<{ full_name: string; url: string; description: string; stars: number; language: string; fetched_at: string }>; count: number }>(`/api/github/repos?category=${encodeURIComponent(category)}&limit=${limit}`),

  // Deep research on a story
  deepResearch: (url: string, title: string, snippet: string) =>
    request<{ ok: boolean; dossier: string; links: string[] }>('/api/deep-research', { method: 'POST', body: JSON.stringify({ url, title, snippet }) }),

  // Independent fact verification — cross-check source claims against the web
  verifyFacts: (data: { url: string; title: string; snippet: string; provider: string }) =>
    request<{
      ok: boolean;
      claims: string[];
      facts: Array<{ claim: string; verdict: string; corrected: string; evidence: string; note: string }>;
      corrected: Array<{ claim: string; verdict: string; corrected: string; evidence: string; note: string }>;
      verified_block: string;
      error: string;
    }>('/api/verify', { method: 'POST', body: JSON.stringify(data) }),

  // Read article text
  readArticle: (url: string) => request<{ url: string; text: string }>(`/api/read-article?url=${encodeURIComponent(url)}`),

  // Source Watchlist
  getWatchlist: () => request<{ ok: boolean; items: Array<{ id: number; url: string; label: string; category: string; enabled: number; last_checked: string; last_error: string }> }>('/api/watchlist'),
  addWatchlistItem: (url: string, label?: string, category?: string) =>
    request<{ ok: boolean; item?: any }>('/api/watchlist/add', { method: 'POST', body: JSON.stringify({ url, label, category }) }),
  updateWatchlistItem: (url: string, updates: { label?: string; category?: string; enabled?: number }) =>
    request<{ ok: boolean; item?: any }>('/api/watchlist/update', { method: 'POST', body: JSON.stringify({ url, ...updates }) }),
  removeWatchlistItem: (url: string) => request<{ ok: boolean }>('/api/watchlist/remove', { method: 'POST', body: JSON.stringify({ url }) }),
  checkWatchlist: () => request<{ ok: boolean; stories: any[]; queued?: number; message?: string }>('/api/watchlist/check'),
  scanWatchlist: (url?: string) =>
    request<{ ok: boolean; stories: any[]; feeds: any[]; count: number; errors: any[] }>('/api/watchlist/scan', {
      method: 'POST',
      body: JSON.stringify(url ? { url } : {}),
    }),

  // Export
  exportMarkdown: (id: number) => request<{ ok: boolean; markdown?: string; error?: string }>(`/api/export-markdown?id=${id}`),
  exportAllMarkdown: () => request<{ ok: boolean; count: number; zip?: string }>('/api/export-all-markdown', { method: 'POST' }),
};