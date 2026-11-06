const BASE = import.meta.env.VITE_API || '/api'

async function req(path, opts = {}) {
  const r = await fetch(BASE + path, opts)
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch { /* ignore */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return r.json()
}
const json = (method, body) => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const api = {
  health: () => req('/health'),
  papers: (q = '') => req('/papers?q=' + encodeURIComponent(q)),
  paper: (id) => req(`/papers/${id}`),
  audit: (id) => req(`/papers/${id}/audit`),
  // XHR (not fetch) so large files report real upload progress
  upload: (file, confidential, license, onProgress) => new Promise((resolve, reject) => {
    const f = new FormData()
    f.append('file', file); f.append('confidential', confidential); f.append('license', license)
    const x = new XMLHttpRequest()
    x.open('POST', BASE + '/papers/upload')
    x.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((e.loaded / e.total) * 100))
    x.onload = () => {
      let body = {}
      try { body = JSON.parse(x.responseText) } catch { /* ignore */ }
      if (x.status < 300) return resolve(body)
      const d = body.detail
      const err = new Error(typeof d === 'string' ? d : d?.message || x.statusText)
      if (d && typeof d === 'object') err.info = d          // e.g. {code:'duplicate', existing_id, title, matched_by}
      err.status = x.status
      reject(err)
    }
    x.onerror = () => reject(new Error('Network error'))
    x.send(f)
  }),
  checkHash: (sha256) => req('/papers/check-hash?sha256=' + sha256),
  ingestFolder: () => req('/ingest/folder', { method: 'POST' }),
  reExtract: (id) => req(`/papers/${id}/extract`, { method: 'POST' }),
  remove: (id) => req(`/papers/${id}`, { method: 'DELETE' }),
  pubmedSearch: (q) => req('/pubmed/search?q=' + encodeURIComponent(q)),
  pubmedIngest: (pmid) => req('/pubmed/ingest', json('POST', { pmid })),
  chat: (question, paper_ids) => req('/chat', json('POST', { question, paper_ids })),
  guardrails: () => req('/guardrails'),
  setGuardrails: (patch) => req('/guardrails', json('PUT', patch)),
  testGuardrails: (text) => req('/guardrails/test', json('POST', { text })),
  runEval: (llm) => req('/eval/run?use_llm=' + llm, { method: 'POST' }),
  latestEval: () => req('/eval/latest'),
  usage: () => req('/metrics/usage'),
  llmStatus: () => req('/llm/status'),
  llmTest: (target) => req('/llm/test', json('POST', { target })),
  llmOutage: (on) => req('/llm/simulate-outage', json('POST', { on })),
  llmReset: () => req('/llm/reset-circuit', { method: 'POST' }),
  llmConfig: (c) => req('/llm/config', json('PUT', c)),
  llmFallbacks: () => req('/llm/fallbacks'),
  tokenomics: (days) => req('/tokenomics?days=' + days),
  tokSettings: (b) => req('/tokenomics/settings', json('PUT', b)),
  tokPrice: (model, price_in, price_out) => req('/tokenomics/price', json('PUT', { model, price_in, price_out })),
  jobs: () => req('/jobs'),
  bulkPubmed: (query, n) => req('/jobs/pubmed-bulk', json('POST', { query, n })),
  biorxiv: (b) => req('/connectors/biorxiv', json('POST', b)),
  sqlImport: (b) => req('/connectors/sql', json('POST', b)),
  folderJob: () => req('/connectors/folder', { method: 'POST' }),
  searches: () => req('/monitor/searches'),
  addSearch: (s) => req('/monitor/searches', json('POST', s)),
  delSearch: (id) => req(`/monitor/searches/${id}`, { method: 'DELETE' }),
  runSearch: (id) => req(`/monitor/searches/${id}/run`, { method: 'POST' }),
  alerts: () => req('/monitor/alerts'),
  alertsSeen: () => req('/monitor/alerts/seen', { method: 'POST' }),
  search: (q) => req('/search?q=' + encodeURIComponent(q)),
  explore: () => req('/explore'),
  baseline: () => req('/settings/baseline'),
  setBaseline: (m) => req('/settings/baseline', json('PUT', { manual_review_minutes: m })),
  feedback: (paper_id, kind, rating) => req('/feedback', json('POST', { paper_id, kind, rating })),
}
