'use strict';
// Deterministic event-loop regression for playback intent cancellation. No browser/network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map(), pending = [];
const ctx = new Proxy({}, { get: (_, key) => () => {}, set: () => true });
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: '', value: '', max: '', width: 960, height: 600, dataset: {}, handlers: {}, attributes: {},
    addEventListener(event, callback) { this.handlers[event] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    append() {}, getContext() { return ctx; }
  });
  return elements.get(id);
}
const robot = { position: [0,65,0], facing: 'north', energy: 10, state: 'Running', inventory: [], tool: {} };
const blocks = [];
for (let z=0; z<100; z++) for (let x=0; x<80; x++) blocks.push({position:[x,65,z],block:'minecraft:air',properties:{}});
const records = [
  {kind:'initial',tick:1,region:{min:[0,65,0],max:[79,65,99]},robot,blocks},
  {kind:'final',tick:21,robot:{...robot,state:'Stopped'},blocks:[]}
];
element('recording').textContent = Buffer.from(JSON.stringify({jobId:'test',records,summary:{everyTicks:20,finalRecorded:true},console:{text:'',status:'available'},job:{},result:{}})).toString('base64');
element('speed').value = '1';
const sandbox = { document:{getElementById:element,createElement:()=>({})}, window:{addEventListener(){}}, TextDecoder, Uint8Array,
  atob: s=>Buffer.from(s,'base64').toString('binary'), performance:{now:()=>0},
  setTimeout(callback) { pending.push(callback); }, setInterval() {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'viewer.js'),'utf8'),sandbox);
async function drain() {
  for (let i=0;i<100;i++) {
    await Promise.resolve();
    if (pending.length) pending.shift()();
    else { await Promise.resolve(); if (!pending.length) return; }
  }
  throw new Error('unexpected event-loop work bound');
}
(async()=>{
  await drain(); assert.equal(element('map').dataset.sample,'0');
  element('timeline').value='1'; element('timeline').handlers.input(); await drain();
  assert.equal(element('map').dataset.sample,'1');
  const play = element('play').handlers.click(); // Rewind suspends at 4,000 cells.
  assert.equal(element('map').attributes['aria-busy'],'true');
  element('timeline').value='0'; element('timeline').handlers.input(); // Explicitly pauses/cancels pending play.
  await drain(); await play;
  assert.equal(element('map').dataset.sample,'0');
  assert.equal(element('map').attributes['aria-busy'],'false');
  assert.equal(element('play').textContent,'Play','scrubbing during rewind must cancel pending playback start');
  await element('play').handlers.click();
  assert.equal(element('play').textContent,'Pause','a fresh play intent must still work');
  await element('play').handlers.click();
  assert.equal(element('play').textContent,'Play');
  console.log('PASS: Play-from-end interrupted by scrub stays paused; fresh play/pause works');
})().catch(error=>{console.error(error);process.exitCode=1;});
