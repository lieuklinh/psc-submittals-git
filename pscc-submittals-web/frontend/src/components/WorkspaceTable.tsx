import { useState } from 'react'
import { apiPatch, apiPost } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { Organization, ProjectMember, SpecSection, SubmittalItem, WorkspaceResponse } from '../types'
import { STATUS_LABELS, SUBMITTAL_STATUSES, SUBMITTAL_TYPES } from '../types'
import SubmittalDetailsModal from './SubmittalDetailsModal'

const TYPE_LABELS = Object.fromEntries(SUBMITTAL_TYPES)

const STATUS_DOT: Record<string, string> = {
  unassigned: '⚪', required: '⚪', assigned: '🔵', requested: '🔵', received: '🔵',
  under_review: '🔵', approved: '🟢', approved_as_noted: '🟢', already_available: '🟢',
  closed: '🟢', revise_and_resubmit: '🔴', rejected: '🔴', not_required: '🔴',
}

// The PSCC-style "Sub No" (e.g. D-014523-001) is display_number with its
// trailing revision letter stripped — the letter itself lives in its own
// editable "Version" column instead.
function subNo(displayNumber: string): string {
  const parts = displayNumber.split('-')
  return parts.length > 1 ? parts.slice(0, -1).join('-') : displayNumber
}

interface Props {
  projectId: string
  data: WorkspaceResponse
  onRefresh: () => void
  readOnly?: boolean
}

