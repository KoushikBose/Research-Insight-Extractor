import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { LoadingButton, Spinner } from './Spinner.jsx'

/** Job queue status + bulk / external-source connectors. */
export default function Sources({ onChange }) {
  const [jobs, setJobs] = useState({ counts: {}, jobs: [] })
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState('')
  const [bp, setBp] = useState({ query: '', n: 10 })
  const [br, setBr] = useState({ query: '', days: 7, server: 'biorxiv', n: 10 })
  const [sq, setSq] = useState({ path: '', table: '', title_col: '', text_col: '', doi_col: '', date_col: '', authors_col: '', limit: 200, confidential: true })

  const load = useCallback(() => api.jobs().then(setJobs).catch(() => {}), [])
  const active = (jobs.counts.queued || 0) + (jobs.counts.running || 0)
  useEffect(() => { load(); const t = setInterval(load, active ? 1500 : 5000); return () => clearInterval(t) }, [load, active])
  useEffect(() => { if (!active) onChange?.() }, [active])           // refresh library when the queue drains

  const go = async (name, fn, ok) => {
    setBusy(name); setMsg(null)
    try { await fn(); setMsg({ ok }); load() } catch (e) { setMsg({ bad: e.message }) }
    setBusy('')
  }
  const row = (f, k) => <input placeholder={k} value={f[k]} onChange={(e) => (f === sq ? setSq({ ...sq, [k]: e.target.value }) : null)} />

  return (
    <section className="card stack">
      <div className="row between">
        <h2>Sources &amp; job queue {active > 0 && <span className="pill warn"><Spinner size={10} /> {active} active</span>}</h2>
        <button className="ghost small" onClick={() => setOpen(!open)}>{open ? 'Hide connectors' : 'Show connectors'}</button>
      </div>
      <div className="row wrap">
        {['queued', 'running', 'done', 'error'].map((s) => <span key={s} className={'pill ' + (s === 'error' ? 'bad' : s === 'done' ? 'ok' : 'warn')}>{s}: {jobs.counts[s] || 0}</span>)}
      </div>
      {msg && <div className={'alert ' + (msg.ok ? 'ok' : 'bad')}>{msg.ok || msg.bad}</div>}

      {open && (
        <div className="grid3">
          <div className="stack">
            <b>PubMed bulk</b>
            <input placeholder="query" value={bp.query} onChange={(e) => setBp({ ...bp, query: e.target.value })} />
            <input type="number" min="1" max="100" value={bp.n} onChange={(e) => setBp({ ...bp, n: Number(e.target.value) })} />
            <LoadingButton loading={busy === 'pm'} disabled={!bp.query} label="Queue ingest" busyLabel="Queuing…"
              onClick={() => go('pm', () => api.bulkPubmed(bp.query, bp.n), 'PubMed bulk ingest queued')} />
          </div>
          <div className="stack">
            <b>bioRxiv / medRxiv (recent)</b>
            <input placeholder="keyword filter (optional)" value={br.query} onChange={(e) => setBr({ ...br, query: e.target.value })} />
            <div className="row"><select value={br.server} onChange={(e) => setBr({ ...br, server: e.target.value })}><option>biorxiv</option><option>medrxiv</option></select>
              <input type="number" min="1" max="60" value={br.days} title="days back" onChange={(e) => setBr({ ...br, days: Number(e.target.value) })} style={{ width: 70 }} />d
              <input type="number" min="1" max="100" value={br.n} title="max papers" onChange={(e) => setBr({ ...br, n: Number(e.target.value) })} style={{ width: 70 }} /></div>
            <LoadingButton loading={busy === 'br'} label="Queue import" busyLabel="Queuing…"
              onClick={() => go('br', () => api.biorxiv(br), 'Preprint import queued')} />
          </div>
          <div className="stack">
            <b>Internal SQLite database</b>
            {row(sq, 'path')}{row(sq, 'table')}{row(sq, 'title_col')}{row(sq, 'text_col')}{row(sq, 'doi_col')}
            <small>Opened read-only; imported papers are marked confidential.</small>
            <LoadingButton loading={busy === 'sq'} disabled={!sq.path || !sq.table || !sq.title_col || !sq.text_col} label="Queue import" busyLabel="Queuing…"
              onClick={() => go('sq', () => api.sqlImport(sq), 'Database import queued')} />
          </div>
        </div>
      )}

      <table>
        <thead><tr><th>#</th><th>Job</th><th>Status</th><th>Result</th></tr></thead>
        <tbody>
          {jobs.jobs.slice(0, 6).map((j) => (
            <tr key={j.id}><td>{j.id}</td><td>{j.kind}</td>
              <td><span className={'pill ' + (j.status === 'done' ? 'ok' : j.status === 'error' ? 'bad' : 'warn')}>{(j.status === 'running') && <Spinner size={9} />} {j.status}</span></td>
              <td className="muted">{j.error || (j.result ? JSON.stringify(j.result).slice(0, 90) : '')}</td></tr>))}
          {!jobs.jobs.length && <tr><td colSpan="4" className="muted">No jobs yet.</td></tr>}
        </tbody>
      </table>
    </section>
  )
}
