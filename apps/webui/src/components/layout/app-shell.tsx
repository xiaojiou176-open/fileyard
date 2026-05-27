import { AlertTriangle, BriefcaseBusiness, ChartPie, FileStack, House, Inbox, KeyRound, ListTodo, Menu, RotateCcw, ScanSearch, Sparkles, Workflow } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

import { JobCenterSheet } from '@/components/layout/job-center-sheet'
import { Breadcrumb } from '@/components/ui/breadcrumb'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/native-select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useLiveJobs } from '@/hooks/use-live-jobs'
import { getRuntimeSettings, type RuntimeSettings } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { cn, toTitleCase } from '@/lib/utils'
import { createRouteIntentPrefetchHandlers, preloadRouteSet, scheduleLikelyRoutePreload } from '@/routes/lazy-routes'

type NavItem = {
  id: string
  to: string
  label: string
  icon: typeof House
  prefetch: 'dashboard' | 'setup' | 'jobs' | 'inbox' | 'analyze' | 'review' | 'manifest' | 'conflicts' | 'apply' | 'report' | 'rollback'
}

function getDocumentMetadata(pathname: string): { title: string; description: string } {
  const fallback = {
    title: 'Fileorganize | Review-first local organizer',
    description:
      'Fileorganize is a review-first local file organizer and workbench with AI-assisted planning, dry-run-first execution, and rollback-ready recovery.',
  }

  if (pathname === '/') {
    return fallback
  }
  if (pathname.startsWith('/setup')) {
    return {
      title: 'Setup | Fileorganize',
      description: 'Configure workspace roots, runtime defaults, and review-safe settings before you start organizing batches.',
    }
  }
  if (pathname.startsWith('/jobs')) {
    return {
      title: 'Jobs | Fileorganize',
      description: 'Inspect current analyze, apply, and rollback jobs inside the same review-first local workspace.',
    }
  }
  if (pathname.startsWith('/analyze')) {
    return {
      title: 'Analyze | Fileorganize',
      description: 'Draft a manifest from a local batch, optionally with Strategy Pack defaults, before anything reaches Apply.',
    }
  }
  if (pathname.startsWith('/review')) {
    return {
      title: 'Fileorganize Review | Fileorganize',
      description: 'Review queue, collections, learned suggestions, and rule drafts all stay inside the approval layer before execution.',
    }
  }
  if (pathname.startsWith('/manifest')) {
    return {
      title: 'Manifest Workbench | Fileorganize',
      description: 'Inspect and edit manifest rows in the local review workbench before dry-run or real apply.',
    }
  }
  if (pathname.startsWith('/conflicts')) {
    return {
      title: 'Conflicts | Fileorganize',
      description: 'Resolve duplicate targets and review conflicts without bypassing overlay-only and dry-run-first guardrails.',
    }
  }
  if (pathname.startsWith('/apply')) {
    return {
      title: 'Apply | Fileorganize',
      description: 'Queue and inspect deterministic apply jobs that start in dry-run mode and stay rollback-ready.',
    }
  }
  if (pathname.startsWith('/report')) {
    return {
      title: 'Report | Fileorganize',
      description: 'Use the after-action board to inspect results and route back into the right Review focus instead of guessing what to fix next.',
    }
  }
  if (pathname.startsWith('/rollback')) {
    return {
      title: 'Rollback | Fileorganize',
      description: 'Rollback stays bounded, deterministic, and auditable inside the same local-first workflow.',
    }
  }
  if (pathname.startsWith('/inbox')) {
    return {
      title: 'Fileorganize Inbox | Fileorganize',
      description: 'Scan intake batches, pick a Strategy Pack, and hand the batch into Analyze without turning Fileorganize into an autonomous organizer.',
    }
  }
  return fallback
}

