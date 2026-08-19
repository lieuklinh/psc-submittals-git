import { createContext, useContext, useState, type ReactNode } from 'react'

interface AuthUser {
  email: string
  name: string
}

interface AuthContextValue {
  user: AuthUser | null
  login: (name: string, email: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

// DEV-MODE AUTH — mirrors the Streamlit app's current sign-in (manual
// name/email entry, no password, no verification). Swapping this for
// real Microsoft Entra ID / Azure AD is tracked in the README; this is
// not a new gap introduced by the React port.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => {
    const email = localStorage.getItem('user_email')
    const name = localStorage.getItem('user_name')
    return email && name ? { email, name } : null
  })

  function login(name: string, email: string) {
    const cleanEmail = email.trim().toLowerCase()
    const cleanName = name.trim()
    localStorage.setItem('user_email', cleanEmail)
    localStorage.setItem('user_name', cleanName)
    setUser({ email: cleanEmail, name: cleanName })
  }

  function logout() {
    localStorage.removeItem('user_email')
    localStorage.removeItem('user_name')
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
