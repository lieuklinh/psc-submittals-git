import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || !email.trim()) {
      setError('Enter both a name and an email to continue.')
      return
    }
    login(name, email)
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={handleSubmit}>
        <h2>Submittal Extractor (dev mode)</h2>
        <input
          type="text"
          placeholder="Your name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          type="email"
          placeholder="Your PSCC email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {error && <div className="form-error">{error}</div>}
        <button type="submit" className="btn btn-primary">Continue</button>
      </form>
    </div>
  )
}
