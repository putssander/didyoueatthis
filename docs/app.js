'use strict';
const $ = id => document.getElementById(id);
const KEYS = ['openai', 'anthropic', 'google'];
const chosen = new Set();
const suggested = ['openai:gpt-4.1', 'openai:gpt-5', 'anthropic:claude-sonnet-4-6', 'google:gemini-3.8-flash'];
let active = null, manualSession = null, current = 0, lastResults = null;
const key = provider => $('k_' + provider).value.trim();
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const documentSources = {doc:[],ctrl:[]};
const editedSources = {doc:false,ctrl:false};
const CC_BY_SA = 'https://creativecommons.org/licenses/by-sa/4.0/';
function wikiSource(page) {
  return {title:page.title,author:'Wikipedia contributors',url:'https://en.wikipedia.org/?curid='+page.pageid,
    history_url:'https://en.wikipedia.org/w/index.php?curid='+page.pageid+'&action=history',
    revision_observed:page.lastrevid || null,retrieved:new Date().toISOString(),license:'CC BY-SA 4.0',license_url:CC_BY_SA,
    notice:'Community text; third-party quotations and notices may have separate terms. No Wikimedia endorsement.',
    changes:'Plain-text extraction; formatting and section headings removed; passages excerpted and names may be masked. These adaptations are offered under CC BY-SA 4.0.'};
}
function sourceNotice(sources) {
  return sources.map(s=>[`${s.title} — ${s.author || 'user-supplied attribution'}`,s.url,s.history_url ? 'Contributors/history: '+s.history_url : '',s.license ? 'Rights: '+s.license : '',s.license_url,s.changes,s.notice].filter(Boolean).join('\n')).join('\n\n');
}
function renderSources(id) {
  const box=$(id+'-sources'); box.textContent = sourceNotice(documentSources[id]);
  for(const source of documentSources[id]){const link=document.createElement('a');link.href=source.url;link.textContent=' Open source: '+source.title;link.target='_blank';link.rel='noopener noreferrer';box.append(link);} 
  $('custom-rights').hidden = !['doc','ctrl'].some(k=>$(k).value.trim() && (!documentSources[k].length || editedSources[k]));
}
function setDocument(id,text,sources) {
  $(id).value=text;documentSources[id]=sources;editedSources[id]=false;renderSources(id);updateEstimate();
}
function inputSources(id) {
  // Retain upstream attribution when someone edits licensed text; new material still needs a rights basis.
  const wasEdited=editedSources[id]; editedSources[id]=true;
  if(!wasEdited) documentSources[id]=documentSources[id].map(s=>({...s,changes:s.changes+' Edited by the user; any added material needs its own rights basis.'}));
  renderSources(id);
}
async function wikiJSON(query) {
  const response=await fetch('https://en.wikipedia.org/w/api.php?origin=*&format=json&'+query,{signal:AbortSignal.timeout(20000)});
  if(!response.ok)throw new Error(`Wikipedia returned HTTP ${response.status}`);
  const data=await response.json();if(data.error)throw new Error(data.error.info);return data;
}
const cleanWiki = text => text.replace(/^\s*=+\s*[^=\n]+?\s*=+\s*$/gm,'').replace(/\n{3,}/g,'\n\n').trim();
async function loadWikipedia() {
  const data=await wikiJSON('action=query&prop=extracts|info&explaintext=1&exlimit=1&titles=Photosynthesis');
  const page=Object.values(data.query?.pages || {})[0];
  if(!page?.extract || page.extract.split(/\s+/).length<400)throw new Error('Wikipedia did not return enough text. Try again or use the Austen example.');
  setDocument('doc',cleanWiki(page.extract),[wikiSource(page)]);
}

