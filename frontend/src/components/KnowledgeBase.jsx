import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { toast } from '../toast.js'
import { Spinner } from './Spinner.jsx'

const SOURCES = {
  upload: ['📄', 'Upload', 'indigo'], pubmed: ['🧬', 'PubMed', 'teal'], biorxiv: ['🧪', 'bioRxiv', 'amber'], medrxiv: ['🧪', 'medRxiv', 'amber'],
  internal_repo: ['🏢', 'Internal repo', 'rose'], internal_db: ['🗄️', 'Internal DB', 'rose'],
}
const src = (s) => SOURCES[s] || ['📁', s, 'grey']
const isBusy = (p) => p.status === 'ingested' || p.status === 'extracting'
const PAGE = 12
const SORTS = {
  newest: ['Newest added', (a, b) => b.created_at - a.created_at], oldest: ['Oldest added', (a, b) => a.created_at - b.created_at],
  pub: ['Publication date', (a, b) => (b.pub_date || '').localeCompare(a.pub_date || '')], title: ['Title A–Z', (a, b) => a.title.localeCompare(b.title)],
  quality: ['Verification score', (a, b) => (b.grounding ?? -1) - (a.grounding ?? -1)],
}

function Hl({ text, q }) {
  const t = (q || '').trim()
  if (!t || t.length < 2) return <>{text}</>
  const parts = text.split(new RegExp('(' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig'))
  return <>{parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p))}</>
}

function StatusBadge({ p }) {
  if (p.status === 'error') return <span className="pill bad">⚠ failed</span>
  if (isBusy(p)) return <span className="pill warn"><Spinner size={10} /> {p.status === 'extracting' ? 'AI extracting…' : 'queued'}</span>
  return <span className="pill ok">✓ ready</span>
}

