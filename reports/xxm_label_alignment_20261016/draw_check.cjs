// Run from the repository root. Recorded real API evidence; no browser or live service.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const esbuild = require('../../wealth/node_modules/esbuild');
const output = esbuild.buildSync({ stdin: { contents: `
  export {layoutXxmLabels} from './wealth/src/features/index-detail/xxm/markerGeometry';
  export {XxmMacdPrimitive} from './wealth/src/features/index-detail/xxm/XxmMacdPrimitive';
`, resolveDir: process.cwd(), loader: 'ts' }, bundle: true, platform: 'node', format: 'cjs', write: false });
const loaded = { exports: {} };
new Function('module', 'exports', 'require', output.outputFiles[0].text)(loaded, loaded.exports, require);
const { layoutXxmLabels, XxmMacdPrimitive } = loaded.exports;
global.document = { documentElement: {} };
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
const dir = 'reports/xxm_bottom_history_h1_page_20261016_02';
const cases = [], sources = [];
for (const period of ['day', 'm60', 'm90', 'm120']) {
  const paths = [`${dir}/view-${period}-1tabs-cold-tab1.json`, `${dir}/layer-${period}-1tabs-cold-tab1.json`];
  const [view, layer] = paths.map(path => {
    const bytes = fs.readFileSync(path);
    sources.push({ path, sha256: crypto.createHash('sha256').update(bytes).digest('hex') });
    return JSON.parse(bytes);
  });
  for (const marker of view.markers) {
    assert.equal(marker.dif, layer.points.find(p => p.time === marker.event.time).dif);
    assert.deepEqual(marker.event, layer.events.find(event => event.id === marker.event.id));
  }
  for (const width of [1000, 1280, 1445]) for (const height of [114, 170]) {
    const xs = new Map(layer.points.map((p, i) => [period === 'day' ? p.time : Date.parse(p.time) / 1000,
      12 + i * (width - 24) / (layer.points.length - 1)]));
    const min = Math.min(...layer.points.map(p => p.dif)), max = Math.max(...layer.points.map(p => p.dif));
    const yFor = dif => 8 + (max - dif) * (height - 16) / (max - min || 1);
    const positions = view.markers.map(marker => ({ marker, x: xs.get(marker.time), y: yFor(marker.dif) }));
    const labels = layoutXxmLabels(positions, width, height, text => [...text].length * 12);
    const arcs = [], texts = [], lines = [];
    const context = { save() {}, restore() {}, beginPath() {}, rect() {}, clip() {}, fill() {}, stroke() {},
      arc(...args) { arcs.push(args); }, fillText(...args) { texts.push(args); },
      measureText(text) { return { width: [...text].length * 12 }; }, moveTo() {}, lineTo(...args) { lines.push(args); } };
    const primitive = new XxmMacdPrimitive();
    primitive.attached({ chart: { timeScale: () => ({ timeToCoordinate: time => xs.get(time) }) },
      series: { priceToCoordinate: yFor }, requestUpdate() {} });
    primitive.setMarkers(view.markers);
    const begin = performance.now();
    primitive.draw({ useMediaCoordinateSpace: draw => draw({ context, mediaSize: { width, height } }) });
    const drawMs = performance.now() - begin;
    assert.deepEqual(arcs.map(p => p.slice(0, 3)), positions.map(p => [p.x, p.y, 4]));
    assert.equal(texts.length, labels.length);
    assert.equal(primitive.autoscaleInfo(), null);
    for (const label of labels) {
      const own = positions.find(p => p.marker === label.marker);
      assert(label.left >= 3 && label.left + label.width <= width - 3 && label.top >= 3 && label.top + label.height <= height - 3);
      assert(Math.abs(label.top + 8 - own.y) <= 40);
      if (label.leader) assert(Math.abs(Math.hypot(label.leader.toX - own.x, label.leader.toY - own.y) - 4) < 1e-8);
    }
    cases.push({ period, width, height, points: layer.points.length, markers: arcs.length, labels: texts.length,
      leaders: labels.filter(l => l.leader).length, segments: lines.length, drawMs });
  }
  if (period === 'day') {
    const positions = [['2026-07-13', 843, 80], ['2026-07-15', 862.5, 83.5], ['2026-07-17', 881.5, 104.5], ['2026-07-20', 891, 112.5]]
      .map(([time, x, y]) => ({ marker: view.markers.find(m => m.event.time === time), x, y }));
    assert(positions.every(p => p.marker));
    for (const height of [114, 114.5, 115]) {
      const labels = layoutXxmLabels(positions, 1445, height, () => 24);
      assert.equal(labels.length, 4);
      cases.push({ period, scenario: 'July screenshot CSS coordinates', width: 1445, height,
        labels: labels.map(label => ({ date: label.marker.event.time, id: label.marker.event.id, label: label.label,
          anchor: positions.find(p => p.marker === label.marker), left: label.left, top: label.top, leader: label.leader })) });
    }
  }
}
const report = { basis: 'Earlier recorded real h1 API and strict-adapter output; no live UI, browser, or live API this run.',
  liveEndpoint: '127.0.0.1:5175 connection refused; no service restarted or reconfigured', sources, cases };
fs.writeFileSync('reports/xxm_label_alignment_20261016/recorded_api_draw.json', JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ cases: cases.length, maxDrawMs: Math.max(...cases.filter(c => c.drawMs !== undefined).map(c => c.drawMs)),
  draws: cases.filter(c => c.drawMs !== undefined).map(({ period, width, height, markers, labels }) => ({ period, width, height, markers, labels })) }));
