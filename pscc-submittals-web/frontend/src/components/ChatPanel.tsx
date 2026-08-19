import { useState } from 'react'
import { apiPost } from '../api/client'
import Modal from './Modal'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export default function ChatPanel({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSend() {
    const text = input.trim()
    if (!text) return
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)
    try {
      const res = await apiPost<{ answer: string }>(`/api/projects/${projectId}/chat`, { message: text })
      setMessages((prev) => [...prev, { role: 'assistant', content: res.answer }])
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${e instanceof Error ? e.message : String(e)}` }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title="Chat with the agent" onClose={onClose}>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>{m.content}</div>
          </div>
        ))}
        {loading && <div className="chat-row assistant"><div className="bubble assistant">Searching the spec book…</div></div>}
      </div>
      <div className="chat-input-row">
        <input
          placeholder="Ask the Q&A agent about the spec book…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
        <button className="btn btn-primary" onClick={handleSend} disabled={loading}>Send</button>
      </div>
    </Modal>
  )
}
