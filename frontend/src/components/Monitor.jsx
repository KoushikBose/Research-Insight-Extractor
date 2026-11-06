import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { LoadingButton } from './Spinner.jsx'

export default function Monitor({ onOpen, onSeen }) {
  const [searches, setSearches] = useState([])
  const [alerts, setAlerts] = useState([])
  const [f, setF] = useState({ name: '', source: 'pubmed', query: '', interval_hours: 24, auto_ingest: true, max_new: 10 })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(() => { api.searches().then(setSearches); api.alerts().then(setAlerts) }, [])
  useEffect(() => { load(); api.alertsSeen().then(() => onSeen?.()); const t = setInterval(load, 5000); return () => clearInterval(t) }, [load, onSeen])

  const add = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await api.addSearch({ ...f, name: f.name || f.query.slice(0, 40) }); setF({ ...f, name: '', query: '' }); load() } catch (x) { setErr(x.message) }
    setBusy(false)
  }

  return (
    <div className="grid2">
      <section className="card stack">
        <h2>Literature monitor</h2>
        <small>Saved searches run on a schedule, ingest new papers automatically and raise an alert for each.</small>
        {err && <div className="alert bad">{err}</div>}
        <form className="stack" onSubmit={add}>
          <input placeholder="Search query, e.g. JAK1 inhibitor rheumatoid arthritis" value={f.query} onChange={(e) => setF({ ...f, query: e.target.value })} required />
          <div className="row wrap">
            <label>Source<select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
              <option value="pubmed">PubMed</option><option value="biorxiv">bioRxiv</option><option value="medrxiv">medRxiv</option></select></label>
            <label>Every (hours)<input type="number" min="0.1" step="any" value={f.interval_hours} onChange={(e) => setF({ ...f, interval_hours: Number(e.target.value) })} style={{ width: 90 }} /></label>
            <label>Max new / run<input type="number" min="1" max="50" value={f.max_new} onChange={(e) => setF({ ...f, max_new: Number(e.target.value) })} style={{ width: 90 }} /></label>
            <label className="check"><input type="checkbox" checked={f.auto_ingest} onChange={(e) => setF({ ...f, auto_ingest: e.target.checked })} />Auto-ingest</label>
          </div>
          <LoadingButton loading={busy} label="Create & run now" busyLabel="Creating…" />
        </form>
        <table>
          <thead><tr><th>Search</th><th>Source</th><th>Every</th><th>Last run</th><th /></tr></thead>
          <tbody>
            {searches.map((s) => (
              <tr key={s.id}><td><b>{s.name}</b><br /><small>{s.query}</small></td><td>{s.source}</td><td>{s.interval_hours}h</td>
                <td>{s.last_run ? new Date(s.last_run * 1000).toLocaleString() : 'pending'}</td>
                <td><button className="ghost small" onClick={() => api.runSearch(s.id).then(load)}>Run</button>{' '}
                  <button className="ghost small" onClick={() => api.delSearch(s.id).then(load)}>✕</button></td></tr>))}
            {!searches.length && <tr><td colSpan="5" className="muted">No saved searches yet.</td></tr>}
          </tbody>
        </table>
      </section>
      <section className="card">
        <h2>New-paper alerts</h2>
        <div className="scroll" style={{ maxHeight: 520 }}>
          {alerts.map((a) => (
            <div key={a.id} className="hit">
              <div>{a.paper_id ? <a onClick={() => onOpen(a.paper_id)}>{a.title}</a> : <b>{a.title}</b>}<br />
                <small>{a.search_name} · {new Date(a.ts * 1000).toLocaleString()} · {a.ingested ? 'ingested' : 'not ingested'}</small></div>
              {!a.seen && <span className="pill ok">new</span>}
            </div>))}
          {!alerts.length && <p className="muted">Alerts appear here when a monitored search finds papers that are not yet in your knowledge base.</p>}
        </div>
      </section>
    </div>
  )
}
