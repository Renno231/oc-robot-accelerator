async page => {
  const base = __BASE_URL__;
  const errors=[], requests=[];
  page.on('pageerror', error=>errors.push(String(error)));
  page.on('request', request=>requests.push(request.url()));
  const assert=(ok,message)=>{if(!ok)throw new Error(message);};
  const ready=async sample=>page.waitForFunction(n=>document.querySelector('#map')?.dataset.sample===String(n),sample,{timeout:10000});
  const seek=async n=>{await page.locator('#timeline').evaluate((el,value)=>{el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}));},n);await ready(n);};
  const checks=[];
  await page.goto(base+'/synthetic.html');await ready(0);
  assert(await page.locator('#coverage').innerText()==='Recording complete.','complete coverage');
  assert(await page.locator('#energy').innerText()==='100','initial energy');
  assert((await page.locator('#console').innerText()).includes('</script>'),'console text retained');
  assert(await page.evaluate(()=>typeof globalThis.INJECTED)==='undefined','script injection');
  assert(await page.locator('img').count()===0,'HTML injection');
  await page.getByRole('button',{name:'Next sample'}).click();await ready(1);
  assert(await page.locator('#energy').innerText()==='90','sample energy');
  assert(await page.locator('#position').innerText()==='1, 65, 0','sample position');
  const hoverChanged=async()=>page.locator('#map').evaluate(canvas=>{
    const r=canvas.getBoundingClientRect();canvas.dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+340/960*r.width,clientY:r.top+440/600*r.height}));
  });
  await hoverChanged();assert((await page.locator('#cell').innerText()).includes('minecraft:stone'),'delta applied to block map');
  await page.locator('#height').selectOption('66');
  assert((await page.locator('#outside').innerText()).includes('another height'),'height selection');
  await seek(2);assert(await page.locator('#machine').innerText()==='Stopped','final state');
  assert(await page.getByRole('button',{name:'Next sample'}).isDisabled(),'end bounded');
  await seek(0);await page.locator('#height').selectOption('65');await hoverChanged();
  assert((await page.locator('#cell').innerText()).includes('minecraft:air'),'rewind reconstructs initial block');
  await page.locator('#speed').selectOption('100');await page.getByRole('button',{name:'Play',exact:true}).click();
  await ready(2);await page.getByRole('button',{name:'Play',exact:true}).waitFor();
  assert(await page.locator('#energy').innerText()==='80','playback final');
  checks.push('scrub/step/height/energy/inventory/play/end/inert text');
  await page.goto(base+'/partial.html');await ready(0);
  assert((await page.locator('#coverage').innerText()).includes('ended early'),'missing final');
  assert((await page.locator('#limits').innerText()).includes('last line'),'partial line');
  assert(await page.locator('#timeline').getAttribute('max')==='0','cannot project missing interval');
  checks.push('partial/missing-final coverage');
  await page.goto(base+'/stress.html');await ready(0);
  await page.evaluate(async()=>{
    const el=document.querySelector('#timeline');el.value='1';el.dispatchEvent(new Event('input'));
    await new Promise(resolve=>setTimeout(resolve,0));el.value='0';el.dispatchEvent(new Event('input'));
  });await ready(0);
  await page.waitForFunction(()=>document.querySelector('#map').getAttribute('aria-busy')==='false');
  const color=await page.locator('#map').evaluate(canvas=>Array.from(canvas.getContext('2d').getImageData(266,23,1,1).data));
  assert(color[0]===23&&color[1]===34&&color[2]===45,'interrupted seek restored initial air: '+JSON.stringify(color));
  checks.push('8,000-cell asynchronous reconstruction and interrupted backwards seek');
  await seek(1);await page.waitForFunction(()=>document.querySelector('#map').getAttribute('aria-busy')==='false');
  await page.evaluate(()=>{
    document.querySelector('#play').click(); // Rewind from end yields while rebuilding 8,000 cells.
    const el=document.querySelector('#timeline');el.value='0';el.dispatchEvent(new Event('input'));
  });
  await page.waitForFunction(()=>document.querySelector('#map').getAttribute('aria-busy')==='false');
  assert(await page.locator('#play').innerText()==='Play','scrub must cancel pending playback start');
  checks.push('Play-from-end interrupted by scrub remains paused');
  await page.goto(base+'/actual.html');await ready(0);
  const last=Number(await page.locator('#timeline').getAttribute('max'));await seek(last);
  const evidence=await page.evaluate(()=>{
    const data=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(document.querySelector('#recording').textContent.trim()),c=>c.charCodeAt(0))));
    return {last:data.records[data.records.length-1],summary:data.summary};
  });
  assert(await page.locator('#energy').innerText()===String(evidence.last.robot.energy),'actual final energy');
  assert(await page.locator('#position').innerText()===evidence.last.robot.position.join(', '),'actual final position');
  assert(await page.locator('#inventory').innerText()===JSON.stringify({inventory:evidence.last.robot.inventory,tool:evidence.last.robot.tool},null,2),'actual inventory and tool');
  assert(Number(await page.locator('#map').getAttribute('data-tick'))===evidence.summary.lastTick,'actual retained end');
  if(evidence.summary.observationCoverage?.recordingStopped) {
    assert((await page.locator('#coverage').innerText()).includes('size limit'),'actual retention warning');
    assert((await page.locator('#coverage').innerText()).includes('ended early'),'actual retained missing final');
    assert(evidence.summary.lastTick<evidence.summary.observationCoverage.lastObservedTick,'later observed state not projected');
  }
  await page.screenshot({path:__SCREENSHOT__,fullPage:true});
  checks.push('actual retained recording state/ticks and screenshot');
  assert(errors.length===0,'browser errors: '+errors.join(';'));
  assert(requests.every(url=>url.startsWith(base+'/')),'external request: '+requests.join(';'));
  return {status:'passed',checks,requests,errors,actualRecords:last+1,actualLastTick:evidence.summary.lastTick};
}
