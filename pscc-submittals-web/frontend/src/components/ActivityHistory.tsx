import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { ActivityEntry } from '../types'

const LABELS: Record<string, string> = {
  submittal_created: 'created submittal',
  submittal_updated: 'updated submittal',
  submittal_archived: 'archived submittal',
  submittal_deleted: 'deleted submittal',
  marked_already_available: 'marked Already Available',
  marked_not_required: 'marked Not Required',
  member_added: 'added a member',
  member_role_changed: "changed a member's role",
  member_deactivated: 'deactivated a member',
  member_removed: 'removed a member',
  file_uploaded: 'uploaded a file',
  comment_added: 'added a comment',
  legacy_data_migrated: 'migrated legacy data',
  section_assigned: 'assigned a section',
  section_marked_not_required: 'marked a section Not Required',
  section_reactivated: 'reactivated a section',
  access_requested: 'requested access',
  access_approved: 'approved an access request',
  access_denied: 'denied an access request',
}

export default function ActivityHistory({ projectId, isAdmin }: { projectId: string; isAdmin: boolean }) {
  const [entries, setEntries] = useState<ActivityEntry[]>([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (isAdmin) {
      apiGet<ActivityEntry[]>(`/api/projects/${projectId}/activity`).then(setEntries).catch(() => {})
    }
  }, [projectId, isAdmin])

  if (!isAdmin) return null

  return (
    <details className="activity-history" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>📜 Activity history</summary>
      {entries.length === 0 && <p className="muted">No activity recorded yet.</p>}
      {entries.slice(0, 200).map((e) => (
        <div className="history-row" key={e.id}>
          <strong>{e.actor_email}</strong> {LABELS[e.action_type] ?? e.action_type.replace(/_/g, ' ')}{' '}
          <span className="muted">{e.created_at.slice(0, 16).replace('T', ' ')}</span>
        </div>
      ))}
    </details>
  )
}
