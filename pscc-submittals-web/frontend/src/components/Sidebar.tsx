import { useEffect, useRef, useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate } from 'react-router-dom'
import { apiGet, apiPatch, apiPost } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import logo from '../assets/logo.png'
import type { Notification, Project } from '../types'
import { ROLE_LABELS } from '../types'

const POPOVER_WIDTH = 240
const POPOVER_EST_HEIGHT = 260

export default function Sidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const popoverRef = useRef<HTMLDivElement | null>(null)

  const refresh = useCallback(() => {
    apiGet<Project[]>('/api/projects').then(setProjects).catch(() => {})
    apiGet<Notification[]>('/api/notifications').then(setNotifications).catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 20000)
    return () => clearInterval(interval)
  }, [refresh])

  // Popover renders in a portal (escapes the scrollable project list), so
  // clicking outside it needs its own listener to close it.
  useEffect(() => {
    if (!openMenuId) return
    function handleClickOutside(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpenMenuId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [openMenuId])

  const unreadCount = notifications.filter((n) => !n.is_read).length

  function toggleMenu(projectId: string, e: React.MouseEvent<HTMLButtonElement>) {
    if (openMenuId === projectId) {
      setOpenMenuId(null)
      return
    }
    const rect = e.currentTarget.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom
    const top = spaceBelow >= POPOVER_EST_HEIGHT ? rect.bottom + 4 : Math.max(8, rect.top - POPOVER_EST_HEIGHT - 4)
    const left = Math.min(rect.right - POPOVER_WIDTH, window.innerWidth - POPOVER_WIDTH - 8)
    setMenuPos({ top, left: Math.max(8, left) })
    setOpenMenuId(projectId)
  }

  async function handlePin(p: Project) {
    await apiPatch(`/api/projects/${p.id}`, { pinned: !p.pinned })
    refresh()
  }

  async function handleRename(p: Project) {
    const title = renameValue.trim()
    if (title) await apiPatch(`/api/projects/${p.id}`, { title })
    setRenamingId(null)
    refresh()
  }

  async function handleDeleteAction(p: Project) {
    if (p.delete_requested_by) {
      if (p.role === 'owner_admin') {
        if (confirm(`Permanently delete "${p.title}"?`)) {
          await apiPost(`/api/projects/${p.id}/delete-confirm`)
          refresh()
        }
      }
    } else {
      await apiPost(`/api/projects/${p.id}/delete-request`)
      refresh()
    }
    setOpenMenuId(null)
  }

  async function handleCancelDelete(p: Project) {
    await apiPost(`/api/projects/${p.id}/delete-cancel`)
    refresh()
    setOpenMenuId(null)
  }

  async function handleNotifClick(n: Notification) {
    if (!n.is_read) await apiPost(`/api/notifications/${n.id}/read`)
    refresh()
    navigate(`/project/${n.project_id}`)
  }

  const openProject = projects.find((p) => p.id === openMenuId) ?? null

  return (
    <aside className="sidebar">
      <div className="sidebar-brand"><img src={logo} alt="Petticoat Schmitt" className="sidebar-logo" /></div>

      <details className="sidebar-section" open={unreadCount > 0}>
        <summary>🔔 Notifications ({unreadCount})</summary>
        <div className="notif-list">
          {notifications.length === 0 && <p className="muted">Nothing yet.</p>}
          {notifications.map((n) => (
            <button key={n.id} className="notif-item" onClick={() => handleNotifClick(n)}>
              {!n.is_read ? '🔵' : '⚪'} {n.message}
            </button>
          ))}
        </div>
      </details>

      <details className="sidebar-section" open>
        <summary>📋 My projects ({projects.length})</summary>
        <div className="project-list">
          {projects.length === 0 && <p className="muted">Nothing here yet.</p>}
          {projects.map((p) => (
            <div key={p.id} className="project-row">
              <Link to={`/project/${p.id}`} className="project-link">
                {p.pinned ? '📌 ' : ''}
                {p.title}
                <span className="role-tag"> · {ROLE_LABELS[p.role ?? ''] ?? p.role}</span>
              </Link>
              <button className="menu-btn" onClick={(e) => toggleMenu(p.id, e)}>⋯</button>
            </div>
          ))}
        </div>
      </details>

      {openProject && menuPos && createPortal(
        <div
          ref={popoverRef}
          className="menu-popover menu-popover-portal"
          style={{ top: menuPos.top, left: menuPos.left, width: POPOVER_WIDTH }}
        >
          {renamingId === openProject.id ? (
            <div className="menu-row">
              <input
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                placeholder="New name"
                autoFocus
              />
              <button onClick={() => handleRename(openProject)}>Save</button>
            </div>
          ) : (
            <button onClick={() => { setRenamingId(openProject.id); setRenameValue(openProject.title) }}>Rename</button>
          )}
          <button onClick={() => handlePin(openProject)}>{openProject.pinned ? 'Unpin' : 'Pin'}</button>
          {openProject.delete_requested_by ? (
            openProject.role === 'owner_admin' ? (
              <>
                <div className="menu-note">Delete requested by {openProject.delete_requested_by}</div>
                <button onClick={() => handleDeleteAction(openProject)}>Confirm delete</button>
                <button onClick={() => handleCancelDelete(openProject)}>Deny</button>
              </>
            ) : (
              <div className="menu-note">Delete requested — waiting on Owner Admin.</div>
            )
          ) : (
            <button onClick={() => handleDeleteAction(openProject)}>
              {openProject.role === 'owner_admin' ? 'Delete' : 'Request delete'}
            </button>
          )}
        </div>,
        document.body,
      )}

      <div className="sidebar-spacer" />

      <Link to="/" className="btn btn-block">＋ Start a new project</Link>

      <div className="sidebar-footer">
        <div className="signed-in-as">Signed in as <strong>{user?.name}</strong></div>
        <div className="muted">{user?.email}</div>
        <button className="btn btn-block" onClick={logout}>Log out</button>
      </div>
    </aside>
  )
}
