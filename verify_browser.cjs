const assert=require('node:assert/strict');
const windows=process.platform==='win32';
const {chromium}=require(windows?'C:/Users/szq43/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright':'/mnt/c/Users/szq43/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({...windows?{channel:'msedge'}:{executablePath:'/home/szq43/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell'},headless:true,args:['--no-sandbox']});
 let cleanupSample=null,cleanupTasks=[];
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const api=async(path,data)=>page.evaluate(async({path,data})=>{const state=await (await fetch('/api/state')).json();const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':state.token},body:JSON.stringify(data)}:{});const v=await r.json();if(!r.ok)throw Error(v.error);return v},{path,data});
 try{
  await page.goto('http://localhost:8787/#samples');
  await page.locator('#sample-new').waitFor();
  await page.screenshot({path:'runs/workspace-samples.png',fullPage:true});
  assert.equal(await page.getByText('开启自动评测',{exact:true}).count(),0);
  await page.locator('#sample-new').click();
  await page.locator('#sample-title').fill('界面验证样本');
  await page.locator('#sample-category').fill('自动检查');
  await page.locator('#sample-state').fill('This is a test input.');
  await page.locator('#question-instructions').fill('Is this a test input?');
  await page.locator('#question-answer').selectOption('true');
  cleanupSample=await page.locator('#sample-id').inputValue();
  await page.locator('#save-sample').click();
  await page.locator('#sample-dialog').waitFor({state:'hidden'});
  await page.locator(`[data-edit="${cleanupSample}"]`).click();
  await page.locator('#sample-title').fill('界面验证样本 · 已编辑');
  await page.locator('#save-sample').click();
  await page.locator('#sample-dialog').waitFor({state:'hidden'});
  await page.locator(`[data-single="${cleanupSample}"]`).click();
  assert.match(await page.locator('#request-estimate').textContent(),/单样本测试.*2 次 API 请求/);
  await page.locator('#new-task-name').fill('界面验证 · 单样本草稿');
  await page.getByRole('button',{name:'仅创建任务',exact:true}).click();
  await page.waitForURL(/#task\//);
  cleanupTasks.push(page.url().split('#task/')[1]);
  await page.getByRole('button',{name:'运行任务',exact:true}).waitFor();
  await page.screenshot({path:'runs/workspace-draft.png',fullPage:true});
  await page.goto('http://localhost:8787/#samples');
  await page.locator('[data-collection="示例样本"]').click();
  await page.locator('[data-select="route-zh"]').check();
  await page.locator('[data-select="route-en"]').check();
  await page.locator('#batch-create').click();
  assert.match(await page.locator('#request-estimate').textContent(),/2 个样本.*4 次 API 请求/);
  await page.locator('#task-dialog .close-dialog').click();
  // Use a mock task to verify queue execution and thresholds without paid calls.
  const create=await api('/api/tasks/create',{name:'界面验证 · 概率边界',sample_ids:[cleanupSample],models:['clef'],provider:'mock',start:true});
  cleanupTasks.push(create.id);
  for(let i=0;i<40;i++){const t=await api('/api/task?id='+create.id);if(t.status==='completed')break;await page.waitForTimeout(300)}
  const done=await api('/api/task?id='+create.id);assert.equal(done.status,'completed');
  await page.goto('http://localhost:8787/#task/'+create.id);
  await page.locator('[data-tab="threshold"]').click();
  await page.locator('#threshold-slider').waitFor();
  const tradeoff=await page.evaluate(()=>{
   const scores=[{probability:.4,expected:true},{probability:.1,expected:false}];
   return {default:binaryStats(scores,.5),lower:binaryStats(scores,.3)};
  });
  assert.equal(tradeoff.default.fn,1);
  assert.equal(tradeoff.lower.tp,1);
  assert.equal(tradeoff.lower.tn,1);
  assert.equal(tradeoff.default.brier,tradeoff.lower.brier);
  assert.equal(await page.locator('#threshold-value').textContent(),'0.50');
  assert.match(await page.locator('#analysis-content').textContent(),/正确识别（TP）1/);
  const countBefore=(await api('/api/task?id='+create.id)).done;
  await page.locator('#threshold-slider').focus();
  await page.keyboard.press('End');
  for(let i=0;i<20;i++)await page.keyboard.press('ArrowLeft');
  assert.match(await page.locator('#analysis-content').textContent(),/漏报（FN）1/);
  assert.equal((await api('/api/task?id='+create.id)).done,countBefore);
  await page.screenshot({path:'runs/workspace-threshold.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'runs/workspace-mobile-threshold.png',fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.goto('http://localhost:8787/#samples');
  await page.locator('#sample-new').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:'runs/workspace-mobile-samples.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: sample create/edit, single draft, batch selection, queue, threshold boundary/recompute, desktop/mobile, no JS errors');
 }finally{
  try{for(const id of cleanupTasks)await api('/api/tasks/action',{id,action:'archive'});if(cleanupSample)await api('/api/samples/delete',{id:cleanupSample})}catch(e){console.error('Cleanup:',e.message)}
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
