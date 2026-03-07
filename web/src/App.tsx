import { useState, useEffect } from 'react'
import { Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { Button } from '@/components/ui/button'
import Dashboard from '@/pages/Dashboard'
import Auth from '@/pages/Auth'
import Keys from '@/pages/Keys'
import Login from '@/pages/Login'
import { hasStoredApiKey, setStoredApiKey, useApi, type ServerStatus } from '@/hooks/use-api'
import { Server, KeyRound, Shield, LogOut } from 'lucide-react'
import { toast } from 'sonner'

function App() {
  const { get } = useApi()
  const navigate = useNavigate()
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)

  // Check authentication on mount
  useEffect(() => {
    const checkAuth = async () => {
      if (!hasStoredApiKey()) {
        setIsAuthenticated(false)
        return
      }

      // Validate stored key
      const { status } = await get<ServerStatus>('/server/status')
      if (status === 401) {
        setStoredApiKey(null)
        setIsAuthenticated(false)
      } else {
        setIsAuthenticated(true)
      }
    }

    checkAuth()
  }, [])

  const handleLogin = () => {
    setIsAuthenticated(true)
    navigate('/')
  }

  const handleLogout = () => {
    setStoredApiKey(null)
    setIsAuthenticated(false)
    toast.success('Logged out')
  }

  // Show nothing while checking auth
  if (isAuthenticated === null) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  // Show login if not authenticated
  if (!isAuthenticated) {
    return (
      <>
        <Login onLogin={handleLogin} />
        <Toaster richColors position="bottom-right" />
      </>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center">
                <span className="text-primary-foreground font-bold text-lg">&gt;_</span>
              </div>
              <div>
                <h1 className="text-xl font-semibold tracking-tight">LLMux</h1>
                <p className="text-xs text-muted-foreground">Proxy Management</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <nav className="flex items-center gap-1">
                <NavLink
                  to="/"
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                    }`
                  }
                >
                  <Server className="w-4 h-4" />
                  Dashboard
                </NavLink>
                <NavLink
                  to="/auth"
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                    }`
                  }
                >
                  <Shield className="w-4 h-4" />
                  Authentication
                </NavLink>
                <NavLink
                  to="/keys"
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                    }`
                  }
                >
                  <KeyRound className="w-4 h-4" />
                  API Keys
                </NavLink>
              </nav>

              <div className="h-6 w-px bg-border" />

              <Button variant="ghost" size="sm" onClick={handleLogout}>
                <LogOut className="w-4 h-4 mr-2" />
                Logout
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="container mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/auth" element={<Auth />} />
          <Route path="/keys" element={<Keys />} />
        </Routes>
      </main>

      <Toaster richColors position="bottom-right" />
    </div>
  )
}

export default App
