import React from 'react'

export function Spinner({ size = 14 }) {
  return <span className="spinner" style={{ width: size, height: size }} role="status" aria-label="loading" />
}

/** Button that shows a spinner + busy label while its action runs. */
export function LoadingButton({ loading, label, busyLabel, children, ...props }) {
  return (
    <button {...props} disabled={loading || props.disabled}>
      {loading && <Spinner />} {loading ? (busyLabel || label || children) : (label || children)}
    </button>
  )
}

/** Full-width activity banner with optional progress bar (0-100). */
export function Activity({ text, progress }) {
  return (
    <div className="activity">
      <div className="row"><Spinner size={16} /> <b>{text}</b>{progress != null && <span>{progress}%</span>}</div>
      <div className="progress"><i className={progress == null ? 'indeterminate' : ''} style={progress != null ? { width: `${progress}%` } : {}} /></div>
    </div>
  )
}
