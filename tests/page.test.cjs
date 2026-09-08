const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM, VirtualConsole } = require('jsdom');
const core = require('../docs/core.js');
const root = path.resolve(__dirname, '..');
const wikiText=Array.from({length:6},(_,i)=>Array.from({length:110},(_,j)=>`science${i}word${j}`).join(' ')).join('\n\n');
const wikiResponse=()=>({ok:true,json:async()=>({query:{pages:{'123':{pageid:123,title:'Photosynthesis',lastrevid:456,extract:wikiText}}}})});
function page(fetchImpl = async (url) => { if(url.includes('en.wikipedia.org'))return wikiResponse(); throw new Error('Unexpected network request'); }) {
  const errors = [], virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  let html = fs.readFileSync(path.join(root, 'docs/index.html'), 'utf8').replace(/<script[^>]+src=[\s\S]*?<\/script>/g, '');
  const scripts = ['core.js', 'app.js'].map(name => `<script>${fs.readFileSync(path.join(root,'docs',name),'utf8')}</script>`).join('');
  html = html.replace('</body>', scripts + '</body>');
  const dom = new JSDOM(html, { runScripts: 'dangerously', url: 'https://example.test/didyoueatthis/', virtualConsole,
    beforeParse(window) { window.HTMLElement.prototype.scrollIntoView = () => {}; window.fetch = fetchImpl; window.AbortSignal = AbortSignal; window.AbortController = AbortController; }
  });
  assert.equal(errors.length, 0, errors.map(e=>e.message).join('\n'));
  const $ = id => dom.window.document.getElementById(id);
  const input = (id,value) => { if(['doc','ctrl'].includes(id)) $('rights-basis').value='own'; /* synthetic fixtures owned by the test */ $(id).value = value; $(id).dispatchEvent(new dom.window.Event('input',{bubbles:true})); };
  return {dom,$,input,errors};
}
const tick = () => new Promise(resolve=>setImmediate(resolve));
const wordText = Array.from({length:600},(_,i)=>`token${i}`).join(' ');
const answer = (family,truth,text,extra={}) => ({family,truth,text,group:'g',tier:'target',model:'m',...extra});

test('the loaded page wires quick start, navigation, partial scoring and bulk replies without network', async () => {
  const {dom,$,input,errors} = page();
  assert.equal($('manual').checked,true); assert.equal($('api-panel').hidden,true);
  $('quick').click(); await tick();
  assert.equal($('manualbox').hidden,false); assert.match($('prompt-position').textContent,/Prompt 1 of 3/);
  assert.match($('current-prompt').value,/Continue this passage/); assert.equal($('scoremanual').disabled,true);
  const firstPrompt = $('current-prompt').value;
  input('current-answer','[UNKNOWN]'); $('next').click(); assert.match($('prompt-position').textContent,/Prompt 2/);
  $('prev').click(); assert.equal($('current-answer').value,'[UNKNOWN]'); assert.equal($('current-prompt').value,firstPrompt);
  $('scoremanual').click(); assert.equal($('result').hidden,false); assert.match($('result').textContent,/Exploratory \/ inconclusive/);
  input('bulk','##### ANSWER 1 #####\nfirst reply\n\n##### ANSWER 3 #####\nlast reply'); $('parsebulk').click();
  assert.equal($('current-answer').value,'first reply'); assert.match($('bulk-feedback').textContent,/Filled 2/);
  $('next').click(); $('next').click(); assert.equal($('current-answer').value,'last reply');
  input('bulk','##### ANSWER 1 #####\nnew\n##### ANSWER 1 #####\nduplicate'); $('parsebulk').click();
  assert.match($('bulk-feedback').textContent,/duplicate/); $('prev').click(); $('prev').click(); assert.equal($('current-answer').value,'first reply');
  $('copy-prompt').click(); await tick(); assert.match($('copy-feedback').textContent,/Copy was blocked/);
  assert.equal(errors.length,0); dom.window.close();
});

