import { ArrowRight, Bot, CheckCircle2, CircleAlert, ClipboardList, FolderOpen, KeyRound, NotebookText, PlugZap, Rocket, Workflow } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, TableWrapper } from '@/components/ui/table'
import { getRuntimeSettings, listJobs, type RuntimeSettings } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import type { Job } from '@/lib/types'
import { createRouteIntentPrefetchHandlers } from '@/routes/lazy-routes'
import { formatDate, progressToPercent } from '@/lib/utils'

const DASHBOARD_DOC_LINKS = {
  codex: 'https://github.com/xiaojiou176-open/fileyard/blob/main/docs/codex_mcp.md',
  claude: 'https://github.com/xiaojiou176-open/fileyard/blob/main/docs/claude_code_mcp.md',
  mcp: 'https://github.com/xiaojiou176-open/fileyard/blob/main/docs/mcp.md',
  developerGuide: 'https://github.com/xiaojiou176-open/fileyard/blob/main/docs/developer_guide.md',
} as const

type NextStepKind = 'setup' | 'analyze' | 'review' | 'apply' | 'report'
type FlowStage = 'setup' | 'analyze' | 'review' | 'apply'

export function DashboardPage() {
  const { t } = useI18n()
  const [jobs, setJobs] = useState<Job[]>([])
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null)

  useEffect(() => {
    let mounted = true

    async function loadJobs() {
      const [nextJobs, nextSettings] = await Promise.all([listJobs(), getRuntimeSettings()])
      if (mounted) {
        setJobs(nextJobs)
        setRuntimeSettings(nextSettings)
      }
    }

    void loadJobs()
    return () => {
      mounted = false
    }
  }, [])

  const analyzeJob = jobs.find((job) => job.kind === 'analyze')
  const applyJob = jobs.find((job) => job.kind === 'apply')
  const reportJob = jobs.find((job) => job.report_path)
  const latestJob = jobs[0] ?? null
  const pendingFiles = analyzeJob?.summary?.total ?? 0
  const dryRunWaiting = jobs.filter((job) => job.kind === 'apply' && job.summary?.dry_run === true && job.status !== 'succeeded').length
  const succeededJobs = jobs.filter((job) => job.status === 'succeeded').length
  const analyzeJobId = analyzeJob?.id ?? ''
  const reviewTargetJobId = analyzeJobId
  const applyTargetJobId = applyJob?.id ?? analyzeJobId
  const latestReportLabel = reportJob ? reportJob.id.slice(-6) : t('dashboard.snapshot.empty')

  const setupPrefetch = createRouteIntentPrefetchHandlers('setup')
  const analyzePrefetch = createRouteIntentPrefetchHandlers('analyze')
  const reviewPrefetch = createRouteIntentPrefetchHandlers('review')
  const applyPrefetch = createRouteIntentPrefetchHandlers('apply')
  const jobsPrefetch = createRouteIntentPrefetchHandlers('jobs')
  const reportPrefetch = createRouteIntentPrefetchHandlers('report')

  const nextStepKind: NextStepKind = useMemo(() => {
    if (!runtimeSettings?.ready) {
      return 'setup'
    }
    if (reportJob) {
      return 'report'
    }
    if (applyTargetJobId && dryRunWaiting > 0) {
      return 'apply'
    }
    if (reviewTargetJobId) {
      return 'review'
    }
    return 'analyze'
  }, [applyTargetJobId, dryRunWaiting, reportJob, reviewTargetJobId, runtimeSettings?.ready])

  const flowStage: FlowStage = useMemo(() => {
    if (!runtimeSettings?.ready) {
      return 'setup'
    }
    if (applyTargetJobId && dryRunWaiting > 0) {
      return 'apply'
    }
    if (reviewTargetJobId) {
      return 'review'
    }
    return 'analyze'
  }, [applyTargetJobId, dryRunWaiting, reviewTargetJobId, runtimeSettings?.ready])

  const flowStageIndex = flowStage === 'setup' ? 0 : flowStage === 'analyze' ? 1 : flowStage === 'review' ? 2 : 3

  const readinessSummary = runtimeSettings?.ready
    ? t('dashboard.command.ready.stateReady')
    : t('dashboard.command.ready.stateNeedsSetup', {
        items: runtimeSettings?.missing?.join(', ') || t('dashboard.setupCard.loading'),
      })

  const nextStepMeta = {
    setup: {
      title: t('dashboard.command.next.setupTitle'),
      description: t('dashboard.command.next.setupDescription'),
      cta: t('dashboard.command.next.setupCta'),
      to: '/setup',
      prefetch: setupPrefetch,
    },
    analyze: {
      title: t('dashboard.command.next.analyzeTitle'),
      description: t('dashboard.command.next.analyzeDescription'),
      cta: t('dashboard.command.next.analyzeCta'),
      to: '/analyze',
      prefetch: analyzePrefetch,
    },
    review: {
      title: t('dashboard.command.next.reviewTitle'),
      description: t('dashboard.command.next.reviewDescription'),
      cta: t('dashboard.command.next.reviewCta'),
      to: reviewTargetJobId ? `/review/${reviewTargetJobId}` : '/analyze',
      prefetch: reviewPrefetch,
    },
    apply: {
      title: t('dashboard.command.next.applyTitle'),
      description: t('dashboard.command.next.applyDescription'),
      cta: t('dashboard.command.next.applyCta'),
      to: applyTargetJobId ? `/apply/${applyTargetJobId}` : '/jobs',
      prefetch: applyPrefetch,
    },
    report: {
      title: t('dashboard.command.next.reportTitle'),
      description: t('dashboard.command.next.reportDescription'),
      cta: t('dashboard.command.next.reportCta'),
      to: reportJob ? `/report/${reportJob.id}` : '/jobs',
      prefetch: reportPrefetch,
    },
  }[nextStepKind]

  const stageMeta = {
    setup: {
      label: t('dashboard.command.stage.setupLabel'),
      description: t('dashboard.command.stage.setupDescription'),
    },
    analyze: {
      label: t('dashboard.command.stage.analyzeLabel'),
      description: t('dashboard.command.stage.analyzeDescription'),
    },
    review: {
      label: t('dashboard.command.stage.reviewLabel'),
      description: t('dashboard.command.stage.reviewDescription'),
    },
    apply: {
      label: t('dashboard.command.stage.applyLabel'),
      description: reportJob ? t('dashboard.command.stage.applyReportReady') : t('dashboard.command.stage.applyDescription'),
    },
  }[flowStage]

  const flowSteps = [
    { key: 'setup', label: t('dashboard.flow.setup') },
    { key: 'analyze', label: t('dashboard.flow.analyze') },
    { key: 'review', label: t('dashboard.flow.review') },
    { key: 'apply', label: t('dashboard.flow.apply') },
  ]

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-3xl border border-border/70 bg-[linear-gradient(135deg,hsl(var(--brand-soft))_0%,hsl(var(--card))_55%,hsl(var(--accent)/0.6)_100%)] p-6 shadow-card sm:p-8">
        <div className="pointer-events-none absolute -right-20 -top-16 h-56 w-56 rounded-full bg-primary/10 blur-3xl" />
        <div className="space-y-6">
          <div className="max-w-3xl space-y-4">
            <Badge variant={runtimeSettings?.ready ? 'success' : 'secondary'}>
              {runtimeSettings?.ready ? t('dashboard.badge.ready') : t('dashboard.badge.setupRequired')}
            </Badge>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t('dashboard.hero.title')}</h1>
            <p className="text-sm text-muted-foreground sm:text-base">{t('dashboard.hero.description')}</p>
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link {...nextStepMeta.prefetch} to={nextStepMeta.to}>
                  {nextStepMeta.cta}
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link {...jobsPrefetch} to="/jobs">
                  {t('dashboard.cta.openJobs')}
                </Link>
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="border-border/70 bg-card/90">
              <CardHeader className="pb-3">
                <CardDescription>{t('dashboard.command.ready.title')}</CardDescription>
                <CardTitle className="text-xl">{runtimeSettings?.ready ? t('dashboard.command.ready.valueReady') : t('dashboard.command.ready.valueNeedsSetup')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-muted-foreground">
                <p>{readinessSummary}</p>
                <div className="flex items-center gap-2 text-foreground">
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                  <span>{runtimeSettings?.ready ? t('dashboard.command.ready.connected') : t('dashboard.command.ready.finish')}</span>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-card/90">
              <CardHeader className="pb-3">
                <CardDescription>{t('dashboard.command.next.title')}</CardDescription>
                <CardTitle className="text-xl">{nextStepMeta.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <p>{nextStepMeta.description}</p>
                <Button asChild size="sm" variant="secondary">
                  <Link {...nextStepMeta.prefetch} to={nextStepMeta.to}>
                    {nextStepMeta.cta}
                  </Link>
                </Button>
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-card/90">
              <CardHeader className="pb-3">
                <CardDescription>{t('dashboard.command.stage.title')}</CardDescription>
                <CardTitle className="text-xl">{stageMeta.label}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-muted-foreground">
                <p>{stageMeta.description}</p>
                <div className="flex items-center gap-2 text-foreground">
                  <Workflow className="h-4 w-4 text-primary" />
                  <span>{latestJob ? t('dashboard.command.stage.latestJob', { jobId: latestJob.id.slice(-6) }) : t('dashboard.command.stage.noBatch')}</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {!runtimeSettings?.ready ? (
        <Card className="border-primary/25 bg-primary/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="h-4 w-4" />
              {t('dashboard.setupCard.title')}
            </CardTitle>
            <CardDescription>{t('dashboard.setupCard.description')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <span>{t('dashboard.setupCard.missing', { items: runtimeSettings?.missing?.join(', ') || t('dashboard.setupCard.loading') })}</span>
            <Button asChild size="sm">
              <Link {...setupPrefetch} to="/setup">
                {t('dashboard.setupCard.openSetup')}
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.55fr_0.95fr]">
        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.flow.title')}</CardTitle>
            <CardDescription>{t('dashboard.flow.description')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {flowSteps.map((step, index) => {
                const state = index < flowStageIndex ? 'complete' : index === flowStageIndex ? 'current' : 'upcoming'
                return (
                  <div
                    className="rounded-2xl border border-border/70 bg-muted/30 p-4"
                    key={step.key}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-medium">{step.label}</p>
                      <Badge variant={state === 'complete' ? 'success' : state === 'current' ? 'secondary' : 'outline'}>
                        {state === 'complete'
                          ? t('dashboard.flow.state.complete')
                          : state === 'current'
                            ? t('dashboard.flow.state.current')
                            : t('dashboard.flow.state.upcoming')}
                      </Badge>
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="flex flex-wrap gap-3">
              <Button asChild variant="secondary">
                <Link {...nextStepMeta.prefetch} to={nextStepMeta.to}>
                  {nextStepMeta.cta}
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link {...jobsPrefetch} to="/jobs">
                  {t('dashboard.cta.openJobs')}
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.snapshot.title')}</CardTitle>
            <CardDescription>{t('dashboard.snapshot.description')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <SnapshotRow
              icon={FolderOpen}
              label={t('dashboard.snapshot.pendingFiles')}
              value={String(pendingFiles)}
              helper={t('dashboard.snapshot.pendingFilesHint')}
            />
            <SnapshotRow
              icon={CircleAlert}
              label={t('dashboard.snapshot.dryRun')}
              value={String(dryRunWaiting)}
              helper={t('dashboard.snapshot.dryRunHint')}
            />
            <SnapshotRow
              icon={NotebookText}
              label={t('dashboard.snapshot.latestReport')}
              value={latestReportLabel}
              helper={reportJob ? t('dashboard.snapshot.latestReportHint') : t('dashboard.snapshot.noReport')}
            />
            <SnapshotRow
              icon={Rocket}
              label={t('dashboard.snapshot.successfulJobs')}
              value={String(succeededJobs)}
              helper={t('dashboard.snapshot.successfulJobsHint')}
            />
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.recentJobs.title')}</CardTitle>
            <CardDescription>{t('dashboard.recentJobs.description')}</CardDescription>
          </CardHeader>
          <CardContent>
            <TableWrapper>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Job ID</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Progress</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead className="text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell className="max-w-[220px] truncate font-medium">{job.id}</TableCell>
                      <TableCell>{job.kind}</TableCell>
                      <TableCell>
                        <Badge variant={job.status === 'succeeded' ? 'success' : job.status === 'failed' ? 'destructive' : 'secondary'}>
                          {job.status}
                        </Badge>
                      </TableCell>
                      <TableCell>{progressToPercent(job.progress)}%</TableCell>
                      <TableCell>{formatDate(job.started_at)}</TableCell>
                      <TableCell className="text-right">
                        <Button asChild size="sm" variant="ghost">
                          <Link {...reviewPrefetch} to={`/review/${job.id}`}>
                            View
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableWrapper>
          </CardContent>
        </Card>

        <Card className="border-border/80 bg-card/95">
          <CardHeader>
            <CardTitle>{t('dashboard.builder.title')}</CardTitle>
            <CardDescription>{t('dashboard.builder.description')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-2xl border border-border/70 bg-muted/30 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="space-y-1">
                  <p className="font-medium">{t('dashboard.builder.ai.title')}</p>
                  <p className="text-sm text-muted-foreground">{t('dashboard.builder.ai.description')}</p>
                </div>
                <Bot className="h-5 w-5 text-primary" />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="outline">{t('dashboard.builder.badge.reviewSafe')}</Badge>
                <Badge variant="outline">{runtimeSettings?.model || 'gemini-3-flash-preview'}</Badge>
              </div>
            </div>

            <div className="rounded-2xl border border-border/70 bg-muted/30 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="space-y-1">
                  <p className="font-medium">{t('dashboard.builder.mcp.title')}</p>
                  <p className="text-sm text-muted-foreground">{t('dashboard.builder.mcp.description')}</p>
                </div>
                <PlugZap className="h-5 w-5 text-primary" />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="outline">{t('dashboard.builder.badge.localFirst')}</Badge>
                <Badge variant="outline">{t('dashboard.builder.badge.reviewSafe')}</Badge>
              </div>
            </div>

            <div className="rounded-2xl border border-border/70 bg-muted/30 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="space-y-1">
                  <p className="font-medium">{t('dashboard.builder.api.title')}</p>
                  <p className="text-sm text-muted-foreground">{t('dashboard.builder.api.description')}</p>
                </div>
                <ClipboardList className="h-5 w-5 text-primary" />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="outline">OpenAPI</Badge>
                <Badge variant="outline">generated client</Badge>
              </div>
            </div>

            <div className="rounded-2xl border border-border/70 bg-muted/30 p-4">
              <p className="font-medium">{t('dashboard.builder.pack.title')}</p>
              <p className="mt-1 text-sm text-muted-foreground">{t('dashboard.builder.pack.description')}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="outline">{t('dashboard.builder.badge.templateOnly')}</Badge>
                <Badge variant="outline">
                  {runtimeSettings?.active_strategy_pack_id
                    ? t('dashboard.builder.pack.current', { packId: runtimeSettings.active_strategy_pack_id })
                    : t('dashboard.builder.pack.none')}
                </Badge>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button asChild size="sm" variant="outline">
                <a href={DASHBOARD_DOC_LINKS.codex} rel="noreferrer" target="_blank">
                  {t('dashboard.builder.link.codex')}
                </a>
              </Button>
              <Button asChild size="sm" variant="outline">
                <a href={DASHBOARD_DOC_LINKS.claude} rel="noreferrer" target="_blank">
                  {t('dashboard.builder.link.claude')}
                </a>
              </Button>
              <Button asChild size="sm" variant="outline">
                <a href={DASHBOARD_DOC_LINKS.mcp} rel="noreferrer" target="_blank">
                  {t('dashboard.builder.link.mcp')}
                </a>
              </Button>
              <Button asChild size="sm" variant="outline">
                <a href={DASHBOARD_DOC_LINKS.developerGuide} rel="noreferrer" target="_blank">
                  {t('dashboard.builder.link.devGuide')}
                </a>
              </Button>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}

function SnapshotRow({
  icon: Icon,
  label,
  value,
  helper,
}: {
  icon: typeof FolderOpen
  label: string
  value: string
  helper: string
}) {
  return (
    <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold tracking-tight">{value}</p>
          <p className="text-xs text-muted-foreground">{helper}</p>
        </div>
        <Icon className="mt-1 h-4 w-4 text-primary" />
      </div>
    </div>
  )
}
