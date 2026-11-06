import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { LoadingButton, Spinner } from './Spinner.jsx'

const SUGGEST = [
  'What dosage and sample size were used?',
  'Summarise the key results with p-values.',
  'Which assays were used?',
]

/** Floating Q&A chatbot (bottom-right). Stays mounted so the conversation survives page changes. */
export default function ChatWidget({ currentPaperId, onOpenPaper }) {
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [scope, setScope] = useState('all')           // 'all' | 'paper'
  const end = useRef()
  const input = useRef()

  useEffect(() => { setScope(currentPaperId ? 'paper' : 'all') }, [currentPaperId])
  useEffect(() => { if (open) { end.current?.scrollIntoView({ behavior: 'smooth' }); input.current?.focus() } }, [msgs, open, busy])

  const send = async (text) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setQ(''); setBusy(true)
    const ids = scope === 'paper' && currentPaperId ? [currentPaperId] : null
    setMsgs((m) => [...m, { role: 'user', text: question }])
    try {
      const r = await api.chat(question, ids)
      setMsgs((m) => [...m, { role: 'bot', ...r }])
    } catch (e) {
      setMsgs((m) => [...m, { role: 'bot', answer: e.message, guardrail_flags: ['error'] }])
    }
    setBusy(false)
  }

  if (!open) {
    return (
      <button className="fab" onClick={() => setOpen(true)} title="Ask the research assistant" aria-label="Open chat">
        💬{msgs.length > 0 && <span className="fab-dot" />}
      </button>
    )
  }

  return (
    <div className="chat-panel" role="dialog" aria-label="Research assistant">
      <div className="chat-head">
        <div><b>Research assistant</b><small>LangChain Deep Agent · guarded</small></div>
        <div className="row">
          {msgs.length > 0 && <button className="icon" title="Clear conversation" onClick={() => setMsgs([])}>🗑</button>}
          <button className="icon" title="Close" onClick={() => setOpen(false)}>✕</button>
        </div>
      </div>

      {currentPaperId && (
        <div className="scope">
          <button className={scope === 'paper' ? 'on' : ''} onClick={() => setScope('paper')}>This paper</button>
          <button className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>All papers</button>
        </div>
      )}

      <div className="chat-body">
        {!msgs.length && (
          <div className="welcome">
            <p>👋 Ask me about the papers in your knowledge base{scope === 'paper' ? ' (this paper)' : ''}. Answers are cited.</p>
            {SUGGEST.map((s) => <button key={s} className="ghost small" onClick={() => send(s)}>{s}</button>)}
          </div>
        )}
        {msgs.map((m, i) => m.role === 'user'
          ? <div key={i} className="msg user">{m.text}</div>
          : (
            <div key={i} className={'msg bot' + (m.blocked ? ' blocked' : '')}>
              {m.answer?.split('\n').filter(Boolean).map((l, j) => <p key={j}>{l}</p>)}
              <div className="meta">
                {m.mode && <span className="pill">{m.mode}</span>}
                {m.model_label && <span className={'pill ' + (m.fallback_used ? 'warn' : 'ok')} title={m.fallback_used ? 'The primary model failed; the fallback answered' : 'Primary model'}>{m.fallback_used ? '⚠ fallback · ' : '🤖 '}{m.model_label}</span>}
                {m.latency_ms > 0 && <span className="pill">{(m.latency_ms / 1000).toFixed(1)}s</span>}
                {(m.guardrail_flags || []).filter((f) => f !== 'model_fallback').map((f) => <span key={f} className="pill warn">🛡 {f.split(':')[0]}</span>)}
                {(m.citations || []).map((c) => (
                  <a key={c} className="chip" onClick={() => onOpenPaper?.(Number(c.split('/')[0]))}>📄 {c}</a>))}
              </div>
              {m.passages?.length > 0 && (
                <details><summary>Evidence ({m.passages.length})</summary>
                  {m.passages.map((p, k) => <blockquote key={k}><b>{p.title} / {p.section}</b><br />{p.text}</blockquote>)}
                </details>)}
            </div>
          ))}
        {busy && <div className="msg bot"><Spinner /> Thinking… (planning → searching → verifying)</div>}
        <div ref={end} />
      </div>

      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send() }}>
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)}
          placeholder={scope === 'paper' ? 'Ask about this paper…' : 'Ask across all papers…'} />
        <LoadingButton loading={busy} label="Send" busyLabel="" disabled={!q.trim()} />
      </form>
    </div>
  )
}
