import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { setStoredApiKey, useApi, type ServerStatus } from '@/hooks/use-api'
import { toast } from 'sonner'
import { KeyRound, LogIn, RefreshCw, Shield } from 'lucide-react'

interface LoginProps {
  onLogin: () => void
}

export default function Login({ onLogin }: LoginProps) {
  const { get } = useApi()
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(false)

  const handleLogin = async () => {
    if (!apiKey.trim()) {
      toast.error('Please enter an API key')
      return
    }

    if (!apiKey.startsWith('llmux-')) {
      toast.error('Invalid API key format. Keys should start with "llmux-"')
      return
    }

    setLoading(true)

    // Temporarily store the key to test it
    setStoredApiKey(apiKey)

    // Try to fetch server status to validate the key
    const { error, status } = await get<ServerStatus>('/server/status')

    if (status === 401) {
      setStoredApiKey(null)
      toast.error('Invalid API key')
      setLoading(false)
      return
    }

    if (error) {
      setStoredApiKey(null)
      toast.error(`Connection failed: ${error}`)
      setLoading(false)
      return
    }

    toast.success('Authenticated successfully')
    onLogin()
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-md animate-fade-in">
        <div className="text-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center mx-auto mb-4">
            <span className="text-primary-foreground font-bold text-2xl">&gt;_</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">LLMux</h1>
          <p className="text-muted-foreground mt-1">Proxy Management Console</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="w-5 h-5" />
              Authentication Required
            </CardTitle>
            <CardDescription>
              Enter your LLMux API key to access the management console.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="api-key">API Key</Label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="api-key"
                  type="password"
                  placeholder="llmux-..."
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="pl-10 font-mono"
                  onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Use an API key created via the CLI: <code className="bg-muted px-1 rounded">python cli.py</code> → API Keys → Create
              </p>
            </div>

            <Button
              onClick={handleLogin}
              disabled={loading}
              className="w-full"
            >
              {loading ? (
                <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <LogIn className="w-4 h-4 mr-2" />
              )}
              Sign In
            </Button>
          </CardContent>
        </Card>

        <p className="text-center text-xs text-muted-foreground mt-6">
          Your API key is stored locally in your browser and sent with each request.
        </p>
      </div>
    </div>
  )
}

