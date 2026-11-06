import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Activity, LoadingButton, Spinner } from './Spinner.jsx'
import Sources from './Sources.jsx'
import KnowledgeBase from './KnowledgeBase.jsx'
import { toast } from '../toast.js'

const ALLOWED_EXT = ['pdf', 'xml', 'txt', 'md']
const MAX_MB = 15

async function sha256Hex(file) {
  try {
    const h = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, '0')).join('')
  } catch { return null }   // insecure context / very old browser: rely on the server-side check
}

export default function Library({ onOpen, initialFilter = '' }) {
  const [refreshKey, setRefreshKey] = useState(0)     // bump to make the knowledge base reload
  const [sq, setSq] = useState('')
  const [sres, setSres] = useState(null)
  const [searching, setSearching] = useState(false)
  const [confidential, setConf] = useState(false)
  const [license, setLicense] = useState('unknown')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [task, setTask] = useState('')       // what is currently running
  const [progress, setProgress] = useState(null)
  const [pq, setPq] = useState('')
  const [hits, setHits] = useState([])
  const fileRef = useRef()

  const load = useCallback(() => setRefreshKey((k) => k + 1), [])

  const wrap = async (fn, okMsg, label = 'Working…') => {
    setBusy(true); setMsg(null); setTask(label); setProgress(null)
    try {
      const r = await fn()
      const m = okMsg(r)
      if (Array.isArray(r) && r.some((x) => x?.error)) {   // folder ingest: per-file errors incl. duplicates
        const errs = r.filter((x) => x?.error)
        errs.slice(0, 4).forEach((x) => toast.error(`${x.file}: ${x.error}`, { title: 'Skipped' }))
        if (errs.length > 4) toast.error(`…and ${errs.length - 4} more skipped.`)
      }
      toast.success(m); load()
    } catch (e) { toast.error(e.message, { title: 'Request failed' }) }
    setBusy(false); setTask(''); setProgress(null)
  }
  const dupToast = (name, info) => toast.error(info.message || `"${name}" is already in the library.`, {
    title: 'Duplicate document — not uploaded',
    action: info.existing_id ? { label: 'Open existing paper', onClick: () => onOpen(info.existing_id) } : undefined,
    ttl: 12000,
  })

  const upload = async (e) => {
    e.preventDefault()
    const files = [...fileRef.current.files]
    if (!files.length) { toast.warn('Choose at least one file first.', { title: 'Nothing selected' }); return }
    setBusy(true); setMsg(null)
    const seen = new Set()
    let saved = 0, attached = 0, rejected = 0
    for (const [i, f] of files.entries()) {
      const ext = f.name.includes('.') ? f.name.split('.').pop().toLowerCase() : ''
      // 1) client-side validation
      if (!ALLOWED_EXT.includes(ext)) { toast.error(`"${f.name}": .${ext || '?'} files are not supported (use PDF, XML, TXT or MD).`, { title: 'Invalid file type' }); rejected++; continue }
      if (f.size === 0) { toast.error(`"${f.name}" is empty.`, { title: 'Invalid file' }); rejected++; continue }
      if (f.size > MAX_MB * 1048576) { toast.error(`"${f.name}" is ${(f.size / 1048576).toFixed(1)} MB; the limit is ${MAX_MB} MB.`, { title: 'File too large' }); rejected++; continue }
      // 2) duplicate checks in the browser: same file chosen twice, or already stored (SHA-256 sent, not the file)
      setTask(`Checking ${f.name} for duplicates…`); setProgress(null)
      const sha = await sha256Hex(f)
      if (sha) {
        if (seen.has(sha)) { toast.error(`"${f.name}" appears more than once in your selection — skipped.`, { title: 'Duplicate in selection' }); rejected++; continue }
        seen.add(sha)
        try {
          const h = await api.checkHash(sha)
          if (h.duplicate) { dupToast(f.name, h); rejected++; continue }
        } catch { /* server re-checks anyway */ }
      }
      // 3) upload (server enforces file, text, DOI and title duplicate rules too)
      setTask(`Uploading ${f.name} (${i + 1}/${files.length}, ${(f.size / 1048576).toFixed(1)} MB)…`); setProgress(0)
      try {
        const r = await api.upload(f, confidential, license, (p) => {
          setProgress(p)
          if (p >= 100) { setTask(`Saving to SQLite & parsing ${f.name} — large documents can take a moment…`); setProgress(null) }
        })
        r.file_attached ? attached++ : saved++
      } catch (err) {
        rejected++
        if (err.info?.code === 'duplicate') dupToast(f.name, err.info)
        else toast.error(`"${f.name}": ${err.message}`, { title: 'Upload failed' })
      }
    }
    if (saved) toast.success(`${saved} document(s) saved to SQLite — AI extraction is running in the background.`, { title: 'Upload complete' })
    if (attached) toast.info(`${attached} existing paper(s) had no stored original; the file was attached.`, { title: 'Original file saved' })
    if (!saved && !attached && !rejected) toast.info('No changes.')
    fileRef.current.value = ''
    setBusy(false); setTask(''); setProgress(null)
    load()
  }

  return (
    <div className="stack">
      {busy && <Activity text={task} progress={progress} />}
      {msg && <div className={'alert ' + (msg.ok ? 'ok' : 'bad')}>{msg.ok || msg.bad}</div>}
      <div className="grid2">
        <section className="card">
          <h2>Ingest papers</h2>
          <form onSubmit={upload} className="stack">
            <input type="file" multiple accept=".pdf,.xml,.txt,.md" ref={fileRef} />
            <div className="row">
              <label>Licence
                <select value={license} onChange={(e) => setLicense(e.target.value)}>
                  <option value="unknown">Unknown (quotes capped)</option>
                  <option value="cc-by">Open access (CC-BY)</option>
                  <option value="internal">Internal</option>
                  <option value="subscription">Subscription</option>
                </select>
              </label>
              <label className="check"><input type="checkbox" checked={confidential} onChange={(e) => setConf(e.target.checked)} />
                Confidential (never sent to external LLM)</label>
            </div>
            <div className="row">
              <LoadingButton loading={busy && /^(Checking|Uploading|Saving)/.test(task)}
                disabled={busy} label="Upload & analyse" busyLabel="Uploading…" />
              <LoadingButton type="button" className="ghost" loading={busy && task.startsWith('Ingesting')} disabled={busy}
                label="Ingest internal repository" busyLabel="Ingesting…"
                onClick={() => wrap(api.ingestFolder, (r) => `${r.length} internal file(s) processed`, 'Ingesting internal repository…')} />
            </div>
            <small>PDF, JATS XML (PubMed Central / bioRxiv) or text · max 15 MB · duplicates detected by content hash</small>
          </form>
        </section>

        <section className="card">
          <h2>PubMed</h2>
          <form className="row" onSubmit={(e) => { e.preventDefault(); wrap(async () => { const h = await api.pubmedSearch(pq); setHits(h); return h }, (h) => `${h.length} result(s)`, 'Searching PubMed…') }}>
            <input placeholder="e.g. JAK1 inhibitor rheumatoid arthritis" value={pq} onChange={(e) => setPq(e.target.value)} />
            <LoadingButton loading={busy && task.startsWith('Searching')} disabled={busy || !pq} label="Search" busyLabel="Searching…" />
          </form>
          <div className="scroll">
            {hits.map((h) => (
              <div key={h.pmid} className="hit">
                <div><b>{h.title}</b><br /><small>{h.authors.slice(0, 3).join(', ')} · {h.pub_date} · PMID {h.pmid}</small></div>
                <button className="ghost" disabled={busy || !h.abstract}
                  onClick={() => wrap(() => api.pubmedIngest(h.pmid), () => 'Added from PubMed', `Adding PMID ${h.pmid}…`)}>
                  {busy && task.includes(h.pmid) ? <Spinner /> : 'Add'}</button>
              </div>
            ))}
          </div>
        </section>
      </div>

      <KnowledgeBase onOpen={onOpen} initialFilter={initialFilter} refreshKey={refreshKey} />

      <section className="card stack">
        <h2>Search passages <small>(hybrid: keyword + semantic — finds paraphrases, not just exact words)</small></h2>
        <form className="row" onSubmit={async (e) => { e.preventDefault(); setSearching(true); try { setSres(await api.search(sq)) } catch (x) { setMsg({ bad: x.message }) } setSearching(false) }}>
          <input placeholder="e.g. drugs that shrink tumours in rodents" value={sq} onChange={(e) => setSq(e.target.value)} />
          <LoadingButton loading={searching} disabled={!sq.trim()} label="Search" busyLabel="Searching…" />
        </form>
        {sres && (
          <div>
            {!sres.semantic_enabled && <div className="alert warn">Semantic model unavailable — keyword results only.</div>}
            {sres.results.map((r, i) => (
              <div key={i} className="hit"><div><a onClick={() => onOpen(r.paper_id)}>{r.title}</a> <small>/ {r.section}</small><br />
                <span style={{ fontSize: 13 }}>{r.text.slice(0, 260)}…</span></div><span className="pill">{r.via}</span></div>))}
            {!sres.results.length && <p className="muted">No passages matched.</p>}
          </div>)}
      </section>

      <Sources onChange={load} />
    </div>
  )
}