function Preview({ id, onOpen }) {
  const [d, setD] = useState(null)
  useEffect(() => { api.paper(id).then(setD).catch(() => setD(false)) }, [id])
  if (d === null) return <div className="kb-preview"><Spinner /> Loading preview…</div>
  if (d === false || !d.insights) return <div className="kb-preview muted">No analysis yet — it appears here once extraction finishes.</div>
  const det = d.insights.details || {}
  const rows = [['Design', 'study_design'], ['Sample size', 'sample_size'], ['Dosage', 'dosage'], ['Key result', 'key_results'], ['Statistics', 'statistics'], ['Conclusion', 'conclusion']]
  const ents = Object.values(d.insights.entities || {}).flat().slice(0, 8)
  const filled = rows.filter(([, k]) => det[k]?.value)
  return (
    <div className="kb-preview">
      {filled.length === 0 && <p className="muted" style={{ margin: '0 0 6px' }}>No structured experimental details were found in this paper's text{d.sections?.length === 1 && d.sections[0].name === 'Abstract' ? ' (abstract only)' : ''}.</p>}
      {filled.length > 0 && <table><tbody>
        {filled.map(([label, k]) => (
          <tr key={k}><td className="muted" style={{ width: 90 }}>{label}</td>
            <td>{det[k].value.length > 150 ? det[k].value.slice(0, 150) + '…' : det[k].value} {det[k].status === 'verified' && <span className="pill ok" title="Evidence quote verified in the source">✓</span>}</td></tr>))}
      </tbody></table>}
      {ents.length > 0 && <div style={{ marginTop: 6 }}>{ents.map((e) => <span key={e.text} className="chip">{e.text}</span>)}</div>}
      <button className="small" style={{ marginTop: 8 }} onClick={() => onOpen(id)}>Open full analysis →</button>
    </div>
  )
}

export default function KnowledgeBase({ onOpen, initialFilter = '', refreshKey = 0 }) {
  const [papers, setPapers] = useState(null)
  const [q, setQ] = useState(initialFilter)
  const [qDebounced, setQd] = useState(initialFilter)
  const [status, setStatus] = useState('all')
  const [source, setSource] = useState('all')
  const [sort, setSort] = useState('newest')
  const [view, setView] = useState(() => { try { return localStorage.getItem('kbView') || 'cards' } catch { return 'cards' } })
  const [sel, setSel] = useState({})
  const [open, setOpen] = useState(null)           // paper id with an expanded preview
  const [confirm, setConfirm] = useState(null)     // paper id awaiting delete confirmation
  const [limit, setLimit] = useState(PAGE)
  const [bulkConfirm, setBulkConfirm] = useState(false)
  const searchRef = useRef()

  useEffect(() => { setQ(initialFilter); setQd(initialFilter) }, [initialFilter])
  useEffect(() => { const t = setTimeout(() => setQd(q), 250); return () => clearTimeout(t) }, [q])
  useEffect(() => { try { localStorage.setItem('kbView', view) } catch { /* ignore */ } }, [view])
  useEffect(() => {                                   // "/" focuses the search box, like most search UIs
    const h = (e) => { if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) { e.preventDefault(); searchRef.current?.focus() } }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [])

  const load = useCallback(() => api.papers(qDebounced).then(setPapers).catch((e) => { setPapers([]); toast.error(e.message, { title: 'Could not load papers' }) }), [qDebounced])
  useEffect(() => { load() }, [load, refreshKey])
  useEffect(() => {
    if (!papers?.some(isBusy)) return
    const t = setInterval(load, 2500); return () => clearInterval(t)
  }, [papers, load])
  useEffect(() => setLimit(PAGE), [qDebounced, status, source, sort])

  const counts = useMemo(() => {
    const all = papers || []
    return { total: all.length, ready: all.filter((p) => p.status === 'ready').length, busy: all.filter(isBusy).length, error: all.filter((p) => p.status === 'error').length,
      conf: all.filter((p) => p.confidential).length, stored: all.filter((p) => p.has_file).length,
      sources: Object.entries(all.reduce((m, p) => ({ ...m, [p.source]: (m[p.source] || 0) + 1 }), {})) }
  }, [papers])

  const shown = useMemo(() => (papers || [])
    .filter((p) => (status === 'all' ? true : status === 'ready' ? p.status === 'ready' : status === 'busy' ? isBusy(p) : status === 'error' ? p.status === 'error'
      : status === 'conf' ? p.confidential : true))
    .filter((p) => source === 'all' || p.source === source)
    .sort(SORTS[sort][1]), [papers, status, source, sort])
  const page = shown.slice(0, limit)
  const selected = Object.keys(sel).filter((k) => sel[k]).map(Number)
  const filtersOn = q || status !== 'all' || source !== 'all'
  const clear = () => { setQ(''); setStatus('all'); setSource('all') }

  const del = async (ids) => {
    try { await Promise.all(ids.map((id) => api.remove(id))); toast.success(`${ids.length} paper(s) deleted`); setSel({}); setConfirm(null); load() }
    catch (e) { toast.error(e.message, { title: 'Delete failed' }) }
  }
  const reExtract = async (ids) => {
    try { await Promise.all(ids.map((id) => api.reExtract(id))); toast.success(`AI extraction queued for ${ids.length} paper(s)`); setSel({}); load() }
    catch (e) { toast.error(e.message, { title: 'Could not queue extraction' }) }
  }
  const authors = (a) => (a?.length ? a.slice(0, 2).join(', ') + (a.length > 2 ? ' et al.' : '') : '')

  const renderCard = (p) => {
    const [icon, label, color] = src(p.source)
    return (
      <article key={p.id} className={'kb-card ' + (sel[p.id] ? 'selected ' : '') + (p.status === 'error' ? 'err' : isBusy(p) ? 'busy' : '')}>
        <div className="kb-top">
          <label className="kb-check" title="Select"><input type="checkbox" checked={!!sel[p.id]} onChange={(e) => setSel({ ...sel, [p.id]: e.target.checked })} /></label>
          <span className={'src ' + color}>{icon} {label}</span>
          <StatusBadge p={p} />
          <span style={{ flex: 1 }} />
          {!!p.confidential && <span className="pill bad" title="Confidential: processed locally, never sent to the external LLM">🔒</span>}
          {!!p.has_file && <span className="pill" title={`Original file stored in SQLite${p.file_size ? ` (${(p.file_size / 1024).toFixed(0)} KB)` : ''}`}>💾</span>}
        </div>
        <h3 className="kb-title" onClick={() => onOpen(p.id)} title={p.title}><Hl text={p.title} q={q} /></h3>
        <div className="kb-meta">{[authors(p.authors), p.pub_date, p.doi && `doi:${p.doi}`].filter(Boolean).join('  ·  ') || 'No bibliographic metadata'}</div>
        <p className="kb-sum">
          {p.summary ? <>{p.summary}{p.summary.length >= 259 ? '…' : ''}</> : isBusy(p) ? <span className="muted"><Spinner size={11} /> AI summary will appear here shortly…</span>
            : <span className="muted">No AI summary yet.</span>}
        </p>
        <div className="kb-chips">
          {(p.keywords || []).slice(0, 4).map((k) => <button key={k} className="chip kb-chip" title="Filter by this term" onClick={() => setQ(k)}>{k}</button>)}
          {(p.keywords || []).length > 4 && <span className="muted"> +{p.keywords.length - 4}</span>}
        </div>
        {(p.grounding != null || (p.flags || []).length > 0) && (
          <div className="kb-quality">
            {p.grounding != null && <span title="Share of extracted fields whose evidence quote was verified in the source">✓ {(p.grounding * 100).toFixed(0)}% verified</span>}
            {p.model_label && <span className={'pill ' + (p.fallback_used ? 'warn' : '')} title={p.fallback_used ? 'Served by the fallback model' : 'Model used'}>{p.fallback_used ? '⚠ ' : ''}{p.model_label}</span>}
            {!p.model_label && p.mode === 'extractive' && <span className="pill">offline engine</span>}
            {(p.flags || []).slice(0, 2).map((f) => <span key={f} className="pill warn" title={f}>⚠ {f.split(':')[0].replace(/_/g, ' ')}</span>)}
          </div>)}
        {open === p.id && <Preview id={p.id} onOpen={onOpen} />}
        <div className="kb-foot">
          <button className="small" onClick={() => onOpen(p.id)}>Open</button>
          <button className="ghost small" onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? 'Hide ▴' : 'Preview ▾'}</button>
          <span style={{ flex: 1 }} />
          {confirm === p.id
            ? <><button className="small danger" onClick={() => del([p.id])}>Delete?</button><button className="ghost small" onClick={() => setConfirm(null)}>Cancel</button></>
            : <button className="ghost small" title="Delete paper" onClick={() => setConfirm(p.id)}>Delete</button>}
        </div>
      </article>
    )
  }

  const stat = (label, n, key, color) => (
    <button className={'kb-stat ' + (status === key ? 'on' : '')} onClick={() => setStatus(status === key ? 'all' : key)} style={{ '--c': color }}>
      <b>{n}</b><span>{label}</span></button>)

  return (
    <section className="card kb">
      <div className="row between wrap">
        <h2 style={{ margin: 0 }}>Knowledge base <small>— {counts.total} paper{counts.total === 1 ? '' : 's'}</small></h2>
        <div className="seg" role="group" aria-label="View">
          <button className={view === 'cards' ? 'on' : ''} onClick={() => setView('cards')} title="Card view">▦ Cards</button>
          <button className={view === 'table' ? 'on' : ''} onClick={() => setView('table')} title="Compact table">☰ Table</button>
        </div>
      </div>

      <div className="kb-stats">
        {stat('All', counts.total, 'all', '#4f46e5')}{stat('Ready', counts.ready, 'ready', '#15803d')}{stat('Processing', counts.busy, 'busy', '#b45309')}
        {stat('Failed', counts.error, 'error', '#b91c1c')}{stat('Confidential', counts.conf, 'conf', '#be185d')}
        <span className="kb-stat static"><b>{counts.stored}</b><span>file stored</span></span>
      </div>

      <div className="kb-toolbar">
        <div className="kb-search">
          <span>🔍</span>
          <input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, keyword or entity (gene, drug…)   —  press /" />
          {q && <button className="icon-btn" onClick={() => setQ('')} aria-label="Clear search">✕</button>}
        </div>
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source">
          <option value="all">All sources</option>
          {counts.sources.map(([s, n]) => <option key={s} value={s}>{src(s)[1]} ({n})</option>)}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
          {Object.entries(SORTS).map(([k, [label]]) => <option key={k} value={k}>Sort: {label}</option>)}
        </select>
      </div>

      {filtersOn && (
        <div className="kb-active">
          <span className="muted">Showing {shown.length} of {counts.total}</span>
          {q && <span className="chip">“{q}” <a onClick={() => setQ('')}>✕</a></span>}
          {status !== 'all' && <span className="chip">status: {status} <a onClick={() => setStatus('all')}>✕</a></span>}
          {source !== 'all' && <span className="chip">source: {src(source)[1]} <a onClick={() => setSource('all')}>✕</a></span>}
          <a onClick={clear}>Clear all</a>
        </div>)}

      {selected.length > 0 && (
        <div className="kb-bulk">
          <b>{selected.length} selected</b>
          <button className="ghost small" onClick={() => setSel(Object.fromEntries(shown.map((p) => [p.id, true])))}>Select all {shown.length}</button>
          <button className="ghost small" onClick={() => reExtract(selected)}>↻ Re-extract</button>
          {bulkConfirm
            ? <><button className="small danger" onClick={() => { setBulkConfirm(false); del(selected) }}>Yes, delete {selected.length}</button>
              <button className="ghost small" onClick={() => setBulkConfirm(false)}>Cancel</button></>
            : <button className="small danger" onClick={() => setBulkConfirm(true)}>Delete</button>}
          <button className="ghost small" onClick={() => { setSel({}); setBulkConfirm(false) }}>Clear</button>
        </div>)}

      {papers === null && <p><Spinner /> Loading knowledge base…</p>}
      {papers && !shown.length && (
        <div className="kb-empty">
          <div style={{ fontSize: 34 }}>{filtersOn ? '🔎' : '📚'}</div>
          <b>{filtersOn ? 'No papers match these filters' : 'Your knowledge base is empty'}</b>
          <span className="muted">{filtersOn ? 'Try a different term or clear the filters.' : 'Upload a PDF or XML, add a paper from PubMed, or ingest the internal repository above.'}</span>
          {filtersOn && <button className="ghost" onClick={clear}>Clear filters</button>}
        </div>)}

      {view === 'cards' && <div className="kb-grid">{page.map(renderCard)}</div>}

      {view === 'table' && shown.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="kb-table">
            <thead><tr><th style={{ width: 28 }}><input type="checkbox" checked={page.length > 0 && page.every((p) => sel[p.id])}
              onChange={(e) => setSel(e.target.checked ? Object.fromEntries(page.map((p) => [p.id, true])) : {})} /></th>
              <th>Title</th><th>Date</th><th>Source</th><th>Verified</th><th>Status</th><th /></tr></thead>
            <tbody>
              {page.map((p) => (
                <React.Fragment key={p.id}>
                  <tr className={sel[p.id] ? 'selected' : ''}>
                    <td><input type="checkbox" checked={!!sel[p.id]} onChange={(e) => setSel({ ...sel, [p.id]: e.target.checked })} /></td>
                    <td style={{ maxWidth: 420 }}><a onClick={() => onOpen(p.id)}><Hl text={p.title} q={q} /></a> {!!p.confidential && '🔒'} {!!p.has_file && '💾'}
                      <div className="kb-chips">{(p.keywords || []).slice(0, 3).map((k) => <button key={k} className="chip kb-chip" onClick={() => setQ(k)}>{k}</button>)}</div></td>
                    <td>{p.pub_date}</td><td><span className={'src ' + src(p.source)[2]}>{src(p.source)[0]} {src(p.source)[1]}</span></td>
                    <td>{p.grounding != null ? `${(p.grounding * 100).toFixed(0)}%` : '—'}</td><td><StatusBadge p={p} /></td>
                    <td style={{ whiteSpace: 'nowrap' }}><button className="ghost small" onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? '▴' : '▾'}</button>{' '}
                      {confirm === p.id ? <><button className="small danger" onClick={() => del([p.id])}>Delete?</button> <button className="ghost small" onClick={() => setConfirm(null)}>✕</button></>
                        : <button className="ghost small" onClick={() => setConfirm(p.id)}>Delete</button>}</td>
                  </tr>
                  {open === p.id && <tr><td /><td colSpan="6"><Preview id={p.id} onOpen={onOpen} /></td></tr>}
                </React.Fragment>))}
            </tbody>
          </table>
        </div>)}

      {shown.length > limit && (
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <button className="ghost" onClick={() => setLimit(limit + PAGE)}>Show {Math.min(PAGE, shown.length - limit)} more ({shown.length - limit} remaining)</button>
        </div>)}
    </section>
  )
}
