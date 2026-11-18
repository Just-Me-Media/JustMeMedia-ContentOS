import { useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { api } from '../lib/api';
import { useToast } from '../components/Toast';
import { escapeHtml, htmlToPlainText, plainTextToHtml, sanitizeHtml } from '../lib/richText';
import {
  Wand2, Loader2, Save, Eye, Sparkles, Image, AlignLeft, LayoutGrid,
  Bold, Italic, Underline, Link, Minus, List, Trash2, CheckCircle2, Palette, Eraser,
  MessageSquare, Send, Globe, Undo2, AlertCircle,
} from 'lucide-react';

type ChatSource = { title: string; url: string; snippet: string };
type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  sources?: ChatSource[];
  suggested_body?: string;
  image_prompt?: string;
};

export default function Studio({ embedded = false }: { embedded?: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [providers, setProviders] = useState<Array<{ id: string; name: string }>>([]);
  const [provider, setProvider] = useState('');
  const [title, setTitle] = useState('');
  const [platform, setPlatform] = useState('LinkedIn');
  const [tone, setTone] = useState('thought_leadership');
  const [body, setBody] = useState('');
  const [bodyHtml, setBodyHtml] = useState('');
  const [tags, setTags] = useState('');
  const [imagePrompt, setImagePrompt] = useState('');
  const [mediaUrl, setMediaUrl] = useState('');
  const [generating, setGenerating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);

  // Rich text editor
  const editorRef = useRef<HTMLDivElement | null>(null);
  const savedRange = useRef<Range | null>(null);

  // Formatting state
  const [formattedThread, setFormattedThread] = useState<string[] | null>(null);
  const [formattedCarousel, setFormattedCarousel] = useState<Array<{ slide: number; title?: string; heading?: string; body: string }> | null>(null);

  // Draw Things state
  const [dtAvailable, setDtAvailable] = useState(false);
  const [imageProviders, setImageProviders] = useState<Array<{ id: string; name: string; available: boolean }>>([]);
  const [generatingImage, setGeneratingImage] = useState(false);

  // Media gallery
  const [gallery, setGallery] = useState<Array<{ filename: string; url: string; modified: string }>>([]);

  // AI assistant
  const [panel, setPanel] = useState<'preview' | 'assistant'>('preview');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatting, setChatting] = useState(false);
  const [appliedSnapshot, setAppliedSnapshot] = useState<{ title: string; bodyHtml: string; imagePrompt: string } | null>(null);
  const [appliedPromptIndex, setAppliedPromptIndex] = useState<number | null>(null);
  const [appliedDraftIndex, setAppliedDraftIndex] = useState<number | null>(null);
  const [editedPrompts, setEditedPrompts] = useState<Record<number, string>>({});
  const [imagePromptFlash, setImagePromptFlash] = useState(false);
  const imagePromptRef = useRef<HTMLTextAreaElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Independent fact verification
  const [sourceUrl, setSourceUrl] = useState('');
  const [verification, setVerification] = useState<import('../lib/types').VerificationReport | null>(null);
  const [verifying, setVerifying] = useState(false);

  const { toast } = useToast();

  const loadGallery = () => {
    api.listMedia(12)
      .then((d) => setGallery(d.files || []))
      .catch(() => {});
  };

  // ── Rich text editing ────────────────────────────────────────────────────
  const syncFromEditor = () => {
    const el = editorRef.current;
    if (!el) return;
    const html = el.innerHTML;
    setBodyHtml(html);
    setBody(htmlToPlainText(html));
  };

  const setEditorHtml = (html: string) => {
    const clean = sanitizeHtml(html);
    if (editorRef.current) editorRef.current.innerHTML = clean;
    setBodyHtml(clean);
    setBody(htmlToPlainText(clean));
  };

  const setEditorText = (text: string) => setEditorHtml(plainTextToHtml(text));

  const rememberSelection = () => {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    if (editorRef.current?.contains(range.commonAncestorContainer)) {
      savedRange.current = range.cloneRange();
    }
  };

  const restoreSelection = (): boolean => {
    const el = editorRef.current;
    const range = savedRange.current;
    const sel = window.getSelection();
    if (!el || !range || !sel) return false;
    el.focus();
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  };

  const exec = (command: string, value?: string) => {
    const el = editorRef.current;
    if (!el) return;
    el.focus();
    document.execCommand('styleWithCSS', false, 'true');
    document.execCommand(command, false, value);
    syncFromEditor();
  };

  const applyLink = () => {
    if (!restoreSelection()) editorRef.current?.focus();
    const url = window.prompt('Enter URL:', 'https://');
    if (!url) return;
    restoreSelection();
    const safeUrl = url.trim();
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed) {
      exec('createLink', safeUrl);
    } else {
      exec('insertHTML', `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(safeUrl)}</a>`);
    }
  };

  const applyHeading = () => {
    editorRef.current?.focus();
    const current = String(document.queryCommandValue('formatBlock') || '').toLowerCase();
    exec('formatBlock', current === 'h2' ? 'p' : 'h2');
  };

  const applyColor = (color: string) => {
    restoreSelection();
    exec('foreColor', color);
  };

  const COLOR_SWATCHES = ['#15BF7F', '#0EA5E9', '#EF4444', '#F59E0B', '#8B5CF6', '#1A1A1A'];

  useEffect(() => {
    setAppliedSnapshot(null);
    setAppliedDraftIndex(null);
    setAppliedPromptIndex(null);
    if (location.state?.title) {
      setTitle(location.state.title);
      setEditorText(location.state.body || '');
      setPlatform(location.state.platform || 'LinkedIn');
      setImagePrompt(location.state.image_prompt || '');
      setMediaUrl(location.state.media_url || '');
      if (location.state.source_url) setSourceUrl(location.state.source_url);
      if (location.state.verification) setVerification(location.state.verification);
    }
    if (location.state?.editId) {
      const id = location.state.editId;
      setEditingId(id);
      api.getDrafts().then((drafts) => {
        const d = drafts.find((x: any) => x.id === id);
        if (d) {
          setTitle(d.title);
          setEditorHtml(d.body_html || plainTextToHtml(d.body || ''));
          setPlatform(d.platform);
          setTags(d.tags || '');
          setImagePrompt(d.image_prompt || '');
          setMediaUrl(d.media_url || '');
        }
      });
    }

    api.getProviders().then((d) => {
      const list = d.providers || [];
      setProviders(list);
      if (list.length) setProvider(list[0].id);
    }).catch(() => {});

    api.getDrawThingsStatus().then((d) => {
      setDtAvailable(d.available);
    }).catch(() => {});

    api.getImageProviders().then((d) => {
      setImageProviders(d.providers || []);
    }).catch(() => {});

    loadGallery();
  }, [location.state]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, chatting, panel]);

  // ── AI assistant ─────────────────────────────────────────────────────────
  const sendChat = async (text?: string) => {
    const message = (text ?? chatInput).trim();
    if (!message || chatting) return;

    setPanel('assistant');
    setChatInput('');
    const history = messages.slice(-10).map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: 'user', content: message }]);
    setChatting(true);
    try {
      const plainBody = htmlToPlainText(editorRef.current?.innerHTML || bodyHtml) || body;
      const res = await api.chat({
        message,
        title,
        body: plainBody,
        platform,
        image_prompt: imagePrompt,
        provider,
        history,
      });
      if (!res.ok) throw new Error(res.error || 'The assistant could not respond');
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: res.reply || 'Done.',
        sources: res.sources,
        suggested_body: res.suggested_body,
        image_prompt: res.image_prompt,
      }]);
    } catch (e: any) {
      const error = e.message || 'Assistant unavailable';
      setMessages((prev) => [...prev, { role: 'assistant', content: `⚠️ ${error}` }]);
      toast(error, 'error');
    } finally {
      setChatting(false);
    }
  };

  const revealImagePrompt = () => {
    document.getElementById('image-section')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => imagePromptRef.current?.focus(), 350);
    setImagePromptFlash(true);
    window.setTimeout(() => setImagePromptFlash(false), 2000);
  };

  const rememberApplySnapshot = () => {
    setAppliedSnapshot((prev) => prev ?? {
      title,
      bodyHtml: sanitizeHtml(editorRef.current?.innerHTML || bodyHtml),
      imagePrompt,
    });
  };

  const applyChatSuggestion = (message: ChatMessage, index: number) => {
    if (!message.suggested_body && !message.image_prompt) return;
    rememberApplySnapshot();

    if (message.suggested_body) {
      setEditorText(message.suggested_body);
      setAppliedDraftIndex(index);
      // Show the result immediately instead of leaving the change off-screen.
      setPanel('preview');
      window.requestAnimationFrame(() => {
        editorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }
    if (message.image_prompt) {
      setImagePrompt(message.image_prompt);
      setAppliedPromptIndex(index);
      if (!message.suggested_body) revealImagePrompt();
    }

    toast(
      message.suggested_body
        ? 'AI revision applied — Save Draft to keep it'
        : 'Image prompt updated — Generate Image to use it',
      'success',
    );
  };

  const useChatImagePrompt = (message: ChatMessage, index: number) => {
    if (!message.image_prompt) return;
    rememberApplySnapshot();
    setImagePrompt(message.image_prompt);
    setAppliedPromptIndex(index);
    revealImagePrompt();
    toast('Image prompt updated — Generate Image to use it', 'success');
  };

  const undoChatSuggestion = () => {
    if (!appliedSnapshot) return;
    setTitle(appliedSnapshot.title);
    setImagePrompt(appliedSnapshot.imagePrompt);
    setEditorHtml(appliedSnapshot.bodyHtml || '');
    setAppliedSnapshot(null);
    setAppliedDraftIndex(null);
    setAppliedPromptIndex(null);
    toast('Reverted the AI edit', 'info');
  };

  const QUICK_PROMPTS: Array<{ label: string; prompt: string }> = [
    { label: 'Polish this draft', prompt: 'Improve this draft while keeping my voice and platform conventions.' },
    { label: 'Make it punchier', prompt: 'Make this post shorter, punchier and stronger on the hook, then return the full revised post.' },
    { label: 'Find data & sources', prompt: 'Find credible, recent data and sources I could use to strengthen this post.' },
    { label: 'Image prompts', prompt: 'Suggest 3 strong, concrete image prompts that match the story and brand style.' },
  ];

  const runVerify = async () => {
    if (!title.trim()) { toast('Add a headline first', 'error'); return; }
    if (!sourceUrl.trim()) { toast('Add the source URL below to verify its claims', 'error'); return; }
    setVerifying(true);
    try {
      const res = await api.verifyFacts({
        url: sourceUrl.trim(), title, snippet: '', provider,
      });
      if (!res.ok && !res.facts?.length) {
        toast(res.error || 'Verification could not complete', 'error');
        setVerification({ ok: false, checked: 0, facts: [], corrected: [], error: res.error || 'Verification failed', verified_at: '' });
        return;
      }
      setVerification({
        ok: res.ok,
        checked: res.claims?.length || res.facts?.length || 0,
        facts: res.facts || [],
        corrected: res.corrected || [],
        error: res.error || '',
        verified_at: new Date().toISOString(),
      });
      const corrections = res.corrected?.length || 0;
      if (corrections > 0) toast(`${corrections} source claim(s) corrected — review below`, 'error');
      else toast('All checkable claims confirmed by independent sources', 'success');
    } catch (e: any) {
      toast(e.message || 'Verification failed', 'error');
    } finally {
      setVerifying(false);
    }
  };

  const generate = async () => {
    if (!title.trim()) { toast('Add a headline first', 'error'); return; }
    setGenerating(true);
    setFormattedThread(null);
    setFormattedCarousel(null);
    try {
      const data = await api.generatePost({ title, platform, tone, provider, deep_research: true, auto_image: true });
      if (data.ok && (data.result || data.final_post)) {
        setEditorText(data.result || data.final_post || '');
        if (data.image_prompt) setImagePrompt(data.image_prompt);
        if (data.media_url) setMediaUrl(data.media_url);
        toast(data.media_url ? 'Post draft ready with image!' : 'Post draft ready!', 'success');
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
        const dataUrl = `data:image/png;base64,${res.b64}`;
        setMediaUrl(res.filename ? `/api/media/${res.filename}` : dataUrl);
        loadGallery();
        toast('Image generated with Draw Things!', 'success');
      } else if (res.ok && res.image_url) {
        setMediaUrl(res.image_url);
        loadGallery();
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
    const editorHtml = formattedThread
      ? plainTextToHtml(formattedThread.join('\n\n---\n\n'))
      : sanitizeHtml(editorRef.current?.innerHTML || bodyHtml);
    const plainBody = formattedThread
      ? formattedThread.join('\n\n---\n\n')
      : htmlToPlainText(editorHtml) || body;
    try {
      if (editingId) {
        await api.updateDraft(editingId, {
          title,
          body: plainBody,
          body_html: editorHtml,
          platform,
          tags,
          image_prompt: imagePrompt,
          media_url: mediaUrl,
        });
        toast('Draft updated!', 'success');
        setEditingId(null);
      } else {
        const created = await api.createDraft({
          title,
          body: plainBody,
          body_html: editorHtml,
          platform,
          tags,
          image_prompt: imagePrompt,
          media_url: mediaUrl,
          status: 'Draft',
        });
        if (created?.id) setEditingId(created.id);
        toast('Saved to queue', 'success');
      }
      setAppliedSnapshot(null);
      setAppliedDraftIndex(null);
      setAppliedPromptIndex(null);
      setTimeout(() => navigate('/queue'), 800);
    } catch {
      toast('Save failed', 'error');
    }
  };

  const uploadLocalImage = (file: File) => {
    setUploadingImage(true);
    const reader = new FileReader();
    reader.onload = async () => {
      const dataUrl = reader.result as string;
      setMediaUrl(dataUrl);
      try {
        const saved = await api.uploadImage(dataUrl);
        if (saved.ok && saved.url) {
          setMediaUrl(saved.url);
          loadGallery();
        }
      } catch {
        // Keep the data URL so the image is not lost if saving fails.
      }
      setUploadingImage(false);
      toast('Image attached to post', 'success');
    };
    reader.onerror = () => {
      setUploadingImage(false);
      toast('Failed to read image file', 'error');
    };
    reader.readAsDataURL(file);
  };

  return (
    <div className={embedded ? "" : "flex h-full bg-canvas animate-fade-up"}>
      <div className={embedded ? "flex-1 flex flex-col min-w-0" : "flex-1 flex flex-col border-r border-edge min-w-0"}>
        <div className="flex h-16 items-center justify-between px-8 border-b border-edge bg-surface">
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-brand-600">
            <Wand2 size={13} /> Content Studio
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPanel('assistant')}
              className="btn-ghost"
              title="Open the AI assistant"
            >
              <MessageSquare size={14} /> Ask AI
            </button>
            <button onClick={save} className="btn-primary">
              <Save size={15} /> Save Draft
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-3xl">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Headline / working title…"
              className="w-full bg-transparent text-3xl font-bold text-ink placeholder-faint focus:outline-none mb-6 tracking-tight"
            />

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
                className="flex items-center gap-2 rounded-lg bg-brand-500 text-white px-4 py-2 text-[12px] font-semibold hover:bg-brand-600 transition-colors disabled:opacity-50"
              >
                {generating ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} Generate Post
              </button>
              <button
                onClick={() => document.getElementById('local-image-input')?.click()}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-semibold text-ink transition-colors ${uploadingImage ? 'bg-brand-500 text-white opacity-70 cursor-not-allowed' : 'border-edge bg-raised hover:bg-edge cursor-pointer'}`}
              >
                <Image size={14} />
                {uploadingImage ? 'Attaching…' : 'Image'}
              </button>
              <input
                id="local-image-input"
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  uploadLocalImage(file);
                  e.target.value = '';
                }}
              />
            </div>

            <div
              ref={editorRef}
              contentEditable
              suppressContentEditableWarning
              role="textbox"
              aria-multiline="true"
              data-placeholder="Write your post here, or click Generate Post above to let AI draft it…"
              onInput={syncFromEditor}
              onMouseUp={rememberSelection}
              onKeyUp={rememberSelection}
              onPaste={(e) => {
                e.preventDefault();
                const text = e.clipboardData.getData('text/plain');
                document.execCommand('insertHTML', false, plainTextToHtml(text));
                syncFromEditor();
              }}
              className={`rich-editor w-full bg-surface border border-edge rounded-xl p-5 text-[14px] leading-relaxed text-ink focus:outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 shadow-card ${body.trim() ? '' : 'is-empty'}`}
            />

            <div className="flex flex-wrap items-center gap-1 mt-2 p-2 rounded-lg bg-raised border border-edge">
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={() => exec('bold')}
                title="Bold (⌘B)"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors"
              >
                <Bold size={13} />
              </button>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={() => exec('italic')}
                title="Italic (⌘I)"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors"
              >
                <Italic size={13} />
              </button>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={() => exec('underline')}
                title="Underline (⌘U)"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors"
              >
                <Underline size={13} />
              </button>
              <div className="w-px h-5 bg-edge mx-1" />
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={applyLink}
                title="Insert link"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors"
              >
                <Link size={13} />
              </button>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={applyHeading}
                title="Toggle heading"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors text-[10px] font-bold"
              >
                H2
              </button>
              <div className="w-px h-5 bg-edge mx-1" />
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={() => exec('insertHorizontalRule')}
                title="Insert divider"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors"
              >
                <Minus size={13} />
              </button>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={() => exec('insertUnorderedList')}
                title="Bullet list"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors"
              >
                <List size={13} />
              </button>
              <div className="w-px h-5 bg-edge mx-1" />

              {/* Text colour */}
              <span className="flex items-center gap-1 pr-1" title="Text colour">
                <Palette size={12} className="text-faint" />
                {COLOR_SWATCHES.map((color) => (
                  <button
                    key={color}
                    type="button"
                    onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                    onClick={() => applyColor(color)}
                    title={`Text colour ${color}`}
                    className="w-4 h-4 rounded-full border border-black/10 hover:scale-110 transition-transform"
                    style={{ backgroundColor: color }}
                  />
                ))}
                <label
                  onMouseDown={rememberSelection}
                  title="Custom text colour"
                  className="relative w-5 h-5 rounded-full border border-dashed border-faint cursor-pointer overflow-hidden bg-[conic-gradient(red,yellow,lime,aqua,blue,magenta,red)]"
                >
                  <input
                    type="color"
                    defaultValue="#15BF7F"
                    onChange={(e) => applyColor(e.target.value)}
                    className="absolute inset-0 opacity-0 cursor-pointer"
                  />
                </label>
              </span>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); rememberSelection(); }}
                onClick={() => exec('removeFormat')}
                title="Clear formatting"
                className="w-7 h-7 rounded-md bg-surface border border-edge text-ink hover:bg-edge flex items-center justify-center transition-colors"
              >
                <Eraser size={13} />
              </button>

              <div className="ml-auto flex items-center gap-2">
                <span className="text-[11px] text-faint">{body.length} chars</span>
                <input
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  placeholder="tags, comma separated"
                  className="rounded-md border border-edge bg-surface px-2 py-1 text-[11px] text-ink placeholder-faint focus:outline-none focus:border-brand-500 w-40"
                />
              </div>
            </div>

            <div className="card p-4 my-6">
              <div className="text-[11px] font-bold uppercase tracking-widest text-faint mb-3">
                Deep Fact Verification
              </div>
              <p className="text-[12px] text-sub mb-3 leading-relaxed">
                Cross-check this story's claims against independent web sources. Corrections are
                applied to the draft and reviewed here before you approve.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                  placeholder="https://source-article-url…"
                  className="flex-1 min-w-[220px] rounded-lg border border-edge bg-surface px-3 py-2 text-[12px] text-ink placeholder-faint focus:outline-none focus:border-brand-500"
                />
                <button
                  onClick={runVerify}
                  disabled={verifying}
                  className="flex items-center gap-1.5 rounded-lg border border-brand-300 bg-brand-50 text-brand-700 px-3 py-2 text-[12px] font-semibold hover:bg-brand-100 disabled:opacity-50"
                >
                  {verifying ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
                  Verify Facts
                </button>
              </div>
              {verification && (
                <div className="mt-4 pt-4 border-t border-edge space-y-2">
                  <div className="text-[12px] font-bold text-ink">
                    {verification.checked} claims checked · {verification.corrected.length} corrected
                    {verification.error && <span className="text-amber-600 font-normal"> · {verification.error}</span>}
                  </div>
                  {verification.corrected.map((f, i) => (
                    <div key={i} className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-[12px]">
                      <div className="text-amber-800"><span className="font-bold">Source said:</span> {f.claim}</div>
                      <div className="text-emerald-700 mt-1"><span className="font-bold">Verified:</span> {f.corrected || f.note}</div>
                      {f.evidence && <a href={f.evidence} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline text-[11px] mt-1 block truncate">{f.evidence}</a>}
                    </div>
                  ))}
                  {verification.facts.filter(f => f.verdict === 'confirmed').map((f, i) => (
                    <div key={i} className="rounded-lg bg-raised p-2.5 text-[11px] text-sub flex items-start gap-2">
                      <CheckCircle2 size={13} className="text-emerald-600 flex-shrink-0 mt-0.5" />
                      <span><span className="font-semibold text-ink">Verified:</span> {f.claim}</span>
                    </div>
                  ))}
                  {verification.facts.filter(f => f.verdict === 'unverifiable').map((f, i) => (
                    <div key={i} className="rounded-lg bg-raised p-2.5 text-[11px] text-sub flex items-start gap-2">
                      <AlertCircle size={13} className="text-amber-600 flex-shrink-0 mt-0.5" />
                      <span><span className="font-semibold text-ink">Unverifiable (omitted):</span> {f.claim}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card p-4 my-6">
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

            <div id="image-section" className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="text-[11px] font-bold uppercase tracking-widest text-faint flex items-center gap-2">
                  <Image size={14} /> AI Art Direction (Draw Things)
                </div>
                <span className={`text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full ${imageProviders.some(p => p.available) ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}>
                  {imageProviders.some(p => p.available)
                    ? `● ${imageProviders.filter(p => p.available).map(p => p.name).join(' + ')}`
                    : '⚠️ No image provider — enable Draw Things or set a cloud API key'}
                </span>
              </div>

              <textarea
                ref={imagePromptRef}
                value={imagePrompt}
                onChange={(e) => setImagePrompt(e.target.value)}
                placeholder="Image prompt for FLUX / Draw Things…"
                rows={3}
                className={`w-full rounded-lg border bg-raised px-3 py-2 text-[12px] text-ink placeholder-faint focus:outline-none focus:border-brand-500 mb-3 resize-y min-h-[60px] max-h-40 overflow-y-auto transition-shadow ${
                  imagePromptFlash ? 'border-brand-500 ring-2 ring-brand-300' : 'border-edge'
                }`}
              />

              <div className="flex items-center justify-between">
                <span className="text-[11px] text-faint">
                  {dtAvailable ? 'Local http://127.0.0.1:7860 active' : 'To fix: Open Draw Things → Settings → Turn on HTTP Server (Port 7860)'}
                </span>
                <button
                  onClick={handleGenerateImage}
                  disabled={generatingImage || !dtAvailable}
                  className="flex items-center gap-1.5 rounded-lg bg-brand-500 text-white px-3.5 py-1.5 text-[12px] font-semibold hover:bg-brand-600 transition-colors disabled:opacity-50"
                >
                  {generatingImage ? <Loader2 size={13} className="animate-spin" /> : <Image size={13} />} Generate Image
                </button>
              </div>

              {mediaUrl && (
                <div className="mt-4 rounded-xl overflow-hidden border border-edge bg-raised">
                  <div className="relative max-h-96 overflow-hidden flex items-center justify-center bg-black/5 group">
                    <img src={mediaUrl} alt="Generated visual" className="w-full h-auto max-h-96 object-contain" />
                    {mediaUrl.startsWith('/api/media/') && (
                      <button
                        onClick={() => api.openMedia(mediaUrl.replace('/api/media/', ''))}
                        className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity text-white font-bold"
                      >
                        View in Folder
                      </button>
                    )}
                  </div>
                  <div className="px-4 py-2.5 bg-surface border-t border-edge flex items-center justify-between">
                    <div className="flex items-center gap-2 text-emerald-600 text-[12px] font-semibold">
                      <CheckCircle2 size={14} /> Image Attached to Post
                    </div>
                    <button
                      onClick={() => setMediaUrl('')}
                      className="flex items-center gap-1 text-[11px] text-red-500 hover:text-red-700 font-medium"
                    >
                      <Trash2 size={12} /> Remove
                    </button>
                  </div>
                </div>
              )}

              {/* Recent generations gallery */}
              <div className="mt-5 pt-4 border-t border-edge">
                <div className="flex items-center justify-between mb-2.5">
                  <div className="text-[11px] font-bold uppercase tracking-widest text-faint">
                    Recent Generations {gallery.length > 0 && `(${gallery.length})`}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={loadGallery}
                      className="text-[11px] font-semibold text-sub hover:text-brand-600 transition-colors"
                    >
                      Refresh
                    </button>
                    <button
                      onClick={() => api.openMedia('')}
                      className="text-[11px] font-semibold text-sub hover:text-brand-600 transition-colors"
                    >
                      Open Folder
                    </button>
                  </div>
                </div>

                {gallery.length === 0 ? (
                  <p className="text-[11px] text-faint">No generated images yet. Click Generate Image above.</p>
                ) : (
                  <div className="grid grid-cols-4 gap-2">
                    {gallery.map((img) => (
                      <button
                        key={img.filename}
                        onClick={() => {
                          setMediaUrl(img.url);
                          toast('Image attached to post', 'success');
                        }}
                        title={`${img.filename} · ${img.modified}`}
                        className={`relative rounded-lg overflow-hidden border-2 transition-colors ${
                          mediaUrl === img.url ? 'border-brand-500' : 'border-edge hover:border-brand-300'
                        }`}
                      >
                        <img src={img.url} alt={img.filename} className="w-full h-16 object-cover" />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="w-[390px] flex-shrink-0 flex flex-col bg-raised border-l border-edge min-h-0">
        {/* Panel tabs */}
        <div className="flex items-center gap-1 p-2.5 border-b border-edge bg-surface">
          <button
            onClick={() => setPanel('preview')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-colors ${
              panel === 'preview' ? 'bg-raised text-ink border border-edge' : 'text-sub hover:text-ink'
            }`}
          >
            <Eye size={13} /> Preview
          </button>
          <button
            onClick={() => setPanel('assistant')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-colors ${
              panel === 'assistant' ? 'bg-brand-500 text-white' : 'text-sub hover:text-ink'
            }`}
          >
            <MessageSquare size={13} /> AI Assistant
          </button>
          {appliedSnapshot && (
            <button
              onClick={undoChatSuggestion}
              className="ml-auto flex items-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-semibold text-amber-700 hover:bg-amber-50 transition-colors"
              title="Undo the last AI edit"
            >
              <Undo2 size={13} /> Undo
            </button>
          )}
        </div>

        {panel === 'preview' ? (
          <div className="flex-1 overflow-y-auto p-6">
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

              <div className="p-4 text-[13px] leading-relaxed text-ink min-h-[140px]">
                {title && <div className="font-bold text-[14px] mb-2">{title}</div>}
                {body.trim() ? (
                  <div
                    className="rich-preview"
                    dangerouslySetInnerHTML={{ __html: sanitizeHtml(bodyHtml || plainTextToHtml(body)) }}
                  />
                ) : (
                  <span className="text-faint">Your post copy will appear here as you write…</span>
                )}
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
        ) : (
          <div className="flex-1 flex flex-col min-h-0">
            {/* Conversation */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.length === 0 && (
                <div className="rounded-xl border border-edge bg-surface p-4">
                  <div className="flex items-center gap-2 text-[12px] font-bold text-ink mb-1">
                    <Sparkles size={13} className="text-brand-600" /> Work on this draft with AI
                  </div>
                  <p className="text-[11px] text-sub leading-relaxed">
                    Ask for edits, a stronger hook, research, data, sources or image prompts. The assistant sees your
                    current title, post text and image brief.
                  </p>
                </div>
              )}

              {messages.map((message, index) => (
                <div key={index} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                  <div
                    className={`rounded-xl px-3.5 py-2.5 text-[12px] leading-relaxed whitespace-pre-wrap ${
                      message.role === 'user'
                        ? 'bg-brand-500 text-white max-w-[88%]'
                        : 'bg-surface border border-edge text-ink max-w-full'
                    }`}
                  >
                    {message.content}

                    {message.sources && message.sources.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-edge space-y-1">
                        <div className="text-[9px] font-bold uppercase tracking-widest text-faint">Sources</div>
                        {message.sources.map((source) => (
                          <a
                            key={source.url}
                            href={source.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block text-[11px] text-brand-600 hover:underline truncate"
                            title={source.snippet || source.title}
                          >
                            {source.title}
                          </a>
                        ))}
                      </div>
                    )}

                    {(message.suggested_body || message.image_prompt) && (
                      <div className="mt-2 pt-2 border-t border-edge">
                        <div className="flex flex-wrap gap-1.5">
                          {message.suggested_body && (
                            <button
                              onClick={() => applyChatSuggestion(message, index)}
                              className={`flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-semibold transition-colors ${
                                appliedDraftIndex === index
                                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                  : 'bg-brand-500 text-white hover:bg-brand-600'
                              }`}
                            >
                              {appliedDraftIndex === index ? <CheckCircle2 size={11} /> : <Wand2 size={11} />}
                              {appliedDraftIndex === index ? 'Applied to draft' : 'Apply to draft'}
                            </button>
                          )}
                          {message.image_prompt && (
                            <button
                              onClick={() => useChatImagePrompt(message, index)}
                              className={`flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-semibold transition-colors ${
                                appliedPromptIndex === index
                                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                                  : 'border-edge bg-raised text-ink hover:bg-edge'
                              }`}
                            >
                              {appliedPromptIndex === index ? <CheckCircle2 size={11} /> : <Image size={11} />}
                              {appliedPromptIndex === index ? 'Prompt applied' : 'Use image prompt'}
                            </button>
                          )}
                        </div>
                        {message.image_prompt && (
                          <div className="mt-1.5 space-y-1.5">
                            <textarea
                              value={editedPrompts[index] ?? message.image_prompt}
                              onChange={(e) => setEditedPrompts((prev) => ({ ...prev, [index]: e.target.value }))}
                              rows={3}
                              className="w-full rounded-md border border-edge bg-raised px-2 py-1.5 text-[10px] leading-snug text-ink resize-y max-h-32 overflow-y-auto focus:outline-none focus:border-brand-500"
                            />
                            <button
                              onClick={() => useChatImagePrompt({ ...message, image_prompt: editedPrompts[index] ?? message.image_prompt! }, index)}
                              className={`flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-semibold transition-colors ${
                                appliedPromptIndex === index
                                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                                  : 'border-edge bg-raised text-ink hover:bg-edge'
                              }`}
                            >
                              {appliedPromptIndex === index ? <CheckCircle2 size={11} /> : <Image size={11} />}
                              {appliedPromptIndex === index ? 'Prompt applied' : 'Use this prompt'}
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {chatting && (
                <div className="flex items-center gap-2 text-[11px] text-sub px-1">
                  <Loader2 size={12} className="animate-spin" />
                  Thinking…
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Composer */}
            <div className="border-t border-edge p-3 bg-surface">
              <div className="flex flex-wrap gap-1 mb-2">
                {QUICK_PROMPTS.map((quick) => (
                  <button
                    key={quick.label}
                    onClick={() => sendChat(quick.prompt)}
                    disabled={chatting}
                    className="rounded-full border border-edge bg-raised px-2.5 py-1 text-[10px] font-semibold text-sub hover:text-brand-700 hover:border-brand-300 transition-colors disabled:opacity-50"
                  >
                    {quick.label}
                  </button>
                ))}
              </div>
              <textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendChat();
                  }
                }}
                rows={2}
                placeholder="Ask for edits, research or image prompts… (Enter to send)"
                className="w-full resize-none rounded-lg border border-edge bg-raised px-3 py-2 text-[12px] text-ink placeholder-faint focus:outline-none focus:border-brand-500"
              />
              <div className="flex items-center justify-between mt-2 gap-2">
                <div className="flex items-center gap-1.5 text-[10px] text-faint">
                  <Globe size={11} /> Searches the web only when it needs current data
                </div>
                <button
                  onClick={() => sendChat()}
                  disabled={chatting || !chatInput.trim()}
                  className="flex items-center gap-1.5 rounded-lg bg-brand-500 text-white px-3 py-1.5 text-[11px] font-semibold hover:bg-brand-600 transition-colors disabled:opacity-50"
                >
                  {chatting ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Send
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}