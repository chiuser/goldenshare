import React, {useLayoutEffect, useRef, useState} from 'react';
import {placeQuadrantLabels, QUADRANT_LAYOUT} from './quadrant-layout.mjs';

export function NativeQuadrantLabels({plot, rows, spec}) {
  const host = useRef(null), native = useRef(null), scroll = useRef(null), centered = useRef(false);
  const [geometry,setGeometry] = useState(null);
  const signature = JSON.stringify({rows:rows.map(r=>[r.行业,r[spec.x],r[spec.y]]),spec});
  const enabled = spec.type==='scatter' && spec.x==='收入增长（%）' && spec.y==='利润率变化（百分点）'
    && !spec.groupBy && !spec.logX && !spec.logY;
  useLayoutEffect(()=>{
    if (!enabled) {setGeometry(null);return;}
    let frame = null, disposed = false;
    const measure = ()=>{
      frame=null;
      if (disposed || !host.current || !native.current) return;
      const h=host.current.getBoundingClientRect();
      const grid=native.current.querySelector('.recharts-cartesian-grid')?.getBoundingClientRect();
      const marks=[...native.current.querySelectorAll('.recharts-scatter-symbol')];
      if (!grid?.width || !grid.height || marks.length!==rows.length) {setGeometry(null);return;}
      const bounds={left:grid.left-h.left,right:grid.right-h.left,top:grid.top-h.top,bottom:grid.bottom-h.top};
      const xd=spec.xDomain, yd=spec.valueDomain;
      if (!xd || !yd || xd.length!==2 || yd.length!==2) {setGeometry(null);return;}
      const points=marks.map((m,i)=>{
        const rect=m.getBoundingClientRect(), row=rows[i];
        return {name:row.行业,x:rect.left+rect.width/2-h.left,y:rect.top+rect.height/2-h.top};
      });
      // Refuse an order/scale mismatch instead of attaching a name to a different dot.
      const valid=points.every((p,i)=>Math.abs(p.x-(bounds.left+(rows[i][spec.x]-xd[0])/(xd[1]-xd[0])*grid.width))<1
        && Math.abs(p.y-(bounds.bottom-(rows[i][spec.y]-yd[0])/(yd[1]-yd[0])*grid.height))<1);
      if (!valid) {setGeometry(null);return;}
      try {
        const zero={x:bounds.left-xd[0]/(xd[1]-xd[0])*grid.width,y:bounds.bottom+yd[0]/(yd[1]-yd[0])*grid.height};
        const labels=placeQuadrantLabels(points,bounds,zero);
        const next={width:h.width,height:h.height,labels,bounds,zero};
        setGeometry(old=>JSON.stringify(old)===JSON.stringify(next)?old:next);
        if (!centered.current && scroll.current && scroll.current.clientWidth<h.width) {
          scroll.current.scrollLeft=(h.width-scroll.current.clientWidth)/2;
          centered.current=true;
        }
      } catch {setGeometry(null);}
    };
    const schedule=()=>{if(frame===null)frame=requestAnimationFrame(measure);};
    const resize=new ResizeObserver(schedule);resize.observe(host.current);
    const mutations=new MutationObserver(schedule);
    mutations.observe(native.current,{childList:true,subtree:true,attributes:true,attributeFilter:['d','transform','cx','cy','width','height']});
    schedule();
    return ()=>{disposed=true;resize.disconnect();mutations.disconnect();if(frame!==null)cancelAnimationFrame(frame);};
  },[signature,enabled]);
  return <div ref={scroll} className="quadrant-scroll"><div ref={host} className="named-quadrant" style={{minWidth:QUADRANT_LAYOUT.minWidth}} data-label-count={geometry?.labels.length??0}>
    {geometry&&<svg className="quadrant-fill-layer" width={geometry.width} height={geometry.height} aria-hidden="true">
      <rect data-quadrant-fill="income-down-margin-up" x={geometry.bounds.left} y={geometry.bounds.top}
        width={geometry.zero.x-geometry.bounds.left} height={geometry.zero.y-geometry.bounds.top} fill={QUADRANT_LAYOUT.fills.incomeDownMarginUp}/>
      <rect data-quadrant-fill="both-up" x={geometry.zero.x} y={geometry.bounds.top}
        width={geometry.bounds.right-geometry.zero.x} height={geometry.zero.y-geometry.bounds.top} fill={QUADRANT_LAYOUT.fills.bothUp}/>
      <rect data-quadrant-fill="both-down" x={geometry.bounds.left} y={geometry.zero.y}
        width={geometry.zero.x-geometry.bounds.left} height={geometry.bounds.bottom-geometry.zero.y} fill={QUADRANT_LAYOUT.fills.bothDown}/>
      <rect data-quadrant-fill="income-up-margin-down" x={geometry.zero.x} y={geometry.zero.y}
        width={geometry.bounds.right-geometry.zero.x} height={geometry.bounds.bottom-geometry.zero.y} fill={QUADRANT_LAYOUT.fills.incomeUpMarginDown}/>
    </svg>}
    <div ref={native} className="native-quadrant-plot">{plot}</div>
    {geometry&&<svg className="quadrant-name-layer" width={geometry.width} height={geometry.height} aria-label="29个一级行业名称" data-reviewed-rows>
      {geometry.labels.map(l=><g key={l.name} data-industry-label={l.name} data-anchor-x={l.anchor.x} data-anchor-y={l.anchor.y}>
        {l.cost>19&&<line className="quadrant-name-connector" x1={l.anchor.x} y1={l.anchor.y} x2={l.endX} y2={l.endY}/>}
        <text x={l.x+l.width/2} y={l.y+l.height/2} textAnchor="middle" dominantBaseline="central">{l.name}</text>
      </g>)}
    </svg>}
  </div></div>;
}
