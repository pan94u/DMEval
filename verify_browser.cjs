const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('C:/Users/szq43/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1080}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const samples=[],tasks=[];
 const out=path.join(__dirname,'runs','product-check');fs.mkdirSync(out,{recursive:true});
 async function api(url,data){return page.evaluate(async({url,data})=>{const state=await(await fetch('/api/state')).json();const r=await fetch(url,data?{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':state.token},body:JSON.stringify(data)}:{});const body=await r.json();if(!r.ok)throw Error(body.error);return body},{url,data})}
 try{
  await page.goto('http://127.0.0.1:8787/#samples');await page.locator('#sample-new').waitFor();
  assert.equal(await page.locator('.sidebar-scale,#history-link').count(),0);
  assert.equal(await page.evaluate(async()=> (await fetch('/api/history')).status),404);
  await page.locator('[data-inspect]').first().click();
  await page.locator('#inspect-dialog').waitFor();
  assert.equal(await page.locator('#inspect-body pre:visible').count(),0);
  await page.waitForTimeout(300);await page.screenshot({path:path.join(out,'sample-details.png')});
  await page.locator('#inspect-body .raw-disclosure summary').click();assert.ok(await page.locator('#inspect-body pre:visible').count());
  await page.keyboard.press('Escape');
  await page.locator('#sample-new').click();
  await page.locator('#sample-title').fill('验证 · 自然表单');
  await page.locator('#sample-state').fill('客户只收到处理中通知。');
  await page.locator('#question-title').fill('退款是否已经完成？');
  await page.locator('#question-instructions').fill('只有明确完成的记录才判断为是。');
  await page.locator('#question-answer').selectOption('false');
  const formId=await page.locator('#sample-id').inputValue();samples.push(formId);
  await page.locator('#save-sample').click();await page.locator('#sample-dialog').waitFor({state:'hidden'});
  await page.locator('[data-single="'+formId+'"]').click();
  await page.locator('#new-task-name').fill('验证 · 单样本草稿');
  await page.getByRole('button',{name:'保存任务',exact:true}).click();
  await page.waitForURL(/#task\//);tasks.push(page.url().split('#task/')[1]);
  await page.getByRole('button',{name:'运行任务',exact:true}).waitFor();
  await page.goto('http://127.0.0.1:8787/#samples');await page.locator('#sample-new').waitFor();
  const suffix=Date.now();
  const question={type:'noul',instructions:'Is completion explicitly confirmed?'};
  for(const [suffixId,gold] of [['yes',true],['no',false]]){
   const id='product-check-'+suffix+'-'+suffixId;samples.push(id);
   await api('/api/samples/save',{title:'验证 · '+suffixId,category:'临时验证',case:{id,state:{order:'CHECK',amount:80,events:[{at:'10:00',business_status:gold?'completed':'pending'}],identity_verified:true},questions:{completion:question},expected:{completion:gold},presentation:{questions:{completion:{title:'退款是否已经完成？'}}}}});
  }
  const choiceId='product-check-'+suffix+'-choice';samples.push(choiceId);
  await api('/api/samples/save',{title:'验证 · 团队选择',category:'临时验证',case:{id:choiceId,state:'Payment system is unavailable.',questions:{team:{type:'choice',instructions:'Choose the responsible team.',criteria:{billing:'账单与退款团队',technical:'技术支持团队'}}},expected:{team:'technical'},presentation:{questions:{team:{title:'应交给哪个团队处理？'}}}}});
  await page.reload();await page.locator('#sample-new').waitFor();
  await page.locator('#sample-search').fill('product-check-'+suffix+'-yes');
  await page.locator('[data-edit="'+samples[1]+'"]').click();
  assert.equal(await page.locator('#sample-state').isVisible(),false);
  assert.ok(await page.locator('#sample-structured-editor [data-human-path]').count());
  const amount=page.locator('#sample-structured-editor input[type=number]').first();await amount.fill('81');
  await page.waitForTimeout(250);await page.screenshot({path:path.join(out,'structured-editor.png')});
  await page.locator('#save-sample').click();await page.locator('#sample-dialog').waitFor({state:'hidden'});
  const library=await api('/api/state');assert.equal(library.samples.find(s=>s.id===samples[1]).case.state.amount,81);
  const created=await api('/api/tasks/create',{name:'验证 · 结果产品化',sample_ids:samples.slice(1),models:['clef','clef-flash'],repeats:2,provider:'mock',start:true});tasks.push(created.id);
  let complete;
  for(let i=0;i<100;i++){complete=await api('/api/task?id='+created.id);if(complete.status==='completed')break;await page.waitForTimeout(300)}
  assert.equal(complete.status,'completed');const originalResults=JSON.stringify(complete.results);
  await page.goto('http://127.0.0.1:8787/#task/'+created.id);await page.locator('.result-table').waitFor();
  assert.equal(await page.locator('.result-table').getByText('technical',{exact:true}).count(),0);
  assert.ok(await page.locator('.result-table').getByText('技术支持团队',{exact:true}).count());
  await page.waitForTimeout(300);await page.screenshot({path:path.join(out,'results.png'),fullPage:true});
  await page.locator('[data-tab=threshold]').click();await page.locator('#threshold-percent').waitFor();
  await page.locator('#threshold-percent').fill('80');
  assert.match(await page.locator('#policy-status').textContent(),/尚未保存/);
  assert.match(await page.locator('#analysis-content').textContent(),/2 个独立样本/);
  await page.locator('#save-policy').click();await page.waitForFunction(()=>document.getElementById('policy-status').textContent.includes('已采用'));
  await page.waitForTimeout(300);await page.screenshot({path:path.join(out,'threshold.png'),fullPage:true});
  const applied=await api('/api/task?id='+created.id);assert.equal(applied.decision_policy[0].threshold,.8);assert.equal(applied.decision_policy.length,1);assert.equal(JSON.stringify(applied.results),originalResults);
  await page.reload();await page.locator('[data-tab=threshold]').click();await page.locator('#threshold-percent').waitFor();assert.equal(await page.locator('#threshold-percent').inputValue(),'80');
  await page.locator('#analysis-model').selectOption('clef-flash');assert.equal(await page.locator('#threshold-percent').inputValue(),'50');
  await page.locator('#analysis-model').selectOption('clef');assert.equal(await page.locator('#threshold-percent').inputValue(),'80');
  await page.locator('[data-tab=results]').click();
  const exportEvent=page.waitForEvent('download');await page.locator('#export-task').click();const download=await exportEvent;await download.saveAs(path.join(out,'report.csv'));assert.match(fs.readFileSync(path.join(out,'report.csv'),'utf8'),/技术支持团队/);
  await page.locator('[data-result]').first().click();assert.equal(await page.locator('#inspect-body pre:visible').count(),0);await page.keyboard.press('Escape');
  for(const width of [390,768]){
   await page.setViewportSize({width,height:900});await page.goto('http://127.0.0.1:8787/#samples');await page.locator('#sample-new').waitFor();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.locator('[data-inspect]').first().click();await page.waitForTimeout(300);await page.screenshot({path:path.join(out,'mobile-sample-'+width+'.png')});await page.keyboard.press('Escape');
   await page.goto('http://127.0.0.1:8787/#task/'+created.id);await page.locator('[data-tab=threshold]').click();await page.locator('#threshold-percent').waitFor();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   if(width===390)await page.screenshot({path:path.join(out,'mobile-threshold.png'),fullPage:true});
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: human sample/details/editing, choice labels, raw disclosures, mock batch, independent sample analysis, persisted/scoped thresholds, unchanged raw results, CSV report, 390/768/1440 layouts; no paid calls.');
 }finally{
  for(const id of tasks){try{await api('/api/tasks/action',{id,action:'archive'})}catch{}}
  for(const id of samples){try{await api('/api/samples/delete',{id})}catch{}}
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
