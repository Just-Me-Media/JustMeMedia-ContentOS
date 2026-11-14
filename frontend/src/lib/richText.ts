/**
 * Lightweight rich-text helpers for the Studio editor.
 *
 * The editor is a contentEditable surface. Drafts keep their formatting in
 * `body_html` while publishing and exporting continue to use plain-text `body`.
 */

const ALLOWED_TAGS = new Set([
  'B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'BR', 'P', 'DIV',
  'H1', 'H2', 'H3', 'UL', 'OL', 'LI', 'A', 'SPAN', 'HR', 'BLOCKQUOTE',
]);

const BLOCK_TAGS = new Set([
  'P', 'DIV', 'H1', 'H2', 'H3', 'UL', 'OL', 'LI', 'BLOCKQUOTE',
]);

const SAFE_COLOR = /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|[a-z]+)$/i;

export function isHtml(value: string): boolean {
  return /<\/?[a-z][\s\S]*>/i.test(value || '');
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Convert stored plain-text bodies (AI output, old drafts) into editor HTML. */
export function plainTextToHtml(text: string): string {
  if (!text) return '';
  return escapeHtml(text).replace(/\r\n/g, '\n').replace(/\n/g, '<br>');
}

function sanitizeStyle(style: string): string {
  const declarations = style.split(';').map((part) => part.trim()).filter(Boolean);
  const safe: string[] = [];
  for (const declaration of declarations) {
    const [rawProp, ...rawValue] = declaration.split(':');
    const prop = rawProp.trim().toLowerCase();
    const value = rawValue.join(':').trim();
    if (!value) continue;
    if (prop === 'color' || prop === 'background-color') {
      if (SAFE_COLOR.test(value)) safe.push(`${prop}: ${value}`);
    } else if (prop === 'font-weight') {
      if (/^(normal|bold|[1-9]00)$/i.test(value)) safe.push(`${prop}: ${value}`);
    } else if (prop === 'font-style') {
      if (/^(normal|italic|oblique)$/i.test(value)) safe.push(`${prop}: ${value}`);
    } else if (prop === 'text-decoration' || prop === 'text-decoration-line') {
      if (/^(none|underline|line-through|underline line-through)$/i.test(value)) {
        safe.push(`${prop}: ${value}`);
      }
    }
  }
  return safe.join('; ');
}

function cleanNode(node: Node, doc: Document): Node | null {
  if (node.nodeType === Node.TEXT_NODE) {
    return doc.createTextNode(node.nodeValue || '');
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return null;

  const el = node as HTMLElement;
  const tag = el.tagName.toUpperCase();

  // Safari's foreColor can produce <font color="...">; convert it to a span.
  if (tag === 'FONT') {
    const span = doc.createElement('span');
    const color = (el.getAttribute('color') || '').trim();
    if (color && SAFE_COLOR.test(color)) span.setAttribute('style', `color: ${color}`);
    el.childNodes.forEach((child) => {
      const cleaned = cleanNode(child, doc);
      if (cleaned) span.appendChild(cleaned);
    });
    return span;
  }

  // Unwrap unknown tags but keep their (cleaned) children.
  if (!ALLOWED_TAGS.has(tag)) {
    const fragment = doc.createDocumentFragment();
    el.childNodes.forEach((child) => {
      const cleaned = cleanNode(child, doc);
      if (cleaned) fragment.appendChild(cleaned);
    });
    return fragment;
  }

  const out = doc.createElement(tag.toLowerCase());

  if (tag === 'A') {
    const href = (el.getAttribute('href') || '').trim();
    if (/^(https?:|mailto:|#)/i.test(href)) {
      out.setAttribute('href', href);
      out.setAttribute('target', '_blank');
      out.setAttribute('rel', 'noopener noreferrer');
    }
  }

  if (tag === 'SPAN' || tag === 'P' || tag === 'DIV' || tag === 'H1' || tag === 'H2' || tag === 'H3' || tag === 'LI') {
    const style = sanitizeStyle(el.getAttribute('style') || '');
    if (style) out.setAttribute('style', style);
  }

  el.childNodes.forEach((child) => {
    const cleaned = cleanNode(child, doc);
    if (cleaned) out.appendChild(cleaned);
  });

  return out;
}

/** Strip anything script-like or unsupported before rendering authored HTML. */
export function sanitizeHtml(html: string): string {
  if (!html) return '';
  const doc = new DOMParser().parseFromString(`<div id="root">${html}</div>`, 'text/html');
  const root = doc.getElementById('root');
  if (!root) return '';
  const container = doc.createElement('div');
  root.childNodes.forEach((child) => {
    const cleaned = cleanNode(child, doc);
    if (cleaned) container.appendChild(cleaned);
  });
  return container.innerHTML;
}

/** Flatten editor HTML into the plain text used for publishing, search and export. */
export function htmlToPlainText(html: string): string {
  if (!html) return '';
  if (!isHtml(html)) return html;

  const doc = new DOMParser().parseFromString(`<div id="root">${html}</div>`, 'text/html');
  const root = doc.getElementById('root');
  if (!root) return '';
  const parts: string[] = [];

  const pushNewline = () => {
    if (parts.length && !parts[parts.length - 1].endsWith('\n')) parts.push('\n');
  };

  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push((node.nodeValue || '').replace(/\u00a0/g, ' '));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;

    const el = node as HTMLElement;
    const tag = el.tagName.toUpperCase();

    if (tag === 'BR') {
      parts.push('\n');
      return;
    }
    if (tag === 'HR') {
      pushNewline();
      parts.push('---');
      pushNewline();
      return;
    }
    if (tag === 'LI') {
      pushNewline();
      parts.push('• ');
      el.childNodes.forEach(walk);
      pushNewline();
      return;
    }
    if (BLOCK_TAGS.has(tag)) pushNewline();
    el.childNodes.forEach(walk);
    if (BLOCK_TAGS.has(tag)) pushNewline();
  };

  root.childNodes.forEach(walk);

  return parts
    .join('')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
