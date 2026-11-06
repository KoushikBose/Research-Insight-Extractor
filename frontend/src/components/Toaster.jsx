import React, { useEffect, useState } from 'react'
import { dismiss, subscribe } from '../toast.js'

const ICON = { error: '⛔', success: '✅', warn: '⚠️', info: 'ℹ️' }

export default function Toaster() {
  const [items, setItems] = useState([])
  useEffect(() => subscribe(setItems), [])
  return (
    <div className="toaster" aria-live="assertive">
      {items.map((t) => (
        <div key={t.id} className={'toast ' + t.type} role={t.type === 'error' ? 'alert' : 'status'}>
          <span className="toast-icon">{ICON[t.type]}</span>
          <div className="toast-body">
            {t.title && <b>{t.title}</b>}
            <div>{t.message}</div>
            {t.action && (
              <button className="toast-action" onClick={() => { t.action.onClick(); dismiss(t.id) }}>{t.action.label}</button>
            )}
          </div>
          <button className="toast-x" aria-label="Dismiss" onClick={() => dismiss(t.id)}>✕</button>
        </div>
      ))}
    </div>
  )
}
