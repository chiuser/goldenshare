import test from 'node:test';
import assert from 'node:assert/strict';
import {placeQuadrantLabels} from '../report_app/quadrant-layout.mjs';

test('literal anchors remain unchanged, including zero and negative positions',()=>{
  const points=[{name:'左下',x:70,y:260},{name:'中点',x:250,y:160},{name:'右上',x:420,y:70}];
  const original=JSON.stringify(points);
  const labels=placeQuadrantLabels(points,{left:20,right:500,top:20,bottom:330},{x:250,y:160});
  assert.equal(JSON.stringify(points),original);
  assert.deepEqual(labels.map(l=>l.anchor),[{x:70,y:260},{x:250,y:160},{x:420,y:70}]);
  assert.deepEqual(labels.map(l=>l.name),['左下','中点','右上']);
});

test('29 crowded literal observations all receive readable names',()=>{
  const points=Array.from({length:29},(_,i)=>({name:'行业'+String(i+1).padStart(2,'0'),x:430+(i%6)*13,y:270+Math.floor(i/6)*16}));
  const labels=placeQuadrantLabels(points,{left:30,right:900,top:30,bottom:650},{x:450,y:330});
  assert.equal(labels.length,29);
  assert.equal(new Set(labels.map(l=>l.name)).size,29);
  for(const a of labels){
    assert.ok(a.x>=30&&a.x+a.width<=900&&a.y>=30&&a.y+a.height<=650);
    for(const b of labels){
      if(a===b)continue;
      assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y);
    }
    for(const p of points)assert.ok(p.x<a.x||p.x>a.x+a.width||p.y<a.y||p.y>a.y+a.height);
  }
});

test('identical coordinates keep distinct industry identities',()=>{
  const labels=placeQuadrantLabels([{name:'甲',x:200,y:200},{name:'乙',x:200,y:200}],{left:20,right:450,top:20,bottom:450});
  assert.deepEqual(labels.map(l=>l.name),['甲','乙']);
  assert.deepEqual(labels.map(l=>l.anchor),[{x:200,y:200},{x:200,y:200}]);
  assert.notDeepEqual([labels[0].x,labels[0].y],[labels[1].x,labels[1].y]);
});

test('invalid or ambiguous names and coordinates are refused',()=>{
  const bounds={left:0,right:500,top:0,bottom:500};
  assert.throws(()=>placeQuadrantLabels([{name:'甲',x:NaN,y:4}],bounds));
  assert.throws(()=>placeQuadrantLabels([{name:'甲',x:5,y:4},{name:'甲',x:9,y:8}],bounds));
  assert.throws(()=>placeQuadrantLabels([{name:'甲',x:5,y:4}],{left:0,right:0,top:0,bottom:0}));
});