export function AppShell() {
  const location = useLocation()
  const { locale, setLocale, t } = useI18n()
  const [jobCenterOpen, setJobCenterOpen] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null)
  const { jobs, state } = useLiveJobs()

  const analyzeJobId = jobs.find((job) => job.kind === 'analyze')?.id ?? ''
  const applyJobId = jobs.find((job) => job.kind === 'apply')?.id ?? ''
  const reportJobId = jobs.find((job) => job.report_path)?.id ?? ''
  const rollbackJobId = jobs.find((job) => job.kind === 'rollback')?.id ?? ''
  const reviewTarget = analyzeJobId ? `/review/${analyzeJobId}` : '/analyze'
  const applyTarget = applyJobId ? `/apply/${applyJobId}` : analyzeJobId ? `/apply/${analyzeJobId}` : '/jobs'

  const mainNavItems: NavItem[] = [
    { id: 'dashboard', to: '/', label: t('appShell.nav.dashboard'), icon: House, prefetch: 'dashboard' },
    { id: 'setup', to: '/setup', label: t('appShell.nav.setup'), icon: KeyRound, prefetch: 'setup' },
    { id: 'analyze', to: '/analyze', label: t('appShell.nav.analyze'), icon: Sparkles, prefetch: 'analyze' },
    { id: 'review', to: reviewTarget, label: t('appShell.nav.review'), icon: ScanSearch, prefetch: 'review' },
  ]

  const secondaryNavItems = useMemo(() => {
    const items: NavItem[] = [
      { id: 'jobs', to: '/jobs', label: t('appShell.nav.jobs'), icon: Workflow, prefetch: 'jobs' },
      { id: 'inbox', to: '/inbox', label: t('appShell.nav.inbox'), icon: Inbox, prefetch: 'inbox' },
    ]

    if (analyzeJobId) {
      items.push(
        { id: 'manifest', to: `/manifest/${analyzeJobId}`, label: t('appShell.nav.manifest'), icon: FileStack, prefetch: 'manifest' },
        { id: 'conflicts', to: `/conflicts/${analyzeJobId}`, label: t('appShell.nav.conflicts'), icon: AlertTriangle, prefetch: 'conflicts' },
      )
    }

    if (analyzeJobId || applyJobId) {
      items.push({ id: 'apply', to: applyTarget, label: t('appShell.nav.apply'), icon: ListTodo, prefetch: 'apply' })
    }

    if (reportJobId) {
      items.push({ id: 'report', to: `/report/${reportJobId}`, label: t('appShell.nav.report'), icon: ChartPie, prefetch: 'report' })
    }

    if (rollbackJobId) {
      items.push({ id: 'rollback', to: `/rollback/${rollbackJobId}`, label: t('appShell.nav.rollback'), icon: RotateCcw, prefetch: 'rollback' })
    }

    return items
  }, [analyzeJobId, applyJobId, applyTarget, reportJobId, rollbackJobId, t])

  useEffect(() => {
    return scheduleLikelyRoutePreload(location.pathname)
  }, [location.pathname])

  useEffect(() => {
    if (jobs.length === 0) {
      return
    }
    const hotRoutes = jobs.some((job) => job.status === 'running' || job.status === 'queued' || job.status === 'cancelling')
      ? (['manifest', 'apply', 'report', 'rollback'] as const)
      : (['analyze', 'jobs'] as const)
    preloadRouteSet(...hotRoutes)
  }, [jobs])

  useEffect(() => {
    if (typeof document !== 'undefined') {
      const metadata = getDocumentMetadata(location.pathname)
      document.title = metadata.title
      const description = document.querySelector('meta[name="description"]')
      const descriptionTag =
        description instanceof HTMLMetaElement
          ? description
          : (() => {
              const tag = document.createElement('meta')
              tag.setAttribute('name', 'description')
              document.head.appendChild(tag)
              return tag
            })()
      descriptionTag.content = metadata.description

      for (const [property, content] of [
        ['og:title', metadata.title],
        ['og:description', metadata.description],
      ] as const) {
        const current = document.querySelector(`meta[property="${property}"]`)
        let tag: HTMLMetaElement
        if (current instanceof HTMLMetaElement) {
          tag = current
        } else {
          tag = document.createElement('meta')
          tag.setAttribute('property', property)
          document.head.appendChild(tag)
        }
        tag.content = content
      }
    }
  }, [location.pathname])

  useEffect(() => {
    let mounted = true
    void (async () => {
      try {
        const next = await getRuntimeSettings()
        if (mounted) {
          setRuntimeSettings(next)
        }
      } catch {
        if (mounted) {
          setRuntimeSettings(null)
        }
      }
    })()
    return () => {
      mounted = false
    }
  }, [location.pathname])

  const crumbs = useMemo(() => {
    const path = location.pathname.split('/').filter(Boolean)
    if (path.length === 0) {
      return [{ label: t('appShell.breadcrumb.home'), href: '/' }]
    }

    const output = [{ label: t('appShell.breadcrumb.home'), href: '/' }]
    let acc = ''
    for (const token of path) {
      acc += `/${token}`
      output.push({ label: toTitleCase(token), href: acc })
    }
    return output
  }, [location.pathname, t])

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            'radial-gradient(circle at 18% 6%, hsl(var(--primary) / 0.08), transparent 28%), radial-gradient(circle at 88% 12%, hsl(var(--accent-strong) / 0.25), transparent 22%)',
        }}
      />
      <div className="mx-auto grid w-full max-w-[1720px] grid-cols-1 gap-0 lg:grid-cols-[296px_1fr] lg:px-4">
        <aside className="motion-surface hidden lg:block lg:py-4">
          <div className="sticky top-4 space-y-4">
            <div className="workspace-panel p-4">
              <div className="flex items-center gap-3">
                <div className="shadow-float grid h-11 w-11 place-items-center rounded-[1rem] bg-primary text-primary-foreground">
                  <BriefcaseBusiness className="h-5 w-5" />
                </div>
                <div className="space-y-1">
                  <p className="workspace-kicker">Fileorganize</p>
                  <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">{t('appShell.brand.subtitle')}</p>
                </div>
              </div>
            </div>

            <div className="workspace-panel-soft p-3">
              <nav className="space-y-5">
                <div className="space-y-1">
                  <div className="px-3 pb-2">
                    <p className="workspace-kicker">{t('appShell.section.primary')}</p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{t('appShell.section.primaryHint')}</p>
                  </div>
                  {mainNavItems.map((item) => {
                    const Icon = item.icon
                    const prefetchHandlers = createRouteIntentPrefetchHandlers(item.prefetch)
                    return (
                      <NavLink
                        className={({ isActive }) =>
                          cn(
                            'group flex items-center gap-3 rounded-[1rem] px-3 py-2.5 text-sm transition-all',
                            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                            'motion-nav-item',
                            isActive
                              ? 'border border-primary/10 bg-[linear-gradient(135deg,hsl(var(--accent))_0%,hsl(var(--card))_100%)] text-foreground shadow-float'
                              : 'text-muted-foreground hover:bg-card/85 hover:text-foreground',
                          )
                        }
                        key={`${item.id}-${item.to}`}
                        onFocus={prefetchHandlers.onFocus}
                        onMouseEnter={prefetchHandlers.onMouseEnter}
                        onPointerDown={prefetchHandlers.onPointerDown}
                        onTouchStart={prefetchHandlers.onTouchStart}
                        to={item.to}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </NavLink>
                    )
                  })}
                </div>

                <div className="space-y-1">
                  <div className="px-3 pb-2">
                    <p className="workspace-kicker">{t('appShell.section.secondary')}</p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{t('appShell.section.secondaryHint')}</p>
                  </div>
                  {secondaryNavItems.map((item) => {
                    const Icon = item.icon
                    const prefetchHandlers = createRouteIntentPrefetchHandlers(item.prefetch)
                    return (
                      <NavLink
                        className={({ isActive }) =>
                          cn(
                            'group flex items-center gap-3 rounded-[1rem] px-3 py-2.5 text-sm transition-all',
                            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                            'motion-nav-item',
                            isActive
                              ? 'border border-primary/10 bg-[linear-gradient(135deg,hsl(var(--accent))_0%,hsl(var(--card))_100%)] text-foreground shadow-float'
                              : 'text-muted-foreground hover:bg-card/85 hover:text-foreground',
                          )
                        }
                        key={`${item.id}-${item.to}`}
                        onFocus={prefetchHandlers.onFocus}
                        onMouseEnter={prefetchHandlers.onMouseEnter}
                        onPointerDown={prefetchHandlers.onPointerDown}
                        onTouchStart={prefetchHandlers.onTouchStart}
                        to={item.to}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </NavLink>
                    )
                  })}
                </div>
              </nav>
            </div>

            <div className="workspace-panel p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <p className="workspace-kicker">{t('appShell.header.jobCenter')}</p>
                  <p className="text-sm font-medium tracking-[-0.02em] text-foreground">
                    {runtimeSettings?.ready ? t('appShell.header.settingsReady') : t('appShell.header.completeSetup')}
                  </p>
                </div>
                <span
                  className={cn(
                    'rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.14em]',
                    runtimeSettings?.ready ? 'border-transparent bg-success/16 text-success' : 'border-transparent bg-secondary text-secondary-foreground',
                  )}
                >
                  {runtimeSettings?.ready ? t('appShell.header.settingsReady') : t('appShell.header.completeSetup')}
                </span>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <span className="rounded-full border border-border/90 bg-transparent px-2.5 py-1 text-[0.72rem] font-semibold uppercase tracking-[0.14em] text-foreground">
                  {state === 'open' ? t('appShell.header.sseOnline') : t('appShell.header.sseFallback')}
                </span>
                {runtimeSettings?.model ? (
                  <span className="rounded-full border border-border/90 bg-transparent px-2.5 py-1 text-[0.72rem] font-semibold uppercase tracking-[0.14em] text-foreground">
                    {runtimeSettings.model}
                  </span>
                ) : null}
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild size="sm" variant={runtimeSettings?.ready ? 'outline' : 'default'}>
                  <Link {...createRouteIntentPrefetchHandlers('setup')} to="/setup">
                    <KeyRound className="mr-2 h-4 w-4" />
                    {runtimeSettings?.ready ? t('appShell.header.settingsReady') : t('appShell.header.completeSetup')}
                  </Link>
                </Button>
              </div>
            </div>
          </div>
        </aside>

        <div className="min-h-screen px-4 pb-8 pt-4 sm:px-6 lg:px-10">
          <header className="motion-surface motion-surface-delay workspace-panel sticky top-4 z-20 mb-6 flex flex-wrap items-center justify-between gap-4 px-4 py-3 sm:px-5">
            <div className="min-w-0 flex-1">
              <Breadcrumb items={crumbs} />
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <label className="sr-only" htmlFor="app-locale">
                {t('appShell.language.label')}
              </label>
              <NativeSelect
                aria-label={t('appShell.language.label')}
                className="h-9 w-[172px] text-xs"
                id="app-locale"
                onChange={(event) => setLocale(event.target.value === 'zh-CN' ? 'zh-CN' : 'en')}
                value={locale}
              >
                <option value="en">{t('appShell.language.english')}</option>
                <option value="zh-CN">{t('appShell.language.chinese')}</option>
              </NativeSelect>
              <Button className="lg:hidden" onClick={() => setMobileNavOpen(true)} variant="outline">
                <Menu className="h-4 w-4" />
                {t('appShell.header.navigationButton')}
              </Button>
              <span className="rounded-full border border-border/90 bg-card/70 px-2.5 py-1 text-[0.72rem] font-semibold uppercase tracking-[0.14em] text-foreground">
                {state === 'open' ? t('appShell.header.sseOnline') : t('appShell.header.sseFallback')}
              </span>
              <Button asChild size="sm" variant={runtimeSettings?.ready ? 'outline' : 'default'}>
                <Link {...createRouteIntentPrefetchHandlers('setup')} to="/setup">
                  <KeyRound className="mr-2 h-4 w-4" />
                  {runtimeSettings?.ready ? t('appShell.header.settingsReady') : t('appShell.header.completeSetup')}
                </Link>
              </Button>
              <Button onClick={() => setJobCenterOpen(true)} size="sm" variant="secondary">
                {t('appShell.header.jobCenter')}
              </Button>
            </div>
          </header>

          <main>
            <h1 className="sr-only">Fileorganize Review-First Workspace</h1>
            <Outlet />
          </main>
        </div>
      </div>

      <JobCenterSheet jobs={jobs} onOpenChange={setJobCenterOpen} open={jobCenterOpen} streamState={state} />
      <Sheet onOpenChange={setMobileNavOpen} open={mobileNavOpen}>
        <SheetContent side="left">
          <SheetHeader>
            <SheetTitle>{t('appShell.mobile.navigation')}</SheetTitle>
            <SheetDescription>{t('appShell.mobile.description')}</SheetDescription>
          </SheetHeader>
          <nav className="space-y-5">
            <div className="space-y-2">
              <div className="px-3">
                <p className="workspace-kicker">{t('appShell.section.primary')}</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{t('appShell.section.primaryHint')}</p>
              </div>
              {mainNavItems.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-3 rounded-[1rem] px-3 py-3 text-sm transition-all',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                        isActive
                          ? 'border border-primary/10 bg-[linear-gradient(135deg,hsl(var(--accent))_0%,hsl(var(--card))_100%)] text-foreground shadow-float'
                          : 'text-muted-foreground hover:bg-card/85 hover:text-foreground',
                      )
                    }
                    key={`mobile-${item.id}-${item.to}`}
                    onClick={() => setMobileNavOpen(false)}
                    to={item.to}
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </NavLink>
                )
              })}
            </div>

            <div className="space-y-2">
              <div className="px-3">
                <p className="workspace-kicker">{t('appShell.section.secondary')}</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{t('appShell.section.secondaryHint')}</p>
              </div>
              {secondaryNavItems.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-3 rounded-[1rem] px-3 py-3 text-sm transition-all',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                        isActive
                          ? 'border border-primary/10 bg-[linear-gradient(135deg,hsl(var(--accent))_0%,hsl(var(--card))_100%)] text-foreground shadow-float'
                          : 'text-muted-foreground hover:bg-card/85 hover:text-foreground',
                      )
                    }
                    key={`mobile-${item.id}-${item.to}`}
                    onClick={() => setMobileNavOpen(false)}
                    to={item.to}
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </NavLink>
                )
              })}
            </div>
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  )
}
