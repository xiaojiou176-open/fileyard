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
import { formatDate, progressToPercent } from '@/lib/utils'
import { createRouteIntentPrefetchHandlers } from '@/routes/lazy-routes'

const DASHBOARD_DOC_LINKS = {
  codex: 'https://github.com/xiaojiou176-open/fileorganize/blob/main/docs/codex_mcp.md',
  claude: 'https://github.com/xiaojiou176-open/fileorganize/blob/main/docs/claude_code_mcp.md',
  mcp: 'https://github.com/xiaojiou176-open/fileorganize/blob/main/docs/mcp.md',
  developerGuide: 'https://github.com/xiaojiou176-open/fileorganize/blob/main/docs/developer_guide.md',
} as const

type NextStepKind = 'setup' | 'analyze' | 'review' | 'apply' | 'report'
type FlowStage = 'setup' | 'analyze' | 'review' | 'apply'
type SurfaceBadgeVariant = 'default' | 'secondary' | 'outline' | 'success' | 'warning' | 'destructive'

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
  const jobsPrefetch = createRouteIntentPrefetchHandlers('jobs')
  const reviewPrefetch = createRouteIntentPrefetchHandlers('review')
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
      prefetch: createRouteIntentPrefetchHandlers('analyze'),
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
      prefetch: createRouteIntentPrefetchHandlers('apply'),
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

  const commandDeck: Array<{
    id: string
    kicker: string
    title: string
    description: string
    icon: typeof Workflow
    badge: string
    badgeVariant: SurfaceBadgeVariant
  }> = [
    {
      id: 'ready',
      kicker: t('dashboard.command.ready.title'),
      title: runtimeSettings?.ready ? t('dashboard.command.ready.valueReady') : t('dashboard.command.ready.valueNeedsSetup'),
      description: readinessSummary,
      icon: runtimeSettings?.ready ? CheckCircle2 : CircleAlert,
      badge: runtimeSettings?.ready ? t('dashboard.badge.ready') : t('dashboard.badge.setupRequired'),
      badgeVariant: runtimeSettings?.ready ? 'success' : 'secondary',
    },
    {
      id: 'next',
      kicker: t('dashboard.command.next.title'),
      title: nextStepMeta.title,
      description: nextStepMeta.description,
      icon: ArrowRight,
      badge: nextStepMeta.cta,
      badgeVariant: 'outline',
    },
    {
      id: 'stage',
      kicker: t('dashboard.command.stage.title'),
      title: stageMeta.label,
      description: stageMeta.description,
      icon: Workflow,
      badge: latestJob ? t('dashboard.command.stage.latestJob', { jobId: latestJob.id.slice(-6) }) : t('dashboard.command.stage.noBatch'),
      badgeVariant: 'outline',
    },
  ]

  const snapshotCards = [
    {
      id: 'pending',
      icon: FolderOpen,
      label: t('dashboard.snapshot.pendingFiles'),
      value: String(pendingFiles),
      helper: t('dashboard.snapshot.pendingFilesHint'),
    },
    {
      id: 'dry-run',
      icon: CircleAlert,
      label: t('dashboard.snapshot.dryRun'),
      value: String(dryRunWaiting),
      helper: t('dashboard.snapshot.dryRunHint'),
    },
    {
      id: 'report',
      icon: NotebookText,
      label: t('dashboard.snapshot.latestReport'),
      value: latestReportLabel,
      helper: reportJob ? t('dashboard.snapshot.latestReportHint') : t('dashboard.snapshot.noReport'),
    },
    {
      id: 'success',
      icon: Rocket,
      label: t('dashboard.snapshot.successfulJobs'),
      value: String(succeededJobs),
      helper: t('dashboard.snapshot.successfulJobsHint'),
    },
  ]

  const builderLanes = [
    {
      id: 'ai',
      icon: Bot,
      title: t('dashboard.builder.ai.title'),
      description: t('dashboard.builder.ai.description'),
      badges: [t('dashboard.builder.badge.reviewSafe'), runtimeSettings?.model || 'gemini-3-flash-preview'],
    },
    {
      id: 'mcp',
      icon: PlugZap,
      title: t('dashboard.builder.mcp.title'),
      description: t('dashboard.builder.mcp.description'),
      badges: [t('dashboard.builder.badge.localFirst'), t('dashboard.builder.badge.reviewSafe')],
    },
    {
      id: 'api',
      icon: ClipboardList,
      title: t('dashboard.builder.api.title'),
      description: t('dashboard.builder.api.description'),
      badges: ['OpenAPI', 'generated client'],
    },
    {
      id: 'pack',
      icon: Workflow,
      title: t('dashboard.builder.pack.title'),
      description: t('dashboard.builder.pack.description'),
      badges: [
        t('dashboard.builder.badge.templateOnly'),
        runtimeSettings?.active_strategy_pack_id
          ? t('dashboard.builder.pack.current', { packId: runtimeSettings.active_strategy_pack_id })
          : t('dashboard.builder.pack.none'),
      ],
    },
  ]

  return (
    <div className="space-y-6">
      <section className="workspace-panel relative overflow-hidden p-6 sm:p-8">
        <div className="workspace-grid pointer-events-none absolute inset-0 opacity-[0.16]" />
        <div className="pointer-events-none absolute -right-16 top-0 h-72 w-72 rounded-full bg-primary/10 blur-3xl" />
        <div
          className="pointer-events-none absolute inset-0 opacity-70"
          style={{
            background: 'linear-gradient(140deg, hsl(var(--brand-soft)) 0%, transparent 40%, hsl(var(--accent) / 0.45) 100%)',
          }}
        />
        <div className="relative grid gap-6 xl:grid-cols-[minmax(0,1.18fr)_360px] xl:items-start">
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={runtimeSettings?.ready ? 'success' : 'secondary'}>
                {runtimeSettings?.ready ? t('dashboard.badge.ready') : t('dashboard.badge.setupRequired')}
              </Badge>
              <Badge variant="outline">{stageMeta.label}</Badge>
            </div>

            <div className="max-w-3xl space-y-4">
              <p className="workspace-kicker">{t('appShell.brand.subtitle')}</p>
              <h1 className="max-w-2xl text-4xl font-light tracking-[-0.05em] text-foreground sm:text-5xl lg:text-[3.5rem]">
                {t('dashboard.hero.title')}
              </h1>
              <p className="max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">{t('dashboard.hero.description')}</p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link {...nextStepMeta.prefetch} to={nextStepMeta.to}>
                  {nextStepMeta.cta}
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link {...jobsPrefetch} to="/jobs">
                  {t('dashboard.cta.openJobs')}
                </Link>
              </Button>
            </div>
          </div>

          <div className="grid gap-3">
            {commandDeck.map((card) => (
              <CommandDeckCard
                badge={card.badge}
                badgeVariant={card.badgeVariant}
                description={card.description}
                icon={card.icon}
                key={card.id}
                kicker={card.kicker}
                title={card.title}
              />
            ))}
          </div>
        </div>
      </section>

      {!runtimeSettings?.ready ? (
        <Card className="border-primary/20 bg-primary/5">
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
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{t('dashboard.flow.title')}</CardTitle>
            <CardDescription>{t('dashboard.flow.description')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="rounded-[1.2rem] border border-border/80 bg-muted/40 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-1">
                  <p className="workspace-kicker">{t('dashboard.command.stage.title')}</p>
                  <p className="text-base font-semibold tracking-[-0.02em] text-foreground">{stageMeta.label}</p>
                  <p className="text-sm leading-6 text-muted-foreground">{stageMeta.description}</p>
                </div>
                <Button asChild variant="secondary">
                  <Link {...nextStepMeta.prefetch} to={nextStepMeta.to}>
                    {nextStepMeta.cta}
                  </Link>
                </Button>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {flowSteps.map((step, index) => {
                const state = index < flowStageIndex ? 'complete' : index === flowStageIndex ? 'current' : 'upcoming'
                const stateLabel =
                  state === 'complete'
                    ? t('dashboard.flow.state.complete')
                    : state === 'current'
                      ? t('dashboard.flow.state.current')
                      : t('dashboard.flow.state.upcoming')

                return <WorkflowStepCard index={index + 1} key={step.key} label={step.label} state={state} stateLabel={stateLabel} />
              })}
            </div>

            <div className="flex flex-wrap gap-3">
              <Button asChild variant="outline">
                <Link {...nextStepMeta.prefetch} to={nextStepMeta.to}>
                  {nextStepMeta.cta}
                </Link>
              </Button>
              <Button asChild variant="ghost">
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
          <CardContent className="grid gap-3 sm:grid-cols-2">
            {snapshotCards.map((card) => (
              <SnapshotMetricCard helper={card.helper} icon={card.icon} key={card.id} label={card.label} value={card.value} />
            ))}
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
                  {jobs.length > 0 ? (
                    jobs.map((job) => (
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
                    ))
                  ) : (
                    <TableRow>
                      <TableCell className="py-10 text-sm text-muted-foreground" colSpan={6}>
                        {t('dashboard.command.stage.noBatch')}
                      </TableCell>
                    </TableRow>
                  )}
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
            {builderLanes.map((lane) => (
              <BuilderLaneCard badges={lane.badges} description={lane.description} icon={lane.icon} key={lane.id} title={lane.title} />
            ))}

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

function CommandDeckCard({
  kicker,
  title,
  description,
  icon: Icon,
  badge,
  badgeVariant,
}: {
  kicker: string
  title: string
  description: string
  icon: typeof Workflow
  badge: string
  badgeVariant: SurfaceBadgeVariant
}) {
  return (
    <div className="rounded-[1.25rem] border border-border/80 bg-card/85 p-4 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <p className="workspace-kicker">{kicker}</p>
          <p className="text-base font-semibold tracking-[-0.025em] text-foreground">{title}</p>
          <p className="text-sm leading-6 text-muted-foreground">{description}</p>
          <Badge variant={badgeVariant}>{badge}</Badge>
        </div>
        <div className="grid h-10 w-10 place-items-center rounded-full border border-primary/15 bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </div>
      </div>
    </div>
  )
}

function WorkflowStepCard({
  index,
  label,
  state,
  stateLabel,
}: {
  index: number
  label: string
  state: 'complete' | 'current' | 'upcoming'
  stateLabel: string
}) {
  return (
    <div
      className={
        state === 'current'
          ? 'rounded-[1.2rem] border border-primary/15 bg-[linear-gradient(135deg,hsl(var(--accent))_0%,hsl(var(--card))_100%)] p-4 shadow-card'
          : 'rounded-[1.2rem] border border-border/70 bg-muted/30 p-4'
      }
    >
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <span className="workspace-mono inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/80 bg-card/80 text-xs font-semibold text-muted-foreground">
            {String(index).padStart(2, '0')}
          </span>
          <p className="font-medium tracking-[-0.015em] text-foreground">{label}</p>
        </div>
        <Badge variant={state === 'complete' ? 'success' : state === 'current' ? 'secondary' : 'outline'}>{stateLabel}</Badge>
      </div>
    </div>
  )
}

function SnapshotMetricCard({
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
    <div className="rounded-[1.2rem] border border-border/70 bg-muted/25 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <p className="workspace-kicker">{label}</p>
          <p className="workspace-value text-3xl">{value}</p>
          <p className="text-xs leading-5 text-muted-foreground">{helper}</p>
        </div>
        <div className="grid h-10 w-10 place-items-center rounded-full border border-primary/15 bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </div>
      </div>
    </div>
  )
}

function BuilderLaneCard({
  icon: Icon,
  title,
  description,
  badges,
}: {
  icon: typeof Workflow
  title: string
  description: string
  badges: string[]
}) {
  return (
    <div className="rounded-[1.2rem] border border-border/70 bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <p className="font-medium tracking-[-0.015em] text-foreground">{title}</p>
          <p className="text-sm leading-6 text-muted-foreground">{description}</p>
        </div>
        <div className="grid h-10 w-10 place-items-center rounded-full border border-primary/15 bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {badges.map((badge) => (
          <Badge key={badge} variant="outline">
            {badge}
          </Badge>
        ))}
      </div>
    </div>
  )
}
