import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, TableSkeleton, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'
import { Modal, useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

// Superuser-only user management: list / create / delete / reset password.
// Same management-table pattern as the Stores tab: header row with the primary
// action (New User opens a modal form), table-list below with per-row actions.
export function UsersPanel({ me }) {
  const { confirm, prompt, alert } = useModals()
  const toast = useToast()
  const [users, setUsers] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [adding, setAdding] = useState(false)
  const [nu, setNu] = useState({ username: '', password: '', is_superuser: false })

  function load() {
    setBusy(true); setErr(null)
    api.users().then(r => setUsers(r.users)).catch(e => setErr(String(e))).finally(() => setBusy(false))
  }
  useEffect(() => { load() }, [])

  const ctl = useTableControls(users, { searchKeys: ['username'], deps: [users.length] })

  async function create(e) {
    e.preventDefault(); setErr(null)
    const name = nu.username.trim()
    try {
      await api.createUser(name, nu.password, nu.is_superuser)
      setNu({ username: '', password: '', is_superuser: false }); setAdding(false)
      toast.success(`User “${name}” created`); load()
    } catch (e) { setErr(String(e.message || e)); toast.error(String(e.message || e)) }
  }
  async function del(u) {
    const ok = await confirm({ title: `Delete user “${u}”?`, danger: true, confirmLabel: 'Delete user',
      message: 'Removes the user and purges their stores. This cannot be undone.' })
    if (!ok) return
    try { await api.deleteUser(u); toast.success(`User “${u}” deleted`); load() } catch (e) { setErr(String(e.message || e)); toast.error(String(e.message || e)) }
  }
  async function reset(u) {
    const pw = await prompt({ title: `Reset password — ${u}`, placeholder: 'New password (min 6 chars)',
      confirmLabel: 'Update', required: true })
    if (!pw) return
    try { await api.setUserPassword(u, pw); toast.success(`Password reset for “${u}”`); await alert({ title: 'Done', message: `Password updated for “${u}”.` }) }
    catch (e) { setErr(String(e.message || e)); toast.error(String(e.message || e)) }
  }

  const inp = 'bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 w-full focus:outline-none focus:border-lime'
  return (
    <div className="space-y-5">
      {err && <div className="card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      <div className="card">
        <div className="p-3 border-b border-edge flex items-center justify-between gap-2 flex-wrap">
          <span className="text-mute text-[11px] font-mono uppercase tracking-wider">users · {users.length}</span>
          <button onClick={() => setAdding(true)} className="btn btn-primary text-xs flex items-center gap-1">
            <Icon name="add" size={14} /> New User
          </button>
        </div>
        <TableToolbar ctl={ctl} placeholder="search username…" />
        {busy ? <TableSkeleton rows={6} cols={4} toolbar={false} /> : (
          <table className="w-full text-sm font-mono">
            <thead><tr className="text-mute text-[11px] uppercase tracking-wider border-b border-edge">
              <Th ctl={ctl} k="username">Username</Th>
              <Th ctl={ctl} k="is_superuser">Role</Th>
              <Th ctl={ctl} k="created_at">Created</Th>
              <th className="p-2 text-right">Actions</th>
            </tr></thead>
            <tbody>
              {ctl.view.map(u => (
                <tr key={u.username} className={`border-b border-edge/40 hover:bg-edge/20 ${u.username === me?.username ? 'bg-lime/5' : ''}`}>
                  <td className="p-2 text-slate-200">
                    <span className="inline-flex items-center gap-2">
                      <Icon name="person" size={14} className="text-mute" />{u.username}
                      {u.username === me?.username && <span className="text-lime text-[10px] inline-flex items-center gap-1"><Icon name="circle" size={10} /> you</span>}
                    </span>
                  </td>
                  <td className="p-2">{u.is_superuser ? <span className="text-lime">superuser</span> : <span className="text-mute">user</span>}</td>
                  <td className="p-2 text-mute">{(u.created_at || '').replace('T', ' ').slice(0, 16)}</td>
                  <td className="p-2 text-right whitespace-nowrap">
                    <button onClick={() => reset(u.username)} className="tag border border-edge text-mute hover:text-lime mr-1">reset pw</button>
                    <button onClick={() => del(u.username)} disabled={u.is_superuser}
                      className="tag border border-edge text-mute hover:text-red disabled:opacity-30">delete</button>
                  </td>
                </tr>
              ))}
              {ctl.view.length === 0 && <tr><td colSpan={4} className="p-6 text-center text-mute">no users — hit New User</td></tr>}
            </tbody>
          </table>
        )}
        <Pagination ctl={ctl} />
      </div>

      {/* New User — modal form (was an always-visible inline form) */}
      <Modal open={adding} onClose={() => setAdding(false)} size="sm" title="New user"
        subtitle="min 6-char password · superusers can manage users">
        <form onSubmit={create} className="space-y-3">
          <div>
            <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">username</div>
            <input autoFocus value={nu.username} onChange={e => setNu({ ...nu, username: e.target.value })} className={inp} />
          </div>
          <div>
            <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">password</div>
            <input type="password" value={nu.password} onChange={e => setNu({ ...nu, password: e.target.value })} className={inp} />
          </div>
          <label className="font-mono text-xs text-mute flex items-center gap-1">
            <input type="checkbox" checked={nu.is_superuser} onChange={e => setNu({ ...nu, is_superuser: e.target.checked })} className="accent-lime" />
            superuser
          </label>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={() => setAdding(false)} className="btn btn-ghost text-xs">Cancel</button>
            <button type="submit" disabled={!nu.username || !nu.password} className="btn btn-primary text-xs disabled:opacity-50">
              <Icon name="add" size={14} /> Create user
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
