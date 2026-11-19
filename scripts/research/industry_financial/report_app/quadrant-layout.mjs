// Presentation geometry only. Anchors are measured native dots, never financial values.
export const QUADRANT_LAYOUT = Object.freeze({
  minWidth: 940, height: 720, fontSize: 14, lineHeight: 22,
  characterWidth: 14.5, gap: 5, pointRadius: 7,
  fills: Object.freeze({
    bothUp: 'rgba(239,68,68,0.12)',
    incomeDownMarginUp: 'rgba(239,68,68,0.05)',
    bothDown: 'rgba(34,197,94,0.12)',
    incomeUpMarginDown: 'rgba(34,197,94,0.05)',
  }),
});

const overlap = (a, b, gap = 0) => a.x < b.x + b.width + gap && b.x < a.x + a.width + gap
  && a.y < b.y + b.height + gap && b.y < a.y + a.height + gap;

export function placeQuadrantLabels(points, bounds, zero = {}) {
  if (new Set(points.map(p => p.name)).size !== points.length || points.some(p =>
    typeof p.name !== 'string' || !p.name || !Number.isFinite(p.x) || !Number.isFinite(p.y))) {
    throw new Error('Every industry requires one unique name and a finite native point');
  }
  if (![bounds.left, bounds.right, bounds.top, bounds.bottom].every(Number.isFinite)
    || bounds.right <= bounds.left || bounds.bottom <= bounds.top) throw new Error('Invalid plot bounds');
  const {gap, pointRadius, lineHeight, characterWidth} = QUADRANT_LAYOUT;
  const dots = points.map(p => ({x:p.x-pointRadius, y:p.y-pointRadius, width:pointRadius*2, height:pointRadius*2}));
  const axes = [];
  if (Number.isFinite(zero.x)) axes.push({x:zero.x-2, y:bounds.top, width:4, height:bounds.bottom-bounds.top});
  if (Number.isFinite(zero.y)) axes.push({x:bounds.left, y:zero.y-2, width:bounds.right-bounds.left, height:4});
  // Place crowded observations first, leaving isolated observations close to their dots.
  const order = [...points].sort((a,b) => {
    const count = p => points.filter(q => Math.hypot(p.x-q.x,p.y-q.y)<95).length;
    return count(b)-count(a) || a.y-b.y || a.x-b.x || a.name.localeCompare(b.name,'zh');
  });
  const labels = [];
  for (const p of order) {
    const width = Array.from(p.name).length*characterWidth+4, height = lineHeight;
    const candidates = [];
    for (const distance of [12,24,38,54,74,98,126,158,194,234]) {
      for (const [dx,dy] of [[1,-1],[-1,-1],[1,1],[-1,1],[1,0],[-1,0],[0,-1],[0,1]]) {
        const x = p.x + dx*distance - (dx<0?width:dx===0?width/2:0);
        const y = p.y + dy*distance - (dy<0?height:dy===0?height/2:0);
        const box = {x,y,width,height};
        if (x<bounds.left+3 || x+width>bounds.right-3 || y<bounds.top+3 || y+height>bounds.bottom-3) continue;
        if ([...dots,...axes,...labels].some(other=>overlap(box,other,gap))) continue;
        const endX = Math.max(x,Math.min(p.x,x+width)), endY = Math.max(y,Math.min(p.y,y+height));
        candidates.push({...box, endX, endY, cost:Math.hypot(endX-p.x,endY-p.y)});
      }
    }
    candidates.sort((a,b)=>a.cost-b.cost);
    const box = candidates[0];
    if (!box) throw new Error('No readable label position for '+p.name);
    labels.push({...box,name:p.name,anchor:{x:p.x,y:p.y}});
  }
  return points.map(p=>labels.find(l=>l.name===p.name));
}
