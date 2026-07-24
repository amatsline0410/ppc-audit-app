import React, { createContext, useContext, useState, useCallback, useRef } from 'react'
import ReactDOM from 'react-dom'
import { Icon } from './ui.jsx'

// ─────────────────────────────────────────────────────────────────────────────
// Toast kit — animated, Material-Icon success/error/info/warning notifications.
// <ToastProvider> mounts once (in App); useToast() gives imperative fire-and-forget
// toasts: toast.success('Uploaded 12 rows'). Each slides in, the icon pops with a
// ring pulse, and a shrinking bar tracks the auto-dismiss.
// ─────────────────────────────────────────────────────────────────────────────

const ToastCtx = createContext(null)
export function useToast() {
  const ctx = useContext(ToastCtx)
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>')
  return ctx
}

const KIND = {
  success: { icon: 'check_circle', text: 'text-up', border: 'border-up/40', ring: 'bg-up/30' },
  error:   { icon: 'error',        text: 'text-red', border: 'border-red/40', ring: 'bg-red/30' },
  info:    { icon: 'info',         text: 'text-cyan', border: 'border-cyan/40', ring: 'bg-cyan/30' },
  warning: { icon: 'warning',      text: 'text-amber', border: 'border-amber/40', ring: 'bg-amber/30' },
}
const DUR = 3400   // ms on screen before auto-dismiss

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const idRef = useRef(0)
  const dismiss = useCallback((id) => setToasts(ts => ts.filter(t => t.id !== id)), [])
  const push = useCallback((kind, message, opts = {}) => {
    if (!message) return
    const id = ++idRef.current
    const dur = opts.duration ?? DUR
    setToasts(ts => [...ts, { id, kind, message, dur }])
    if (dur > 0) setTimeout(() => dismiss(id), dur)
    return id
  }, [dismiss])

  const api = {
    success: (m, o) => push('success', m, o),
    error:   (m, o) => push('error', m, o),
    info:    (m, o) => push('info', m, o),
    warning: (m, o) => push('warning', m, o),
    show: push, dismiss,
  }

  return (
    <ToastCtx.Provider value={api}>
      {children}
      {ReactDOM.createPortal(
        <div className="fixed top-4 right-4 z-[60] flex flex-col gap-2 w-[330px] max-w-[calc(100vw-2rem)] pointer-events-none">
          {toasts.map(t => <ToastCard key={t.id} t={t} onClose={() => dismiss(t.id)} />)}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  )
}

function ToastCard({ t, onClose }) {
  const k = KIND[t.kind] || KIND.info
  return (
    <div className={`pointer-events-auto card border ${k.border} p-3 flex items-start gap-3 shadow-2xl
                     relative overflow-hidden animate-[toastIn_260ms_cubic-bezier(.2,.9,.3,1.3)]`}>
      <span className="relative flex items-center justify-center shrink-0 w-6 h-6">
        <span className={`absolute w-6 h-6 rounded-full ${k.ring} animate-[ringPulse_700ms_ease-out]`} />
        <Icon name={k.icon} size={22} className={`relative ${k.text} animate-[iconPop_380ms_ease-out]`} />
      </span>
      <div className="min-w-0 flex-1 font-mono text-xs text-body leading-snug break-words">{t.message}</div>
      <button onClick={onClose} aria-label="dismiss" className="shrink-0 text-mute hover:text-body leading-none"><Icon name="close" size={14} /></button>
      {t.dur > 0 && (
        <span className={`absolute left-0 bottom-0 h-0.5 ${k.ring}`}
              style={{ animation: `toastBar ${t.dur}ms linear forwards` }} />
      )}
    </div>
  )
}
