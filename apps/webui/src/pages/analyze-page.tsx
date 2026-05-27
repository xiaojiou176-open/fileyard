import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, FolderSearch, Upload } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { createAnalyzeJob, getRuntimeSettings, listStrategyPacks, type RuntimeSettings } from '@/lib/api'
import type { InputMode, StrategyPack } from '@/lib/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { LogPanel } from '@/components/observability/log-panel'
import { useLiveJob } from '@/hooks/use-live-job'
import { useI18n } from '@/lib/i18n'
import { cn, progressToPercent } from '@/lib/utils'
import { createRouteIntentPrefetchHandlers, preloadRoute } from '@/routes/lazy-routes'

const IS_TEST_ENV = import.meta.env.MODE === 'test'

export function AnalyzePage() {
  const { t } = useI18n()
  const [searchParams] = useSearchParams()
  const [step, setStep] = useState(1)
  const [mode, setMode] = useState<InputMode>('directory')
  const [directoryPath, setDirectoryPath] = useState('~/.fileorganize/workspaces/default/data/raw')
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([])
  const [model, setModel] = useState('gemini-3-flash-preview')
  const [workers, setWorkers] = useState('1')
  const [offline, setOffline] = useState(false)
  const [categories, setCategories] = useState('work,travel,docs,product,other')
  const [maxFiles, setMaxFiles] = useState('500')
  const [maxTotalMb, setMaxTotalMb] = useState('4096')
  const [maxFileMb, setMaxFileMb] = useState('128')
  const [submitting, setSubmitting] = useState(false)
  const [currentJobId, setCurrentJobId] = useState('')
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null)
  const [strategyPacks, setStrategyPacks] = useState<StrategyPack[]>([])
  const [selectedStrategyPackId, setSelectedStrategyPackId] = useState('')
  const lastJobSignalRef = useRef('')
  const uploadInputRef = useRef<HTMLInputElement | null>(null)
  const folderInputRef = useRef<HTMLInputElement | null>(null)

  const { job, events, state, refresh } = useLiveJob(currentJobId, currentJobId.length > 0)

  const canNext = useMemo(() => {
    if (step === 1) {
      return mode === 'directory' ? directoryPath.trim().length > 0 : uploadedFiles.length > 0
    }
    if (step === 2) {
      return model.length > 0 && Number(workers) > 0 && categories.trim().length > 0
    }
    return true
  }, [categories, directoryPath, mode, model, step, uploadedFiles.length, workers])

  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute('webkitdirectory', '')
      folderInputRef.current.setAttribute('directory', '')
    }
  }, [])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const [next, packs] = await Promise.all([getRuntimeSettings(), listStrategyPacks()])
        if (!alive) {
          return
        }
        setRuntimeSettings(next)
        setStrategyPacks(packs.items)
        setDirectoryPath(next.input_root)
        setModel(next.model || 'gemini-3-flash-preview')
        setWorkers(String(next.analyze_defaults.workers || 1))
        setCategories(next.analyze_defaults.categories.join(',') || 'work,travel,docs,product,other')
        setMaxFiles(String(next.analyze_defaults.max_files || 0))
        setMaxTotalMb(String(next.analyze_defaults.max_total_mb || 0))
        setMaxFileMb(String(next.analyze_defaults.max_file_mb || 0))
        const nextPackId = searchParams.get('strategyPack') || next.active_strategy_pack_id || packs.active_strategy_pack_id || ''
        setSelectedStrategyPackId(nextPackId)
        const inboxJobId = searchParams.get('jobId') ?? ''
        if (inboxJobId) {
          setCurrentJobId(inboxJobId)
          setStep(3)
          setSubmitting(true)
        }
        if (searchParams.get('inputRoot')) {
          setDirectoryPath(searchParams.get('inputRoot') || next.input_root)
        }
        if (nextPackId) {
          const selectedPack = packs.items.find((pack) => pack.id === nextPackId)
          if (selectedPack) {
            setModel(selectedPack.model || next.model || 'gemini-3-flash-preview')
            setWorkers(String(selectedPack.workers || next.analyze_defaults.workers || 1))
            setCategories(selectedPack.categories.join(',') || next.analyze_defaults.categories.join(',') || 'work,travel,docs,product,other')
          }
        }
        if (next.has_api_key && next.ready) {
          setOffline(false)
        }
      } catch {
        if (alive) {
          setRuntimeSettings(null)
        }
      }
    })()
    return () => {
      alive = false
    }
  }, [searchParams])

  useEffect(() => {
    const status = job?.status ?? ''
    const nextSignal = job?.id ? `${job.id}:${status}` : ''
    if (!status || !nextSignal || nextSignal === lastJobSignalRef.current) {
      return
    }
    lastJobSignalRef.current = nextSignal

    if (status === 'succeeded') {
      const timer = window.setTimeout(() => {
        setSubmitting(false)
        setStep(4)
        toast.success(t('analyze.toast.success'))
      }, 0)
      return () => {
        window.clearTimeout(timer)
      }
    }

    if (status === 'failed') {
      const timer = window.setTimeout(() => {
        setSubmitting(false)
        toast.error(job?.latest_error ?? t('analyze.toast.failed'))
      }, 0)
      return () => {
        window.clearTimeout(timer)
      }
    }
  }, [job, t])

  async function runAnalyze() {
    setSubmitting(true)
    setStep(3)
    try {
      const created = await createAnalyzeJob({
        inputMode: mode,
        inputDirectory: directoryPath,
        files: uploadedFiles,
        model,
        categories,
        workers: Number(workers),
        maxFiles: Number(maxFiles),
        maxTotalMb: Number(maxTotalMb),
        maxFileMb: Number(maxFileMb),
        offline,
      })
      setCurrentJobId(created.id)
    } catch (error) {
      setSubmitting(false)
      toast.error(error instanceof Error ? error.message : 'Analyze submission failed.')
    }
  }

  const progress = progressToPercent(job?.progress ?? 0)
  const source = searchParams.get('source') ?? ''
  const inboxBatchId = searchParams.get('batchId') ?? ''
  const watchSourceId = searchParams.get('watchSourceId') ?? ''
  const selectedStrategyPack = useMemo(
    () => strategyPacks.find((pack) => pack.id === selectedStrategyPackId) ?? null,
    [selectedStrategyPackId, strategyPacks],
  )
  const reviewPrefetch = createRouteIntentPrefetchHandlers('review')
  const applyPrefetch = createRouteIntentPrefetchHandlers('apply')
  const runAnalyzePrefetch = createRouteIntentPrefetchHandlers('review', 'manifest', 'apply', 'conflicts')
  const stepLabels = [t('analyze.step.inputSource'), t('analyze.step.parameters'), t('analyze.step.run'), t('analyze.step.review')]

  function applyStrategyPack(packId: string) {
    setSelectedStrategyPackId(packId)
    const selectedPack = strategyPacks.find((pack) => pack.id === packId)
    if (!selectedPack) {
      return
    }
    setModel(selectedPack.model || model)
    setWorkers(String(selectedPack.workers || workers))
    setCategories(selectedPack.categories.join(',') || categories)
  }

  useEffect(() => {
    if (!IS_TEST_ENV && step >= 3) {
      void preloadRoute('review')
      void preloadRoute('manifest')
      void preloadRoute('apply')
    }
  }, [step])

  return (
    <div className="space-y-6">
      <section className="workspace-panel relative overflow-hidden p-6 sm:p-8">
        <div className="workspace-grid pointer-events-none absolute inset-0 opacity-[0.12]" />
        <div className="relative max-w-3xl space-y-4">
          <p className="workspace-kicker">{t('analyze.page.title')}</p>
          <h1 className="text-3xl font-semibold tracking-[-0.04em] text-foreground sm:text-4xl">{t('analyze.page.title')}</h1>
        </div>
      </section>
      <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>{t('analyze.flow.title')}</CardTitle>
            <CardDescription>{t('analyze.flow.description')}</CardDescription>
          </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-4">
            {stepLabels.map((name, index) => {
              const idx = index + 1
              const active = step === idx
              const done = step > idx
              return (
                <Button
                  className={cn(
                    'rounded-xl border px-3 py-2 text-left text-sm transition-colors',
                    active && 'border-primary bg-primary/10 text-foreground',
                    done && 'border-success/60 bg-success/10',
                    !active && !done && 'border-border text-foreground/90',
                  )}
                  disabled={submitting && idx !== 3}
                  key={name}
                  onClick={() => setStep(idx)}
                  type="button"
                  variant="ghost"
                >
                  <p className="text-xs opacity-70">Step {idx}</p>
                  <p className="font-medium">{name}</p>
                </Button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {source === 'inbox' ? (
        <Alert className="border-primary/20 bg-primary/5">
          <AlertTitle>{t('analyze.alert.handoffTitle')}</AlertTitle>
          <AlertDescription>
            {t('analyze.alert.handoffDescription', {
              batchId: inboxBatchId ? ` (${inboxBatchId})` : '',
              watchSourceId: watchSourceId ? ` for source ${watchSourceId}` : '',
            })}
          </AlertDescription>
        </Alert>
      ) : null}

      {step === 1 ? (
        <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>{t('analyze.step1.title')}</CardTitle>
            <CardDescription>{t('analyze.step1.description')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Tabs onValueChange={(value) => setMode(value as InputMode)} value={mode}>
              <TabsList>
                <TabsTrigger value="directory">Connected Folder</TabsTrigger>
                <TabsTrigger value="upload">Upload</TabsTrigger>
              </TabsList>
            </Tabs>

            {mode === 'directory' ? (
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="dir-path">
                  {t('analyze.field.connectedSourceFolder')}
                </label>
                <Input id="dir-path" onChange={(event) => setDirectoryPath(event.target.value)} value={directoryPath} />
                <p className="text-xs text-muted-foreground">{t('analyze.field.connectedSourceHint')}</p>
                {!runtimeSettings?.ready && !offline ? (
                  <Alert className="border-warning/30 bg-warning/10">
                    <AlertTitle>{t('analyze.alert.setupIncomplete.title')}</AlertTitle>
                    <AlertDescription>{t('analyze.alert.setupIncomplete.description')}</AlertDescription>
                  </Alert>
                ) : null}
              </div>
            ) : (
              <div className="rounded-[1.2rem] border border-dashed border-border/80 bg-muted/25 p-6">
                <div className="flex flex-col items-center gap-3 text-center">
                  <div className="rounded-full border border-border bg-background p-2">
                    <Upload className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium">{t('analyze.upload.title')}</p>
                    <p className="text-xs text-muted-foreground">{t('analyze.upload.description')}</p>
                  </div>
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button
                      onClick={() => {
                        folderInputRef.current?.click()
                      }}
                      size="sm"
                      type="button"
                      variant="secondary"
                    >
                      {t('analyze.upload.chooseFolder')}
                    </Button>
                    <Button
                      onClick={() => {
                        uploadInputRef.current?.click()
                      }}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      {t('analyze.upload.chooseFiles')}
                    </Button>
                  </div>
                  <input
                    accept="image/*,video/*,audio/*,application/pdf,.doc,.docx,.txt"
                    className="sr-only"
                    multiple
                    onChange={(event) => setUploadedFiles(Array.from(event.target.files ?? []))}
                    ref={uploadInputRef}
                    type="file"
                  />
                  <input
                    accept="image/*,video/*,audio/*,application/pdf,.doc,.docx,.txt"
                    className="sr-only"
                    multiple
                    onChange={(event) => setUploadedFiles(Array.from(event.target.files ?? []))}
                    ref={folderInputRef}
                    type="file"
                  />
                  <p className="text-xs text-muted-foreground">{t('analyze.upload.selectedCount', { count: uploadedFiles.length })}</p>
                  {uploadedFiles.length > 0 ? (
                    <div className="flex flex-wrap justify-center gap-2">
                      {uploadedFiles.slice(0, 3).map((file) => {
                        const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath
                        return (
                          <Badge key={`${file.name}-${relativePath || ''}`} variant="secondary">
                            {relativePath || file.name}
                          </Badge>
                        )
                      })}
                      {uploadedFiles.length > 3 ? <Badge variant="outline">+{uploadedFiles.length - 3}</Badge> : null}
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {step === 2 ? (
        <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>Step 2 - Configure Parameters</CardTitle>
            <CardDescription>Choose the AI and batch settings for this run. Most people only need to check the model, speed, and file limits before Fileorganize drafts a reviewable manifest.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="model">
                AI Model
              </label>
              <Select id="model" onValueChange={setModel} value={model}>
                <option value="gemini-3-flash-preview">gemini-3-flash-preview</option>
                <option value="gemini-3.1-pro-preview">gemini-3.1-pro-preview</option>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="analyze-pack">
                Strategy Pack
              </label>
              <Select id="analyze-pack" onValueChange={applyStrategyPack} value={selectedStrategyPackId}>
                {strategyPacks.map((pack) => (
                  <option key={pack.id} value={pack.id}>
                    {pack.name}
                  </option>
                ))}
              </Select>
              <p className="text-xs text-muted-foreground">A strategy pack is a starter template for Analyze. It changes defaults like model, categories, and worker count for this run, but Review still decides what actually moves forward.</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="workers">
                Parallel Workers
              </label>
              <Input id="workers" onChange={(event) => setWorkers(event.target.value)} value={workers} />
              <p className="text-xs text-muted-foreground">Higher values run faster but use more local resources. The default of 1 is safer; raise it only when you are processing larger batches.</p>
            </div>
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium" htmlFor="categories">
                Preferred Categories
              </label>
              <Textarea id="categories" onChange={(event) => setCategories(event.target.value)} value={categories} />
              <p className="text-xs text-muted-foreground">This tells AI which category buckets you expect most often, for example `travel,family,docs`. It is a hint for this run, not a hidden internal enum.</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="max-files">
                File Count Limit
              </label>
              <Input id="max-files" onChange={(event) => setMaxFiles(event.target.value)} value={maxFiles} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="max-total-mb">
                Total Size Limit (MB)
              </label>
              <Input id="max-total-mb" onChange={(event) => setMaxTotalMb(event.target.value)} value={maxTotalMb} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="max-file-mb">
                Single File Limit (MB)
              </label>
              <Input id="max-file-mb" onChange={(event) => setMaxFileMb(event.target.value)} value={maxFileMb} />
            </div>
            <div className="flex items-center gap-3">
              <Switch checked={offline} onCheckedChange={setOffline} />
              <div>
                <p className="text-sm font-medium">Offline Preview</p>
                <p className="text-xs text-muted-foreground">Validate the inputs and workflow without calling AI. This is best for a first rehearsal or local debugging.</p>
              </div>
            </div>
            {selectedStrategyPack ? (
              <div className="rounded-[1.2rem] border border-border/70 bg-muted/20 p-4 md:col-span-2">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium">{selectedStrategyPack.name}</p>
                  <Badge variant="secondary">template only</Badge>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {selectedStrategyPack.description || 'This pack gives repeated batch types a familiar starting recipe before you review anything.'}
                </p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">model: {selectedStrategyPack.model || 'keep current default'}</Badge>
                  <Badge variant="outline">workers: {selectedStrategyPack.workers}</Badge>
                  <Badge variant="outline">categories: {selectedStrategyPack.categories.join(', ') || 'none'}</Badge>
                  <Badge variant="outline">review threshold: {Math.round(selectedStrategyPack.review_confidence_threshold * 100)}%</Badge>
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  In plain language: the pack shapes how Fileorganize drafts the first pass. It does not become a second config system, and it never skips Review, dry-run, or manual approval.
                </p>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {step === 3 ? (
        <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>Step 3 - Run Analyze</CardTitle>
            <CardDescription>Use SSE streaming by default. If streaming is unavailable, the UI falls back explicitly and keeps the execution state legible.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert className="workspace-panel-soft border-primary/20 bg-primary/5">
              <AlertTitle>Run Strategy</AlertTitle>
              <AlertDescription>
                Analyze runs input preflight first, then starts the job. Failures are written to manifest `error_code` instead of being swallowed.
              </AlertDescription>
            </Alert>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span>Progress</span>
                <span>{progress}%</span>
              </div>
              <Progress value={progress} />
              <p className="text-xs text-muted-foreground">
                {job ? `${job.kind.toUpperCase()} | ${job.phase}` : 'Waiting to start job'} | {state === 'open' ? 'SSE connected' : 'SSE fallback'}
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button {...runAnalyzePrefetch} disabled={submitting} onClick={() => void runAnalyze()}>
                <FolderSearch className="mr-2 h-4 w-4" />
                {submitting ? 'Analyzing...' : 'Run Analyze'}
              </Button>
              <Button disabled={submitting} onClick={() => setStep(2)} variant="outline">
                Back to Parameters
              </Button>
            </div>

            <LogPanel
              connectionState={state}
              description="Filter by level, auto-scroll, and copy log output."
              events={events}
              onRefresh={() => {
                void refresh()
              }}
              title="Analyze Logs"
            />
          </CardContent>
        </Card>
      ) : null}

      {step === 4 ? (
        <Card className="workspace-panel">
          <CardHeader>
            <CardTitle>Step 4 - Review Manifest</CardTitle>
            <CardDescription>Review the manifest before entering Apply. Do not skip this step.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-[1.15rem] border border-border/70 bg-muted/20 p-4">
                <p className="workspace-kicker">Rows</p>
                <p className="workspace-value mt-2 text-2xl">{job?.summary?.total ?? 0}</p>
              </div>
              <div className="rounded-[1.15rem] border border-border/70 bg-muted/20 p-4">
                <p className="workspace-kicker">Errors</p>
                <p className="workspace-value mt-2 text-2xl text-warning-ink">{job?.summary?.with_error ?? 0}</p>
              </div>
              <div className="rounded-[1.15rem] border border-border/70 bg-muted/20 p-4">
                <p className="workspace-kicker">Ready to Apply</p>
                <p className="workspace-value mt-2 text-2xl text-success">{Math.max((job?.summary?.total ?? 0) - (job?.summary?.with_error ?? 0), 0)}</p>
              </div>
            </div>
            <Alert className="border-success/20 bg-success/10">
              <AlertTitle className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4" />
                Analyze Complete
              </AlertTitle>
              <AlertDescription>Recommended next step: resolve manifest exceptions before entering Apply dry-run.</AlertDescription>
            </Alert>
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link {...reviewPrefetch} to={`/review/${currentJobId}`}>
                  Open Review Queue
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link {...applyPrefetch} to={`/apply/${currentJobId}`}>
                  Go to Apply
                </Link>
              </Button>
              <Badge variant="outline">Mode: {mode}</Badge>
              {selectedStrategyPack ? <Badge variant="outline">Pack: {selectedStrategyPack.name}</Badge> : null}
              {source === 'inbox' ? <Badge variant="secondary">Launched from Inbox</Badge> : null}
            </div>
            <p className="text-sm text-muted-foreground">
              Analyze drafted the manifest. The next human decision still happens in Review Queue, where Copilot, collections, and learning stay review-only and overlay-only until you choose the next action.
            </p>
          </CardContent>
        </Card>
      ) : null}

      <div className="flex gap-3">
        <Button disabled={step === 1 || submitting} onClick={() => setStep((prev) => Math.max(1, prev - 1))} variant="outline">
          Previous
        </Button>
        <Button disabled={!canNext || step === 4 || submitting} onClick={() => setStep((prev) => Math.min(4, prev + 1))}>
          Next
        </Button>
      </div>
    </div>
  )
}
