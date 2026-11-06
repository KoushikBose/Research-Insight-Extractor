import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Activity, LoadingButton } from './Spinner.jsx'

const GROUPS = {
  'Parsing & segmentation': ['segmentation_accuracy'],
  'Extraction accuracy': ['extraction_fact_recall', 'entity_recall', 'keyword_precision@10', 'keyword_recall', 'keyword_f1'],
  'Summary quality': ['rouge1_f', 'rouge2_f', 'rougeL_f'],
  'Faithfulness': ['grounding_rate', 'hallucination_rate', 'numeric_support_rate', 'fabricated_claim_rejected'],
  'Retrieval & dedupe': ['retrieval_recall@1', 'retrieval_recall@3', 'retrieval_mrr', 'bm25_synonym_recall@1', 'semantic_synonym_recall@1', 'hybrid_synonym_recall@1', 'dedupe_accuracy'],
  'Guardrails': ['injection_detection_tpr', 'injection_false_positive_rate', 'document_injection_neutralised',
    'pii_redaction_recall', 'pii_false_positive_rate', 'medical_advice_block_tpr', 'benign_query_pass_rate', 'upload_rejection_rate'],
  'Performance & impact': ['latency_p50_ms', 'latency_p95_ms', 'review_time_reduction'],
}
const fmt = (k, v) => (k.includes('latency') ? `${(v / 1000).toFixed(2)} s` : v <= 1 && !k.includes('mrr') ? `${(v * 100).toFixed(1)}%` : v)

export default function Evaluation({ llmEnabled }) {
  const [rep, setRep] = useState(null)
  const [usage, setUsage] = useState(null)
  const [busy, setBusy] = useState(false)
  const [which, setWhich] = useState('')
  const [base, setBase] = useState(20)
  const [err, setErr] = useState('')

  useEffect(() => { api.latestEval().then(setRep).catch(() => {}); api.usage().then(setUsage).catch(() => {}); api.baseline().then((b) => setBase(b.manual_review_minutes)).catch(() => {}) }, [])
  const run = async (llm) => {
    setBusy(true); setErr(''); setWhich(llm ? 'llm' : 'base')
    try { setRep(await api.runEval(llm)) } catch (e) { setErr(e.message) }
    setBusy(false)
  }

  return (
    <div className="stack">
      <section className="card">
        <div className="row between">
          <h2>Evaluation matrix</h2>
          <div className="row">
            <LoadingButton loading={busy && which === 'base'} disabled={busy} label="Run (extractive baseline)" busyLabel="Running…" onClick={() => run(false)} />
            <LoadingButton loading={busy && which === 'llm'} disabled={busy || !llmEnabled} title={llmEnabled ? '' : 'Set GROQ_API_KEY'} label="Run (LLM engine)" busyLabel="Running…" onClick={() => run(true)} />
          </div>
        </div>
        {err && <div className="alert bad">{err}</div>}
        {busy && <Activity text={which === 'llm' ? 'Running benchmark with the LLM engine (calls the API per paper)…' : 'Running benchmark…'} />}
        {rep && <p>Engine: <b>{rep.engine}</b> {rep.model && `(${rep.model})`} · {rep.n_papers} gold papers ·
          targets passed <b>{rep.passed}/{rep.total_targets}</b></p>}
      </section>

      {rep && (
        <div className="grid3">
          {Object.entries(GROUPS).map(([g, keys]) => (
            <section className="card" key={g}>
              <h3>{g}</h3>
              <table><tbody>
                {keys.filter((k) => k in rep.metrics).map((k) => {
                  const t = rep.targets[k]
                  return (
                    <tr key={k}>
                      <td>{k.replace(/_/g, ' ')}</td>
                      <td><b>{fmt(k, rep.metrics[k])}</b></td>
                      <td>{t ? <span className={'pill ' + (t.pass ? 'ok' : 'bad')} title={`target ${t.op} ${t.threshold}`}>{t.pass ? 'PASS' : 'FAIL'}</span> : null}</td>
                    </tr>)
                })}
              </tbody></table>
            </section>
          ))}
        </div>
      )}

      {rep && (
        <section className="card">
          <h3>Field-level fact recall</h3>
          {Object.entries(rep.per_field_fact_recall).map(([f, v]) => (
            <div key={f} className="bar"><span>{f}</span><div><i style={{ width: `${v * 100}%` }} className={v < 0.6 ? 'low' : ''} /></div><b>{(v * 100).toFixed(0)}%</b></div>
          ))}
          <h3>Per paper</h3>
          <table>
            <thead><tr><th>Paper</th><th>Fact recall</th><th>ROUGE-1</th><th>Keyword recall</th><th>Latency</th><th>Weak fields</th></tr></thead>
            <tbody>{rep.per_paper.map((p) => (
              <tr key={p.paper}><td>{p.paper}</td><td>{p.fact_recall}</td><td>{p.rouge1}</td><td>{p.keyword_recall}</td>
                <td>{p.latency_ms} ms</td><td>{p.weak_fields.join(', ') || '—'}</td></tr>))}</tbody>
          </table>
        </section>
      )}

      {usage && (
        <section className="card">
          <div className="row"><label className="check">Manual review baseline (min/paper)
            <input type="number" min="1" max="600" value={base} style={{ width: 80 }} onChange={(e) => setBase(Number(e.target.value))}
              onBlur={() => api.setBaseline(base).then(() => api.usage().then(setUsage))} /></label>
            <small>Measured time-to-insight (upload + extraction) is compared against this, over {usage.measured_papers} paper(s).</small></div>
          <div className="row between"><h3>Live usage &amp; adoption</h3><button className="ghost small" onClick={() => api.usage().then(setUsage)}>Refresh</button></div>
          <div className="kpis">
            {[['Papers ingested', usage.papers_ingested], ['Ready', usage.papers_ready], ['Assistant queries', usage.chat_queries],
              ['Blocked by guardrails', usage.chat_blocked], ['Avg extraction', `${usage.avg_extraction_s}s`],
              ['Review-time reduction', usage.review_time_reduction != null ? `${(usage.review_time_reduction * 100).toFixed(1)}%` : '—'],
              ['Hours saved (est.)', usage.hours_saved_est], ['Live grounding', usage.avg_live_grounding_rate != null ? `${(usage.avg_live_grounding_rate * 100).toFixed(0)}%` : '—'],
              ['👍 rate', usage.feedback_positive_rate != null ? `${(usage.feedback_positive_rate * 100).toFixed(0)}%` : '—']]
              .map(([l, v]) => <div key={l} className="kpi"><b>{v}</b><span>{l}</span></div>)}
          </div>
        </section>
      )}
    </div>
  )
}
