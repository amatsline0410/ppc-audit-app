import React, { useState } from 'react'
import { api } from '../api/client.js'
import { Icon } from './ui.jsx'

// Username/password login gate. On success calls onLogin(user).
export function Login({ onLogin }) {
  const [mode, setMode] = useState('login')   // login | register
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const reg = mode === 'register'

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setErr(null)
    try { onLogin(await (reg ? api.register : api.login)(username.trim(), password)) }
    catch (e) { setErr(String(e.message || e)) }
    finally { setBusy(false) }
  }
  function swap() { setMode(reg ? 'login' : 'register'); setErr(null) }

  const inp = 'w-full bg-panel border border-edge rounded px-3 py-2 font-mono text-sm text-slate-100 focus:outline-none focus:border-lime'
  return (
    <div className="min-h-screen flex items-center justify-center bg-ink p-4">
      <form onSubmit={submit} className="card p-6 w-full max-w-sm space-y-4">
        <div>
          <div className="text-lime font-mono text-lg font-bold">PPC Audit + Profit Console</div>
          <div className="text-mute text-xs font-mono mt-1">{reg ? 'create an account' : 'sign in to continue'}</div>
        </div>
        <label className="block">
          <span className="text-mute text-[11px] font-mono uppercase tracking-wider">Username</span>
          <input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} className={`${inp} mt-1`} />
        </label>
        <label className="block">
          <span className="text-mute text-[11px] font-mono uppercase tracking-wider">Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className={`${inp} mt-1`} />
          {reg && <span className="text-mute text-[10px] font-mono">at least 6 characters</span>}
        </label>
        {err && <div className="card border-red/40 p-2 font-mono text-xs text-red inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
        <button type="submit" disabled={busy || !username || !password} aria-busy={busy}
          className="btn btn-primary w-full">{busy ? (reg ? 'creating…' : 'signing in…') : (reg ? 'Create account' : 'Sign in')}</button>
        <button type="button" onClick={swap} className="w-full font-mono text-xs text-mute hover:text-lime">
          {reg ? 'have an account? Sign in' : "new here? Create an account"}
        </button>
      </form>
    </div>
  )
}
