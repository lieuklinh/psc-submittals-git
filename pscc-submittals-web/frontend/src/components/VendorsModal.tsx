import { useEffect, useState } from 'react'
import { apiGet, apiPatch, apiPost } from '../api/client'
import type { Organization } from '../types'
import { ORGANIZATION_TYPES } from '../types'
import Modal from './Modal'

export default function VendorsModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('subcontractor')

  function refresh() {
    apiGet<Organization[]>(`/api/projects/${projectId}/organizations`).then(setOrgs).catch(() => {})
  }

  useEffect(refresh, [projectId])

  async function handleRename(org: Organization, name: string) {
    if (!name.trim() || name === org.organization_name) return
    await apiPatch(`/api/projects/${projectId}/organizations/${org.id}`, { organization_name: name.trim() })
    refresh()
  }

  async function handleTradeChange(org: Organization, trade: string) {
    await apiPatch(`/api/projects/${projectId}/organizations/${org.id}`, { trade: trade || null })
    refresh()
  }

  async function toggleActive(org: Organization) {
    const action = org.is_active ? 'deactivate' : 'reactivate'
    await apiPost(`/api/projects/${projectId}/organizations/${org.id}/${action}`)
    refresh()
  }

  async function handleAdd() {
    if (!newName.trim()) return
    await apiPost(`/api/projects/${projectId}/organizations`, {
      organization_name: newName.trim(),
      organization_type: newType,
    })
    setNewName('')
    refresh()
  }

  return (
    <Modal title="Manage Vendors" onClose={onClose}>
      <p className="muted">The subcontractor/vendor directory for this project.</p>
      {orgs.length === 0 && <p className="muted">No organizations added yet.</p>}
      {orgs.map((org) => (
        <div className="vendor-row" key={org.id}>
          <input defaultValue={org.organization_name} onBlur={(e) => handleRename(org, e.target.value)} />
          <input
            defaultValue={org.trade ?? ''}
            placeholder="Trade (optional)"
            onBlur={(e) => handleTradeChange(org, e.target.value)}
          />
          <span className="muted">{org.is_active ? 'Active' : 'Inactive'}</span>
          <button onClick={() => toggleActive(org)}>{org.is_active ? 'Deactivate' : 'Reactivate'}</button>
        </div>
      ))}

      <div className="invite-row">
        <input placeholder="Organization name" value={newName} onChange={(e) => setNewName(e.target.value)} />
        <select value={newType} onChange={(e) => setNewType(e.target.value)}>
          {ORGANIZATION_TYPES.map((t) => (
            <option key={t} value={t}>{t.replace('_', ' ')}</option>
          ))}
        </select>
        <button className="btn btn-primary" onClick={handleAdd}>Add</button>
      </div>
    </Modal>
  )
}
