import React, { useEffect } from 'react'
import ReactDOM from 'react-dom'
import { Icon } from './ui.jsx'

// Slide-in side drawer (e-commerce-cart style): fixed to the right edge, slides
// over the page with a dimmed backdrop. Esc / backdrop / × close it. Content
// stays mounted while hidden (only translated off-screen) so panel state
// survives open/close; the OWNER persists the open flag (e.g. localStorage) so
// it survives refresh.
export function SideDrawer({ open, onClose, title, children, width = 'w-[400px]' }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'   // lock background scroll while overlaying
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [open, onClose])

  return ReactDOM.createPortal(
    <>
      <div onClick={onClose} aria-hidden="true"
        className={`fixed inset-0 z-40 bg-ink/60 backdrop-blur-[1px] transition-opacity duration-300
          ${open ? 'opacity-100' : 'opacity-0 pointer-events-none'}`} />
      <aside role="dialog" aria-label={title}
        className={`fixed top-0 right-0 z-50 h-full ${width} max-w-[92vw] bg-panel border-l border-edge
          flex flex-col transition-transform duration-300 ${open ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="px-4 py-3 border-b border-edge flex items-center justify-between shrink-0">
          <span className="font-mono text-xs uppercase tracking-wider text-mute">{title}</span>
          <button onClick={onClose} title="close drawer"
            className="text-mute hover:text-slate-100 border border-edge rounded p-1 flex items-center">
            <Icon name="close" size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">{children}</div>
      </aside>
    </>,
    document.body,
  )
}
