import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiGet, apiPost, apiUpload } from '../api/client'
import logo from '../assets/logo.png'

interface IrregularCode {
  code: string
  reason: string
  context: string
}

interface ProjectInfo {
  project_name: string
  ccua_project_number: string
  pscc_job_number: string
  engineer_name: string
  engineer_address: string
  contractor_name: string
  contractor_address: string
  owner_name: string
  owner_address: string
  prepared_by: string
}

interface ScanResponse {
  status: 'existing' | 'new'
  project?: { id: string }
  scan_id?: string
  file_hash?: string
  filename?: string
  irregular_codes?: IrregularCode[]
  project_info?: ProjectInfo
}

type Stage = 'idle' | 'scanning' | 'reviewing_codes' | 'confirm' | 'extracting' | 'error'

interface ConfirmJobStatus {
  status: 'running' | 'done' | 'error'
  steps: string[]
  project_id: string | null
  error: string | null
}

const FIELD_LABELS: [keyof ProjectInfo, string][] = [
  ['project_name', 'Project Name'],
  ['ccua_project_number', 'CCUA Project #'],
  ['pscc_job_number', 'PSCC Job #'],
  ['engineer_name', 'Engineer'],
  ['contractor_name', 'Contractor'],
  ['owner_name', 'Owner'],
  ['prepared_by', 'Prepared By'],
]

export default function UploadFlow() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [stage, setStage] = useState<Stage>('idle')
  const [statusMessage, setStatusMessage] = useState('')
  const [scanId, setScanId] = useState('')
  const [filename, setFilename] = useState('')
  const [irregularCodes, setIrregularCodes] = useState<IrregularCode[]>([])
  const [corrections, setCorrections] = useState<Record<string, string>>({})
  const [projectInfo, setProjectInfo] = useState<ProjectInfo | null>(null)
  const [error, setError] = useState('')
  const [jobSteps, setJobSteps] = useState<string[]>([])
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [])

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setStage('scanning')
    setStatusMessage('Reading the spec book...')
    setError('')
    try {
      const res = await apiUpload<ScanResponse>('/api/projects/scan', file)
      if (res.status === 'existing' && res.project) {
        navigate(`/project/${res.project.id}`)
        return
      }
      setScanId(res.scan_id!)
      setFilename(res.filename!)
      setProjectInfo(res.project_info as ProjectInfo)
      if (res.irregular_codes && res.irregular_codes.length > 0) {
        setIrregularCodes(res.irregular_codes)
        setStage('reviewing_codes')
      } else {
        setStage('confirm')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setStage('error')
    }
  }

  function continueFromCodeReview() {
    setStage('confirm')
  }

  async function handleConfirmExtract() {
    if (!projectInfo) return
    setStage('extracting')
    setJobSteps([])
    setError('')
    try {
      const res = await apiPost<{ job_id: string }>('/api/projects/confirm', {
        scan_id: scanId,
        filename,
        project_info: projectInfo,
        code_corrections: corrections,
      })
      pollJobStatus(res.job_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setStage('error')
    }
  }

  function pollJobStatus(jobId: string) {
    const interval = window.setInterval(async () => {
      try {
        const job = await apiGet<ConfirmJobStatus>(`/api/projects/confirm/${jobId}/status`)
        setJobSteps(job.steps)
        if (job.status === 'done' && job.project_id) {
          window.clearInterval(interval)
          navigate(`/project/${job.project_id}`)
        } else if (job.status === 'error') {
          window.clearInterval(interval)
          setError(job.error || 'Extraction failed.')
          setStage('error')
        }
      } catch (err) {
        window.clearInterval(interval)
        setError(err instanceof Error ? err.message : String(err))
        setStage('error')
      }
    }, 1000)
    pollRef.current = interval
  }

  function resetFlow() {
    setStage('idle')
    setError('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  if (stage === 'idle' || stage === 'scanning') {
    return (
      <div className="welcome-container">
        <img src={logo} alt="Petticoat Schmitt" className="welcome-logo" />
        <div className="welcome-title">Submittal Extractor</div>
        <div className="welcome-sub">Attach a spec book PDF to pull out every submittal requirement.</div>
        <label className="upload-dropzone">
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            onChange={handleFileChange}
            disabled={stage === 'scanning'}
            hidden
          />
          {stage === 'scanning' ? statusMessage : 'Please attach a spec book PDF  +'}
        </label>
      </div>
    )
  }

  if (stage === 'error') {
    return (
      <div className="panel">
        <p className="error-text">Extraction failed: {error}</p>
        <button className="btn btn-primary" onClick={resetFlow}>Try again</button>
      </div>
    )
  }

  if (stage === 'reviewing_codes') {
    return (
      <div className="panel">
        <h4>Review unusual section codes</h4>
        <p className="muted">Edit any code that should be corrected, then confirm to continue.</p>
        <table className="simple-table">
          <thead>
            <tr><th>Original</th><th>Corrected</th><th>Reason</th><th>Context</th></tr>
          </thead>
          <tbody>
            {irregularCodes.map((c) => (
              <tr key={c.code}>
                <td>{c.code}</td>
                <td>
                  <input
                    defaultValue={c.code}
                    onChange={(e) => setCorrections((prev) => ({ ...prev, [c.code]: e.target.value }))}
                  />
                </td>
                <td className="muted">{c.reason}</td>
                <td className="muted">{c.context}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn btn-primary" onClick={continueFromCodeReview}>Confirm and continue</button>
      </div>
    )
  }

  if (stage === 'confirm' && projectInfo) {
    return (
      <div className="panel">
        <h4>Confirm extracted project details</h4>
        <div className="confirm-card">
          {FIELD_LABELS.map(([key, label]) => (
            <div className="field-row" key={key}>
              <label>{label}</label>
              <input
                value={projectInfo[key] ?? ''}
                onChange={(e) => setProjectInfo({ ...projectInfo, [key]: e.target.value })}
              />
            </div>
          ))}
        </div>
        <button className="btn btn-primary" onClick={handleConfirmExtract}>Confirm and continue</button>
      </div>
    )
  }

  if (stage === 'extracting') {
    const visibleSteps = jobSteps.filter((s) => s !== 'Done')
    return (
      <div className="panel">
        <div className="status-box">
          <div className="status-header">
            <span className="status-spinner" />
            <span>Extracting submittals…</span>
          </div>
          {visibleSteps.length > 0 && (
            <div className="status-steps">
              {visibleSteps.map((step, i) => (
                <div key={i} className="status-step">{step}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  return null
}