test('manual and API flows score the same exact replies and export no keys', async () => {
  const calls = [];
  const {dom,$,input,errors} = page(async(url,options)=>{calls.push({url,...options}); return {ok:true,json:async()=>({choices:[{message:{content:'token64 token65 token66 token67 token68 token69 token70 token71 token72 token73 token74 token75 token76 token77 token78 token79 token80 token81 token82 token83'},finish_reason:'stop'}]})};});
  input('doc',wordText); input('passages','1'); $('automatic').click(); input('k_openai','dummy-test-key');
  $('go').click(); for(let i=0;i<10;i++) await tick();
  assert.equal(calls.length,1); assert.equal(calls[0].url,'https://api.openai.com/v1/chat/completions');
  assert.equal(calls[0].headers.authorization,'Bearer dummy-test-key'); assert.equal($('go').disabled,false);
  assert.match($('result').textContent,/1 \/ 1/); assert.equal($('dl').hidden,false);
  const blobs=[]; dom.window.URL.createObjectURL=blob=>{blobs.push(blob);return 'blob:report';}; dom.window.URL.revokeObjectURL=()=>{}; dom.window.HTMLAnchorElement.prototype.click=()=>{};
  $('dl').click(); const content=await new Promise(resolve=>{const reader=new dom.window.FileReader();reader.onload=()=>resolve(reader.result);reader.readAsText(blobs[0]);});
  assert.equal(content.includes('dummy-test-key'),false); const report=JSON.parse(content); assert.equal(report.answers[0].hit,true); assert.equal(report.mode,'api');
  $('manual').click(); $('go').click(); input('current-answer',report.answers[0].text); $('scoremanual').click(); assert.match($('result').textContent,/1 \/ 1/);
  assert.equal(errors.length,0);dom.window.close();
});

test('API errors, cancellation and exhausted reasoning budgets remain inconclusive', async () => {
  const {dom,$,input} = page(async()=>({ok:false,status:401}));
  input('doc',wordText); $('automatic').click(); input('k_openai','dummy'); $('go').click(); for(let i=0;i<10;i++) await tick();
  assert.match($('result').textContent,/HTTP 401/); assert.match($('result').textContent,/inconclusive/); assert.equal($('go').disabled,false); dom.window.close();
  const cancelled = page((url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('aborted')))));
  cancelled.input('doc',wordText);cancelled.$('automatic').click();cancelled.input('k_openai','dummy');cancelled.$('go').click();cancelled.$('stop').click();for(let i=0;i<10;i++) await tick();
  assert.match(cancelled.$('status').textContent,/Run stopped/);assert.equal(cancelled.$('go').disabled,false);cancelled.dom.window.close();
  const exhausted=page(async()=>({ok:true,json:async()=>({choices:[{message:{content:''},finish_reason:'length'}]})}));
  exhausted.input('doc',wordText);exhausted.$('automatic').click();exhausted.input('k_openai','dummy');exhausted.$('go').click();for(let i=0;i<10;i++) await tick();
  assert.match(exhausted.$('result').textContent,/Output budget exhausted/);assert.match(exhausted.$('result').textContent,/inconclusive/);exhausted.dom.window.close();
});

test('settings reject empty text, impossible thresholds, missing models and name-free cloze', () => {
  const {dom,$,input}=page();$('go').click();assert.match($('status').textContent,/Add your text/);
  input('doc',wordText);input('hitw','80');$('go').click();assert.match($('status').textContent,/cannot exceed/);
  input('hitw','20');input('prefix','64,broken');$('go').click();assert.match($('status').textContent,/whole numbers/);
  input('prefix','64');$('m_continuation').checked=false;$('m_cloze').checked=true;$('go').click();assert.match($('status').textContent,/no usable missing name/);
  $('m_continuation').checked=true;$('m_cloze').checked=false;$('automatic').click();$('go').click();assert.match($('status').textContent,/API key/);
  input('custom','local:nope');$('add-model').click();assert.match($('model-feedback').textContent,/Use openai/);dom.window.close();
});

test('names are hidden, repeated-name leakage is excluded, and methods stay separate', () => {
  const tokens=('the traveller reached Zorinda after the rain while '+Array(125).fill('quiet roads crossed fields').join(' ')).split(' ');
  const text=tokens.join(' '),probes=core.buildCloze(text,'target','doc',3);
  assert.ok(probes.length); assert.equal(probes[0].truth,'Zorinda');assert.equal(probes[0].prompt.includes('Zorinda'),false);assert.match(probes[0].prompt,/\[MASK\]/);
  assert.deepEqual(core.candidateNames('the traveller reached Zorinda and later Zorinda returned'.split(' '),''),[]);
  assert.equal(core.scoreAnswer(answer('cloze','Zorinda','ZORINDA!'),20).hit,true);
  assert.equal(core.scoreAnswer(answer('cloze','Zorinda','Zorinda or Alice'),20).hit,false);
  const report=core.makeReport([answer('cloze','Zorinda','Zorinda'),answer('continuation','a b c d e','a b c d e')],{methods:['cloze','continuation'],hitWords:5});
  assert.equal(report.report.length,2);assert.equal(report.report[0].target.hit_groups,1);
});

