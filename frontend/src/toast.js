// Tiny global toast store (no dependency). Usage: toast.error('msg', { action: { label, onClick } })
let items = []
let nextId = 1
const subs = new Set()
const emit = () => subs.forEach((f) => f([...items]))

function push(type, message, opts = {}) {
  const id = nextId++
  const ttl = opts.ttl ?? (type === 'error' ? 8000 : 4500)
  items = [...items, { id, type, message, action: opts.action, title: opts.title }]
  emit()
  if (ttl > 0) setTimeout(() => dismiss(id), ttl)
  return id
}

export function dismiss(id) {
  items = items.filter((t) => t.id !== id)
  emit()
}

export const toast = {
  error: (m, o) => push('error', m, o),
  success: (m, o) => push('success', m, o),
  warn: (m, o) => push('warn', m, o),
  info: (m, o) => push('info', m, o),
}

export function subscribe(fn) {
  subs.add(fn)
  fn([...items])
  return () => subs.delete(fn)
}
