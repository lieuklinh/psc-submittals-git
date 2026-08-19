import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { apiGet } from '../api/client'
import AccessRequestGate from '../components/AccessRequestGate'
import ActivityHistory from '../components/ActivityHistory'
import ChatPanel from '../components/ChatPanel'
import FlagReview from '../components/FlagReview'
import ProjectHeader from '../components/ProjectHeader'
import WorkspaceTable from '../components/WorkspaceTable'
import type { Project, WorkspaceResponse } from '../types'

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [workspace, setWorkspace] = useState<WorkspaceResponse | null>(null)
  const [showChat, setShowChat] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    if (!id) return
    apiGet<Project>(`/api/projects/${id}`).then(setProject).catch((e) => setError(String(e)))
    apiGet<WorkspaceResponse>(`/api/projects/${id}/workspace`).then(setWorkspace).catch(() => {})
  }, [id])

  useEffect(refresh, [refresh])

  if (!id) return null
  if (error) return <p className="error-text">{error}</p>
  if (!project) return <p className="muted">Loading…</p>

  const role = project.my_role ?? null
  const isAdmin = role === 'owner_admin' || role === 'admin'

  const hasAccess = role !== null
  // `readOnly` means "not a project member at all" — it hides row actions
  // (Details) entirely, since a non-member has no view into a submittal's
  // files/comments/history. A Viewer IS a member and per spec can view
  // files, comments, and communication history (just not edit anything or
  // upload/comment) — that distinction is handled inside WorkspaceTable
  // via `canEdit`/`canWrite`, not by collapsing Viewer into this flag.
  const isReadOnly = !hasAccess

  return (
    <div className="project-page">
      <ProjectHeader project={project} role={role} onOpenChat={() => setShowChat(true)} />
      {!hasAccess && workspace && (
        <AccessRequestGate
          project={project}
          membershipStatus={workspace.membership_status}
          onRequested={refresh}
        />
      )}
      {hasAccess && <FlagReview projectId={id} isAdmin={isAdmin} />}
      {workspace && <WorkspaceTable projectId={id} data={workspace} onRefresh={refresh} readOnly={isReadOnly} />}
      {hasAccess && <ActivityHistory projectId={id} isAdmin={isAdmin} />}
      {showChat && <ChatPanel projectId={id} onClose={() => setShowChat(false)} />}
    </div>
  )
}
