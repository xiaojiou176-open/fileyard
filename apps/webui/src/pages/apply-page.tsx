import { startTransition, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ShieldCheck, TriangleAlert } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { createApplyJob, getJob } from '@/lib/api'
import type { Job } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { LogPanel } from '@/components/observability/log-panel'
import { useLiveJob } from '@/hooks/use-live-job'
import { useI18n } from '@/lib/i18n'
import { progressToPercent } from '@/lib/utils'
import { createRouteIntentPrefetchHandlers, preloadRoute } from '@/routes/lazy-routes'

export function ApplyPage() {
  const { t } = useI18n()
  const { jobId = '' } = useParams()
  const [sourceJob, setSourceJob] = useState<Job | null>(null)
  const [activeJobId, setActiveJobId] = useState('')
  const [dryRunReady, setDryRunReady] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const lastJobSignalRef = useRef('')

  const trackedJobId = activeJobId || jobId
  const { job, events, state, refresh } = useLiveJob(trackedJobId, trackedJobId.length > 0)

  useEffect(() => {
    let mounted = true
    void (async () => {
      const next = await getJob(jobId)
      if (!mounted) {
        return
      }
      setSourceJob(next ?? null)
      setDryRunReady(Boolean(next?.summary?.dry_run && next?.status === 'succeeded'))
    })()

    return () => {
      mounted = false
    }
  }, [jobId])

  useEffect(() => {
    const status = job?.status ?? ''
    const nextSignal = job?.id ? `${job.id}:${status}` : ''
    if (!status || !nextSignal || nextSignal === lastJobSignalRef.current) {
      return
    }
    lastJobSignalRef.current = nextSignal

    if (status === 'succeeded' && job?.summary?.dry_run) {
      startTransition(() => {
        setDryRunReady(true)
        setSubmitting(false)
      })
      toast.success(t('apply.toast.dryRunCompleted'))
      return
    }

    if (status === 'succeeded' && job?.summary?.dry_run === false) {
      startTransition(() => {
        setSubmitting(false)
      })
      toast.success(t('apply.toast.applyCompleted'))
      return
    }

    if (status === 'failed') {
      startTransition(() => {
        setSubmitting(false)
      })
      toast.error(job?.latest_error ?? t('apply.toast.failed'))
    }
  }, [job, t])

  async function submitApply(execute: boolean) {
    setSubmitting(true)
    try {
      const created = await createApplyJob({
        analyzeJobId: sourceJob?.kind === 'analyze' ? sourceJob.id : undefined,
        manifestPath: sourceJob?.kind === 'analyze' ? undefined : sourceJob?.manifest_path,
        execute,
      })
      setActiveJobId(created.id)
    } catch (error) {
      setSubmitting(false)
      toast.error(error instanceof Error ? error.message : t('apply.toast.submitFailed'))
    }
  }

  const current = useMemo(() => job ?? sourceJob, [job, sourceJob])
  const progress = progressToPercent(current?.progress ?? 0)
  const outputRoot = current?.summary?.output_root ?? '~/.fileyard/workspaces/default/data/organized'
  const strictReady = current?.strict_integrity_ready ?? true
  const isCancelling = current?.status === 'cancelling'
  const reviewPrefetch = createRouteIntentPrefetchHandlers('review')
  const conflictsPrefetch = createRouteIntentPrefetchHandlers('conflicts')
  const dryRunPrefetch = createRouteIntentPrefetchHandlers('report', 'rollback', 'conflicts')
  const executePrefetch = createRouteIntentPrefetchHandlers('report', 'rollback')

  useEffect(() => {
    if (dryRunReady) {
      void preloadRoute('report')
      void preloadRoute('rollback')
    }
  }, [dryRunReady])

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('apply.page.title')}</CardTitle>
          <CardDescription>{t('apply.page.description')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <StatCard label={t('apply.stats.outputRoot')} value={outputRoot} />
            <StatCard label={t('apply.stats.totalReady')} value={String(current?.summary?.total ?? 0)} />
            <StatCard label={t('apply.stats.needsAttention')} tone="warning" value={String(current?.summary?.with_error ?? 0)} />
            <StatCard label={t('apply.stats.rollbackReady')} tone="success" value={strictReady ? t('apply.stats.ready') : t('apply.stats.partial')} />
          </div>

          <Alert className="border-warning/30 bg-warning/10">
            <AlertTitle className="flex items-center gap-2">
              <TriangleAlert className="h-4 w-4" />
              {t('apply.alert.dryRunTitle')}
            </AlertTitle>
            <AlertDescription>{t('apply.alert.dryRunDescription')}</AlertDescription>
          </Alert>

          <div className="space-y-2">
            <p className="text-sm font-medium">{t('apply.progress.label')}</p>
            <Progress aria-label={t('apply.progress.label')} value={progress} />
            <p className="text-xs text-muted-foreground">
              {current ? `${current.phase} | ${progress}%` : t('apply.progress.waiting')} | {state === 'open' ? t('apply.progress.sseConnected') : t('apply.progress.sseFallback')}
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button asChild variant="outline">
              <Link {...reviewPrefetch} to={`/review/${sourceJob?.id ?? jobId}`}>
                {t('apply.cta.backReview')}
              </Link>
            </Button>

            <Button {...dryRunPrefetch} disabled={submitting || isCancelling} onClick={() => void submitApply(false)} variant="secondary">
              {t('apply.cta.preview')}
            </Button>

            <Dialog>
              <DialogTrigger asChild>
                <Button {...executePrefetch} disabled={!dryRunReady || submitting || isCancelling}>
                  <AlertTriangle className="mr-2 h-4 w-4" />
                  {t('apply.cta.organizeNow')}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t('apply.dialog.title')}</DialogTitle>
                  <DialogDescription>{t('apply.dialog.description')}</DialogDescription>
                </DialogHeader>
                <div className="space-y-3 text-sm text-muted-foreground">
                  <p>{t('apply.dialog.resolveConflicts')}</p>
                  <div className="flex gap-2">
                    <Badge variant="outline">{t('apply.dialog.previewChecked')}</Badge>
                    <Badge variant="outline">{t('apply.dialog.verifySha1')}</Badge>
                  </div>
                </div>
                <div className="mt-4 flex justify-between gap-2">
                  <Button asChild size="sm" variant="outline">
                    <Link {...conflictsPrefetch} to={`/conflicts/${sourceJob?.id ?? jobId}`}>
                      {t('apply.dialog.openConflicts')}
                    </Link>
                  </Button>
                  <Button {...executePrefetch} disabled={submitting || isCancelling} onClick={() => void submitApply(true)} size="sm" variant="destructive">
                    {t('apply.dialog.start')}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </div>

          <LogPanel
            connectionState={state}
            description={t('apply.logs.description')}
            events={events}
            onRefresh={() => {
              void refresh()
            }}
            title={t('apply.logs.title')}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('apply.guardrails.title')}</CardTitle>
          <CardDescription>{t('apply.guardrails.description')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <GuardItem title={t('apply.guardrails.item.dryRunFirst')} />
          <GuardItem title={t('apply.guardrails.item.allowedRoot')} />
          <GuardItem title={t('apply.guardrails.item.conflicts')} />
          <GuardItem title={t('apply.guardrails.item.errorCode')} />
        </CardContent>
      </Card>
    </div>
  )
}

function GuardItem({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-border p-3">
      <ShieldCheck className="h-4 w-4 text-success" />
      <span>{title}</span>
    </div>
  )
}

function StatCard({ label, value, tone = 'default' }: { label: string; value: string; tone?: 'default' | 'warning' | 'success' }) {
  return (
    <div className="rounded-xl border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={
          tone === 'warning'
            ? 'text-lg font-semibold text-[hsl(var(--warning-ink))]'
            : tone === 'success'
              ? 'text-lg font-semibold text-success'
              : 'text-lg font-semibold'
        }
      >
        {value}
      </p>
    </div>
  )
}
