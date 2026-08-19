import { useEffect, useRef, useState } from 'react'
import { apiDownload, apiGet, apiPost, apiUpload } from '../api/client'
import type { ActivityEntry, Attachment, Comment, SpecSection, SubmittalItem } from '../types'
import { ATTACHMENT_FOLDERS } from '../types'
import Modal from './Modal'

const FOLDER_LABELS = Object.fromEntries(ATTACHMENT_FOLDERS)

interface Props {
  item: SubmittalItem
  section: SpecSection | undefined
  projectId: string
  canWrite: boolean
  onClose: () => void
}

export default function SubmittalDetailsModal({ item, section, projectId, canWrite, onClose }: Props) {
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [comments, setComments] = useState<Comment[]>([])
  const [history, setHistory] = useState<ActivityEntry[]>([])
  const [newComment, setNewComment] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [uploadDescription, setUploadDescription] = useState('')
  const [uploadFolder, setUploadFolder] = useState('from_vendor')
  const fileRef = useRef<HTMLInputElement>(null)

  function refresh() {
    apiGet<Attachment[]>(`/api/items/${item.id}/attachments?project_id=${projectId}`).then(setAttachments).catch(() => {})
    apiGet<Comment[]>(`/api/items/${item.id}/comments?project_id=${projectId}`).then(setComments).catch(() => {})
    apiGet<ActivityEntry[]>(`/api/items/${item.id}/activity?project_id=${projectId}`).then(setHistory).catch(() => {})
  }

  useEffect(refresh, [item.id, projectId])

  function handleFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    setPendingFile(e.target.files?.[0] ?? null)
  }

  async function handleUpload() {
    if (!pendingFile || !uploadDescription.trim()) return
    await apiUpload(`/api/items/${item.id}/attachments?project_id=${projectId}`, pendingFile, 'file', {
      description: uploadDescription.trim(),
      folder: uploadFolder,
    })
    setPendingFile(null)
    setUploadDescription('')
    setUploadFolder('from_vendor')
    if (fileRef.current) fileRef.current.value = ''
    refresh()
  }

  async function handleDownload(att: Attachment) {
    const blob = await apiDownload(`/api/attachments/${att.id}/download`)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = att.original_filename
    a.click()
    URL.revokeObjectURL(url)
  }

  async function handlePostComment() {
    if (!newComment.trim()) return
    await apiPost(`/api/items/${item.id}/comments?project_id=${projectId}`, { body: newComment.trim() })
    setNewComment('')
    refresh()
  }

  return (
    <Modal title={`${item.display_number} — ${item.title}`} onClose={onClose}>
      {section && (
        <>
          <p className="muted">Section: {section.section_number} {section.section_name}</p>
          {section.section_summary && (
            <div className="section-summary-block">{section.section_summary}</div>
          )}
        </>
      )}

      <h4>Attachments</h4>
      {attachments.length === 0 && <p className="muted">No files uploaded yet.</p>}
      {attachments.map((att) => (
        <div className="file-card" key={att.id}>
          <div className="file-icon">📎</div>
          <div className="file-meta">
            <div className="file-name">{att.original_filename}</div>
            <div className="file-sub">{FOLDER_LABELS[att.folder] ?? att.folder} · Uploaded by {att.uploaded_by}</div>
            {att.description && <div className="file-sub">{att.description}</div>}
          </div>
          <button onClick={() => handleDownload(att)}>Download</button>
        </div>
      ))}
      {canWrite ? (
        <div className="upload-row">
          <input ref={fileRef} type="file" onChange={handleFileChosen} />
          {pendingFile && (
            <>
              <select value={uploadFolder} onChange={(e) => setUploadFolder(e.target.value)}>
                {ATTACHMENT_FOLDERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              <input
                placeholder="Brief description (required)…"
                value={uploadDescription}
                onChange={(e) => setUploadDescription(e.target.value)}
              />
              <button className="btn btn-primary" onClick={handleUpload} disabled={!uploadDescription.trim()}>
                Upload
              </button>
            </>
          )}
        </div>
      ) : (
        <p className="muted">Viewers have read-only access — files can't be uploaded here.</p>
      )}

      <h4>Comments</h4>
      {comments.length === 0 && <p className="muted">No comments yet.</p>}
      {comments.map((c) => (
        <div className="comment-row" key={c.id}>
          <strong>{c.author_email}</strong> <span className="muted">{c.created_at.slice(0, 16).replace('T', ' ')}</span>
          <p>{c.body}</p>
        </div>
      ))}
      {canWrite ? (
        <>
          <textarea
            placeholder="Add a comment…"
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
          />
          <button className="btn btn-primary" onClick={handlePostComment}>Post comment</button>
        </>
      ) : (
        <p className="muted">Viewers have read-only access — comments can't be posted here.</p>
      )}

      <details open={showHistory} onToggle={(e) => setShowHistory((e.target as HTMLDetailsElement).open)}>
        <summary>History</summary>
        {history.length === 0 && <p className="muted">No history for this submittal yet.</p>}
        {history.map((h) => (
          <div className="history-row" key={h.id}>
            <strong>{h.actor_email}</strong> {h.action_type.replace(/_/g, ' ')}{' '}
            <span className="muted">{h.created_at.slice(0, 16).replace('T', ' ')}</span>
          </div>
        ))}
      </details>
    </Modal>
  )
}
