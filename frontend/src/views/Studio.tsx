import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useToast } from '../components/Toast';
import {
  Wand2, Loader2, Save, Eye, Sparkles, Image as ImageIcon, AlignLeft, LayoutGrid,
} from 'lucide-react';

export default function Studio() {
  const [providers, setProviders] = useState<Array<{ id: string; name: string }>>([]);
  const [provider, setProvider] = useState('');
  const [title, setTitle] = useState('');
  const [platform, setPlatform] = useState('LinkedIn');
  const [tone, setTone] = useState('thought_leadership');
  const [body, setBody] = useState('');
  const [tags, setTags] = useState('');
  const [imagePrompt, setImagePrompt] = useState('');
  const [mediaUrl, setMediaUrl] = useState('');
  const [generating, setGenerating] = useState(false);

  // Formatting state
  const [formattedThread, setFormattedThread] = useState<string[] | null>(null);
  const [formattedCarousel, setFormattedCarousel] = useState<Array<{ slide: number; title?: string; heading?: string; body: string }> | null>(null);

  // Draw Things state
  const [dtAvailable, setDtAvailable] = useState(false);
  const [generatingImage, setGeneratingImage] = useState(false);

  const { toast } = useToast();

  useEffect(() => {
    api.getProviders().then((d) => {
      const list = d.providers || [];
      setProviders(list);
      if (list.length) setProvider(list[0].id);
    }).catch(() => {});

    api.getDrawThingsStatus().then((d) => {
      setDtAvailable(d.available);
    }).catch(() => {});
  }, []);

  const generate = async () => {
    if (!title.trim()) { toast('Add a headline first', 'error'); return; }
    setGenerating(true);
    setFormattedThread(null);
    setFormattedCarousel(null);
    try {
      const data = await api.generatePost({ title, platform, tone, provider, deep_research: true });
      if (data.ok && (data.result || data.final_post)) {
        setBody(data.result || data.final_post || '');
        if (data.image_prompt) setImagePrompt(data.image_prompt);
        toast('Post draft ready!', 'success');
      } else {
        toast(data.error || 'Generation failed', 'error');
      }
    } catch (e: any) {
      toast(e.message || 'Generation failed', 'error');
    } finally {
      setGenerating(false);
    }
  };

  const handleFormatThread = async () => {
    if (!body.trim()) { toast('Write or generate a post first', 'info'); return; }
    try {
      const data = await api.formatThread(body);
      if (data.ok && data.tweets) {
        setFormattedThread(data.tweets);
        setFormattedCarousel(null);
        toast(`Formatted into ${data.count}-tweet thread`, 'success');
      }
    } catch {
      toast('Failed to format thread', 'error');
    }
  };

  const handleFormatCarousel = async () => {
    if (!body.trim()) { toast('Write or generate a post first', 'info'); return; }
    try {
      const data = await api.formatCarousel(title || 'Key Takeaways', body);
      if (data.ok && data.slides) {
        setFormattedCarousel(data.slides);
        setFormattedThread(null);
        toast(`Formatted into ${data.count}-slide carousel`, 'success');
      }
    } catch {
      toast('Failed to format carousel', 'error');
    }
  };

  const handleGenerateImage = async () => {
    if (!imagePrompt.trim()) { toast('Image prompt is empty', 'error'); return; }
    setGeneratingImage(true);
    try {
      const res = await api.generateImage(imagePrompt);
      if (res.ok && res.b64) {
        // Convert base64 to a data URL for preview
        const dataUrl = `data:image/png;base64,${res.b64}`;
        setMediaUrl(dataUrl);
        toast('Image generated with Draw Things!', 'success');
      } else if (res.ok && res.image_url) {
        setMediaUrl(res.image_url);
        toast('Image generated!', 'success');
      } else {
        toast(res.error || 'Image generation failed', 'error');
      }
    } catch (e: any) {
      toast(e.message || 'Draw Things connection error', 'error');
    } finally {
      setGeneratingImage(false);
    }
  };

  const save = async () => {
    if (!title.trim()) { toast('Headline is required', 'error'); return; }
    try {
      await api.createDraft({
        title,
        body: formattedThread ? formattedThread.join('\n\n---\n\n') : body,
        platform,
        tags,
        image_prompt: imagePrompt,
        media_url: mediaUrl,
        status: 'Draft',
      });
      toast('Saved to queue', 'success');
    } catch {
      toast('Save failed', 'error');
    }
  };

  return (
    <div className="flex h-full bg-canvas animate-fade-up">
      {/* Main editor */}
      <div className="flex-1 flex flex-col border-r border-edge min-w-0">
        <div className="flex h-16 items-center justify-between px-8 border-b border-edge bg-surface">
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-brand-600">
            <Wand2 size={13} /> Content Studio
          </div>
          <button onClick={save} className="btn-primary">
            <Save size={15} /> Save Draft
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-3xl">
            {/* Title */}
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Headline / working title…"
              className="w-full bg-transparent text-3xl font-bold text-ink placeholder-faint focus:outline-none mb-6 tracking-tight"
            />

            {/* AI Control Bar */}
            <div className="flex flex-wrap items-center gap-2 mb-6 card p-3">
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-[12px] text-ink font-medium focus:outline-none focus:border-brand-500"
              >
                {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-[12px] text-ink font-medium focus:outline-none focus:border-brand-500"
              >
                {['LinkedIn', 'X', 'YouTube', 'Facebook', 'Instagram', 'General'].map((p) => <option key={p}>{p}</option>)}
              </select>
              <select
                value={tone}
                onChange={(e) => setTone(e.target.value)}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-[12px] text-ink font-medium focus:outline-none focus:border-brand-500"
              >
                <option value="thought_leadership">Thought Leadership</option>
                <option value="viral_story">Viral & Punchy</option>
                <option value="technical_deep_dive">Deep Technical</option>
                <option value="contrarian">Contrarian Hot-Take</option>
              </select>

              <button
                onClick={generate}
                disabled={generating}
                className="ml-auto flex items-center gap-2 rounded-lg bg-brand-500 text-white px-4 py-2 text-[12px] font-semibold hover:bg-brand-600 transition-colors disabled:opacity-50"
              >
                {generating ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} Generate Post
              </button>
            </div>

            {/* Body TextArea */}
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Write your post here, or click Generate Post above to let AI draft it…"
              className="w-full min-h-[320px] bg-surface border border-edge rounded-xl p-5 text-[14px] leading-relaxed text-ink placeholder-faint focus:outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 resize-y shadow-card"
            />
            <div className="flex items-center justify-between mt-3 text-[12px] text-faint mb-6">
              <span>{body.length} characters</span>
              <input
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="tags, comma separated"
                className="bg-transparent placeholder-faint text-right focus:outline-none w-56 text-sub"
              />
            </div>

            {/* Formatting tools */}
            <div className="card p-4 mb-6">
              <div className="text-[11px] font-bold uppercase tracking-widest text-faint mb-3">
                Repurpose & Format Tools
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={handleFormatThread}
                  className="flex items-center gap-1.5 rounded-lg border border-edge bg-raised px-3 py-1.5 text-[12px] font-semibold text-ink hover:bg-edge transition-colors"
                >
                  <AlignLeft size={13} /> Split into Thread (X)
                </button>
                <button
                  onClick={handleFormatCarousel}
                  className="flex items-center gap-1.5 rounded-lg border border-edge bg-raised px-3 py-1.5 text-[12px] font-semibold text-ink hover:bg-edge transition-colors"
                >
                  <LayoutGrid size={13} /> Format as Carousel (LinkedIn/IG)
                </button>
              </div>

              {/* Thread output preview */}
              {formattedThread && (
                <div className="mt-4 pt-4 border-t border-edge space-y-2">
                  <div className="text-[12px] font-bold text-ink">Thread Outline ({formattedThread.length} tweets):</div>
                  {formattedThread.map((tweet, idx) => (
                    <div key={idx} className="rounded-lg bg-raised p-3 text-[12px] text-sub font-mono">
                      <span className="font-bold text-brand-600">{idx + 1}/ </span>
                      {tweet}
                    </div>
                  ))}
                </div>
              )}

              {/* Carousel output preview */}
              {formattedCarousel && (
                <div className="mt-4 pt-4 border-t border-edge space-y-2">
                  <div className="text-[12px] font-bold text-ink">Carousel Outline ({formattedCarousel.length} slides):</div>
                  <div className="grid grid-cols-2 gap-2">
                    {formattedCarousel.map((slide) => (
                      <div key={slide.slide} className="rounded-lg bg-raised p-3 text-[12px] border border-edge">
                        <div className="font-bold text-ink mb-1">Slide {slide.slide}: {slide.title || slide.heading}</div>
                        <div className="text-sub text-[11px] leading-relaxed">{slide.body}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Image Prompt & Draw Things Card */}
            <div className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="text-[11px] font-bold uppercase tracking-widest text-faint flex items-center gap-2">
                  <ImageIcon size={14} /> AI Art Direction (Draw Things)
                </div>
                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${dtAvailable ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-raised text-faint border border-edge'}`}>
                  {dtAvailable ? '● Draw Things Ready' : 'Draw Things Offline'}
                </span>
              </div>

              <input
                value={imagePrompt}
                onChange={(e) => setImagePrompt(e.target.value)}
                placeholder="Image prompt for FLUX / Draw Things…"
                className="w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[12px] text-ink placeholder-faint focus:outline-none focus:border-brand-500 mb-3"
              />

              <div className="flex items-center justify-between">
                <span className="text-[11px] text-faint">
                  {dtAvailable ? 'Local 127.0.0.1:7860 active' : 'Enable HTTP Server in Draw Things Settings'}
                </span>
                <button
                  onClick={handleGenerateImage}
                  disabled={generatingImage || !dtAvailable}
                  className="flex items-center gap-1.5 rounded-lg bg-brand-500 text-white px-3.5 py-1.5 text-[12px] font-semibold hover:bg-brand-600 transition-colors disabled:opacity-50"
                >
                  {generatingImage ? <Loader2 size={13} className="animate-spin" /> : <ImageIcon size={13} />} Generate Image
                </button>
              </div>

              {mediaUrl && (
                <div className="mt-3 rounded-xl overflow-hidden border border-edge max-h-48">
                  <img src={mediaUrl} alt="Generated visual" className="w-full h-full object-cover" />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Live Preview card */}
      <div className="w-[380px] flex-shrink-0 overflow-y-auto p-6 bg-raised border-l border-edge">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-faint mb-4">
          <Eye size={13} /> Live Preview ({platform})
        </div>

        <div className="bg-white rounded-2xl overflow-hidden shadow-card border border-edge">
          <div className="flex items-center gap-3 p-4 border-b border-edge">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white font-bold text-sm">
              JM
            </div>
            <div>
              <div className="text-[13px] font-semibold text-ink">JustMeMedia</div>
              <div className="text-[11px] text-faint">{platform} Post · Preview</div>
            </div>
          </div>

          <div className="p-4 text-[13px] leading-relaxed text-ink whitespace-pre-wrap min-h-[140px]">
            {title && <div className="font-bold text-[14px] mb-2">{title}</div>}
            {body || <span className="text-faint">Your post copy will appear here as you write…</span>}
          </div>

          {mediaUrl && (
            <div className="border-t border-edge overflow-hidden">
              <img src={mediaUrl} alt="Post attachment" className="w-full h-44 object-cover" />
            </div>
          )}

          <div className="flex items-center gap-4 px-4 py-3 border-t border-edge text-[12px] text-sub bg-raised/50">
            <span>👍 Like</span>
            <span>💬 Comment</span>
            <span>🔁 Repost</span>
            <span>📤 Send</span>
          </div>
        </div>
      </div>
    </div>
  );
}