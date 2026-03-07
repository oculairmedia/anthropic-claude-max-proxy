import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useApi, type AuthStatus, type AuthLoginResponse, type MessageResponse } from '@/hooks/use-api'
import { toast } from 'sonner'
import { LogIn, LogOut, RefreshCw, Shield, Clock, ExternalLink } from 'lucide-react'

export default function Auth() {
  const { get, post } = useApi()
  const [searchParams, setSearchParams] = useSearchParams()
  const [claudeStatus, setClaudeStatus] = useState<AuthStatus | null>(null)
  const [chatgptStatus, setChatgptStatus] = useState<AuthStatus | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const fetchStatus = async () => {
    const [claude, chatgpt] = await Promise.all([
      get<AuthStatus>('/auth/claude/status'),
      get<AuthStatus>('/auth/chatgpt/status'),
    ])

    if (claude.data) setClaudeStatus(claude.data)
    if (chatgpt.data) setChatgptStatus(chatgpt.data)
  }

  useEffect(() => {
    // Check for OAuth callback results
    const success = searchParams.get('success')
    const error = searchParams.get('error')
    const provider = searchParams.get('provider')
    const longTerm = searchParams.get('long_term')

    if (success === 'true') {
      toast.success(`${provider === 'claude' ? 'Claude' : 'ChatGPT'} authentication successful${longTerm ? ' (long-term token)' : ''}`)
      setSearchParams({})
    } else if (error) {
      toast.error(`Authentication failed: ${error}`)
      setSearchParams({})
    }

    fetchStatus()
  }, [])

  const handleClaudeLogin = async (longTerm: boolean = false) => {
    setActionLoading(longTerm ? 'claude-long-term' : 'claude-login')
    const endpoint = longTerm ? '/auth/claude/login-long-term' : '/auth/claude/login'
    const { data, error } = await get<AuthLoginResponse>(endpoint)

    if (data?.auth_url) {
      window.location.href = data.auth_url
    } else {
      toast.error(error || 'Failed to start login')
      setActionLoading(null)
    }
  }

  const handleClaudeRefresh = async () => {
    setActionLoading('claude-refresh')
    const { data, error } = await post<MessageResponse>('/auth/claude/refresh')

    if (data?.success) {
      toast.success('Tokens refreshed successfully')
      fetchStatus()
    } else {
      toast.error(error || 'Failed to refresh tokens')
    }
    setActionLoading(null)
  }

  const handleClaudeLogout = async () => {
    setActionLoading('claude-logout')
    const { data, error } = await post<MessageResponse>('/auth/claude/logout')

    if (data?.success) {
      toast.success('Logged out successfully')
      fetchStatus()
    } else {
      toast.error(error || 'Failed to logout')
    }
    setActionLoading(null)
  }

  const handleChatgptLogin = async () => {
    setActionLoading('chatgpt-login')
    const { data, error } = await get<AuthLoginResponse>('/auth/chatgpt/login')

    if (data?.auth_url) {
      window.location.href = data.auth_url
    } else {
      toast.error(error || 'Failed to start login')
      setActionLoading(null)
    }
  }

  const handleChatgptRefresh = async () => {
    setActionLoading('chatgpt-refresh')
    const { data, error } = await post<MessageResponse>('/auth/chatgpt/refresh')

    if (data?.success) {
      toast.success('Tokens refreshed successfully')
      fetchStatus()
    } else {
      toast.error(error || 'Failed to refresh tokens')
    }
    setActionLoading(null)
  }

  const handleChatgptLogout = async () => {
    setActionLoading('chatgpt-logout')
    const { data, error } = await post<MessageResponse>('/auth/chatgpt/logout')

    if (data?.success) {
      toast.success('Logged out successfully')
      fetchStatus()
    } else {
      toast.error(error || 'Failed to logout')
    }
    setActionLoading(null)
  }

  const getStatusBadge = (hasTokens: boolean, isExpired: boolean) => {
    if (!hasTokens) {
      return <span className="px-2 py-1 text-xs rounded-full bg-muted text-muted-foreground">Not configured</span>
    }
    if (isExpired) {
      return <span className="px-2 py-1 text-xs rounded-full bg-warning/10 text-warning">Expired</span>
    }
    return <span className="px-2 py-1 text-xs rounded-full bg-success/10 text-success">Active</span>
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Authentication</h2>
        <p className="text-muted-foreground mt-1">Manage OAuth tokens for API providers</p>
      </div>

      <div className="grid gap-6">
        {/* Claude Authentication */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-gradient-to-br from-orange-500/20 to-orange-600/10">
                  <Shield className="w-6 h-6 text-orange-500" />
                </div>
                <div>
                  <CardTitle>Claude (Anthropic)</CardTitle>
                  <CardDescription>OAuth authentication for Claude Pro/Max</CardDescription>
                </div>
              </div>
              {getStatusBadge(claudeStatus?.has_tokens ?? false, claudeStatus?.is_expired ?? true)}
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Status info */}
            <div className="grid grid-cols-3 gap-4 p-4 rounded-lg bg-muted/30">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Token Type</p>
                <p className="font-mono text-sm">{claudeStatus?.token_type || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Expires In</p>
                <p className="font-mono text-sm flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  {claudeStatus?.time_until_expiry || '—'}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Status</p>
                <p className="text-sm">{claudeStatus?.has_tokens ? (claudeStatus?.is_expired ? 'Needs refresh' : 'Valid') : 'Not authenticated'}</p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap gap-3">
              {!claudeStatus?.has_tokens ? (
                <>
                  <Button onClick={() => handleClaudeLogin(false)} disabled={!!actionLoading}>
                    {actionLoading === 'claude-login' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <LogIn className="w-4 h-4 mr-2" />}
                    Login with Claude
                    <ExternalLink className="w-3.5 h-3.5 ml-2 opacity-50" />
                  </Button>
                  <Button variant="outline" onClick={() => handleClaudeLogin(true)} disabled={!!actionLoading}>
                    {actionLoading === 'claude-long-term' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <LogIn className="w-4 h-4 mr-2" />}
                    Setup Long-Term Token
                    <ExternalLink className="w-3.5 h-3.5 ml-2 opacity-50" />
                  </Button>
                </>
              ) : (
                <>
                  {claudeStatus?.token_type !== 'long_term' && (
                    <Button variant="outline" onClick={handleClaudeRefresh} disabled={!!actionLoading}>
                      {actionLoading === 'claude-refresh' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                      Refresh Token
                    </Button>
                  )}
                  <Button variant="outline" onClick={() => handleClaudeLogin(false)} disabled={!!actionLoading}>
                    {actionLoading === 'claude-login' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <LogIn className="w-4 h-4 mr-2" />}
                    Re-authenticate
                    <ExternalLink className="w-3.5 h-3.5 ml-2 opacity-50" />
                  </Button>
                  <Button variant="destructive" onClick={handleClaudeLogout} disabled={!!actionLoading}>
                    {actionLoading === 'claude-logout' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <LogOut className="w-4 h-4 mr-2" />}
                    Logout
                  </Button>
                </>
              )}
            </div>
          </CardContent>
        </Card>

        {/* ChatGPT Authentication */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-gradient-to-br from-green-500/20 to-green-600/10">
                  <Shield className="w-6 h-6 text-green-500" />
                </div>
                <div>
                  <CardTitle>ChatGPT (OpenAI)</CardTitle>
                  <CardDescription>OAuth authentication for ChatGPT Plus/Pro</CardDescription>
                </div>
              </div>
              {getStatusBadge(chatgptStatus?.has_tokens ?? false, chatgptStatus?.is_expired ?? true)}
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Status info */}
            <div className="grid grid-cols-3 gap-4 p-4 rounded-lg bg-muted/30">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Account ID</p>
                <p className="font-mono text-sm truncate">{chatgptStatus?.account_id || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Expires In</p>
                <p className="font-mono text-sm flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  {chatgptStatus?.time_until_expiry || '—'}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Status</p>
                <p className="text-sm">{chatgptStatus?.has_tokens ? (chatgptStatus?.is_expired ? 'Needs refresh' : 'Valid') : 'Not authenticated'}</p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap gap-3">
              {!chatgptStatus?.has_tokens ? (
                <Button onClick={handleChatgptLogin} disabled={!!actionLoading}>
                  {actionLoading === 'chatgpt-login' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <LogIn className="w-4 h-4 mr-2" />}
                  Login with ChatGPT
                  <ExternalLink className="w-3.5 h-3.5 ml-2 opacity-50" />
                </Button>
              ) : (
                <>
                  <Button variant="outline" onClick={handleChatgptRefresh} disabled={!!actionLoading}>
                    {actionLoading === 'chatgpt-refresh' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                    Refresh Token
                  </Button>
                  <Button variant="outline" onClick={handleChatgptLogin} disabled={!!actionLoading}>
                    {actionLoading === 'chatgpt-login' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <LogIn className="w-4 h-4 mr-2" />}
                    Re-authenticate
                    <ExternalLink className="w-3.5 h-3.5 ml-2 opacity-50" />
                  </Button>
                  <Button variant="destructive" onClick={handleChatgptLogout} disabled={!!actionLoading}>
                    {actionLoading === 'chatgpt-logout' ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <LogOut className="w-4 h-4 mr-2" />}
                    Logout
                  </Button>
                </>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
