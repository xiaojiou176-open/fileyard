import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ShieldAlert, Undo2 } from 'lucide-react'
import { toast } from 'sonner'
import { useParams } from 'react-router-dom'

import { createRollbackJob, getJob, getRuntimeSettings, type RuntimeSettings } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { Job } from '@/lib/types'
import { LogPanel } from '@/components/observability/log-panel'
import { useLiveJob } from '@/hooks/use-live-job'
import { useI18n } from '@/lib/i18n'

export function RollbackPage() {
  const { t } = useI18n()
  const { jobId = '' } = useParams()
  const [ackRisk, setAckRisk] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [sourceJob, setSourceJob] = useState<Job | null>(null)
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null)
  const [activeRollbackJobId, setActiveRollbackJobId] = useState('')
  const [sourceJobId, setSourceJobId] = useState(jobId)
  const [manifestPath, setManifestPath] = useState('')
  const [allowedRoot, setAllowedRoot] = useState('~/.fileorganize/workspaces/default/data/raw,~/.fileorganize/workspaces/default/data/organized')
  const [strictIntegrity, setStrictIntegrity] = useState(true)
  const [auditReason, setAuditReason] = useState('')
  const [dryRunApproved, setDryRunApproved] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [isLoadingSource, setIsLoadingSource] = useState(true)
  const lastJobSignalRef = useRef('')

  const trackedRollbackId = activeRollbackJobId || jobId
  const { job, events, state, refresh } = useLiveJob(trackedRollbackId, trackedRollbackId.length > 0)
  const defaultAllowedRoot = runtimeSettings?.allowed_root ?? '~/.fileorganize/workspaces/default/data/raw,~/.fileorganize/workspaces/default/data/organized'

  const applyFallbackDefaults = useCallback(() => {
    setSourceJob(null)
    setSourceJobId(jobId)
    setManifestPath('')
    setAllowedRoot(defaultAllowedRoot)
    setStrictIntegrity(true)
    setDryRunApproved(false)
  }, [defaultAllowedRoot, jobId])

  const reloadSourceJob = useCallback(async () => {
    setIsLoadingSource(true)
    try {
      const [next, runtime] = await Promise.all([getJob(jobId), getRuntimeSettings()])
      setRuntimeSettings(runtime)
      setSourceJob(next ?? null)
      setSourceJobId(next?.id ?? jobId)
      setManifestPath(next?.rollback_manifest_path ?? next?.manifest_path ?? '')
      setAllowedRoot(next?.summary?.allowed_root ?? runtime.allowed_root)
      setDryRunApproved(Boolean(next?.summary?.dry_run && next?.status === 'succeeded'))
      setLoadError('')
    } catch (error) {
      applyFallbackDefaults()
      setLoadError(error instanceof Error ? error.message : t('rollback.loadError.fallback'))
    } finally {
      setIsLoadingSource(false)
    }
  }, [applyFallbackDefaults, jobId, t])

  useEffect(() => {
    void reloadSourceJob()
  }, [reloadSourceJob])

  useEffect(() => {
    const status = job?.status ?? ''
    const nextSignal = job?.id ? `${job.id}:${status}` : ''
    if (!status || !nextSignal || nextSignal === lastJobSignalRef.current) {
      return
    }
    lastJobSignalRef.current = nextSignal

    if (status === 'succeeded' && job?.summary?.dry_run) {
      startTransition(() => {
        setSubmitting(false)
        setDryRunApproved(true)
      })
      toast.success(t('rollback.toast.previewCompleted'))
      return
    }

    if (status === 'succeeded' && job?.summary?.dry_run === false) {
      startTransition(() => {
        setSubmitting(false)
      })
      toast.success(t('rollback.toast.completed'))
      return
    }

    if (status === 'failed') {
      startTransition(() => {
        setSubmitting(false)
      })
      toast.error(job?.latest_error ?? t('rollback.toast.failed'))
    }
  }, [job, t])

  async function submitRollback(execute: boolean) {
    setSubmitting(true)
    try {
      const created = await createRollbackJob({
        analyzeJobId: sourceJobId,
        manifestPath,
        execute,
        sourceJobId,
        allowedRoot,
        strictIntegrity,
        auditReason,
      })
      setActiveRollbackJobId(created.id)
      if (!execute) {
        setDryRunApproved(false)
      }
    } catch (error) {
      setSubmitting(false)
      toast.error(error instanceof Error ? error.message : t('rollback.toast.submitFailed'))
    }
  }

  const resolvedJob = useMemo(() => job ?? sourceJob, [job, sourceJob])
  const rollbackReady = Boolean(sourceJobId.trim().length > 0 && manifestPath.trim().length > 0 && allowedRoot.trim().length > 0)
  const isCancelling = resolvedJob?.status === 'cancelling'
  const canExecute = rollbackReady && dryRunApproved && ackRisk && auditReason.trim().length > 0 && !submitting && !isCancelling

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('rollback.page.title')}</CardTitle>
          <CardDescription>{t('rollback.page.description')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-4">
            <MetaCard label={t('rollback.meta.selectedJob')} value={resolvedJob?.id ?? jobId} />
            <MetaCard label={t('rollback.meta.sourceJob')} value={sourceJobId || '-'} />
            <MetaCard label={t('rollback.meta.allowedRoot')} value={allowedRoot || '-'} />
            <MetaCard label={t('rollback.meta.tamperProtection')} value={strictIntegrity ? t('rollback.meta.enabled') : t('rollback.meta.disabled')} />
          </div>
          {isLoadingSource ? <p className="text-sm text-muted-foreground">{t('rollback.loading')}</p> : null}

          {loadError ? (
            <Alert className="border-destructive/30 bg-destructive/10">
              <AlertTitle>{t('rollback.loadError.title')}</AlertTitle>
              <AlertDescription className="space-y-3">
                <p>{loadError}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    disabled={isLoadingSource}
                    onClick={() => {
                      void reloadSourceJob()
                    }}
                    size="sm"
                    variant="outline"
                  >
                    {t('rollback.loadError.retry')}
                  </Button>
                  <Button
                    disabled={isLoadingSource}
                    onClick={() => {
                      applyFallbackDefaults()
                      setLoadError('')
                      toast.info(t('rollback.loadError.restoreInfo'))
                    }}
                    size="sm"
                    variant="secondary"
                  >
                    {t('rollback.loadError.restoreDefaults')}
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}

          {!rollbackReady ? (
            <Alert className="border-destructive/30 bg-destructive/10">
              <AlertTitle className="flex items-center gap-2">
                <ShieldAlert className="h-4 w-4" />
                {t('rollback.alert.locked.title')}
              </AlertTitle>
              <AlertDescription>{t('rollback.alert.locked.description')}</AlertDescription>
            </Alert>
          ) : (
            <Alert className="border-success/30 bg-success/10">
              <AlertTitle>{t('rollback.alert.ready.title')}</AlertTitle>
              <AlertDescription>{t('rollback.alert.ready.description')}</AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="rollback-source-job">
                {t('rollback.field.sourceJob')}
              </label>
              <Input id="rollback-source-job" onChange={(event) => setSourceJobId(event.target.value)} value={sourceJobId} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="rollback-manifest">
                {t('rollback.field.manifest')}
              </label>
              <Input id="rollback-manifest" onChange={(event) => setManifestPath(event.target.value)} value={manifestPath} />
            </div>
            <div className="md:col-span-2">
              <Button onClick={() => setShowAdvanced((prev) => !prev)} type="button" variant="outline">
                {showAdvanced ? t('rollback.field.hideAdvanced') : t('rollback.field.showAdvanced')}
              </Button>
            </div>
            {showAdvanced ? (
              <>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="rollback-allowed-root">
                {t('rollback.field.allowedRoot')}
              </label>
              <Input id="rollback-allowed-root" onChange={(event) => setAllowedRoot(event.target.value)} value={allowedRoot} />
              <p className="text-xs text-muted-foreground">{t('rollback.field.allowedRootHint')}</p>
            </div>
            <label className="flex min-h-11 items-center gap-2 rounded-xl border border-border px-3 py-3 text-sm" htmlFor="rollback-strict-integrity">
              <Checkbox checked={strictIntegrity} id="rollback-strict-integrity" onCheckedChange={setStrictIntegrity} />
              {t('rollback.field.strictIntegrity')}
            </label>
              </>
            ) : null}
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium" htmlFor="rollback-audit-reason">
                {t('rollback.field.auditReason')}
              </label>
              <Textarea
                id="rollback-audit-reason"
                onChange={(event) => setAuditReason(event.target.value)}
                placeholder={t('rollback.field.auditReasonPlaceholder')}
                required
                value={auditReason}
              />
            </div>
          </div>

          <label className="flex min-h-11 items-center gap-2 text-sm" htmlFor="rollback-ack-risk">
            <Checkbox checked={ackRisk} id="rollback-ack-risk" onCheckedChange={setAckRisk} />
            {t('rollback.ack')}
          </label>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              disabled={submitting || !rollbackReady || isCancelling}
              onClick={() => {
                void submitRollback(false)
              }}
              variant="secondary"
            >
              {t('rollback.cta.preview')}
            </Button>
            <Button
              disabled={!canExecute}
              onClick={() => {
                void submitRollback(true)
              }}
              variant="destructive"
            >
              <Undo2 className="mr-2 h-4 w-4" />
              {t('rollback.cta.execute')}
            </Button>
            <Badge variant={dryRunApproved ? 'success' : 'warning'}>{dryRunApproved ? t('rollback.badge.previewApproved') : t('rollback.badge.waitingForPreview')}</Badge>
          </div>

          <LogPanel
            connectionState={state}
            description={t('rollback.logs.description')}
            events={events}
            onRefresh={() => {
              void refresh()
            }}
            title={t('rollback.logs.title')}
          />
        </CardContent>
      </Card>
    </div>
  )
}

function MetaCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="break-all text-sm font-medium">{value || '-'}</p>
    </div>
  )
}
