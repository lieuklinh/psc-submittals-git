import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/client'
import type { SectionFlag } from '../types'

export default function FlagReview({ projectId, isAdmin }: { projectId: string; isAdmin: boolean }) {
  const [flags, setFlags] = useState<SectionFlag[]>([])
  const [customValues, setCustomValues] = useState<Record<string, string>>({})

  function refresh() {
    apiGet<SectionFlag[]>(`/api/projects/${projectId}/flags`).then(setFlags).catch(() => {})
  }

  useEffect(refresh, [projectId])

  if (flags.length === 0) return null

  async function handleConfirm(flag: SectionFlag, value: string) {
    if (!value.trim()) return
    await apiPost(`/api/projects/${projectId}/flags/${flag.id}/resolve`, {
      section_id: flag.section_id,
      resolved_value: value.trim(),
      original_code: flag.original_code,
    })
    refresh()
  }

  return (
    <div className="flag-review">
      <p className="warning-banner">⚠️ {flags.length} section(s) need a quick review before this project is finalized.</p>
      {flags.map((flag) => (
        <div className="flag-card" key={flag.id}>
          <strong>{flag.description}</strong>
          <p className="muted">{flag.llm_explanation}</p>
          {isAdmin ? (
            <div className="flag-options">
              <button onClick={() => handleConfirm(flag, flag.original_code)}>{flag.original_code}</button>
              <button onClick={() => handleConfirm(flag, flag.embedded_code)}>{flag.embedded_code}</button>
              {flag.suggested_code && (
                <button onClick={() => handleConfirm(flag, flag.suggested_code!)}>{flag.suggested_code}</button>
              )}
              <input
                placeholder="Custom value"
                value={customValues[flag.id] ?? ''}
                onChange={(e) => setCustomValues((prev) => ({ ...prev, [flag.id]: e.target.value }))}
              />
              <button onClick={() => handleConfirm(flag, customValues[flag.id] ?? '')}>Confirm custom</button>
            </div>
          ) : (
            <p className="muted">Waiting on a project admin to resolve this.</p>
          )}
        </div>
      ))}
    </div>
  )
}
