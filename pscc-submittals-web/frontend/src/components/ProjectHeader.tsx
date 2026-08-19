import { useState } from 'react'
import { apiDownload } from '../api/client'
import type { Project } from '../types'
import { ROLE_LABELS } from '../types'
import TeamModal from './TeamModal'
import VendorsModal from './VendorsModal'

interface Props {
  project: Project
  role: string | null
  onOpenChat: () => void
}

export default function ProjectHeader({ project, role, onOpenChat }: Props) {
  const [showTeam, setShowTeam] = useState(false)
  const [showVendors, setShowVendors] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const isAdmin = role === 'owner_admin' || role === 'admin'

  async function handleDownload() {
    setDownloading(true)
    try {
      const blob = await apiDownload(`/api/projects/${project.id}/download`)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${project.title}_submittal_package.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('No extraction output available yet.')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="project-header">
      <h1>{project.title}</h1>
      <div className="project-header-meta">
        <span className="muted">
          Uploaded by {project.uploaded_by}
          {role && ` · your role: ${ROLE_LABELS[role] ?? role}`}
        </span>
        <div className="header-actions">
          {isAdmin && <button className="btn" onClick={() => setShowTeam(true)}>👥 Manage Team</button>}
          {isAdmin && <button className="btn" onClick={() => setShowVendors(true)}>🏷️ Vendors</button>}
        </div>
      </div>
      <div className="header-actions-row">
        <button className="btn" onClick={onOpenChat}>Chat with the agent</button>
        <button className="btn" onClick={handleDownload} disabled={downloading}>
          {downloading ? 'Preparing...' : 'Download the extraction'}
        </button>
      </div>

      {showTeam && <TeamModal projectId={project.id} onClose={() => setShowTeam(false)} />}
      {showVendors && <VendorsModal projectId={project.id} onClose={() => setShowVendors(false)} />}
    </div>
  )
}