test('prefix sweeps count a passage once and missing controls cannot produce strong evidence', () => {
  const probes=core.buildProbes(wordText.split(' ').reduce((a,w,i)=>a + (i && i % 110 === 0 ? '\n\n' : ' ') + w,''),'target','doc',3,[16,64],40);
  assert.equal(probes[0].truth,probes[1].truth);assert.equal(probes[0].group,probes[1].group);
  assert.equal(core.summarise(probes.map(p=>core.scoreAnswer({...p,text:p.truth},20))).hit_groups,3);
  const make=(tier,hit)=>Array.from({length:6},(_,i)=>core.scoreAnswer(answer('continuation','a b c d e',hit?'a b c d e':'z y x w v',{group:'g'+i,tier}),5));
  const target=core.summarise(make('target',true)),control=core.summarise(make('control',false));
  assert.equal(core.assess(target,control,'continuation'),'strong');assert.equal(core.assess(target,null,'continuation'),'signal');
  assert.equal(core.assess(target,{...control,reliable:false},'continuation'),'inconclusive');
  assert.equal(core.assess(target,control,'cloze'),'signal');
  assert.equal(core.assess(target,target,'cloze'),'no_signal');
  assert.equal(core.scoreAnswer(answer('continuation','a b c d e','a b c d e',{error:'HTTP 500'}),5).hit,false);
  assert.equal(core.scoreAnswer(answer('continuation','a b c d e','a b c d e',{truncated:true}),5).hit,false);
  assert.equal(core.scoreAnswer(answer('continuation','a b c d e',''),5).missing,true);
  assert.equal(core.scoreAnswer(answer('continuation','a b c d e',"I can't provide that text."),5).refused,true);
  assert.ok(Math.abs(core.clopperPearson(0,30)[1] - 0.1157033082)<1e-8);
});

test('cloze UI works and hostile model replies are rendered as text',()=>{
  const {dom,$,input}=page();input('doc','the traveller reached Zorinda after the rain while '+Array(125).fill('quiet roads crossed fields').join(' '));
  $('m_continuation').checked=false;$('m_cloze').checked=true;$('go').click();assert.match($('current-prompt').value,/\[MASK\]/);
  input('current-answer','<img src=x onerror="alert(1)">');$('scoremanual').click();assert.equal($('result').querySelector('img'),null);assert.match($('result').textContent,/<img/);dom.window.close();
});

test('provider requests have appropriate budgets and never score Gemini thought parts',async()=>{
  const calls=[];const {dom,$,input}=page(async(url,options)=>{calls.push({url,...options});return{ok:true,json:async()=>url.includes('googleapis')?{candidates:[{content:{parts:[{thought:true,text:'hidden thought'},{text:'visible answer'}]},finishReason:'STOP'}]}:url.includes('anthropic')?{content:[{type:'text',text:'visible answer'}],stop_reason:'end_turn'}:{choices:[{message:{content:'visible answer'},finish_reason:'stop'}]}};});
  input('doc',wordText);input('passages','1');$('automatic').click();for(const p of ['openai','google','anthropic'])input('k_'+p,'dummy-'+p);
  for(const el of $('models').querySelectorAll('input'))el.click(); // disable 4.1, enable three others
  $('go').click();for(let i=0;i<10;i++)await tick();assert.equal(calls.length,3);
  const open=JSON.parse(calls.find(c=>c.url.includes('openai')).body);assert.match(open.reasoning_effort,/^(minimal|low)$/);assert.ok(open.max_completion_tokens>2048);
  const google=calls.find(c=>c.url.includes('googleapis'));assert.equal(google.url.includes('dummy'),false);assert.equal(JSON.parse(google.body).generationConfig.thinkingConfig.thinkingLevel,'minimal');
  assert.equal($('result').textContent.includes('hidden thought'),false);assert.match($('result').textContent,/visible answer/);dom.window.close();
});

test('Wikipedia failures preserve a pasted control and remembered keys can be removed',async()=>{
  const {dom,$,input}=page(async()=>{throw new Error('offline');});input('ctrl','my existing control');$('load_fresh').click();await tick();assert.equal($('ctrl').value,'my existing control');assert.match($('fresh_hint').textContent,/existing control was kept/);
  input('k_openai','dummy');$('remember').click();assert.equal(dom.window.localStorage.getItem('didyoueatthis_key_openai'),'dummy');$('forget').click();assert.equal(dom.window.localStorage.getItem('didyoueatthis_key_openai'),null);assert.equal($('k_openai').value,'');dom.window.close();
});

