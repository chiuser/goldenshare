import { useState } from "react";

/** Expand the backend's complete tie set without comparing rounded rates. */
export function ReturnDates({ dates }: { dates: string[] }) {
  const [expanded,setExpanded] = useState(false);
  if (!dates.length) return <>暂无有效结果</>;
  if (dates.length === 1) return <>{dates[0]}</>;
  return <span className="ta-return-tie-dates">{dates[0]} 等 {dates.length} 天
    <button type="button" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded ? "收起日期" : "展开日期"}</button>
    {expanded && <span>{dates.join("、")}</span>}
  </span>;
}
