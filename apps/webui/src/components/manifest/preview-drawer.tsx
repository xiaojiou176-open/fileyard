import { FileAudio2, FileImage, FileText, Music4 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { PanelSkeleton, Skeleton } from '@/components/ui/skeleton'
import { getManifestPreview } from '@/lib/api'
import type { ManifestRow, PreviewPayload } from '@/lib/types'
import { cn } from '@/lib/utils'

interface PreviewDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  jobId: string
  row: ManifestRow | null
  editedRow?: ManifestRow | null
}

const PREVIEW_CACHE_SESSION_KEY = 'fileman.preview-cache.v1'
const PREVIEW_RETRY_BACKOFF_MS = 220
const MEDIA_FINGERPRINT_FIELDS = [
  'sha1',
  'hash8',
  'blake3',
  'md5',
  'etag',
  'size',
  'size_bytes',
  'file_size',
  'mtime',
  'file_mtime',
  'modified_at',
  'updated_at',
  'duration_s',
  'pages',
  'width',
  'height',
  'mime',
] as const
const previewMemoryCache = new Map<string, PreviewPayload>()
let cacheHydrated = false

function hydratePreviewCache() {
  if (cacheHydrated || typeof window === 'undefined') {
    cacheHydrated = true
    return
  }
  cacheHydrated = true
  const raw = window.sessionStorage.getItem(PREVIEW_CACHE_SESSION_KEY)
  if (!raw) {
    return
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, PreviewPayload>
    for (const [key, payload] of Object.entries(parsed)) {
      previewMemoryCache.set(key, payload)
    }
  } catch {
    window.sessionStorage.removeItem(PREVIEW_CACHE_SESSION_KEY)
  }
}

function persistPreviewCache() {
  if (typeof window === 'undefined') {
    return
  }
  const entries = Array.from(previewMemoryCache.entries()).slice(-80)
  const payload = Object.fromEntries(entries)
  window.sessionStorage.setItem(PREVIEW_CACHE_SESSION_KEY, JSON.stringify(payload))
}

function getCachedPreview(cacheKey: string): PreviewPayload | null {
  hydratePreviewCache()
  return previewMemoryCache.get(cacheKey) ?? null
}

function setCachedPreview(cacheKey: string, payload: PreviewPayload) {
  previewMemoryCache.set(cacheKey, payload)
  persistPreviewCache()
}

function normalizeFingerprintToken(value: string | number | undefined): string {
  if (value === undefined) {
    return ''
  }
  return String(value).trim()
}

function safeCacheSegment(value: string): string {
  return encodeURIComponent(value.trim().toLowerCase().replace(/\s+/g, ' ')).slice(0, 180)
}

function buildPreviewCacheKey(jobId: string, row: ManifestRow, preview?: PreviewPayload): string {
  const metadata = row.metadata
  const fingerprint = [
    ...MEDIA_FINGERPRINT_FIELDS.map((field) => normalizeFingerprintToken(metadata[field])),
    normalizeFingerprintToken(row.media_type),
    normalizeFingerprintToken(row.file_name),
    normalizeFingerprintToken(preview?.mime),
    normalizeFingerprintToken(preview?.duration_s),
    normalizeFingerprintToken(preview?.pages),
    normalizeFingerprintToken(preview?.thumbnail_url),
  ]
    .filter((item) => item.length > 0)
  const uniqueFingerprint = [...new Set(fingerprint)].slice(0, 8)
  const normalizedFingerprint = uniqueFingerprint.join('|') || 'fingerprint-missing'

  return [`job:${safeCacheSegment(jobId)}`, `row:${safeCacheSegment(row.id)}`, `fp:${safeCacheSegment(normalizedFingerprint)}`].join('|')
}

function mediaFallback(mediaType: string, row: ManifestRow): { title: string; detail: string } {
  if (mediaType === 'audio') {
    return {
      title: 'Audio preview unavailable',
      detail: `Review the transcript summary and duration instead: ${row.metadata.duration_s ?? '-'} seconds`,
    }
  }
  if (mediaType === 'pdf') {
    return {
      title: 'PDF thumbnail unavailable',
      detail: `Pages: ${row.metadata.pages ?? '-'}; the backend can generate a first-page thumbnail when available.`,
    }
  }
  if (mediaType === 'doc' || mediaType === 'docx' || mediaType === 'ppt' || mediaType === 'pptx') {
    return {
      title: 'Document preview unavailable',
      detail: 'Run document conversion first before expecting a visual preview.',
    }
  }
  return {
    title: 'Image thumbnail unavailable',
    detail: 'The backend did not return a thumbnail_url, so the drawer fell back to metadata summary.',
  }
}

