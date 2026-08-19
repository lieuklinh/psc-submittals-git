import { useEffect, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { ProjectMember } from '../types'
import { PROJECT_ROLES, ROLE_LABELS } from '../types'
import Modal from './Modal'
import PersonSearchInput from './PersonSearchInput'

export default function TeamModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { user } = useAuth()
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('assignee')
  const [approveRoles, setApproveRoles] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  function refresh() {
    apiGet<ProjectMember[]>(`/api/projects/${projectId}/members`).then(setMembers).catch(() => {})
  }

  useEffect(refresh, [projectId])

  const myRole = members.find((m) => m.user_email === user?.email)?.role
  const isAdmin = myRole === 'owner_admin' || myRole === 'admin'

  async function handleRoleChange(email: string, role: string) {
    setError('')
    try {
      await apiPatch(`/api/projects/${projectId}/members/${encodeURIComponent(email)}`, { role })
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleDeactivate(email: string) {
    setError('')
    try {
      await apiPost(`/api/projects/${projectId}/members/${encodeURIComponent(email)}/deactivate`)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleRemove(email: string) {
    setError('')
    try {
      await apiDelete(`/api/projects/${projectId}/members/${encodeURIComponent(email)}`)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleApprove(email: string) {
    setError('')
    try {
      await apiPost(`/api/projects/${projectId}/members/${encodeURIComponent(email)}/approve`, {
        role: approveRoles[email] ?? 'assignee',
      })
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleDeny(email: string) {
    setError('')
    try {
      await apiPost(`/api/projects/${projectId}/members/${encodeURIComponent(email)}/deny`)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleInvite() {
    const email = inviteEmail.trim().toLowerCase()
    if (!email) return
    setError('')
    try {
      await apiPost(`/api/projects/${projectId}/members`, { user_email: email, role: inviteRole })
      setInviteEmail('')
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Modal title="Manage Team" onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      {members.map((m) => {
        const isSelf = m.user_email === user?.email

        if (m.status === 'pending') {
          return (
            <div className="member-row" key={m.user_email}>
              <div className="member-info">
                <div>{m.display_name || m.user_email}</div>
                <div className="muted">{m.user_email}</div>
                <div className="muted">Requested access</div>
              </div>
              {isAdmin ? (
                <div className="member-actions">
                  <select
                    value={approveRoles[m.user_email] ?? m.role}
                    onChange={(e) => setApproveRoles((prev) => ({ ...prev, [m.user_email]: e.target.value }))}
                  >
                    {PROJECT_ROLES.map((r) => (
                      <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                    ))}
                  </select>
                  <button onClick={() => handleApprove(m.user_email)}>Approve</button>
                  <button onClick={() => handleDeny(m.user_email)}>Deny</button>
                </div>
              ) : (
                <div className="muted">Pending approval</div>
              )}
            </div>
          )
        }

        return (
          <div className="member-row" key={m.user_email}>
            <div className="member-info">
              <div>{m.display_name || m.user_email}{m.company_role ? ` · ${m.company_role}` : ''}</div>
              <div className="muted">{m.user_email}</div>
              <div className="muted">{m.assigned_count} assigned</div>
            </div>
            {isAdmin && !isSelf ? (
              <div className="member-actions">
                <select value={m.role} onChange={(e) => handleRoleChange(m.user_email, e.target.value)}>
                  {PROJECT_ROLES.map((r) => (
                    <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                  ))}
                </select>
                {m.status === 'active' ? (
                  <button onClick={() => handleDeactivate(m.user_email)}>Deactivate</button>
                ) : (
                  <span className="muted">{m.status}</span>
                )}
                <button onClick={() => handleRemove(m.user_email)}>Remove</button>
              </div>
            ) : (
              <div className="muted">{ROLE_LABELS[m.role] ?? m.role}{isSelf ? ' (you)' : ''}</div>
            )}
          </div>
        )
      })}

      {isAdmin && (
        <div className="invite-row">
          <PersonSearchInput
            value={inviteEmail}
            onChange={setInviteEmail}
            placeholder="Search name or email…"
          />
          <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
            <option value="assignee">Assignee</option>
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
          <button className="btn btn-primary" onClick={handleInvite}>Invite</button>
        </div>
      )}
    </Modal>
  )
}
