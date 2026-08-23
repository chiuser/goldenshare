import DOMPurify from "dompurify";
import { useMemo } from "react";


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
] as const;


export function SanitizedHtmlContent({ html }: { html: string }) {
  const sanitizedHtml = useMemo(
    () =>
      DOMPurify.sanitize(html, {
        ALLOWED_TAGS: [...ALLOWED_TAGS],
        ALLOWED_ATTR: [],
      }),
    [html],
  );

  return <article className="news-reader-html" dangerouslySetInnerHTML={{ __html: sanitizedHtml }} />;
}
