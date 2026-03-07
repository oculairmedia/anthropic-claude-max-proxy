import { useState, useCallback } from 'react'

const API_BASE = '/api/management'

// Get stored API key from localStorage
export function getStoredApiKey(): string | null {
  return localStorage.getItem('llmux_api_key')
}

// Store API key in localStorage
export function setStoredApiKey(key: string | null) {
  if (key) {
    localStorage.setItem('llmux_api_key', key)
  } else {
    localStorage.removeItem('llmux_api_key')
  }
}

// Check if API key is stored
export function hasStoredApiKey(): boolean {
  return !!getStoredApiKey()
}

export function useApi() {
  const [loading, setLoading] = useState(false)

  const request = useCallback(async <T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<{ data: T | null; error: string | null; status?: number }> => {
    setLoading(true)
    const apiKey = getStoredApiKey()

    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> || {}),
      }

      // Add API key header if available
      if (apiKey) {
        headers['X-API-Key'] = apiKey
      }

      const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        return {
          data: null,
          error: errorData.detail || errorData.error?.message || `HTTP ${response.status}`,
          status: response.status
        }
      }

      const data = await response.json()
      return { data, error: null, status: response.status }
    } catch (err) {
      return { data: null, error: err instanceof Error ? err.message : 'Unknown error' }
    } finally {
      setLoading(false)
    }
  }, [])

  const get = useCallback(<T>(endpoint: string) =>
    request<T>(endpoint, { method: 'GET' }), [request])

  const post = useCallback(<T>(endpoint: string, body?: unknown) =>
    request<T>(endpoint, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined
    }), [request])

  const patch = useCallback(<T>(endpoint: string, body?: unknown) =>
    request<T>(endpoint, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined
    }), [request])

  const del = useCallback(<T>(endpoint: string) =>
    request<T>(endpoint, { method: 'DELETE' }), [request])

  return { get, post, patch, del, loading }
}

// Type definitions for API responses
export interface ServerStatus {
  running: boolean
  bind_address: string
  port: number
  uptime_seconds: number | null
  uptime_formatted: string | null
}

export interface AuthStatus {
  has_tokens: boolean
  is_expired: boolean
  expires_at: string | null
  time_until_expiry: string | null
  token_type: string | null
  account_id: string | null
}

export interface AuthLoginResponse {
  auth_url: string
  state: string
}

export interface APIKey {
  id: string
  name: string
  key_prefix: string
  created_at: string
  last_used_at: string | null
  usage_count: number
}

export interface CreateKeyResponse {
  id: string
  name: string
  key: string
  key_prefix: string
  created_at: string
}

export interface MessageResponse {
  message: string
  success: boolean
}
