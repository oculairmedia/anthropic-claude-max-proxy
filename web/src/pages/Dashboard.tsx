import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useApi, type ServerStatus, type AuthStatus } from '@/hooks/use-api'
import { toast } from 'sonner'
import { Activity, Clock, Globe, Shield, Zap, RefreshCw } from 'lucide-react'

export default function Dashboard() {
  const { get } = useApi()
  const [serverStatus, setServerStatus] = useState<ServerStatus | null>(null)
  const [claudeStatus, setClaudeStatus] = useState<AuthStatus | null>(null)
  const [chatgptStatus, setChatgptStatus] = useState<AuthStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchStatus = async () => {
    setLoading(true)
    const [server, claude, chatgpt] = await Promise.all([
      get<ServerStatus>('/server/status'),
      get<AuthStatus>('/auth/claude/status'),
      get<AuthStatus>('/auth/chatgpt/status'),
    ])

    if (server.data) setServerStatus(server.data)
    if (claude.data) setClaudeStatus(claude.data)
    if (chatgpt.data) setChatgptStatus(chatgpt.data)

    if (server.error || claude.error || chatgpt.error) {
      toast.error('Failed to fetch status')
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchStatus()
    // Refresh every 30 seconds
    const interval = setInterval(fetchStatus, 30000)
    return () => clearInterval(interval)
  }, [])

  const getStatusColor = (hasTokens: boolean, isExpired: boolean) => {
    if (!hasTokens) return 'bg-muted'
    if (isExpired) return 'bg-warning'
    return 'bg-success'
  }

  const getStatusText = (hasTokens: boolean, isExpired: boolean) => {
    if (!hasTokens) return 'Not configured'
    if (isExpired) return 'Expired'
    return 'Active'
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
          <p className="text-muted-foreground mt-1">Monitor your proxy server status</p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchStatus} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Server Status Card */}
      <Card className="border-primary/20">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10">
                <Activity className="w-5 h-5 text-primary" />
              </div>
              <div>
                <CardTitle>Server Status</CardTitle>
                <CardDescription>LLMux proxy server</CardDescription>
              </div>
            </div>
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${serverStatus?.running ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}`}>
              <span className={`w-2 h-2 rounded-full ${serverStatus?.running ? 'bg-success animate-pulse' : 'bg-destructive'}`} />
              <span className="text-sm font-medium">{serverStatus?.running ? 'Running' : 'Stopped'}</span>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-6">
            <div className="flex items-center gap-3">
              <Globe className="w-4 h-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Bind Address</p>
                <p className="font-mono text-sm">{serverStatus?.bind_address || '—'}:{serverStatus?.port || '—'}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Clock className="w-4 h-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Uptime</p>
                <p className="font-mono text-sm">{serverStatus?.uptime_formatted || '—'}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Zap className="w-4 h-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Status</p>
                <p className="text-sm font-medium">{serverStatus?.running ? 'Healthy' : 'Offline'}</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Auth Status Cards */}
      <div className="grid grid-cols-2 gap-6">
        {/* Claude Status */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-orange-500/10">
                  <Shield className="w-5 h-5 text-orange-500" />
                </div>
                <div>
                  <CardTitle className="text-base">Claude</CardTitle>
                  <CardDescription>Anthropic API</CardDescription>
                </div>
              </div>
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${getStatusColor(claudeStatus?.has_tokens ?? false, claudeStatus?.is_expired ?? true)}/10`}>
                <span className={`w-2 h-2 rounded-full ${getStatusColor(claudeStatus?.has_tokens ?? false, claudeStatus?.is_expired ?? true)}`} />
                <span className="text-sm font-medium">{getStatusText(claudeStatus?.has_tokens ?? false, claudeStatus?.is_expired ?? true)}</span>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Token Type</span>
                <span className="font-mono">{claudeStatus?.token_type || '—'}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Expires</span>
                <span className="font-mono">{claudeStatus?.time_until_expiry || '—'}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ChatGPT Status */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-green-500/10">
                  <Shield className="w-5 h-5 text-green-500" />
                </div>
                <div>
                  <CardTitle className="text-base">ChatGPT</CardTitle>
                  <CardDescription>OpenAI API</CardDescription>
                </div>
              </div>
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${getStatusColor(chatgptStatus?.has_tokens ?? false, chatgptStatus?.is_expired ?? true)}/10`}>
                <span className={`w-2 h-2 rounded-full ${getStatusColor(chatgptStatus?.has_tokens ?? false, chatgptStatus?.is_expired ?? true)}`} />
                <span className="text-sm font-medium">{getStatusText(chatgptStatus?.has_tokens ?? false, chatgptStatus?.is_expired ?? true)}</span>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Account ID</span>
                <span className="font-mono truncate max-w-[150px]">{chatgptStatus?.account_id || '—'}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Expires</span>
                <span className="font-mono">{chatgptStatus?.time_until_expiry || '—'}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
