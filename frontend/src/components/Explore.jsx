import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Spinner } from './Spinner.jsx'

function Bars({ data, color = 'var(--pri)', onClick }) {
  const max = Math.max(1, ...data.map((d) => d[1]))
  return (
    <div>
      {data.map(([label, v]) => (
        <div key={label} className="bar" style={{ gridTemplateColumns: '150px 1fr 36px', cursor: onClick ? 'pointer' : 'default' }} onClick={() => onClick?.(label)}>
          <span title={label} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
          <div><i style={{ width: `${(v / max) * 100}%`, background: color }} /></div><b>{v}</b>
        </div>
      ))}
      {!data.length && <small>No data yet</small>}
    </div>
  )
}

function Network({ net, onPick }) {
  const W = 560, H = 360, cx = W / 2, cy = H / 2, R = 140
  const pos = useMemo(() => Object.fromEntries(net.nodes.map((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(net.nodes.length, 1) - Math.PI / 2
    return [n.id, [cx + R * Math.cos(a), cy + R * Math.sin(a)]]
  })), [net])
  const maxW = Math.max(1, ...net.edges.map((e) => e.w))
  const maxC = Math.max(1, ...net.nodes.map((n) => n.count))
  if (!net.nodes.length) return <small>Analyse a few papers to see the term network.</small>
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxHeight: 380 }}>
      {net.edges.map((e, i) => (
        <line key={i} x1={pos[e.a][0]} y1={pos[e.a][1]} x2={pos[e.b][0]} y2={pos[e.b][1]}
          stroke="#6366f1" strokeOpacity={0.15 + 0.6 * (e.w / maxW)} strokeWidth={1 + 3 * (e.w / maxW)} />))}
      {net.nodes.map((n) => {
        const [x, y] = pos[n.id]
        const right = x >= cx
        return (
          <g key={n.id} style={{ cursor: 'pointer' }} onClick={() => onPick(n.id)}>
            <circle cx={x} cy={y} r={5 + 9 * (n.count / maxC)} fill="#4f46e5" fillOpacity="0.85"><title>{n.id} ({n.count} papers)</title></circle>
            <text x={x + (right ? 1 : -1) * (12 + 8 * (n.count / maxC))} y={y + 4} textAnchor={right ? 'start' : 'end'} fontSize="11" fill="currentColor">{n.id}</text>
          </g>)
      })}
    </svg>
  )
}

