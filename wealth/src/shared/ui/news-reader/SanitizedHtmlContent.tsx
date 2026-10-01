import DOMPurify from "dompurify";
import { useMemo, type SyntheticEvent } from "react";


const ALLOWED_TAGS = [
  "article",
  "section",
  "header",
  "footer",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "p",
  "br",
  "hr",
  "blockquote",
  "pre",
  "code",
  "strong",
  "em",
  "b",
  "i",
  "u",
  "s",
  "ul",
  "ol",
  "li",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "span",
  "div",
  "img",
] as const;

const IMAGE_SOURCE_ATTRIBUTES = ["src", "data-src", "data-original"] as const;
const IMAGE_INPUT_ATTRIBUTES = [...IMAGE_SOURCE_ATTRIBUTES, "alt"] as const;
const IMAGE_OUTPUT_ATTRIBUTES = ["src", "alt", "loading", "decoding", "referrerpolicy"] as const;
const IMAGE_HOST_ALLOWLIST = new Set([
  "e.thsi.cn",
  "u.thsi.cn",
  "ftapi.10jqka.com.cn",
  "image.cls.cn",
]);
const MAX_IMAGES_PER_ARTICLE = 24;
const SELF_CLOSING_IFRAME_PATTERN = /<iframe\b(?:[^>"']|"[^"]*"|'[^']*')*\/\s*>/gi;


export function SanitizedHtmlContent({ html }: { html: string }) {
  const sanitizedHtml = useMemo(() => sanitizeNewsHtml(html), [html]);

  return (
    <article
      className="news-reader-html"
      dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
      onErrorCapture={hideFailedImage}
    />
  );
}

function removeUnsupportedSelfClosingIframes(html: string): string {
  return html.replace(SELF_CLOSING_IFRAME_PATTERN, "");
}

function sanitizeNewsHtml(html: string): string {
  const candidateHtml = DOMPurify.sanitize(removeUnsupportedSelfClosingIframes(html), {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    ALLOWED_ATTR: [...IMAGE_INPUT_ATTRIBUTES],
    ALLOW_DATA_ATTR: false,
  });
  const template = document.createElement("template");
  template.innerHTML = candidateHtml;

  for (const element of template.content.querySelectorAll("*:not(img)")) {
    for (const attribute of [...element.attributes]) element.removeAttribute(attribute.name);
  }

  let retainedImageCount = 0;
  for (const image of template.content.querySelectorAll("img")) {
    const safeSource = readSafeImageSource(image);
    if (safeSource === null || retainedImageCount >= MAX_IMAGES_PER_ARTICLE) {
      image.remove();
      continue;
    }

    const alt = image.getAttribute("alt")?.trim() ?? "";
    for (const attribute of [...image.attributes]) image.removeAttribute(attribute.name);
    image.setAttribute("src", safeSource);
    image.setAttribute("alt", alt);
    image.setAttribute("loading", "lazy");
    image.setAttribute("decoding", "async");
    image.setAttribute("referrerpolicy", "no-referrer");
    retainedImageCount += 1;
  }

  return DOMPurify.sanitize(template.innerHTML, {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    ALLOWED_ATTR: [...IMAGE_OUTPUT_ATTRIBUTES],
    ALLOW_DATA_ATTR: false,
  });
}

function readSafeImageSource(image: HTMLImageElement): string | null {
  for (const attribute of IMAGE_SOURCE_ATTRIBUTES) {
    const safeSource = normalizeImageSource(image.getAttribute(attribute));
    if (safeSource !== null) return safeSource;
  }
  return null;
}

function normalizeImageSource(rawSource: string | null): string | null {
  const trimmed = rawSource?.trim();
  if (!trimmed) return null;
  const candidate = trimmed.startsWith("//") ? `https:${trimmed}` : trimmed;

  try {
    const parsed = new URL(candidate);
    if (parsed.protocol === "http:") parsed.protocol = "https:";
    if (
      parsed.protocol !== "https:" ||
      parsed.username !== "" ||
      parsed.password !== "" ||
      parsed.port !== "" ||
      !IMAGE_HOST_ALLOWLIST.has(parsed.hostname.toLowerCase())
    ) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

function hideFailedImage(event: SyntheticEvent<HTMLElement>): void {
  if (event.target instanceof HTMLImageElement) event.target.hidden = true;
}
