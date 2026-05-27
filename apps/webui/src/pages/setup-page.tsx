import { CheckCircle2, FolderOpen, KeyRound, ListChecks, ShieldCheck, Sparkles, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { getRuntimeSettings, listStrategyPacks, updateRuntimeSettings, validateRuntimeSettings, type RuntimeSettings } from '@/lib/api'
import type { StrategyPack } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { useI18n } from '@/lib/i18n'
import { createRouteIntentPrefetchHandlers } from '@/routes/lazy-routes'

const MODEL_OPTIONS = ['gemini-3-flash-preview', 'gemini-3.1-pro-preview']

type SetupFormState = {
  apiKey: string
  activeStrategyPackId: string
  model: string
  inputRoot: string
  outputRoot: string
  workers: string
  categories: string
  maxFiles: string
  maxTotalMb: string
  maxFileMb: string
}

export function SetupPage() {
  const { t } = useI18n()
  const [settings, setSettings] = useState<RuntimeSettings | null>(null)
  const [strategyPacks, setStrategyPacks] = useState<StrategyPack[]>([])
  const [form, setForm] = useState<SetupFormState>({
    apiKey: '',
    activeStrategyPackId: '',
    model: 'gemini-3-flash-preview',
    inputRoot: '~/.fileman/workspaces/default/data/raw',
    outputRoot: '~/.fileman/workspaces/default/data/organized',
    workers: '1',
    categories: 'work,travel,docs,product,other',
    maxFiles: '500',
    maxTotalMb: '4096',
    maxFileMb: '128',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [checking, setChecking] = useState(false)
  const analyzePrefetch = createRouteIntentPrefetchHandlers('analyze')
  const dashboardPrefetch = createRouteIntentPrefetchHandlers('dashboard')
  const selectedPack = useMemo(
    () => strategyPacks.find((pack) => pack.id === form.activeStrategyPackId) ?? null,
    [form.activeStrategyPackId, strategyPacks],
  )

  const summarizeApiStatus = (next: RuntimeSettings | null): string => {
    if (!next) {
      return t('setup.apiStatus.loading')
    }
    if (next.api_key_status === 'configured') { // pragma: allowlist secret
      return t('setup.apiStatus.connected')
    }
    if (next.api_key_status === 'placeholder') { // pragma: allowlist secret
      return t('setup.apiStatus.placeholder')
    }
    return t('setup.apiStatus.missing')
  }

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const [next, packs] = await Promise.all([getRuntimeSettings(), listStrategyPacks()])
        if (!alive) {
          return
        }
        setSettings(next)
        setStrategyPacks(packs.items)
        setForm((prev) => ({
          apiKey: '',
          activeStrategyPackId: next.active_strategy_pack_id || packs.active_strategy_pack_id || prev.activeStrategyPackId,
          model: next.model || prev.model,
          inputRoot: next.input_root || prev.inputRoot,
          outputRoot: next.output_root || prev.outputRoot,
          workers: String(next.analyze_defaults.workers || prev.workers),
          categories: next.analyze_defaults.categories.join(',') || prev.categories,
          maxFiles: String(next.analyze_defaults.max_files || prev.maxFiles),
          maxTotalMb: String(next.analyze_defaults.max_total_mb || prev.maxTotalMb),
          maxFileMb: String(next.analyze_defaults.max_file_mb || prev.maxFileMb),
        }))
      } catch (error) {
        if (alive) {
          toast.error(error instanceof Error ? error.message : 'Failed to load the first-run setup page.')
        }
      } finally {
        if (alive) {
          setLoading(false)
        }
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const stage = useMemo(() => {
    if (!settings) {
      return 'loading'
    }
    if (settings.ready) {
      return 'ready'
    }
    if (settings.has_api_key || settings.input_root_exists || settings.output_root_exists) {
      return 'configured'
    }
    return 'not_configured'
  }, [settings])

  const checklistItems = useMemo(
    () => [
      { label: t('setup.checklist.apiKey'), ready: Boolean(settings?.has_api_key) },
      { label: t('setup.checklist.inputRoot'), ready: Boolean(settings?.input_root_exists) },
      { label: t('setup.checklist.outputRoot'), ready: Boolean(settings?.output_root_exists) },
    ],
    [settings?.has_api_key, settings?.input_root_exists, settings?.output_root_exists, t],
  )
  const readyCount = checklistItems.filter((item) => item.ready).length

  async function handleSave() {
    setSaving(true)
    try {
      const next = await updateRuntimeSettings({
        apiKey: form.apiKey.trim().length > 0 ? form.apiKey.trim() : undefined,
        activeStrategyPackId: form.activeStrategyPackId,
        model: form.model,
        inputRoot: form.inputRoot,
        outputRoot: form.outputRoot,
        workers: Number(form.workers),
        categories: form.categories,
        maxFiles: Number(form.maxFiles),
        maxTotalMb: Number(form.maxTotalMb),
        maxFileMb: Number(form.maxFileMb),
        createMissingDirs: true,
      })
      setSettings(next)
      setForm((prev) => ({ ...prev, apiKey: '' }))
      toast.success(next.ready ? 'Initial setup is complete. You can start organizing files now.' : 'Settings were saved. Finish the remaining items to continue.')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save runtime settings.')
    } finally {
      setSaving(false)
    }
  }

  async function handleValidate() {
    setChecking(true)
    try {
      const next = await validateRuntimeSettings()
      setSettings(next)
      toast.success(next.ready ? 'Connection checks passed. You can start organizing files now.' : 'Validation finished, but some items still need attention.')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Connection check failed.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="space-y-6">
      <section className="workspace-panel relative overflow-hidden p-6 sm:p-8">
        <div className="workspace-grid pointer-events-none absolute inset-0 opacity-[0.14]" />
        <div className="pointer-events-none absolute -right-16 -top-12 h-52 w-52 rounded-full bg-primary/10 blur-3xl" />
        <div className="max-w-3xl space-y-4">
          <Badge variant={stage === 'ready' ? 'success' : 'secondary'}>
            {stage === 'ready'
              ? t('setup.badge.ready')
              : stage === 'configured'
                ? t('setup.badge.oneStepLeft')
                : loading
                  ? t('setup.badge.loading')
                  : t('setup.badge.firstRun')}
          </Badge>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t('setup.hero.title')}</h1>
          <p className="text-sm text-muted-foreground sm:text-base">{t('setup.hero.description')}</p>
          <div className="flex flex-wrap gap-3">
            <Button disabled={saving || checking} onClick={() => void handleSave()}>
              <Wand2 className="mr-2 h-4 w-4" />
              {saving ? t('setup.cta.saving') : t('setup.cta.save')}
            </Button>
            <Button disabled={checking} onClick={() => void handleValidate()} variant="outline">
              <Sparkles className="mr-2 h-4 w-4" />
              {checking ? t('setup.cta.checking') : t('setup.cta.check')}
            </Button>
            <Button asChild variant="secondary">
              <Link {...dashboardPrefetch} to="/">
                {t('setup.cta.backHome')}
              </Link>
            </Button>
          </div>
        </div>
      </section>

      {settings && settings.warnings.length > 0 ? (
        <Alert className="border-warning/30 bg-warning/10">
          <AlertTitle>{t('setup.alert.incomplete.title')}</AlertTitle>
          <AlertDescription>{t('setup.alert.incomplete.description', { warnings: settings.warnings.join('; ') })}</AlertDescription>
        </Alert>
      ) : null}

      {settings?.ready ? (
        <Alert className="border-success/30 bg-success/10">
          <AlertTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4" />
            {t('setup.alert.ready.title')}
          </AlertTitle>
          <AlertDescription>{t('setup.alert.ready.description')}</AlertDescription>
        </Alert>
      ) : null}

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>{t('setup.card.connect.title')}</CardTitle>
            <CardDescription>{t('setup.card.connect.description')}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-api-key">
                {t('setup.field.apiKey')}
              </label>
              <Input
                id="setup-api-key"
                onChange={(event) => setForm((prev) => ({ ...prev, apiKey: event.target.value }))}
                placeholder={settings?.has_api_key ? t('setup.field.apiKeyPlaceholderKeep') : t('setup.field.apiKeyPlaceholderPaste')}
                type="password"
                value={form.apiKey}
              />
              <p className="text-xs text-muted-foreground">{t('setup.field.apiKeyStatus', { status: summarizeApiStatus(settings) })}</p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-input-root">
                {t('setup.field.inputRoot')}
              </label>
              <Input
                id="setup-input-root"
                onChange={(event) => setForm((prev) => ({ ...prev, inputRoot: event.target.value }))}
                placeholder={t('setup.field.inputRootPlaceholder')}
                value={form.inputRoot}
              />
              <p className="text-xs text-muted-foreground">{t('setup.field.inputRootHint')}</p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-output-root">
                {t('setup.field.outputRoot')}
              </label>
              <Input
                id="setup-output-root"
                onChange={(event) => setForm((prev) => ({ ...prev, outputRoot: event.target.value }))}
                placeholder={t('setup.field.outputRootPlaceholder')}
                value={form.outputRoot}
              />
              <p className="text-xs text-muted-foreground">{t('setup.field.outputRootHint')}</p>
            </div>

            <div className="flex flex-wrap gap-3 pt-2">
              <Button disabled={saving || checking} onClick={() => void handleSave()}>
                <Wand2 className="mr-2 h-4 w-4" />
                {saving ? t('setup.cta.saving') : t('setup.cta.save')}
              </Button>
              <Button disabled={checking} onClick={() => void handleValidate()} variant="outline">
                <Sparkles className="mr-2 h-4 w-4" />
                {checking ? t('setup.cta.checking') : t('setup.cta.check')}
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="workspace-panel">
            <CardHeader>
              <CardTitle>{t('setup.card.checklist.title')}</CardTitle>
              <CardDescription>{t('setup.card.checklist.description', { ready: String(readyCount), total: String(checklistItems.length) })}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {checklistItems.map((item) => (
                <div className="flex items-center justify-between rounded-2xl border border-border/70 bg-muted/20 px-4 py-3" key={item.label}>
                  <div className="flex items-center gap-3">
                    <div className="grid h-9 w-9 place-items-center rounded-2xl border border-border bg-background">
                      {item.ready ? <CheckCircle2 className="h-4 w-4 text-success" /> : <ListChecks className="h-4 w-4 text-muted-foreground" />}
                    </div>
                    <div>
                      <p className="font-medium">{item.label}</p>
                      <p className="text-xs text-muted-foreground">{item.ready ? t('setup.checklist.ready') : t('setup.checklist.missing')}</p>
                    </div>
                  </div>
                  <Badge variant={item.ready ? 'success' : 'secondary'}>
                    {item.ready ? t('setup.checklist.badgeReady') : t('setup.checklist.badgePending')}
                  </Badge>
                </div>
              ))}
            </CardContent>
          </Card>

          <StatusCard
            icon={KeyRound}
            label={t('setup.status.aiConnection.label')}
            value={settings?.has_api_key ? t('setup.status.aiConnection.ready') : t('setup.status.aiConnection.pending')}
          />
          <StatusCard
            icon={FolderOpen}
            label={t('setup.status.sourceFolder.label')}
            value={settings?.input_root_exists ? t('setup.status.sourceFolder.ready') : t('setup.status.sourceFolder.pending')}
          />
          <StatusCard
            icon={FolderOpen}
            label={t('setup.status.outputFolder.label')}
            value={settings?.output_root_exists ? t('setup.status.outputFolder.ready') : t('setup.status.outputFolder.pending')}
          />

          <Card className="workspace-panel-soft">
            <CardHeader>
              <CardTitle>{t('setup.next.title')}</CardTitle>
              <CardDescription>{t('setup.next.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>{t('setup.next.step1')}</p>
              <p>{t('setup.next.step2')}</p>
              <p>{t('setup.next.step3')}</p>
              <Button asChild className="w-full" disabled={!settings?.ready}>
                <Link {...analyzePrefetch} to="/analyze">
                  {t('setup.next.cta')}
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>{t('setup.card.defaults.title')}</CardTitle>
            <CardDescription>{t('setup.card.defaults.description')}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-pack">
                {t('setup.field.strategyPack')}
              </label>
              <Select
                id="setup-pack"
                onValueChange={(value) =>
                  setForm((prev) => {
                    const nextPack = strategyPacks.find((item) => item.id === value)
                    return {
                      ...prev,
                      activeStrategyPackId: value,
                      model: nextPack?.model || prev.model,
                      categories: nextPack?.categories.join(',') || prev.categories,
                      workers: nextPack ? String(nextPack.workers) : prev.workers,
                    }
                  })
                }
                value={form.activeStrategyPackId}
              >
                {strategyPacks.map((pack) => (
                  <option key={pack.id} value={pack.id}>
                    {pack.name}
                  </option>
                ))}
              </Select>
              <p className="text-xs text-muted-foreground">{t('setup.field.strategyPackHint')}</p>
              {selectedPack ? (
                <div className="rounded-[1.2rem] border border-border/70 bg-muted/20 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{selectedPack.name}</p>
                    <Badge variant="secondary">{t('setup.card.defaults.templateOnly')}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {selectedPack.description || t('setup.card.defaults.packFallback')}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline">model: {selectedPack.model || t('setup.card.defaults.keepCurrent')}</Badge>
                    <Badge variant="outline">workers: {selectedPack.workers}</Badge>
                    <Badge variant="outline">categories: {selectedPack.categories.join(', ') || t('setup.card.defaults.none')}</Badge>
                    <Badge variant="outline">
                      {t('setup.card.defaults.reviewThreshold', { value: String(Math.round(selectedPack.review_confidence_threshold * 100)) })}
                    </Badge>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-model">
                {t('setup.field.model')}
              </label>
              <Select id="setup-model" onValueChange={(value) => setForm((prev) => ({ ...prev, model: value }))} value={form.model}>
                {MODEL_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-categories">
                {t('setup.field.categories')}
              </label>
              <Input id="setup-categories" onChange={(event) => setForm((prev) => ({ ...prev, categories: event.target.value }))} value={form.categories} />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-workers">
                {t('setup.field.workers')}
              </label>
              <Input id="setup-workers" onChange={(event) => setForm((prev) => ({ ...prev, workers: event.target.value }))} value={form.workers} />
            </div>
          </CardContent>
        </Card>

        <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>{t('setup.card.advanced.title')}</CardTitle>
            <CardDescription>{t('setup.card.advanced.description')}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-max-files">
                {t('setup.field.maxFiles')}
              </label>
              <Input id="setup-max-files" onChange={(event) => setForm((prev) => ({ ...prev, maxFiles: event.target.value }))} value={form.maxFiles} />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-max-total-mb">
                {t('setup.field.maxTotalMb')}
              </label>
              <Input
                id="setup-max-total-mb"
                onChange={(event) => setForm((prev) => ({ ...prev, maxTotalMb: event.target.value }))}
                value={form.maxTotalMb}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="setup-max-file-mb">
                {t('setup.field.maxFileMb')}
              </label>
              <Input id="setup-max-file-mb" onChange={(event) => setForm((prev) => ({ ...prev, maxFileMb: event.target.value }))} value={form.maxFileMb} />
            </div>

            <div className="rounded-[1.2rem] border border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">
              <div className="flex items-center gap-2 font-medium text-foreground">
                <ShieldCheck className="h-4 w-4 text-primary" />
                {t('setup.card.advanced.guardrailsTitle')}
              </div>
              <p className="mt-2">{t('setup.card.advanced.guardrailsDescription')}</p>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}

function StatusCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof FolderOpen
  label: string
  value: string
}) {
  return (
    <Card className="workspace-panel-soft">
      <CardContent className="flex items-center gap-3 pt-6">
        <div className="grid h-11 w-11 place-items-center rounded-2xl border border-border bg-muted/50">
          <Icon className="h-5 w-5 text-primary" />
        </div>
        <div>
          <p className="workspace-kicker">{label}</p>
          <p className="mt-1 font-medium tracking-[-0.015em] text-foreground">{value}</p>
        </div>
      </CardContent>
    </Card>
  )
}
