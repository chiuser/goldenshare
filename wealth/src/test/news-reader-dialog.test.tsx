import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NewsReaderDialog } from "../shared/ui/news-reader/NewsReaderDialog";
import type { NewsReaderDialogState, NewsReaderViewModel } from "../shared/ui/news-reader/newsReaderTypes";


function readyItem(overrides: Partial<NewsReaderViewModel> = {}): NewsReaderViewModel {
  return {
    newsId: "news-1",
    title: "测试新闻",
    source: "Tushare",
    publishTime: "2026-08-23T10:00:00+08:00",
    displayPublishTime: "2026/8/23 10:00:00",
    readerMode: "TEXT",
    url: null,
    html: null,
    content: "普通新闻正文",
    ...overrides,
  };
}


function readyState(item: NewsReaderViewModel): NewsReaderDialogState {
  return { status: "ready", requestId: 1, item };
}


afterEach(() => {
  vi.useRealTimers();
  document.body.style.overflow = "";
  document.body.style.paddingRight = "";
});


describe("NewsReaderDialog", () => {
  it("renders the complete title and orders publish time before the labeled source", () => {
    const title = "【伊朗外长：伊朗从未害怕过美国制裁】当地时间23日，伊朗外长阿拉格齐表示，伊朗从未害怕过美国制裁，他们所有的举动都会失败";
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({
            title,
            source: "sina",
            displayPublishTime: "2026年8月23日 19:19:52",
          }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: title })).toHaveTextContent(title);
    const publishTime = screen.getByText("2026年8月23日 19:19:52");
    const source = screen.getByText("来源：sina");
    expect(publishTime.parentElement?.children[0]).toBe(publishTime);
    expect(publishTime.parentElement?.children[1]).toBe(source);
    expect(publishTime.parentElement?.querySelector("i")).toBeNull();
  });

  it("omits the source label when the source is absent", () => {
    render(
      <NewsReaderDialog
        state={readyState(readyItem({ source: null }))}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.queryByText(/来源：/)).not.toBeInTheDocument();
    expect(screen.getByText("2026/8/23 10:00:00")).toBeInTheDocument();
  });

  it("uses native modal lifecycle, Escape close, and ignores backdrop clicks", async () => {
    const onClose = vi.fn();
    const showModalSpy = vi.spyOn(HTMLDialogElement.prototype, "showModal");
    const rendered = render(
      <NewsReaderDialog
        state={{
          status: "loading",
          newsId: "news-1",
          title: "测试新闻",
          publishTime: "2026-08-23T10:00:00+08:00",
          readerMode: "TEXT",
          requestId: 1,
        }}
        onClose={onClose}
        onRetry={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(showModalSpy).toHaveBeenCalledOnce();
    const closeButton = screen.getByRole("button", { name: "关闭新闻阅读器" });
    await waitFor(() => expect(closeButton).toHaveFocus());
    expect(closeButton.querySelector('svg[data-icon-ref="material:close"]')).toBeInTheDocument();
    expect(closeButton).not.toHaveTextContent("×");

    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
    const cancelEvent = new Event("cancel", { bubbles: false, cancelable: true });
    dialog.dispatchEvent(cancelEvent);
    expect(cancelEvent.defaultPrevented).toBe(true);
    expect(onClose).toHaveBeenCalledOnce();

    const closeSpy = vi.spyOn(HTMLDialogElement.prototype, "close");
    rendered.rerender(<NewsReaderDialog state={{ status: "closed" }} onClose={onClose} onRetry={vi.fn()} />);
    expect(closeSpy).toHaveBeenCalledOnce();
  });

  it("locks and restores the exact body inline styles", () => {
    document.body.style.overflow = "scroll";
    document.body.style.paddingRight = "7px";
    const rendered = render(
      <NewsReaderDialog state={readyState(readyItem())} onClose={vi.fn()} onRetry={vi.fn()} />,
    );

    expect(document.body.style.overflow).toBe("hidden");
    rendered.unmount();
    expect(document.body.style.overflow).toBe("scroll");
    expect(document.body.style.paddingRight).toBe("7px");
  });

  it("renders URL with the fixed sandbox contract", () => {
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({ readerMode: "URL", url: "https://example.com/news", content: null }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    const frame = screen.getByTitle("测试新闻");
    expect(frame).toHaveAttribute("src", "https://example.com/news");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(frame.getAttribute("sandbox")).not.toContain("allow-same-origin");
  });

  it("bounds URL frame loading and exposes an explicit retry", async () => {
    vi.useFakeTimers();
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({ readerMode: "URL", url: "https://example.com/slow", content: null }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(12_000);
    });
    expect(screen.getByText("页面暂时无法嵌入")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("sanitizes HTML with no attributes or active elements", () => {
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({
            readerMode: "HTML",
            html: '<article><p onclick="alert(1)" style="color:red" src="https://image.cls.cn/not-an-image.png" data-src="//image.cls.cn/not-an-image.png" alt="错误属性">安全正文</p><script>alert(1)</script><style>body{display:none}</style><form><input></form><iframe src="https://bad"></iframe><a href="https://bad">链接文字</a></article>',
            content: null,
          }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("安全正文")).toBeInTheDocument();
    expect(screen.getByText("链接文字")).toBeInTheDocument();
    const htmlArticle = document.querySelector(".news-reader-html");
    expect(htmlArticle?.querySelector("script")).toBeNull();
    expect(htmlArticle?.querySelector("style")).toBeNull();
    expect(htmlArticle?.querySelector("form")).toBeNull();
    expect(htmlArticle?.querySelector("iframe")).toBeNull();
    expect(htmlArticle?.querySelector("a")).toBeNull();
    expect(htmlArticle?.querySelector("[onclick]")).toBeNull();
    expect(htmlArticle?.querySelector("[style]")).toBeNull();
    expect(htmlArticle?.querySelector("p")?.attributes).toHaveLength(0);
  });

  it("normalizes allowlisted images and rebuilds only safe attributes", () => {
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({
            readerMode: "HTML",
            html: [
              '<p>图片正文</p>',
              '<img src="https://e.thsi.cn/a.jpg" alt=" 图一 " width="120" onerror="alert(1)" srcset="https://evil.example/a.jpg 2x">',
              '<img src="//u.thsi.cn/b.jpg" style="width:9999px" onload="alert(1)">',
              '<img src="http://ftapi.10jqka.com.cn/c.png" class="source-image" id="source-image">',
              '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAUEBA==" data-src="//image.cls.cn/d.png" data-extra="bad">',
            ].join(""),
            content: null,
          }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    const images = [...document.querySelectorAll(".news-reader-html img")];
    expect(images.map((image) => image.getAttribute("src"))).toEqual([
      "https://e.thsi.cn/a.jpg",
      "https://u.thsi.cn/b.jpg",
      "https://ftapi.10jqka.com.cn/c.png",
      "https://image.cls.cn/d.png",
    ]);
    expect(images[0]).toHaveAttribute("alt", "图一");
    for (const image of images) {
      expect(image).toHaveAttribute("loading", "lazy");
      expect(image).toHaveAttribute("decoding", "async");
      expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
      expect(image).not.toHaveAttribute("width");
      expect(image).not.toHaveAttribute("style");
      expect(image).not.toHaveAttribute("class");
      expect(image).not.toHaveAttribute("onerror");
      expect(image).not.toHaveAttribute("onload");
      expect(image).not.toHaveAttribute("id");
      expect(image).not.toHaveAttribute("srcset");
      expect(image).not.toHaveAttribute("data-src");
      expect(image).not.toHaveAttribute("data-extra");
    }
  });

  it("removes non-allowlisted, relative, private, and dangerous image sources", () => {
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({
            readerMode: "HTML",
            html: [
              '<p>危险图片前</p>',
              '<img src="/relative.png">',
              '<img src="https://example.com/unknown.png">',
              '<img src="https://image.cls.cn.evil.example/lookalike.png">',
              '<img src="https://localhost/local.png">',
              '<img src="https://127.0.0.1/private.png">',
              '<img src="https://[::1]/private.png">',
              '<img src="https://user:password@image.cls.cn/credential.png">',
              '<img src="https://image.cls.cn:444/custom-port.png">',
              '<img src="data:image/svg+xml,&lt;svg&gt;&lt;/svg&gt;">',
              '<img src="blob:https://image.cls.cn/id">',
              '<img src="javascript:alert(1)">',
              '<p>危险图片后</p>',
            ].join(""),
            content: null,
          }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(document.querySelector(".news-reader-html img")).toBeNull();
    expect(screen.getByText("危险图片前")).toBeInTheDocument();
    expect(screen.getByText("危险图片后")).toBeInTheDocument();
  });

  it("keeps at most 24 safe images and hides one failed image without removing later text", () => {
    const imagesHtml = Array.from(
      { length: 25 },
      (_, index) => `<img src="https://image.cls.cn/image-${index + 1}.png" alt="图片${index + 1}">`,
    ).join("");
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({
            readerMode: "HTML",
            html: `<img src="/invalid-does-not-use-quota.png">${imagesHtml}<p>图片后的正文</p>`,
            content: null,
          }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    const images = document.querySelectorAll(".news-reader-html img");
    expect(images).toHaveLength(24);
    expect(document.querySelector('[alt="图片25"]')).toBeNull();
    fireEvent.error(images[0]);
    expect(images[0]).toHaveAttribute("hidden");
    expect(screen.getByText("图片后的正文")).toBeInTheDocument();
  });

  it("removes malformed self-closing iframes before parsing and preserves following article text", () => {
    render(
      <NewsReaderDialog
        state={readyState(
          readyItem({
            readerMode: "HTML",
            html: '<div><p><iframe width="100%" src="https://stockpage.example/news"/></p><p>iframe 后的完整新闻正文</p></div>',
            content: null,
          }),
        )}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("iframe 后的完整新闻正文")).toBeInTheDocument();
    expect(document.querySelector("iframe")).toBeNull();
    expect(document.querySelector('[src="https://stockpage.example/news"]')).toBeNull();
  });

  it("renders HTML-looking text as plain text", () => {
    render(
      <NewsReaderDialog
        state={readyState(readyItem({ content: "<script>not executed</script>" }))}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("<script>not executed</script>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("keeps the PC safe gutter contract without a mobile branch", () => {
    const css = readFileSync(resolve(process.cwd(), "src/shared/ui/news-reader/news-reader.css"), "utf8");
    expect(css).toContain("calc(100vw - 64px)");
    expect(css).toContain("calc(100vh - 64px)");
    expect(css).toContain("grid-template-rows: auto minmax(0, 1fr)");
    expect(css).toContain("overflow-wrap: anywhere");
    expect(css).toMatch(/\.news-reader-header\s*{[^}]*position: relative;/s);
    expect(css).toMatch(/\.news-reader-heading\s*{[^}]*padding: 0 52px;[^}]*text-align: center;[^}]*width: 100%;/s);
    expect(css).toMatch(/\.news-reader-meta\s*{[^}]*justify-content: center;/s);
    expect(css).toMatch(/\.news-reader-close\s*{[^}]*position: absolute;[^}]*right: 18px;[^}]*top: 14px;/s);
    expect(css).toMatch(/\.news-reader-html img\s*{[^}]*height: auto;[^}]*max-width: 100%;/s);
    expect(css).not.toContain("text-overflow: ellipsis");
    expect(css).not.toContain("white-space: nowrap");
    expect(css).not.toContain("@media");
  });

  it("keeps shared reader independent and the unsafe HTML sink isolated", () => {
    const root = resolve(process.cwd(), "src");
    const dialogSource = readFileSync(resolve(root, "shared/ui/news-reader/NewsReaderDialog.tsx"), "utf8");
    const sanitizerSource = readFileSync(resolve(root, "shared/ui/news-reader/SanitizedHtmlContent.tsx"), "utf8");
    const marketPageSource = readFileSync(resolve(root, "pages/market-overview/MarketOverviewPage.tsx"), "utf8");
    const panelSource = readFileSync(resolve(root, "features/market-overview/news/MarketNewsPanel.tsx"), "utf8");

    expect(dialogSource).not.toContain("features/market-overview");
    expect(dialogSource).not.toContain("dangerouslySetInnerHTML");
    expect(sanitizerSource.match(/dangerouslySetInnerHTML/g)).toHaveLength(1);
    expect(marketPageSource.match(/<NewsReaderDialog/g)).toHaveLength(1);
    expect(panelSource).not.toContain('aria-disabled="true"');
  });
});