function SectionBlock({
  section, items, projectId, orgs, members, isAdmin, canEdit, canWrite, readOnly, onRefresh,
}: {
  section: SpecSection
  items: SubmittalItem[]
  projectId: string
  orgs: Organization[]
  members: ProjectMember[]
  isAdmin: boolean
  canEdit: boolean
  canWrite: boolean
  readOnly: boolean
  onRefresh: () => void
}) {
  const [detailsItem, setDetailsItem] = useState<SubmittalItem | null>(null)
  const [generating, setGenerating] = useState(false)
  const [expanded, setExpanded] = useState(section.status !== 'not_required')

  const memberLabel = (email: string | null) => {
    if (!email) return '— unassigned —'
    const m = members.find((mm) => mm.user_email === email)
    return m ? `${m.display_name || m.user_email}` : email
  }

  async function updateField(item: SubmittalItem, field: string, value: string | null) {
    await apiPatch(`/api/items/${item.id}?project_id=${projectId}`, { [field]: value })
    onRefresh()
  }

  async function handleAdd() {
    await apiPost(`/api/projects/${projectId}/sections/${section.id}/items`, { title: 'New submittal' })
    onRefresh()
  }

  async function handleGenerateSummary() {
    setGenerating(true)
    try {
      await apiPost(`/api/projects/${projectId}/sections/${section.id}/summary`)
      onRefresh()
    } catch {
      alert("Couldn't generate a summary — check that an OpenAI key is configured and this section has captured text.")
    } finally {
      setGenerating(false)
    }
  }

  async function handleMove(item: SubmittalItem, direction: 'up' | 'down') {
    await apiPost(`/api/items/${item.id}/move?project_id=${projectId}`, { direction })
    onRefresh()
  }

  async function handleAssign(email: string) {
    await apiPatch(`/api/projects/${projectId}/sections/${section.id}/assign`, { user_email: email || null })
    onRefresh()
  }

  async function handleNotRequired() {
    const reason = prompt('Reason this section is not required:')
    if (reason === null) return
    await apiPatch(`/api/projects/${projectId}/sections/${section.id}/not-required`, { reason, not_required: true })
    onRefresh()
  }

  async function handleReactivate() {
    await apiPatch(`/api/projects/${projectId}/sections/${section.id}/not-required`, { not_required: false })
    onRefresh()
  }

  const showMove = isAdmin && !readOnly
  const showActions = !readOnly
  const notRequired = section.status === 'not_required'

  return (
    <div className="section-block">
      <div className="section-header-line">
        <span className="section-header-title">
          <strong>{section.section_number}</strong> - {section.section_name || '(untitled section)'}
          {notRequired && <span className="pill pill-muted">Not Required</span>}
        </span>
        <span className="section-header-controls">
          {isAdmin ? (
            <select
              className="section-assignee-select"
              value={section.assigned_user_email ?? ''}
              onChange={(e) => handleAssign(e.target.value)}
            >
              <option value="">— unassigned —</option>
              {members.map((m) => <option key={m.user_email} value={m.user_email}>{memberLabel(m.user_email)}</option>)}
            </select>
          ) : (
            <span className="muted">Assigned: {memberLabel(section.assigned_user_email)}</span>
          )}
          {isAdmin && (notRequired ? (
            <button className="btn-link" onClick={handleReactivate}>Reactivate</button>
          ) : (
            <button className="btn-link" onClick={handleNotRequired}>Not Required</button>
          ))}
          <button className="btn-link" onClick={() => setExpanded((v) => !v)}>{expanded ? 'Collapse' : 'Expand'}</button>
          {canEdit && !notRequired && <button className="add-btn" onClick={handleAdd}>+ Add</button>}
        </span>
      </div>

      {!expanded ? (
        notRequired && <p className="muted section-not-required-reason">Not required — {section.not_required_reason || 'no reason given'}</p>
      ) : (
        <>
          {section.section_summary ? (
            <div className="section-summary-line">{section.section_summary}</div>
          ) : isAdmin ? (
            <button className="btn-link" onClick={handleGenerateSummary} disabled={generating}>
              {generating ? 'Summarizing…' : '✨ Generate summary'}
            </button>
          ) : (
            <p className="muted">Summary not yet available for this section.</p>
          )}

          {items.length === 0 ? (
            <p className="muted">No submittals under this section yet.</p>
          ) : (
            <table className="workspace-table">
              <colgroup>
                {showMove && <col style={{ width: '6%' }} />}
                <col style={{ width: showMove ? '12%' : readOnly ? '16%' : '14%' }} />
                <col style={{ width: showMove ? '21%' : readOnly ? '26%' : '23%' }} />
                <col style={{ width: showMove ? '8%' : readOnly ? '10%' : '9%' }} />
                <col style={{ width: showMove ? '11%' : readOnly ? '13%' : '12%' }} />
                <col style={{ width: showMove ? '11%' : readOnly ? '13%' : '12%' }} />
                <col style={{ width: showMove ? '11%' : readOnly ? '12%' : '11%' }} />
                <col style={{ width: showMove ? '6%' : readOnly ? '6%' : '6%' }} />
                <col style={{ width: showMove ? '4%' : readOnly ? '4%' : '4%' }} />
                {showActions && <col style={{ width: showMove ? '10%' : '9%' }} />}
              </colgroup>
              <thead>
                <tr>
                  {showMove && <th></th>}
                  <th>Sub No</th><th>Title</th><th>Type</th><th>Vendor</th><th>Responsible</th>
                  <th>Status</th><th>Due</th><th>Ver.</th>{showActions && <th></th>}
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => (
                  <tr key={item.id}>
                    {showMove && (
                      <td className="move-cell">
                        <button
                          className="move-btn"
                          onClick={() => handleMove(item, 'up')}
                          disabled={idx === 0}
                          title="Move up"
                        >
                          ▲
                        </button>
                        <button
                          className="move-btn"
                          onClick={() => handleMove(item, 'down')}
                          disabled={idx === items.length - 1}
                          title="Move down"
                        >
                          ▼
                        </button>
                      </td>
                    )}
                    <td className="muted">{subNo(item.display_number)}</td>
                    <td>
                      {canEdit ? (
                        <textarea
                          className="title-input"
                          rows={2}
                          defaultValue={item.title}
                          onBlur={(e) => e.target.value.trim() && e.target.value !== item.title && updateField(item, 'title', e.target.value.trim())}
                        />
                      ) : item.title}
                    </td>
                    <td>
                      {canEdit ? (
                        <select value={item.submittal_type ?? ''} onChange={(e) => updateField(item, 'submittal_type', e.target.value || null)}>
                          <option value="">—</option>
                          {SUBMITTAL_TYPES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                        </select>
                      ) : (item.submittal_type ? TYPE_LABELS[item.submittal_type] : '—')}
                    </td>
                    <td>
                      {canEdit ? (
                        <select value={item.organization_id ?? ''} onChange={(e) => updateField(item, 'organization_id', e.target.value || null)}>
                          <option value="">—</option>
                          {orgs.map((o) => <option key={o.id} value={o.id}>{o.organization_name}</option>)}
                        </select>
                      ) : (orgs.find((o) => o.id === item.organization_id)?.organization_name ?? '—')}
                    </td>
                    <td>
                      {canEdit ? (
                        <select value={item.responsible_user_email ?? ''} onChange={(e) => updateField(item, 'responsible_user_email', e.target.value || null)}>
                          <option value="">— unassigned —</option>
                          {members.map((m) => <option key={m.user_email} value={m.user_email}>{memberLabel(m.user_email)}</option>)}
                        </select>
                      ) : memberLabel(item.responsible_user_email)}
                    </td>
                    <td>
                      {canEdit ? (
                        <select value={item.status} onChange={(e) => updateField(item, 'status', e.target.value)}>
                          {SUBMITTAL_STATUSES.map((s) => (
                            <option key={s} value={s}>{STATUS_DOT[s] ?? ''} {STATUS_LABELS[s] ?? s}</option>
                          ))}
                        </select>
                      ) : (
                        `${STATUS_DOT[item.status] ?? ''} ${STATUS_LABELS[item.status] ?? item.status}`
                      )}
                    </td>
                    <td>
                      {canEdit ? (
                        <input
                          defaultValue={item.due_date ?? ''}
                          onBlur={(e) => e.target.value !== (item.due_date ?? '') && updateField(item, 'due_date', e.target.value || null)}
                        />
                      ) : (item.due_date ?? '')}
                    </td>
                    <td>
                      {canEdit ? (
                        <input
                          className="version-input"
                          maxLength={2}
                          defaultValue={item.revision_letter}
                          onBlur={(e) => {
                            const v = e.target.value.trim().toUpperCase()
                            if (v && v !== item.revision_letter) updateField(item, 'revision_letter', v)
                            else e.target.value = item.revision_letter
                          }}
                        />
                      ) : item.revision_letter}
                    </td>
                    {showActions && (
                      <td className="row-actions">
                        <button onClick={() => setDetailsItem(item)}>Details</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {detailsItem && (
        <SubmittalDetailsModal
          item={detailsItem}
          section={section}
          projectId={projectId}
          canWrite={canWrite}
          onClose={() => { setDetailsItem(null); onRefresh() }}
        />
      )}
    </div>
  )
}

export default function WorkspaceTable({ projectId, data, onRefresh, readOnly = false }: Props) {
  const { user } = useAuth()
  const { sections, items, organizations, members, is_admin, role } = data
  const itemsBySection = new Map<string, SubmittalItem[]>()
  for (const item of items) {
    const list = itemsBySection.get(item.specification_section_id) ?? []
    list.push(item)
    itemsBySection.set(item.specification_section_id, list)
  }

  // Viewers can read everything (files, comments, history) but can't
  // upload/comment/edit — matches the backend's upload_attachment/
  // add_comment checks (reject role=None and role='viewer', allow
  // everyone else regardless of section assignment).
  const canWrite = !readOnly && role !== 'viewer'

  return (
    <div className="workspace">
      <h4>
        {readOnly ? 'Workspace (view only)' : role === 'viewer' ? 'Workspace (view only — Viewer)' : 'Workspace'}
      </h4>
      {sections.length === 0 && <p className="muted">No sections extracted for this project yet.</p>}
      {sections.map((section) => {
        const secItems = itemsBySection.get(section.id) ?? []
        // Everyone sees every section (2026-08 spec: view all, edit only
        // your own). Full field edit is section-scoped: Admins edit any
        // section, an Assignee edits only sections assigned to them.
        const canEdit = !readOnly && (is_admin || (role === 'assignee' && section.assigned_user_email === user?.email))
        return (
          <SectionBlock
            key={section.id}
            section={section}
            items={secItems}
            projectId={projectId}
            orgs={organizations}
            members={members}
            isAdmin={is_admin && !readOnly}
            canEdit={canEdit}
            canWrite={canWrite}
            readOnly={readOnly}
            onRefresh={onRefresh}
          />
        )
      })}
    </div>
  )
}
