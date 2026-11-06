import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Activity, LoadingButton } from './Spinner.jsx'

const LABELS = {
  objective: 'Objective', study_design: 'Study design', population_or_model: 'Population / model',
  sample_size: 'Sample size', interventions: 'Interventions', dosage: 'Dosage',
  assays_methods: 'Assays & methods', primary_endpoint: 'Primary endpoint', key_results: 'Key results',
  statistics: 'Statistics', limitations: 'Limitations', conclusion: 'Conclusion',
}

function Highlight({ text, terms, extra }) {
  const all = useMemo(() => [...new Set([...(terms || []), ...(extra ? [extra] : [])])]
    .filter((t) => t && t.length > 1).sort((a, b) => b.length - a.length), [terms, extra])
  if (!all.length) return <>{text}</>
  const rx = new RegExp('(' + all.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi')
  return <>{text.split(rx).map((part, i) =>
    i % 2 ? <mark key={i} className={extra && part.toLowerCase() === extra.toLowerCase() ? 'search' : ''}>{part}</mark> : part)}</>
}

export default function PaperView({ id, onBack, onFilter }) {
  const [p, setP] = useState(null)
  const [tab, setTab] = useState('Insights')
  const [q, setQ] = useState('')
  const [audit, setAudit] = useState([])
  const [voted, setVoted] = useState(false)

  useEffect(() => { api.paper(id).then(setP) }, [id])
  // poll while extraction is running (restarts whenever status changes, e.g. after Re-extract)
  const running = p?.status === 'ingested' || p?.status === 'extracting'
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => api.paper(id).then(setP), 2000)
    return () => clearInterval(t)
  }, [running, id])

  if (!p) return <p>Loading…</p>
  const ins = p.insights
  const vote = (r) => { api.feedback(id, 'extraction', r); setVoted(true) }
  const download = () => {
    const blob = new Blob([JSON.stringify({ title: p.title, insights: ins }, null, 2)], { type: 'application/json' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `paper-${id}-insights.json`; a.click()
  }

  return (
    <div className="stack">
      <button className="ghost small" onClick={onBack}>← Library</button>
      <section className="card">
        <h2>{p.title}</h2>
        <small>{p.authors.join(', ')} · {p.pub_date} · {p.source} {p.doi && `· doi:${p.doi}`} {p.confidential && '· 🔒 confidential'}</small>
        {p.file && <div><a href={`/api/papers/${id}/file`} target="_blank" rel="noreferrer">
          📎 {p.file.filename} ({(p.file.size / 1024).toFixed(0)} KB, stored in SQLite)</a></div>}
        <div>{p.flags.map((f) => <span key={f} className="pill warn">⚠ {f}</span>)}</div>
        <div className="tabs">
          {['Insights', 'Sections', 'Audit'].map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => { setTab(t); if (t === 'Audit') api.audit(id).then(setAudit) }}>{t}</button>
          ))}
        </div>
      </section>

      {(p.status === 'ingested' || p.status === 'extracting') && tab !== 'Audit' &&
        <Activity text="AI is analysing this paper (summaries, experimental details, keywords)…" />}
      {p.status === 'error' && <div className="alert bad">Extraction failed: {p.error}</div>}

      {tab === 'Insights' && ins && (
        <>
          <section className="card">
            <div className="row between">
              <h3>Summary</h3>
              <span>
                <span className="pill ok">{ins.mode}{ins.model ? ` · ${ins.model_label || ins.model}` : ''}</span>
                {ins.fallback_used && <span className="pill warn" title="The primary model failed for this paper; the fallback produced the result">⚠ via fallback</span>}
                <span className={'pill ' + (ins.guardrail.grounding_rate >= 0.95 ? 'ok' : 'warn')}>
                  grounding {(ins.guardrail.grounding_rate * 100).toFixed(0)}%</span>
                <span className="pill">{(ins.latency_ms / 1000).toFixed(1)}s</span>
              </span>
            </div>
            <p><Highlight text={ins.summary} terms={ins.keywords} /></p>
            <div>{ins.keywords.map((k) => <span key={k} className="chip">{k}</span>)}</div>
            {ins.entities && Object.entries(ins.entities).filter(([, v]) => v.length).map(([t, v]) => (
              <div key={t} style={{ marginTop: 6 }}><small><b>{t.replace('_', ' / ')}:</b></small>{' '}
                {v.slice(0, 8).map((e) => <a key={e.text} className="chip" title={`${e.count}× — click to find similar papers`} onClick={() => onFilter?.(e.text)}>{e.text}</a>)}</div>))}
          </section>
          <section className="card">
            <h3>Experimental details <small>(every value is checked against its verbatim evidence)</small></h3>
            <table>
              <thead><tr><th>Field</th><th>Extracted</th><th>Evidence</th><th /></tr></thead>
              <tbody>
                {Object.entries(LABELS).map(([k, label]) => {
                  const d = ins.details[k]
                  return (
                    <tr key={k}>
                      <td><b>{label}</b></td>
                      <td>{d?.value ? <Highlight text={d.value} terms={ins.keywords} /> : <span className="muted">not found</span>}</td>
                      <td className="ev">{d?.evidence && <q>{d.evidence}</q>}</td>
                      <td>{d?.status === 'verified' && <span className="pill ok">✓ verified</span>}
                        {d?.status === 'unverified' && <span className="pill bad">⚠ unverified</span>}</td>
                    </tr>)
                })}
              </tbody>
            </table>
            <div className="row">
              <LoadingButton className="ghost" loading={p.status === 'extracting'} label="Re-extract" busyLabel="Extracting…"
                onClick={() => { setP({ ...p, status: 'extracting' }); api.reExtract(id) }} />
              <button className="ghost" onClick={download}>Export JSON</button>
              {!voted ? <>
                <button className="ghost" onClick={() => vote(1)}>👍 Useful</button>
                <button className="ghost" onClick={() => vote(-1)}>👎 Wrong</button></> : <small>Thanks for the feedback</small>}
            </div>
            {ins.guardrail.flags.length > 0 && <small>Guardrail flags: {ins.guardrail.flags.join(', ')}</small>}
          </section>
          {p.tables?.length > 0 && (
            <section className="card">
              <h3>Tables extracted from the PDF ({p.tables.length})</h3>
              {p.tables.map((t, i) => (
                <div key={i} style={{ overflowX: 'auto', marginBottom: 14 }}>
                  <small><b>{t.caption}</b> · page {t.page}</small>
                  <table><thead><tr>{t.rows[0].map((c, j) => <th key={j}>{c}</th>)}</tr></thead>
                    <tbody>{t.rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>
                </div>))}
            </section>)}
          {p.figures?.length > 0 && (
            <section className="card">
              <h3>Figure captions ({p.figures.length}) <small>— figure text is searchable in the assistant</small></h3>
              {p.figures.map((f, i) => <p key={i} style={{ margin: '4px 0' }}><b>{f.label}</b> <small>p.{f.page}</small> {f.caption}</p>)}
            </section>)}
        </>
      )}

      {tab === 'Sections' && (
        <section className="card">
          <input placeholder="Highlight a term in the text…" value={q} onChange={(e) => setQ(e.target.value)} />
          {p.sections.map((s) => (
            <div key={s.name} className="section">
              <h3>{s.name}</h3>
              {ins?.section_summaries?.[s.name] && <p className="summary">💡 <Highlight text={ins.section_summaries[s.name]} terms={ins.keywords} /></p>}
              <p className="fulltext"><Highlight text={s.text} terms={ins?.keywords} extra={q} /></p>
            </div>
          ))}
        </section>
      )}

      {tab === 'Audit' && (
        <section className="card"><h3>Traceability log</h3>
          <table><tbody>{audit.map((a, i) => (
            <tr key={i}><td>{new Date(a.ts * 1000).toLocaleString()}</td><td>{a.action}</td><td className="muted">{a.detail}</td></tr>))}</tbody></table>
        </section>
      )}
    </div>
  )
}