test('custom text needs a declared rights basis and open-licensed text needs attribution',()=>{
  const {dom,$,input}=page();input('doc',wordText);$('rights-basis').value='';$('go').click();
  assert.match($('status').textContent,/Choose a rights basis/);assert.equal($('manualbox').hidden,true);
  $('rights-basis').value='open';$('go').click();assert.match($('status').textContent,/Add source, author and licence/);
  input('source-notes','Example by Test Author; https://example.test/source; CC BY 4.0 https://creativecommons.org/licenses/by/4.0/');$('go').click();
  assert.equal($('manualbox').hidden,false);assert.doesNotMatch($('current-prompt').value,/Test Author/);
  const copied=[];Object.defineProperty(dom.window.navigator,'clipboard',{value:{writeText:async t=>copied.push(t)}});$('copyall').click();
  return new Promise(r=>setTimeout(r,0)).then(()=>{assert.match(copied[0],/Test Author/);assert.match(copied[0],/do not paste into the chat/);dom.window.close();});
});

test('Wikipedia credits survive single/bulk prompts, reports and user edits',async()=>{
  const {dom,$,input}=page();$('quick').click();await tick();
  assert.match($('doc-sources').textContent,/Wikipedia contributors/);assert.doesNotMatch($('current-prompt').value,/CC BY-SA 4.0|curid=123/);
  const copied=[];Object.defineProperty(dom.window.navigator,'clipboard',{value:{writeText:async t=>copied.push(t)}});$('copyall').click();await tick();assert.match(copied[0],/creativecommons.org\/licenses\/by-sa\/4.0/);
  input('current-answer','[UNKNOWN]');$('scoremanual').click();assert.match($('result').textContent,/Source credits and reuse notices/);
  const blobs=[];dom.window.URL.createObjectURL=blob=>{blobs.push(blob);return 'blob:test';};dom.window.URL.revokeObjectURL=()=>{};dom.window.HTMLAnchorElement.prototype.click=()=>{};$('dl').click();
  const content=await new Promise(resolve=>{const reader=new dom.window.FileReader();reader.onload=()=>resolve(reader.result);reader.readAsText(blobs[0]);});const report=JSON.parse(content);
  assert.equal(report.settings.sources.doc[0].revision_observed,456);assert.match(report.reuse_notice,/CC BY-SA/);
  input('doc',$('doc').value+' New words.');$('rights-basis').value='';$('go').click();assert.match($('status').textContent,/rights basis/);assert.match($('doc-sources').textContent,/Wikipedia contributors/);assert.match($('doc-sources').textContent,/Edited by the user/);dom.window.close();
});

test('Wikipedia fetch failures do not replace the target or start a run',async()=>{
  const {dom,$,input}=page(async()=>{throw new Error('offline');});input('doc',wordText);$('quick').click();await tick();assert.equal($('doc').value,wordText);assert.equal($('manualbox').hidden,true);assert.equal($('quick').disabled,false);assert.match($('status').textContent,/existing text was kept/);dom.window.close();
});

test('reasoning shown by the model is scored: hidden recall and guardrail flags', () => {
  const truth = Array.from({length:40},(_,i)=>`hidden${i}`).join(' ');
  const s = core.scoreAnswer(answer('continuation', truth, '[UNKNOWN]', {reasoning: 'This is from a copyrighted book. The text continues: ' + truth.split(' ').slice(0,15).join(' ') + ' ... I should not reproduce it.'}), 20);
  assert.equal(s.hit, false); assert.equal(s.reasoningHit, true); assert.equal(s.guardrail, true);
  const none = core.scoreAnswer(answer('continuation', truth, '[UNKNOWN]'), 20);
  assert.equal(none.reasoningHit, null);
  const sum = core.summarise([s, none]);
  assert.equal(sum.with_reasoning, 1); assert.equal(sum.hidden_recall, 1); assert.equal(sum.guardrail_mentions, 1);
  const cl = core.scoreAnswer(answer('cloze', 'Zorinda', '[UNKNOWN]', {reasoning: 'The masked name is Zorinda but policy says decline.'}), 20);
  assert.equal(cl.reasoningHit, true);
});

test('manual mode accepts pasted thinking via the field and via THINKING markers', async () => {
  const {dom,$,input} = page(); $('quick').click(); await tick();
  const truth = $('current-prompt').value; // not the truth, but any text; we only check plumbing
  input('current-answer','[UNKNOWN]'); input('current-thinking','It is copyrighted, I should decline.');
  input('bulk','##### ANSWER 2 #####\nsecond\n##### THINKING 2 #####\nverbatim recall would violate policy'); $('parsebulk').click();
  $('next').click(); assert.equal($('current-answer').value,'second'); assert.equal($('current-thinking').value,'verbatim recall would violate policy');
  $('scoremanual').click(); assert.match($('result').textContent,/Guardrail weighed/); assert.match($('result').textContent,/GUARDRAIL WEIGHED/);
  dom.window.close();
});
