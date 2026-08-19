import { useState } from 'react'
import { apiPost } from '../api/client'
import type { Project } from '../types'

interface Props {
  project: Project
  membershipStatus: string | null
  onRequested: () => void
}

export default function AccessRequestGate({ project, membershipStatus, onRequested }: Props) {
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)

  async function handleRequest() {
    setSending(true)
    try {
      await apiPost(`/api/projects/${project.id}/request-access`)
      setSent(true)
      onRequested()
    } finally {
      setSending(false)
    }
  }

  if (membershipStatus === 'pending') {
    return (
      <div className="warning-banner">
        🔒 Your request to join <strong>{project.title}</strong> is pending approval from a project admin.
        You have view-only access below in the meantime.
      </div>
    )
  }

  return (
    <div className="warning-banner">
      <div>
        🔒 This spec book already exists as <strong>{project.title}</strong> (uploaded by {project.uploaded_by}).
        You have view-only access below.
      </div>
      <button className="btn btn-primary" onClick={handleRequest} disabled={sending || sent} style={{ marginTop: 8 }}>
        {sent ? 'Request sent' : sending ? 'Sending…' : 'Request to join as a collaborator'}
      </button>
    </div>
  )
}
