import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const assets = resolve(root, "src/assets/auth");
const digest = (name: string) => createHash("sha256").update(readFileSync(resolve(assets, name))).digest("hex");
const pngSize = (name: string) => {
  const file = readFileSync(resolve(assets, name));
  expect(file.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  return [file.readUInt32BE(16), file.readUInt32BE(20)];
};

describe("Wealth document and approved assets — U12", () => {
  it("reads the actual Vite HTML entry, with one title and only the approved seal icons", () => {
    const html = readFileSync(resolve(root, "index.html"), "utf8");
    const doc = new DOMParser().parseFromString(html, "text/html");
    expect(doc.querySelectorAll("title")).toHaveLength(1);
    expect(doc.title).toBe("财势天下");
    const icons = [...doc.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]')];
    expect(icons).toHaveLength(2);
    expect(icons.map(icon => ({ href: icon.getAttribute("href"), sizes: icon.getAttribute("sizes"), type: icon.type }))).toEqual([
      { href: "/src/assets/auth/wealth-world-seal-favicon-32.png?no-inline", sizes: "32x32", type: "image/png" },
      { href: "/src/assets/auth/wealth-world-seal-favicon-64.png?no-inline", sizes: "64x64", type: "image/png" },
    ]);
    expect(html).not.toMatch(/favicon-wealth|财势乾坤|\/Users\/|\/private\/|https?:\/\//);
  });

  it("preserves the accepted background and original seal bytes and dimensions", () => {
    expect(pngSize("wealth-world-login-bg-screen.png")).toEqual([1556, 1011]);
    expect(digest("wealth-world-login-bg-screen.png")).toBe("9fee6c58302760a29db77f28320bb6f15f6ca5f2c64fca460417dc070db67426");
    expect(pngSize("wealth-world-seal.png")).toEqual([1254, 1254]);
    expect(digest("wealth-world-seal.png")).toBe("d45a218fef16c053f1d7119769b5e293b592e5112e529568077f999d51e05430");
  });

  it("uses the frozen 948px crop derivatives with the specified favicon budget", () => {
    expect(pngSize("wealth-world-seal-favicon-32.png")).toEqual([32, 32]);
    expect(pngSize("wealth-world-seal-favicon-64.png")).toEqual([64, 64]);
    expect(digest("wealth-world-seal-favicon-32.png")).toBe("00432078af48e9e9f5e2e7fd0d20e024d330b113789a8d7be2108def00aaf5dc");
    expect(digest("wealth-world-seal-favicon-64.png")).toBe("ce550ccdf0b373d97465b1e4be3d95f759bfb219be04106a5d2654ee523818f4");
    expect([32, 64].reduce((sum, size) => sum + statSync(resolve(assets, `wealth-world-seal-favicon-${size}.png`)).size, 0)).toBeLessThan(32 * 1024);
  });

  it("ships only the three local WOFF2 faces with licenses, swap and no font CDN", () => {
    const names = ["cs-auth-serif-600.woff2", "cs-auth-sans-400.woff2", "cs-auth-sans-500.woff2"];
    for (const name of names) expect(readFileSync(resolve(assets, "fonts", name)).subarray(0, 4).toString()).toBe("wOF2");
    expect(names.reduce((sum, name) => sum + statSync(resolve(assets, "fonts", name)).size, 0)).toBeLessThan(1024 * 1024);
    for (const family of ["Serif", "Sans"]) {
      expect(readFileSync(resolve(assets, "fonts", `Noto${family}SC-OFL.txt`), "utf8")).toContain("SIL OPEN FONT LICENSE Version 1.1");
    }
    const css = readFileSync(resolve(root, "src/features/auth/ui/login-fonts.css"), "utf8");
    expect(css.match(/@font-face/g)).toHaveLength(3);
    expect(css.match(/font-display: swap/g)).toHaveLength(3);
    expect(css).not.toMatch(/https?:\/\/|\/Users\//);
  });
});
