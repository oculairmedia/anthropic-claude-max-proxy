import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useApi, type APIKey, type CreateKeyResponse, type MessageResponse } from '@/hooks/use-api'
import { toast } from 'sonner'
import { Plus, Trash2, Copy, Check, KeyRound, Edit2, RefreshCw, Clock, Hash } from 'lucide-react'

export default function Keys() {
  const { get, post, patch, del } = useApi()
  const [keys, setKeys] = useState<APIKey[]>([])
  const [loading, setLoading] = useState(true)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [newKeyResult, setNewKeyResult] = useState<CreateKeyResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const [deleteKey, setDeleteKey] = useState<APIKey | null>(null)
  const [editKey, setEditKey] = useState<APIKey | null>(null)
  const [editName, setEditName] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  const fetchKeys = async () => {
    setLoading(true)
    const { data, error } = await get<APIKey[]>('/keys')
    if (data) {
      setKeys(data)
    } else if (error) {
      toast.error('Failed to fetch API keys')
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchKeys()
  }, [])

  const handleCreate = async () => {
    if (!newKeyName.trim()) {
      toast.error('Please enter a name for the key')
      return
    }

    setActionLoading(true)
    const { data, error } = await post<CreateKeyResponse>('/keys', { name: newKeyName })

    if (data) {
      setNewKeyResult(data)
      fetchKeys()
    } else {
      toast.error(error || 'Failed to create API key')
      setCreateDialogOpen(false)
    }
    setActionLoading(false)
  }

  const handleCopy = async () => {
    if (newKeyResult?.key) {
      await navigator.clipboard.writeText(newKeyResult.key)
      setCopied(true)
      toast.success('API key copied to clipboard')
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleCloseCreateDialog = () => {
    setCreateDialogOpen(false)
    setNewKeyName('')
    setNewKeyResult(null)
    setCopied(false)
  }

  const handleDelete = async () => {
    if (!deleteKey) return

    setActionLoading(true)
    const { data, error } = await del<MessageResponse>(`/keys/${deleteKey.id}`)

    if (data?.success) {
      toast.success('API key deleted')
      fetchKeys()
    } else {
      toast.error(error || 'Failed to delete API key')
    }
    setDeleteKey(null)
    setActionLoading(false)
  }

  const handleEdit = async () => {
    if (!editKey || !editName.trim()) return

    setActionLoading(true)
    const { data, error } = await patch<APIKey>(`/keys/${editKey.id}`, { name: editName })

    if (data) {
      toast.success('API key renamed')
      fetchKeys()
    } else {
      toast.error(error || 'Failed to rename API key')
    }
    setEditKey(null)
    setEditName('')
    setActionLoading(false)
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—'
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">API Keys</h2>
          <p className="text-muted-foreground mt-1">Manage authentication keys for the proxy</p>
        </div>
        <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={() => { setNewKeyName(''); setNewKeyResult(null); }}>
              <Plus className="w-4 h-4 mr-2" />
              Create Key
            </Button>
          </DialogTrigger>
          <DialogContent>
            {!newKeyResult ? (
              <>
                <DialogHeader>
                  <DialogTitle>Create API Key</DialogTitle>
                  <DialogDescription>
                    Create a new API key to authenticate requests to the proxy.
                  </DialogDescription>
                </DialogHeader>
                <div className="py-4">
                  <Label htmlFor="name">Key Name</Label>
                  <Input
                    id="name"
                    placeholder="e.g., Development, Production"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    className="mt-2"
                    onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                  />
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={handleCloseCreateDialog}>Cancel</Button>
                  <Button onClick={handleCreate} disabled={actionLoading}>
                    {actionLoading && <RefreshCw className="w-4 h-4 mr-2 animate-spin" />}
                    Create Key
                  </Button>
                </DialogFooter>
              </>
            ) : (
              <>
                <DialogHeader>
                  <DialogTitle>API Key Created</DialogTitle>
                  <DialogDescription>
                    Copy your API key now. You won't be able to see it again!
                  </DialogDescription>
                </DialogHeader>
                <div className="py-4 space-y-4">
                  <div>
                    <Label>Key Name</Label>
                    <p className="text-sm mt-1">{newKeyResult.name}</p>
                  </div>
                  <div>
                    <Label>API Key</Label>
                    <div className="flex gap-2 mt-2">
                      <Input
                        readOnly
                        value={newKeyResult.key}
                        className="font-mono text-sm"
                      />
                      <Button variant="outline" size="icon" onClick={handleCopy}>
                        {copied ? <Check className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">
                      Store this key securely. It will only be shown once.
                    </p>
                  </div>
                </div>
                <DialogFooter>
                  <Button onClick={handleCloseCreateDialog}>Done</Button>
                </DialogFooter>
              </>
            )}
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="w-5 h-5" />
            Your API Keys
          </CardTitle>
          <CardDescription>
            {keys.length} key{keys.length !== 1 ? 's' : ''} configured
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : keys.length === 0 ? (
            <div className="text-center py-8">
              <KeyRound className="w-12 h-12 mx-auto text-muted-foreground/50 mb-4" />
              <p className="text-muted-foreground">No API keys yet</p>
              <p className="text-sm text-muted-foreground mt-1">Create your first key to get started</p>
            </div>
          ) : (
            <div className="space-y-3">
              {keys.map((key) => (
                <div
                  key={key.id}
                  className="flex items-center justify-between p-4 rounded-lg border border-border bg-card hover:bg-muted/30 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className="p-2 rounded-lg bg-primary/10">
                      <KeyRound className="w-4 h-4 text-primary" />
                    </div>
                    <div>
                      <p className="font-medium">{key.name}</p>
                      <p className="text-sm text-muted-foreground font-mono">{key.key_prefix}...</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="text-right text-sm">
                      <div className="flex items-center gap-1.5 text-muted-foreground">
                        <Clock className="w-3.5 h-3.5" />
                        <span>Created {formatDate(key.created_at)}</span>
                      </div>
                      <div className="flex items-center gap-1.5 text-muted-foreground mt-0.5">
                        <Hash className="w-3.5 h-3.5" />
                        <span>{key.usage_count} requests</span>
                      </div>
                    </div>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => { setEditKey(key); setEditName(key.name); }}
                      >
                        <Edit2 className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        onClick={() => setDeleteKey(key)}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Edit Dialog */}
      <Dialog open={!!editKey} onOpenChange={(open) => !open && setEditKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename API Key</DialogTitle>
            <DialogDescription>
              Change the name of this API key.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Label htmlFor="edit-name">Key Name</Label>
            <Input
              id="edit-name"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              className="mt-2"
              onKeyDown={(e) => e.key === 'Enter' && handleEdit()}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditKey(null)}>Cancel</Button>
            <Button onClick={handleEdit} disabled={actionLoading}>
              {actionLoading && <RefreshCw className="w-4 h-4 mr-2 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteKey} onOpenChange={(open) => !open && setDeleteKey(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete API Key</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deleteKey?.name}"? This action cannot be undone.
              Any applications using this key will lose access.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {actionLoading && <RefreshCw className="w-4 h-4 mr-2 animate-spin" />}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
