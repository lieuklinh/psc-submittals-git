import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Login from './pages/Login'
import Home from './pages/Home'
import ProjectPage from './pages/ProjectPage'

function Shell() {
  const { user } = useAuth()
  if (!user) return <Login />

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-area">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/project/:id" element={<ProjectPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </AuthProvider>
  )
}