function RowDiff({ label, original, edited }: { label: string; original: string; edited: string }) {
  const changed = original !== edited
  return (
    <div className="rounded-lg border border-border p-2 text-xs">
      <p className="mb-1 text-muted-foreground">{label}</p>
      <p className={changed ? 'line-through opacity-70' : ''}>{original || '-'}</p>
      {changed ? <p className="mt-1 font-medium text-success">{edited || '-'}</p> : null}
    </div>
  )
}

function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export function PreviewDrawer({ open, onOpenChange, jobId, row, editedRow }: PreviewDrawerProps) {
  const [preview, setPreview] = useState<PreviewPayload | null>(null)
  const [loadedImageUrl, setLoadedImageUrl] = useState('')
  const [activeCacheKey, setActiveCacheKey] = useState('')
  const [loadingState, setLoadingState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState('')
  const [retryNonce, setRetryNonce] = useState(0)

  useEffect(() => {
    let alive = true
    const abortController = new AbortController()

    const syncPreview = async () => {
      if (!open || !row?.id) {
        if (!alive) {
          return
        }
        setLoadingState('idle')
        setErrorMessage('')
        setActiveCacheKey('')
        return
      }

      const cacheKey = buildPreviewCacheKey(jobId, row)
      if (!alive) {
        return
      }
      setActiveCacheKey(cacheKey)
      // Clear the previous preview first so row switches never flash stale content.
      setPreview(null)
      setLoadedImageUrl('')
      setErrorMessage('')
      setLoadingState('loading')

      const cached = getCachedPreview(cacheKey)
      if (cached) {
        setPreview({ ...cached, row_id: row.id })
        setLoadingState('ready')
        return
      }

      let lastErrorMessage = ''
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const next = await getManifestPreview(jobId, row.id, { signal: abortController.signal, throwOnError: true })
          if (!alive || abortController.signal.aborted) {
            return
          }
          if (!next) {
            throw new Error('Preview API returned an empty response')
          }

          const normalized = { ...next, row_id: row.id }
          const strictKey = buildPreviewCacheKey(jobId, row, normalized)
          setCachedPreview(cacheKey, normalized)
          if (strictKey !== cacheKey) {
            setCachedPreview(strictKey, normalized)
          }
          setPreview(normalized)
          setLoadingState('ready')
          return
        } catch (error) {
          if (!alive || abortController.signal.aborted) {
            return
          }
          lastErrorMessage = error instanceof Error ? error.message : 'Preview request failed'
          if (attempt === 0) {
            await wait(PREVIEW_RETRY_BACKOFF_MS)
            continue
          }
          setPreview({ row_id: row.id, media_type: row.media_type })
          setLoadingState('error')
          setErrorMessage(`Preview failed to load after 1 automatic retry.${lastErrorMessage ? ` Reason: ${lastErrorMessage}` : ''}`)
          return
        }
      }
    }

    void syncPreview()

    return () => {
      alive = false
      abortController.abort()
    }
  }, [jobId, open, retryNonce, row])

  const activePreview = row && preview?.row_id === row.id ? preview : null
  const loadingPreview = open && Boolean(row?.id) && (loadingState === 'loading' || preview?.row_id !== row?.id)
  const imageReady = Boolean(activePreview?.thumbnail_url) && loadedImageUrl === activePreview?.thumbnail_url

  const fallback = useMemo(() => {
    if (!row) {
      return { title: '', detail: '' }
    }
    return mediaFallback(row.media_type, row)
  }, [row])

  return (
    <Sheet onOpenChange={onOpenChange} open={open}>
      <SheetContent className="motion-surface w-[min(96vw,520px)]">
        {row ? (
          <>
            <SheetHeader className="motion-surface">
              <SheetTitle className="truncate">{row.file_name}</SheetTitle>
              <SheetDescription>{row.original_path}</SheetDescription>
            </SheetHeader>

            <div className="space-y-4 text-sm">
              <div className="overflow-hidden rounded-xl border border-border bg-muted/30">
                {loadingPreview ? (
                  <div className="space-y-3 p-4">
                    <Skeleton className="aspect-[4/3] w-full rounded-xl" />
                    <PanelSkeleton className="border-none bg-transparent p-0" lines={2} />
                  </div>
                ) : activePreview?.thumbnail_url ? (
                  <div className="relative aspect-[4/3] w-full">
                    {!imageReady ? <Skeleton className="absolute inset-0 rounded-none" /> : null}
                    <img
                      alt={row.file_name}
                      className={cn('h-full w-full object-cover transition-opacity duration-300', imageReady ? 'opacity-100' : 'opacity-0')}
                      onError={() => {
                        setLoadedImageUrl('')
                        setErrorMessage('Thumbnail failed to load. Retry the preview.')
                        setLoadingState('error')
                      }}
                      onLoad={() => {
                        setLoadedImageUrl(activePreview.thumbnail_url ?? '')
                      }}
                      src={activePreview.thumbnail_url}
                    />
                  </div>
                ) : (
                  <div className="grid aspect-[4/3] place-items-center bg-[linear-gradient(135deg,hsl(var(--accent)/0.35),hsl(var(--muted)))] text-center">
                    {row.media_type === 'audio' ? <Music4 className="mb-2 h-10 w-10 text-muted-foreground" /> : null}
                    {(row.media_type === 'pdf' || row.media_type === 'doc' || row.media_type === 'docx' || row.media_type === 'ppt' || row.media_type === 'pptx') ? (
                      <FileText className="mb-2 h-10 w-10 text-muted-foreground" />
                    ) : null}
                    {row.media_type === 'image' ? <FileImage className="mb-2 h-10 w-10 text-muted-foreground" /> : null}
                    {row.media_type !== 'audio' && row.media_type !== 'image' && row.media_type !== 'pdf' && row.media_type !== 'doc' && row.media_type !== 'docx' && row.media_type !== 'ppt' && row.media_type !== 'pptx' ? (
                      <FileAudio2 className="mb-2 h-10 w-10 text-muted-foreground" />
                    ) : null}
                    <p className="text-sm font-medium">{fallback.title}</p>
                    <p className="mt-1 max-w-[26ch] text-xs text-muted-foreground">{fallback.detail}</p>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">{row.media_type}</Badge>
                <Badge variant={row.status === 'error' ? 'destructive' : row.status === 'duplicate' ? 'warning' : 'success'}>{row.status}</Badge>
                <Badge variant="secondary">Confidence {Math.round(row.confidence * 100)}%</Badge>
              </div>

              {errorMessage ? (
                <div className="motion-surface rounded-xl border border-warning/40 bg-warning/10 p-3 text-xs text-warning-ink">
                  <p>{errorMessage}</p>
                  <div className="mt-2">
                    <Button
                      onClick={() => {
                        setRetryNonce((prev) => prev + 1)
                      }}
                      size="sm"
                      variant="outline"
                    >
                      Retry Preview
                    </Button>
                  </div>
                </div>
              ) : null}

              <div className="motion-surface rounded-xl border border-border p-3">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">Preview Summary</p>
                  {activeCacheKey ? <p className="max-w-[180px] truncate text-[10px] text-muted-foreground">cache: {activeCacheKey}</p> : null}
                </div>
                {loadingPreview ? (
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-[92%]" />
                    <Skeleton className="h-4 w-[70%]" />
                  </div>
                ) : (
                  <p>{activePreview?.summary || row.notes || 'No summary available yet.'}</p>
                )}
              </div>

              {editedRow ? (
                <div className="motion-surface space-y-2">
                  <p className="text-xs text-muted-foreground">Original vs Edited</p>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <RowDiff edited={editedRow.category} label="Category" original={row.category} />
                    <RowDiff edited={editedRow.title} label="Title" original={row.title} />
                    <RowDiff edited={editedRow.tags.join(', ')} label="Tags" original={row.tags.join(', ')} />
                    <RowDiff edited={editedRow.target_suggestion} label="Target Suggestion" original={row.target_suggestion} />
                    <RowDiff edited={editedRow.ignore ? 'true' : 'false'} label="Ignore Flag" original={row.ignore ? 'true' : 'false'} />
                    <RowDiff edited={editedRow.notes} label="Notes" original={row.notes} />
                  </div>
                </div>
              ) : null}

              <div>
                <p className="mb-2 text-xs text-muted-foreground">Metadata</p>
                <div className="motion-surface grid grid-cols-1 gap-2 rounded-xl border border-border p-3 text-xs sm:grid-cols-2">
                  {Object.entries(row.metadata).map(([key, value]) => (
                    <div key={key}>
                      <p className="text-muted-foreground">{key}</p>
                      <p className="font-medium">{value}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
