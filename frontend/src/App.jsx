import React, { useEffect, useState } from 'react'
import { api } from './api'
import Library from './components/Library.jsx'
import PaperView from './components/PaperView.jsx'
import Chat from './components/Chat.jsx'
import Evaluation from './components/Evaluation.jsx'
import Guardrails from './components/Guardrails.jsx'
import Explore from './components/Explore.jsx'
import Monitor from './components/Monitor.jsx'
import Toaster from './components/Toaster.jsx'
import Models from './components/Models.jsx'
import Tokenomics from './components/Tokenomics.jsx'

const TABS = ['Library', 'Explore', 'Monitor', 'Models', 'Tokenomics', 'Evaluation', 'Guardrails']
const short = (m) => (m || '').replace(/^groq\//, '')

export default function App() {
  const [tab, setTab] = useState('Library')
  const [paperId, setPaperId] = useState(null)
  const [health, setHealth] = useState(null)
  const [filter, setFilter] = useState('')
  const [unseen, setUnseen] = useState(0)

  useEffect(() => { api.health().then(setHealth).catch(() => setHealth({ mode: 'backend offline' })) }, [])
  const refreshAlerts = () => api.alerts().then((a) => setUnseen(a.filter((x) => !x.seen).length)).catch(() => {})
  useEffect(() => { refreshAlerts(); const t = setInterval(refreshAlerts, 20000); return () => clearInterval(t) }, [])

  const open = (id) => { setPaperId(id); setTab('Library') }
  const goLibrary = (q) => { setFilter(q || ''); setPaperId(null); setTab('Library') }

  return (
    <div className="app">
      <header>
        <h1>🧬 Research Insight Extractor</h1>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => { setTab(t); if (t !== 'Library') setPaperId(null) }}>
              {t}{t === 'Monitor' && unseen > 0 && <span className="pill bad" style={{ marginLeft: 6 }}>{unseen}</span>}
            </button>
          ))}
        </nav>
        <span className={'pill ' + (health?.llm_enabled ? 'ok' : 'warn')} title={health?.models ? `LiteLLM gateway · primary ${health.models.primary} · fallback ${health.models.fallback}` : ''}
          style={{ cursor: 'pointer' }} onClick={() => { setTab('Models'); setPaperId(null) }}>
          {health ? (health.models ? `${short(health.models.primary)} ▸ ${short(health.models.fallback)}` : health.mode) : '…'}
          {health && !health.llm_enabled && ' (offline)'}
        </span>
      </header>
      <main>
        {tab === 'Library' && (paperId
          ? <PaperView id={paperId} onBack={() => setPaperId(null)} onFilter={goLibrary} />
          : <Library onOpen={open} initialFilter={filter} />)}
        {tab === 'Explore' && <Explore onOpen={open} goLibrary={goLibrary} />}
        {tab === 'Monitor' && <Monitor onOpen={open} onSeen={() => setUnseen(0)} />}
        {tab === 'Models' && <Models />}
        {tab === 'Tokenomics' && <Tokenomics />}
        {tab === 'Evaluation' && <Evaluation llmEnabled={!!health?.llm_enabled} />}
        {tab === 'Guardrails' && <Guardrails />}
      </main>
      <Toaster />
      <Chat currentPaperId={tab === 'Library' ? paperId : null} onOpenPaper={open} />
    </div>
  )
}
