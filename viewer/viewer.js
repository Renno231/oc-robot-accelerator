(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const text = (id, value) => { $(id).textContent = String(value ?? 'unavailable'); };
  const json = value => JSON.stringify(value, null, 2);
  const data = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob($('recording').textContent.trim()), c => c.charCodeAt(0))));
  const rows = data.records, summary = data.summary;
  const low = rows[0].region.min, high = rows[0].region.max;
  const canvas = $('map'), ctx = canvas.getContext('2d');
  const nx = high[0] - low[0] + 1, nz = high[2] - low[2] + 1;
  const scale = Math.min((canvas.width - 40) / nx, (canvas.height - 40) / nz);
  const ox = (canvas.width - nx * scale) / 2, oz = (canvas.height - nz * scale) / 2;
  const cells = new Map();
  let index = -1, applied = -1, token = 0, playIntent = 0, busy = false, playing = false, clock = 0, playTick = 0;
  text('identity', 'Job '+data.jobId+' · '+rows.length+' samples · ticks '+rows[0].tick+'–'+rows[rows.length - 1].tick);
  const checkpoint = summary.observationCoverage;
  const recordingStop = checkpoint?.recordingStopped ? ' Capture stopped at its byte limit; checkpoint observed through tick '+checkpoint.lastObservedTick+'.' : '';
  text('coverage', (summary.finalRecorded ? 'Final sample recorded.' : 'No final sample recorded — later state is unknown.')+recordingStop);
  text('limits', 'Region '+low.join(', ')+' → '+high.join(', ')+'. Sampling cadence '+summary.everyTicks+' ticks; transient changes can be missed. Coverage checkpoint: '+summary.coverageStatus+'.'+(summary.truncatedLastLine ? ' Incomplete last line excluded.' : '')+' Playback ends at the last retained sample, not the job end.');
  text('warning', data.warning);
  text('console', data.console.text || '(no captured console text)');
  text('console-status', data.console.status+(data.console.truncated ? ' · retained tail from byte '+data.console.offset+' of '+data.console.sourceSize : '')+'. Not indexed by sample tick.');
  text('result', json({job: data.job, result: data.result}));
  $('timeline').max = String(rows.length - 1);
  for (let y = low[1]; y <= high[1]; y++) {
    const option = document.createElement('option'); option.value = String(y); option.textContent = String(y); $('height').append(option);
  }
  $('height').value = String(Math.min(high[1], Math.max(low[1], rows[0].robot.position[1])));
  const key = p => p.join(',');
  function color(block) {
    if (block === 'minecraft:air') return '#17222d';
    if (block.includes('water')) return '#3577ac';
    if (block.includes('lava')) return '#d97431';
    if (block.includes('ore')) return '#aa9560';
    if (block.includes('grass') || block.includes('leaves') || block.includes('crop')) return '#537d4b';
    if (block.includes('dirt') || block.includes('sand')) return '#8d7255';
    let hash = 0; for (const c of block) hash = (hash * 31 + c.charCodeAt(0)) | 0;
    return 'hsl('+(Math.abs(hash) % 360)+' 12% 40%)';
  }
  function draw() {
    if (index < 0 || busy) return;
    const row = rows[index], y = Number($('height').value), robot = row.robot;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let z = low[2]; z <= high[2]; z++) for (let x = low[0]; x <= high[0]; x++) {
      const cell = cells.get(key([x,y,z])); ctx.fillStyle = color(cell.block);
      ctx.fillRect(ox+(x-low[0])*scale, oz+(z-low[2])*scale, Math.max(.2, scale-(scale>8?1:0)), Math.max(.2, scale-(scale>8?1:0)));
    }
    if (row.kind !== 'initial') {
      ctx.strokeStyle = '#ffcc70'; ctx.lineWidth = 2;
      for (const cell of row.blocks) if (cell.position[1] === y) {
        const p = cell.position; ctx.strokeRect(ox+(p[0]-low[0])*scale+1, oz+(p[2]-low[2])*scale+1, Math.max(1,scale-2), Math.max(1,scale-2));
      }
    }
    const inside = p => p[0]>=low[0] && p[0]<=high[0] && p[2]>=low[2] && p[2]<=high[2];
    // Screen-only trail thinning bounds canvas work; retained state/timeline is never thinned.
    const stride = Math.max(1, Math.ceil((index + 1) / 2000)); ctx.fillStyle = '#7fe5cf';
    for (let i=0; i<=index; i+=stride) {
      const p=rows[i].robot.position;
      if (p[1]===y && inside(p)) {ctx.beginPath();ctx.arc(ox+(p[0]-low[0]+.5)*scale,oz+(p[2]-low[2]+.5)*scale,Math.max(1,Math.min(3,scale/8)),0,Math.PI*2);ctx.fill();}
    }
    const p=robot.position;
    if (p[1]===y && inside(p)) {
      const cx=ox+(p[0]-low[0]+.5)*scale, cz=oz+(p[2]-low[2]+.5)*scale;
      const angle={north:0,east:Math.PI/2,south:Math.PI,west:-Math.PI/2}[robot.facing] ?? 0;
      const r=Math.max(4,Math.min(16,scale*.4));ctx.save();ctx.translate(cx,cz);ctx.rotate(angle);
      ctx.beginPath();ctx.moveTo(0,-r);ctx.lineTo(r*.7,r);ctx.lineTo(-r*.7,r);ctx.closePath();ctx.fillStyle='#f7fbff';ctx.fill();ctx.strokeStyle='#101820';ctx.stroke();ctx.restore();
    }
    text('outside', (p[1]!==y ? 'Robot is on another height slice. ' : '')+(!inside(p)?'Robot is outside the recorded region. ':'')+(stride>1?'Trail displays every '+stride+'th recorded position (up to 2,000 points).':''));
    text('position',p.join(', '));text('facing',robot.facing);text('energy',robot.energy);text('machine',robot.state);
    text('inventory',json({inventory:robot.inventory,tool:robot.tool}));
    text('tick','Tick '+row.tick+' · sample '+(index+1)+'/'+rows.length+' · '+row.kind);
    $('timeline').value=String(index);$('previous').disabled=index===0;$('next').disabled=index===rows.length-1;
    text('progress',index===rows.length-1?'End of retained recording':'');
    canvas.dataset.sample=String(index);canvas.dataset.tick=String(row.tick);canvas.dataset.height=String(y);
  }
  async function seek(target) {
    const interrupted=busy, mine=++token;busy=true;canvas.setAttribute('aria-busy','true');
    target=Math.max(0,Math.min(rows.length-1,target));text('progress','Reconstructing recorded state…');
    if (interrupted || target < applied) {cells.clear();applied=-1;}
    let work=0;
    for (let i=applied+1;i<=target;i++) {
      for (const cell of rows[i].blocks) {
        cells.set(key(cell.position),cell);
        if (++work>=4000) {work=0;await new Promise(resolve=>setTimeout(resolve,0));if(mine!==token)return;}
      }
      applied=i;
      if (++work>=4000) {work=0;await new Promise(resolve=>setTimeout(resolve,0));if(mine!==token)return;}
    }
    if(mine!==token)return;
    index=target;busy=false;canvas.setAttribute('aria-busy','false');draw();
  }
  function pause() {++playIntent;playing=false;$('play').textContent='Play';}
  $('timeline').addEventListener('input',()=>{pause();seek(Number($('timeline').value));});
  $('previous').addEventListener('click',()=>{pause();seek(index-1);});
  $('next').addEventListener('click',()=>{pause();seek(index+1);});
  $('height').addEventListener('change',draw);
  $('speed').addEventListener('change',()=>{clock=performance.now();playTick=rows[Math.max(index,0)].tick;});
  $('play').addEventListener('click',async()=>{
    if(playing){pause();return;} if(busy)return;
    const intent=++playIntent;
    if(index===rows.length-1)await seek(0);
    if(intent!==playIntent)return;
    playing=true;$('play').textContent='Pause';clock=performance.now();playTick=rows[Math.max(index,0)].tick;
  });
  setInterval(()=>{
    if(!playing||busy)return;
    const wanted=playTick+(performance.now()-clock)/1000*20*Number($('speed').value);
    let lo=Math.max(0,index),hi=rows.length;
    while(lo+1<hi){const mid=Math.floor((lo+hi)/2);if(rows[mid].tick<=wanted)lo=mid;else hi=mid;}
    if(lo!==index)seek(lo);
    if(lo===rows.length-1)pause();
  },100);
  canvas.addEventListener('mousemove',event=>{
    if(busy)return;const rect=canvas.getBoundingClientRect();
    const x=Math.floor(((event.clientX-rect.left)*canvas.width/rect.width-ox)/scale)+low[0];
    const z=Math.floor(((event.clientY-rect.top)*canvas.height/rect.height-oz)/scale)+low[2];
    const cell=cells.get(key([x,Number($('height').value),z]));
    text('cell',cell?cell.position.join(', ')+' · '+cell.block+' '+json(cell.properties):'Outside recorded region');
  });
  window.addEventListener('pagehide',pause);
  seek(0);
})();