const familyName = family => family === 'cloze' ? 'Missing name' : 'Exact continuation';
function status(message, error = false) { $('status').hidden = false; $('status').className = 'notice' + (error ? ' error' : ''); $('status').textContent = message; }
function focusSection(id) { $(id).scrollIntoView({ behavior: 'smooth', block: 'start' }); }
function saveKeys() { try { for (const provider of KEYS) { const name = 'didyoueatthis_key_' + provider; if ($('remember').checked) localStorage.setItem(name, key(provider)); else localStorage.removeItem(name); } } catch { status('This browser cannot remember keys. They will only be used for this session.'); } }
try { for (const provider of KEYS) { const value = localStorage.getItem('didyoueatthis_key_' + provider); if (value) { $('k_' + provider).value = value; $('remember').checked = true; } } } catch { /* Private browsers may disable storage. */ }
$('remember').onchange = saveKeys;
KEYS.forEach(provider => $('k_' + provider).addEventListener('change', saveKeys));
$('forget').onclick = () => { KEYS.forEach(provider => $('k_' + provider).value = ''); $('remember').checked = false; saveKeys(); status('Keys cleared from this page and remembered storage.'); };
function addModel(model, checked = false) {
  if (!/^(openai|anthropic|google):[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(model)) throw new Error('Use openai:model-id, anthropic:model-id or google:model-id.');
  const existing = [...$('models').querySelectorAll('input')].find(input => input.value === model);
  if (existing) { existing.checked = true; chosen.add(model); updateEstimate(); return; }
  const label = document.createElement('label'), input = document.createElement('input');
  label.className = 'check'; input.type = 'checkbox'; input.value = model; input.checked = checked;
  if (checked) chosen.add(model);
  input.onchange = () => { if (input.checked) chosen.add(model); else chosen.delete(model); updateEstimate(); };
  label.append(input, document.createTextNode(model)); $('models').append(label);
}
suggested.forEach((model, index) => addModel(model, index === 0));
function customModel() { try { addModel($('custom').value.trim(), true); $('custom').value = ''; $('model-feedback').textContent = 'Model added. Its availability depends on your account.'; } catch (error) { $('model-feedback').textContent = error.message; } }
$('add-model').onclick = customModel;
$('custom').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); customModel(); } };
function setMode() { $('api-panel').hidden = $('manual').checked; $('manual-help').hidden = !$('manual').checked; $('go').textContent = $('manual').checked ? 'Create my prompts →' : 'Run test with selected models →'; updateEstimate(); }
$('manual').onchange = setMode; $('automatic').onchange = setMode;
function integer(id, low, high) { const n = Number($(id).value); if (!Number.isInteger(n) || n < low || n > high) throw new Error(`${$(id).labels[0].textContent} must be a whole number from ${low} to ${high}.`); return n; }
function readSettings() {
  const prefixWords = [...new Set($('prefix').value.split(',').map(x => Number(x.trim())))];
  if (!prefixWords.length || prefixWords.some(n => !Number.isInteger(n) || n < 1 || n > 512)) throw new Error('Prefix lengths must be comma-separated whole numbers from 1 to 512.');
  const suffixWords = integer('suffix', 10, 120), hitWords = integer('hitw', 5, 120);
  if (hitWords > suffixWords) throw new Error('The exact-word threshold cannot exceed the hidden ending length.');
  const methods = ['continuation', 'cloze'].filter(m => $('m_' + m).checked);
  if (!methods.length) throw new Error('Select at least one test method.');
  return { sources: JSON.parse(JSON.stringify(documentSources)), rights_basis: $('rights-basis').value, source_notes: $('source-notes').value.trim(), text: $('doc').value.trim(), ctrl: $('ctrl').value.trim(), nP: integer('passages', 1, 60), prefixWords: prefixWords.sort((a,b) => a-b), suffixWords, hitWords, concurrency: integer('conc', 1, 8), methods };
}
function updateEstimate() {
  for (const id of ['doc','ctrl']) $(id + '-count').textContent = `${$(id).value.trim() ? $(id).value.trim().split(/\s+/).length.toLocaleString() : 0} words`;
  try { const st = readSettings(); if (!st.text) { $('estimate').textContent = 'Add your text to prepare the test.'; return; }
    const probes = buildAll(st), n = probes.length, modelCount = $('manual').checked ? 1 : chosen.size;
    $('estimate').textContent = `${n} prompts${$('manual').checked ? ' to copy and paste' : ` × ${modelCount} models = ${n * modelCount} API requests (plus any retries)`}. ${st.nP < 5 ? 'Short exploratory test.' : 'Inspect the number of usable passages in your report.'}${st.ctrl ? '' : ' No control added.'}`;
  } catch (error) { $('estimate').textContent = error.message; }
}
for (const id of ['doc','ctrl','passages','prefix','suffix','hitw','conc','m_continuation','m_cloze']) $(id).addEventListener('input', updateEstimate);
for (const id of ['doc','ctrl']) $(id).addEventListener('input',()=>inputSources(id));
for (const id of ['doc','ctrl']) $('f_' + id).onchange = async event => { const file = event.target.files[0]; if (!file) return; try { setDocument(id,await file.text(),[]); } catch { status('That file could not be read. Try pasting its text instead.', true); } };
function loadBook() { setDocument('doc',$('pp_excerpt').content.textContent.trim(),[{title:'Pride and Prejudice (1813), excerpt',author:'Jane Austen (1775–1817)',url:'https://www.gutenberg.org/ebooks/1342',license:'Original English novel: public-domain source; check applicable local law for your use.',changes:'Excerpted; illustrations and edition captions omitted; whitespace normalised and names may be masked.',notice:'Source edition information: https://www.gutenberg.org/ebooks/1342 — reuse guidance: https://www.gutenberg.org/policy/permission.html'}]); }
$('load_pos').onclick = loadBook;
$('load_wiki').onclick = async()=>{ $('load_wiki').disabled=true; try {await loadWikipedia();status('Wikipedia text loaded with contributor credit and CC BY-SA notices. Review the source for third-party material.');} catch(error){status(error.message,true);} finally{$('load_wiki').disabled=false;} };
$('full-settings').onclick = () => { $('passages').value = '12'; $('prefix').value = '16,32,64,128'; updateEstimate(); };
async function recentWiki() {
  $('load_fresh').disabled = true; $('fresh_hint').textContent = 'Looking for recent articles with enough text…';
  try {
    const json = wikiJSON;
    let continuation = '', collected = [], scanned = 0; const seen = new Set();
    do {
      const changes = await json('action=query&list=recentchanges&rctype=new&rcnamespace=0&rcshow=!redirect&rclimit=50' + (continuation ? '&rccontinue=' + encodeURIComponent(continuation) : ''));
      const pages = changes.query?.recentchanges || []; scanned += pages.length;
      for (let i = 0; i < pages.length && collected.length < 4; i += 20) {
        const batch = pages.slice(i, i + 20); if (!batch.length) continue;
        const extracted = await json('action=query&prop=extracts|info&explaintext=1&exlimit=20&pageids=' + batch.map(p => p.pageid).join('|'));
        for (const page of Object.values(extracted.query?.pages || {})) {
          if (seen.has(page.pageid) || (page.extract || '').split(/\s+/).length < 400) continue;
          seen.add(page.pageid); collected.push({ source: wikiSource(page), text: cleanWiki(page.extract), title: page.title, created: pages.find(p => p.pageid === page.pageid)?.timestamp });
          if (collected.length === 4) break;
        }
      }
      continuation = changes.continue?.rccontinue || '';
    } while (collected.length < 4 && scanned < 150 && continuation);
    if (!collected.length) throw new Error('No sufficiently long articles found. Paste a control text instead.');
    setDocument('ctrl',collected.map(p => p.text).join('\n\n'),collected.map(p=>p.source));
    $('fresh_hint').textContent = `Loaded ${collected.length} articles: ${collected.map(p => `${p.title} (created ${p.created?.slice(0,10) || 'recently'})`).join('; ')}. Their wording may come from older sources.`;
    updateEstimate();
  } catch (error) { $('fresh_hint').textContent = 'Could not load Wikipedia: ' + error.message + ' Your existing control was kept.'; }
  finally { $('load_fresh').disabled = false; }
}
$('load_fresh').onclick = recentWiki;
function prepare() {
  const settings = readSettings(); if (!settings.text) throw new Error('Add your text or use the book example first.');
  const custom = ['doc','ctrl'].some(id=>$(id).value.trim() && (!documentSources[id].length || editedSources[id]));
  if (custom && !settings.rights_basis) throw new Error('Choose a rights basis for the text you supplied before creating prompts or sending it to a provider.');
  if (custom && ['open','public-domain'].includes(settings.rights_basis) && !settings.source_notes) throw new Error('Add source, author and licence notices (or public-domain basis) for the text you supplied.');
  let probes = buildAll(settings);
  for (const probe of probes) {
    const id=probe.tier==='target'?'doc':'ctrl';
    probe.sources=settings.sources[id];   // credits travel with exports and reports, never inside the model prompt
  }
  for (const method of settings.methods) for (const tier of settings.ctrl ? ['target','control'] : ['target']) {
    if (!probes.some(p => p.family === method && p.tier === tier)) throw new Error(`${tier === 'target' ? 'Your text' : 'The control text'} has no usable ${familyName(method).toLowerCase()} prompts. ${method === 'cloze' ? 'Use longer English text containing distinctive names, or turn off the missing-name method.' : 'Add more text or reduce the prefix length.'}`);
  }
  return { settings, probes };
}
function clearResults() { lastResults = null; $('result').hidden = true; $('dl').hidden = true; }
function openManual(session) {
  manualSession = { ...session, answers: session.probes.map(() => '') }; current = 0;
  $('bulk').value = ''; $('bulk-feedback').textContent = ''; $('manualbox').hidden = false; clearResults(); showPrompt();
  status(`Ready: ${session.probes.length} prompts. Start with the first, then paste the model’s reply. ${session.settings.ctrl ? '' : 'This run has no control, so it cannot establish strong evidence.'}`);
  focusSection('manualbox');
}
const promptText = probe => probe.system + '\n\n' + probe.prompt;
function showPrompt() {
  const probe = manualSession.probes[current];
  $('prompt-position').textContent = `Prompt ${current + 1} of ${manualSession.probes.length}`;
  $('prompt-meta').textContent = `${probe.tier === 'target' ? 'Your text' : 'Control text'} · ${familyName(probe.family)}${probe.prefixWords ? ' · ' + probe.prefixWords + '-word prefix' : ''}`;
  $('current-prompt').value = promptText(probe); $('current-answer').value = manualSession.answers[current];
  $('prev').disabled = current === 0; $('next').disabled = current === manualSession.probes.length - 1;
  $('copy-feedback').textContent = ''; updateManualProgress();
}
function updateManualProgress() { const n = manualSession.answers.filter(a => a.trim()).length; $('manual-count').textContent = `${n} replies pasted`; $('manual-progress').max = manualSession.probes.length; $('manual-progress').value = n; $('scoremanual').disabled = n === 0; }
$('current-answer').oninput = () => { manualSession.answers[current] = $('current-answer').value; updateManualProgress(); clearResults(); };
$('mlabel').oninput = clearResults;
$('prev').onclick = () => { if (current > 0) { current--; showPrompt(); } };
$('next').onclick = () => { if (current + 1 < manualSession.probes.length) { current++; showPrompt(); } };
async function copyText(text, feedback, fallback) { try { await navigator.clipboard.writeText(text); $(feedback).textContent = ' Copied! Open a fresh chat for this prompt.'; } catch { if (fallback) { $(fallback).focus(); $(fallback).select(); } $(feedback).textContent = fallback ? ' Copy was blocked. The text is selected; use your browser’s Copy command.' : ' Copy was blocked. Use Download prompts instead.'; } }
$('copy-prompt').onclick = () => copyText(promptText(manualSession.probes[current]), 'copy-feedback', 'current-prompt');
const creditsBlock = () => { const seen = new Map(); manualSession.probes.forEach(p => (p.sources || []).forEach(s => seen.set(s.title + s.url, s))); const notes = readSettings().source_notes; const text = sourceNotice([...seen.values()]) + (notes ? '\n\nUser-supplied source/rights notices:\n' + notes : ''); return text.trim() ? '\n\n## Source credits and reuse notices (keep with this file; do not paste into the chat)\n\n' + text : ''; };
const allPrompts = () => manualSession.probes.map((p,i) => `##### PROMPT ${i+1} #####\n${promptText(p)}`).join('\n\n') + creditsBlock();
$('copyall').onclick = () => copyText(allPrompts(), 'bulk-feedback');
function download(name, text, type) { const url = URL.createObjectURL(new Blob([text], {type})), a = document.createElement('a'); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
$('dlprompts').onclick = () => download('didyoueatthis-prompts.md', 'Use one prompt per NEW chat, with search, files and memory off.\n\n' + allPrompts() + '\n\n## Paste replies using these markers\n\n' + manualSession.probes.map((_,i) => `##### ANSWER ${i+1} #####\n`).join('\n'), 'text/markdown');
$('parsebulk').onclick = () => {
  const matches = [...$('bulk').value.matchAll(/^\s*##### ANSWER (\d+) #####\s*\r?\n([\s\S]*?)(?=^\s*##### ANSWER \d+ #####\s*(?:\r?\n|$)|$(?![\s\S]))/gm)];
  const seen = new Set(); let count = 0;
  for (const match of matches) { const index = +match[1] - 1; if (index < 0 || index >= manualSession.answers.length || seen.has(index)) { $('bulk-feedback').textContent = 'Invalid or duplicate answer number. No replies were changed.'; return; } seen.add(index); }
  for (const match of matches) { if (match[2].trim()) { manualSession.answers[+match[1]-1] = match[2].trim(); count++; } }
  $('bulk-feedback').textContent = count ? `Filled ${count} replies.` : 'No replies found. Use a marker such as ##### ANSWER 1 ##### on its own line, followed by the reply.';
  showPrompt(); clearResults();
};
$('scoremanual').onclick = () => { const model = $('mlabel').value.trim() || 'Unnamed chat model'; const answers = manualSession.probes.map((p,i) => ({...p, model, text: manualSession.answers[i]})); finishReport(answers, manualSession.settings, 'manual'); };
function providerRequest(qualified, probe, keys) {
  const colon = qualified.indexOf(':'), provider = qualified.slice(0, colon), model = qualified.slice(colon + 1);
  const secret = keys[provider]; if (!secret) throw new Error(`Add an API key for ${provider}.`);
  let url, body; const headers = {'content-type':'application/json'};
  if (provider === 'openai') {
    url = 'https://api.openai.com/v1/chat/completions'; headers.authorization = 'Bearer ' + secret;
    const reasoning = /^(gpt-[56]|o[134])/.test(model);
    body = { model, messages: [{role:'system',content:probe.system},{role:'user',content:probe.prompt}], max_completion_tokens: probe.maxTokens + (reasoning ? 2048 : 0) };
    if (reasoning) body.reasoning_effort = /^gpt-5(?:-\d{4}-\d{2}-\d{2})?$/.test(model) || /^gpt-5-(mini|nano)/.test(model) ? 'minimal' : 'low';
    else body.temperature = 0;
  } else if (provider === 'anthropic') {
    url = 'https://api.anthropic.com/v1/messages';
    Object.assign(headers, {'x-api-key':secret,'anthropic-version':'2023-06-01','anthropic-dangerous-direct-browser-access':'true'});
    body = {model, max_tokens:Math.max(256,probe.maxTokens), system:probe.system, messages:[{role:'user',content:probe.prompt}]};
    // Avoid optional sampling/effort fields that vary across Claude generations.
  } else if (provider === 'google') {
    url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`;
    headers['x-goog-api-key'] = secret;
    const generationConfig = {maxOutputTokens: Math.max(64,probe.maxTokens) + 2048};
    if (model.startsWith('gemini-3')) generationConfig.thinkingConfig = {thinkingLevel: model.includes('flash') ? 'minimal' : 'low'};
    else if (model.startsWith('gemini-2.5') && model.includes('flash')) { generationConfig.thinkingConfig = {thinkingBudget:0}; generationConfig.temperature = 0; }
    body = {system_instruction:{parts:[{text:probe.system}]},contents:[{role:'user',parts:[{text:probe.prompt}]}],generationConfig};
  } else throw new Error('Unsupported provider.');
  return {url,body,headers,provider};
}
function parseResponse(provider, data) {
  if (provider === 'openai') { const c = data.choices?.[0]; return {text:c?.message?.content || c?.message?.refusal || '',refused:Boolean(c?.message?.refusal || c?.finish_reason === 'content_filter'),truncated:c?.finish_reason === 'length',meta:{finish_reason:c?.finish_reason,fingerprint:data.system_fingerprint,usage:data.usage}}; }
  if (provider === 'anthropic') return {text:(data.content || []).filter(p=>p.type === 'text').map(p=>p.text).join(''),refused:data.stop_reason === 'refusal',truncated:data.stop_reason === 'max_tokens',meta:{finish_reason:data.stop_reason,usage:data.usage}};
  const candidate = data.candidates?.[0], reason = candidate?.finishReason || data.promptFeedback?.blockReason || '';
  return {text:(candidate?.content?.parts || []).filter(p=>!p.thought).map(p=>p.text || '').join(''),refused:Boolean(data.promptFeedback?.blockReason || /SAFETY|BLOCK|PROHIBITED|RECITATION/.test(reason)),truncated:reason === 'MAX_TOKENS',meta:{finish_reason:reason,usage:data.usageMetadata}};
}
async function callModel(model, probe, session) {
  const request = providerRequest(model, probe, session.keys);
  for (let attempt = 0; attempt < 3; attempt++) {
    if (session.controller.signal.aborted) throw new Error('Run stopped.');
    const response = await fetch(request.url, {method:'POST', headers:request.headers, body:JSON.stringify(request.body), signal:AbortSignal.any([session.controller.signal,AbortSignal.timeout(60000)])});
    if ((response.status === 429 || response.status >= 500) && attempt < 2) {
      await new Promise(resolve=>setTimeout(resolve,1000 * 2 ** attempt)); continue;
    }
    if (!response.ok) { const hint = response.status === 401 || response.status === 403 ? 'Check the key and its permissions.' : response.status === 429 ? 'Quota or rate limit reached. Check billing or retry later.' : response.status === 404 ? 'This model may be unavailable. Check the model ID.' : 'The provider rejected this request. Check model compatibility or use copy-paste mode.'; throw new Error(`HTTP ${response.status}. ${hint}`); }
    const result = parseResponse(request.provider, await response.json());
    if (!result.text.trim() && !result.refused) result.error = result.truncated ? 'Output budget exhausted before a visible answer.' : 'The provider returned no visible answer.';
    return result;
  }
}
function busy(on) {
  // Freeze the run configuration while requests are in progress. Stop stays available.
  for (const element of $('test').querySelectorAll('input,textarea,select,button')) element.disabled = on;
  $('quick').disabled = on; $('stop').disabled = false; $('stop').hidden = !on;
}
async function run() {
  if (active) return;
  let prepared;
  try {
    prepared = prepare();
    if ($('manual').checked) { openManual(prepared); return; }
    if (!chosen.size) throw new Error('Select at least one model.');
    for (const model of chosen) if (!key(model.split(':')[0])) throw new Error(`Add the ${model.split(':')[0]} API key or switch to Copy & paste.`);
  } catch (error) { status(error.message, true); focusSection('status'); return; }
  saveKeys(); clearResults(); $('manualbox').hidden = true;
  const session = {...prepared, keys:Object.fromEntries(KEYS.map(p=>[p,key(p)])), controller:new AbortController()};
  active = session; busy(true);
  const jobs = [...chosen].flatMap(model=>session.probes.map(probe=>({model,probe})));
  const answers = jobs.map(({model,probe})=>({...probe,model,text:'',error:'Not run.'}));
  let cursor = 0, completed = 0; const failedModels = new Map();
  status(`Running ${jobs.length} requests. You can stop and keep partial results.`);
  try {
    await Promise.all(Array.from({length:Math.min(session.settings.concurrency,jobs.length)},async()=>{
      while (cursor < jobs.length && !session.controller.signal.aborted) {
        const index = cursor++, {model,probe} = jobs[index];
        try { if (failedModels.has(model)) throw new Error(failedModels.get(model)); const result = await callModel(model,probe,session); answers[index] = {...probe,model,...result}; }
        catch (error) { const message = session.controller.signal.aborted ? 'Run stopped.' : error.name === 'TimeoutError' ? 'Request timed out. Retry or use copy-paste mode.' : error instanceof TypeError ? 'Network or browser access failed. Try copy-paste mode.' : error.message; answers[index] = {...probe,model,text:'',error:message}; if (/HTTP (400|401|403|404|429)|Network or browser/.test(message)) failedModels.set(model,message); }
        status(`${++completed} / ${jobs.length} requests processed${failedModels.size ? '. A provider failed; details will appear in the report.' : '.'}`);
      }
    }));
    finishReport(answers,session.settings,'api',session.controller.signal.aborted);
  } finally { session.keys = {}; active = null; busy(false); }
}
$('go').onclick = run;
$('stop').onclick = () => { if (active) { active.controller.abort(); $('stop').disabled = true; status('Stopping requests and preparing partial results…'); } };
$('quick').onclick = async () => { if (active) return; $('quick').disabled=true; status('Loading a Wikipedia example with source credits…'); try {await loadWikipedia();} catch(error){status(error.message+' Your existing text was kept; the Austen example is also available below.',true);$('quick').disabled=false;return;} setDocument('ctrl','',[]); $('manual').checked = true; $('passages').value = '3'; $('prefix').value = '64'; $('suffix').value = '40'; $('hitw').value = '20'; $('m_continuation').checked = true; $('m_cloze').checked = false; setMode(); $('quick').disabled=false; run(); };
const verdictLabels = {strong:'Strong continuation evidence',signal:'A signal worth checking',no_signal:'No signal above the control',inconclusive:'Exploratory / inconclusive'};
function explanation(r) {
  if (!r.target.n_groups) return 'No usable target passages were generated for this method.';
  if (r.target.usable_groups < 5) return 'This is a short or incomplete test. Matches below are observations; at least five usable target passages are needed for a verdict.';
  if (!r.target.reliable || (r.control && !r.control.reliable)) return 'Some replies are missing, unknown, refused or failed. Inspect any matches below, but this run cannot support a complete comparison.';
  if (r.control && r.control.usable_groups < 5) return 'The control has too few usable passages for a meaningful comparison. Add more matched control text.';
  if (!r.control) return 'There is no control text. Any exact matches are worth inspecting, but this test cannot establish strong evidence or rule out exposure.';
  if (r.family === 'cloze') return r.verdict === 'signal' ? 'The name-match rate clears the control’s interval. This is suggestive; contextual inference and predictable names can also produce correct answers.' : 'Name recall is not clearly separated from the control. Names can be guessed from context; no result here proves training membership or absence.';
  if (r.verdict === 'strong') return 'At least three passages have an exact continuation and clear the page’s control heuristic. This is consistent with exposure, subject to control quality and other sources of information.';
  if (r.verdict === 'signal') return 'At least one continuation meets the exact-match threshold above the control heuristic. Inspect the wording and repeat with more passages.';
  return 'Exact continuation did not clear the control heuristic. This does not show that the model was never trained on the text.';
}
function finishReport(answers, settings, mode, stopped = false) {
  const {report,scored} = makeReport(answers,settings);
  // Exclude full input documents and API keys; include prompts and held-out answers for inspection.
  const {text,ctrl,...safeSettings} = settings;
  lastResults = {version:3,reuse_notice:'Preserve source credits and licences. Wikipedia excerpt/adaptation material is CC BY-SA 4.0 where applicable, with third-party exceptions. Review model replies before redistribution; no rights in unrelated output are granted by this report.',date:new Date().toISOString(),mode,stopped,settings:safeSettings,has_control:Boolean(ctrl),grading:'Exploratory browser heuristics; methods scored separately. Not a training-membership probability.',report,answers:scored};
  render(report,scored,settings);
  $('dl').hidden = false;
  status(stopped ? 'Run stopped. Partial results are below; unrun requests are marked as errors.' : 'Results ready. Inspect the matches and limitations below.');
  focusSection('result');
}
$('dl').onclick = () => download('didyoueatthis-results.json',JSON.stringify(lastResults,null,2),'application/json');
function render(report,scored,settings) {
  const out = $('result'); out.hidden = false; out.replaceChildren();
  for (const r of report) {
    const card = document.createElement('article'); card.className = 'result-card';
    const mine = scored.filter(s=>s.model === r.model && s.family === r.family);
    let html = `<p class="eyebrow">${esc(r.model)} · ${familyName(r.family)}</p><h2 class="verdict ${r.verdict}">${verdictLabels[r.verdict]}</h2><p>${explanation(r)}</p><div class="result-grid"><div class="metric"><b>${r.target.hit_groups} / ${r.target.n_groups}</b><span>Your text · passages with a match</span></div><div class="metric"><b>${r.control ? `${r.control.hit_groups} / ${r.control.n_groups}` : '—'}</b><span>Control · ${r.control ? 'passages with a match' : 'not supplied'}</span></div></div>`;
    html += `<p class="hint">${r.family === 'cloze' ? 'A hit is the exact missing name, ignoring case and surrounding punctuation. Guessability is not a known fixed chance rate.' : `A hit requires the first ${settings.hitWords} normalised words of the hidden ending (or the entire ending if tokenisation makes it shorter). Prefix variants of one passage count once.`} These counts are not a probability that the model trained on your document.</p>`;
    const sources=[...new Map(mine.flatMap(s=>s.sources || []).map(s=>[s.url || s.title,s])).values()];
    if(sources.length || settings.source_notes)html+=`<details><summary>Source credits and reuse notices</summary><pre>${esc(sourceNotice(sources))}\n${esc(settings.source_notes || '')}</pre></details>`;
    html += '<details><summary>Coverage, uncertainty and failures</summary><div class="wrap"><table><thead><tr><th>Text</th><th>Usable replies</th><th>Unknown</th><th>Refused</th><th>Missing</th><th>Error / truncated</th><th>Hit rate · 95% interval</th></tr></thead><tbody>';
    for (const [name,s] of [['Your text',r.target],['Control',r.control]]) if (s) html += `<tr><td>${name}</td><td>${s.answered}/${s.n_probes}</td><td>${s.unknown}</td><td>${s.refused}</td><td>${s.missing}</td><td>${s.errors}</td><td>${(100*s.rate).toFixed(0)}% · ${(100*s.ci_lo).toFixed(0)}–${(100*s.ci_hi).toFixed(0)}%</td></tr>`;
    html += '</tbody></table></div><p class="hint">Intervals are descriptive Clopper–Pearson intervals over sampled passages, including unanswered passages in the denominator. They are not calibrated membership confidence. Passages within one document may be correlated. Incomplete or unknown responses prevent a definitive category.</p>';
    for (const error of new Set(mine.filter(s=>s.error).map(s=>s.error))) html += `<p class="hint">${esc(error)}</p>`;
    html += '</details>';
    const hits = mine.filter(s=>s.hit);
    html += `<details${hits.length ? ' open' : ''}><summary>Inspect ${hits.length} matching ${hits.length === 1 ? 'reply' : 'replies'}</summary>`;
    if (!hits.length) html += '<p>No reply met the exact-match threshold.</p>';
    for (const s of hits) html += exhibit(s);
    html += `</details><details><summary>Inspect all ${mine.length} prompts and replies</summary>` + mine.map(exhibit).join('') + '</details>';
    html += '<p class="note">Next: check the actual wording, add a closely matched control, and try more passages or another model. Keep search and connected files off throughout.</p>';
    card.innerHTML = html; out.append(card);
  }
}
function exhibit(s) { return `<div class="exhibit"><p class="hint">${esc(s.tier)} · ${esc(s.group)}${s.prefixWords ? ' · prefix ' + s.prefixWords : ''} · ${s.hit ? 'MATCH' : s.error ? 'ERROR' : s.truncated ? 'TRUNCATED' : s.missing ? 'NOT ANSWERED' : s.refused ? 'REFUSED' : s.unknown ? 'UNKNOWN' : 'NO MATCH'}</p><details><summary>Prompt</summary><pre>${esc(promptText(s))}</pre></details><p class="hint">Held-out answer</p><pre>${esc(s.truth)}</pre><p class="hint">Model reply · ${s.ep} leading words exact · ${s.run} longest matching run</p><pre>${esc(s.error || s.text || '(no reply)')}</pre></div>`; }
setMode();