const csvEscape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`

export default function Explore({ onOpen, goLibrary }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [etype, setEtype] = useState('gene_protein')
  const [sel, setSel] = useState({})
  const [onlySel, setOnlySel] = useState(false)
  const [sort, setSort] = useState({ key: null, dir: 'asc' })

  const load = () => api.explore().then(setD).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  if (err) return <div className="alert bad">{err}</div>
  if (!d) return <p><Spinner /> Loading analytics…</p>

  const selCount = Object.values(sel).filter(Boolean).length
  const anySel = selCount > 0
  const rows = d.compare.filter((r) => !anySel || sel[r.id])
  const sortBy = (k) => setSort((s) => ({ key: k, dir: s.key === k && s.dir === 'asc' ? 'desc' : 'asc' }))
  const arrow = (k) => (sort.key === k ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '')
  const cell = (v) => (v === null || v === undefined || v === '' ? <small>—</small> : v)
  const tableRows = [...(onlySel && anySel ? rows : d.compare)].sort((a, b) => {
    if (!sort.key) return 0
    const x = a[sort.key], y = b[sort.key]
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''))
    return sort.dir === 'asc' ? c : -c
  })
  const exportCsv = () => {
    const cols = ['id', 'title', 'year', 'source', 'design', 'population', 'sample_size', 'dosage', 'key_results', 'statistics', 'conclusion']
    const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => csvEscape(r[c])).join(','))].join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'paper-comparison.csv'; a.click()
  }
  const ETYPES = Object.keys(d.entities)

  return (
    <div className="stack">
      <div className="kpis">
        {[['Papers', d.totals.papers], ['Analysed', d.totals.analysed], ['Sources', d.sources.length],
          ['Top term', d.top_keywords[0]?.[0] || '—']].map(([l, v]) => <div key={l} className="kpi"><b style={{ fontSize: 20 }}>{v}</b><span>{l}</span></div>)}
      </div>
      <div className="grid2">
        <section className="card"><h3>Papers per year</h3><Bars data={d.papers_per_year} /></section>
        <section className="card"><h3>Papers by source</h3><Bars data={d.sources} color="#0d9488" /></section>
        <section className="card"><h3>Top keywords</h3><Bars data={d.top_keywords} color="#7c3aed" onClick={(k) => goLibrary(k)} />
          <small>Click a keyword to filter the Library</small></section>
        <section className="card">
          <div className="row between"><h3>Entities</h3>
            <select value={etype} onChange={(e) => setEtype(e.target.value)}>{ETYPES.map((t) => <option key={t} value={t}>{t.replace('_', ' / ')}</option>)}</select></div>
          <Bars data={d.entities[etype] || []} color="#db2777" onClick={(k) => goLibrary(k)} />
        </section>
      </div>
      <section className="card">
        <h3>Concept network <small>(terms that appear together in the same paper)</small></h3>
        <Network net={d.network} onPick={goLibrary} />
      </section>
      <section className="card">
        <div className="row between wrap">
          <div>
            <h3>Cross-paper comparison</h3>
            <small>Tick papers to compare side by side, or leave empty to include all. {anySel ? `${selCount} selected.` : `${d.compare.length} papers shown.`}</small>
          </div>
          <div className="row wrap">
            <label className="check"><input type="checkbox" checked={onlySel} disabled={!anySel} onChange={(e) => setOnlySel(e.target.checked)} /> Selected only</label>
            <button className="ghost small" onClick={() => setSel(Object.fromEntries(d.compare.map((r) => [r.id, true])))}>Select all</button>
            <button className="ghost small" disabled={!anySel} onClick={() => { setSel({}); setOnlySel(false) }}>Clear</button>
            <button className="small" onClick={exportCsv}>Export CSV{anySel ? ` (${selCount})` : ''}</button>
          </div>
        </div>
        <div className="cmp-wrap">
          <table className="cmp">
            <thead>
              <tr>
                <th style={{ width: 28 }} />
                <th className="sortable" onClick={() => sortBy('title')}>Paper{arrow('title')}</th>
                <th className="sortable" onClick={() => sortBy('design')}>Design &amp; population{arrow('design')}</th>
                <th className="sortable num" onClick={() => sortBy('sample_size')}>n{arrow('sample_size')}</th>
                <th>Dose</th>
                <th>Key result</th>
                <th>Statistics</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((r) => (
                <tr key={r.id} className={sel[r.id] ? 'picked' : anySel ? 'dim' : ''}>
                  <td><input type="checkbox" checked={!!sel[r.id]} onChange={(e) => setSel({ ...sel, [r.id]: e.target.checked })} /></td>
                  <td style={{ minWidth: 200 }}><a onClick={() => onOpen(r.id)}>{r.title}</a><br /><small>{[r.year, r.source].filter(Boolean).join(' · ')}</small></td>
                  <td style={{ minWidth: 180 }}>{cell(r.design)}{r.population ? <><br /><small>{r.population}</small></> : null}</td>
                  <td className="num"><b>{r.n ?? '—'}</b></td>
                  <td>{cell(r.dosage)}</td>
                  <td style={{ minWidth: 220 }}>{cell(r.key_results)}</td>
                  <td style={{ minWidth: 140 }}>{cell(r.statistics)}</td>
                </tr>))}
              {!tableRows.length && <tr><td colSpan={7}><small>No papers to compare yet.</small></td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
