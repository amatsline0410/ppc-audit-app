import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { Icon } from './ui.jsx'

// ─────────────────────────────────────────────────────────────────────────────
// Reusable modal kit — Binance-token styled, portal-rendered.
//
//  • <Modal>  — base presentational shell (title · body · footer, sizes, Esc +
//               backdrop-to-close). Use for custom content (drill-downs, forms).
//  • <ModalProvider> + useModals() — imperative confirm / prompt / alert that
//               return Promises, near drop-in replacements for the native
//               window.confirm / window.prompt / window.alert (which can't be
//               styled, block the thread, and clash with the dark theme).
// ─────────────────────────────────────────────────────────────────────────────

const SIZES = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-lg', xl: 'max-w-2xl', '2xl': 'max-w-4xl' }

export function Modal({ open, onClose, title, subtitle, children, footer,
                        size = 'md', closeOnBackdrop = true }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'   // lock background scroll
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [open, onClose])

  if (!open) return null
  return ReactDOM.createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-[fadeIn_120ms_ease-out]"
           onClick={() => closeOnBackdrop && onClose?.()} />
      <div role="dialog" aria-modal="true"
           className={`relative card w-full ${SIZES[size] || SIZES.md} max-h-[90vh] flex flex-col
                       shadow-2xl animate-[popIn_140ms_ease-out]`}>
        {(title || onClose) && (
          <div className="flex items-start justify-between gap-3 p-4 border-b border-edge">
            <div>
              {title && <div className="font-mono text-sm font-semibold text-slate-100">{title}</div>}
              {subtitle && <div className="font-mono text-[11px] text-mute mt-0.5">{subtitle}</div>}
            </div>
            {onClose && (
              <button onClick={onClose} aria-label="Close"
                      className="text-mute hover:text-body text-lg leading-none -mt-1"><Icon name="close" size={18} /></button>
            )}
          </div>
        )}
        <div className="p-4 overflow-y-auto">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 p-4 border-t border-edge">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

// ── imperative confirm / prompt / alert ─────────────────────────────────────
const ModalCtx = createContext(null)
export function useModals() {
  const ctx = useContext(ModalCtx)
  if (!ctx) throw new Error('useModals must be used within <ModalProvider>')
  return ctx
}

// accept a plain string or an options object for ergonomics:
//   confirm('Sure?')  /  confirm({ title, message, danger, confirmLabel })
const norm = (opts) => (typeof opts === 'string' ? { message: opts } : (opts || {}))

export function ModalProvider({ children }) {
  const [dlg, setDlg] = useState(null)   // { kind, resolve, ...opts }
  const [value, setValue] = useState('')
  const inputRef = useRef(null)

  const open = useCallback((kind, opts) => new Promise((resolve) => {
    const o = norm(opts)
    setValue(o.defaultValue || '')
    setDlg({ kind, resolve, ...o })
  }), [])

  const confirm = useCallback((opts) => open('confirm', opts), [open])
  const prompt = useCallback((opts) => open('prompt', opts), [open])
  const alert = useCallback((opts) => open('alert', opts), [open])

  const close = useCallback((result) => {
    setDlg((d) => { d?.resolve(result); return null })
  }, [])

  useEffect(() => {
    if (dlg?.kind === 'prompt') setTimeout(() => inputRef.current?.focus(), 30)
  }, [dlg])

  const isPrompt = dlg?.kind === 'prompt'
  const isAlert = dlg?.kind === 'alert'
  const danger = dlg?.danger
  const onCancel = () => close(isPrompt ? null : false)
  const onOk = () => close(isPrompt ? value : true)

  return (
    <ModalCtx.Provider value={{ confirm, prompt, alert }}>
      {children}
      <Modal open={!!dlg} onClose={onCancel} size="sm"
             title={dlg?.title || (isAlert ? 'Notice' : isPrompt ? 'Input' : 'Confirm')}
             closeOnBackdrop={!danger}
             footer={
               <>
                 {!isAlert && (
                   <button className="btn btn-ghost" onClick={onCancel}>
                     {dlg?.cancelLabel || 'Cancel'}
                   </button>
                 )}
                 <button autoFocus={!isPrompt}
                   onClick={() => { if (isPrompt && dlg?.required && !value.trim()) return; onOk() }}
                   className={`btn ${danger ? 'bg-red text-white hover:bg-red/90' : 'btn-primary'}`}>
                   {dlg?.confirmLabel || (isAlert ? 'OK' : isPrompt ? 'Save' : 'Confirm')}
                 </button>
               </>
             }>
        {dlg?.message && (
          <div className="font-mono text-xs text-body whitespace-pre-line leading-relaxed">{dlg.message}</div>
        )}
        {isPrompt && (
          <input ref={inputRef} value={value} onChange={(e) => setValue(e.target.value)}
                 placeholder={dlg?.placeholder || ''}
                 onKeyDown={(e) => { if (e.key === 'Enter') { if (dlg?.required && !value.trim()) return; onOk() } }}
                 className="mt-3 w-full bg-panel border border-edge rounded px-3 py-2 font-mono text-xs
                            text-slate-100 focus:outline-none focus:border-primary" />
        )}
      </Modal>
    </ModalCtx.Provider>
  )
}
