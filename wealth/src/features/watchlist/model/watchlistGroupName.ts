import type { WatchlistGroupRulesDto } from "../api/watchlistApiTypes";
const segmenter = new Intl.Segmenter("zh", {
  granularity: "grapheme"
});
const encoder = new TextEncoder();
const forbidden = /[\p{Cc}\p{Zl}\p{Zp}\p{Cs}]/u;
const format = /\p{Cf}/u;
const visible = /[\p{L}\p{N}\p{P}\p{S}]/u;
const space = /^\p{Zs}+$/u;
export function validateWatchlistGroupName(raw: string, rules: WatchlistGroupRulesDto, existingNames: string[]) {
  const fail = (error: string) => ({
    name: "",
    error
  });
  if (encoder.encode(raw).length > rules.nameMaxUtf8Bytes) return fail(`名称输入不能超过 ${rules.nameMaxUtf8Bytes} UTF-8 字节`);
  // ECMAScript trim implements exactly the trim set frozen in LLD 7.2.
  const name = raw.normalize("NFC").trim();
  if (encoder.encode(name).length > rules.nameMaxUtf8Bytes) return fail("名称输入过长");
  if (!name) return fail("请输入分组名称");
  for (const char of name) if (forbidden.test(char) || format.test(char) && char !== "\u200c" && char !== "\u200d") return fail("名称不能包含控制字符");
  const segments = [...segmenter.segment(name)];
  if (segments.some(({
    segment
  }) => !space.test(segment) && !visible.test(segment))) return fail("名称需要包含正常可见字符");
  if (segments.length > rules.nameMaxVisibleChars) return fail(`名称最多 ${rules.nameMaxVisibleChars} 个可见字符`);
  if (existingNames.some(existing => existing.normalize("NFC").trim() === name)) return fail("分组名称已存在");
  return {
    name,
    error: ""
  };
}
