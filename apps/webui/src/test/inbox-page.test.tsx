import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/lib/i18n'
import { InboxPage } from '@/pages/inbox-page'

const mocks = vi.hoisted(() => ({
  listWatchSources: vi.fn(async () => []),
  listStrategyPacks: vi.fn(async () => ({
    items: [{ id: 'travel', name: 'Travel Pack', description: '', categories: ['旅行'], workers: 1, review_confidence_threshold: 0.8, default_rule_ids: [], default_template_patterns: [] }],
    active_strategy_pack_id: 'travel',
  })),
  upsertWatchSource: vi.fn(async () => ({ id: 'source-1', name: 'Inbox', input_root: '/tmp/inbox', enabled: true, strategy_pack_id: 'travel' })),
  scanInbox: vi.fn(async () => [
    {
      id: 'batch-1',
      watch_source_id: 'source-1',
      source_name: 'Inbox',
      input_root: '/tmp/inbox',
      file_count: 2,
      file_paths: ['/tmp/inbox/a.png', '/tmp/inbox/b.png'],
      strategy_pack_id: 'travel',
      strategy_pack: {
        id: 'travel',
        name: 'Travel Pack',
        description: 'Trip defaults',
        categories: ['旅行'],
        workers: 1,
        review_confidence_threshold: 0.8,
        default_rule_ids: [],
        default_template_patterns: ['{date}/{category}/{title}__{hash8}'],
      },
      analyze_ready: true,
      analyze_defaults: {
        model: 'gemini-3-flash-preview',
        categories: '旅行',
        workers: 1,
        max_files: 500,
        max_total_mb: 4096,
        max_file_mb: 128,
        offline: false,
      },
      analyze_action: {
        method: 'POST',
        path: '/api/inbox/analyze',
        payload: { watch_source_id: 'source-1', batch_id: 'batch-1', strategy_pack_id: 'travel' },
      },
    },
  ]),
  startInboxAnalyze: vi.fn(async () => ({
    job: { id: 'job-1', kind: 'analyze', status: 'queued', phase: 'queued', progress: 0 },
    job_id: 'job-1',
    mode: 'explicit_inbox_action',
    batch: {
      id: 'batch-1',
      watch_source_id: 'source-1',
      source_name: 'Inbox',
      input_root: '/tmp/inbox',
      file_count: 2,
      file_paths: ['/tmp/inbox/a.png', '/tmp/inbox/b.png'],
      strategy_pack_id: 'travel',
    },
    strategy_pack: {
      id: 'travel',
      name: 'Travel Pack',
      description: 'Trip defaults',
      categories: ['旅行'],
      workers: 1,
      review_confidence_threshold: 0.8,
      default_rule_ids: [],
      default_template_patterns: ['{date}/{category}/{title}__{hash8}'],
    },
    review_next: { review_queue_path: '/api/jobs/job-1/review-queue', execute_allowed: false },
  })),
}))

vi.mock('@/lib/api', () => ({
  listWatchSources: mocks.listWatchSources,
  listStrategyPacks: mocks.listStrategyPacks,
  upsertWatchSource: mocks.upsertWatchSource,
  scanInbox: mocks.scanInbox,
  startInboxAnalyze: mocks.startInboxAnalyze,
}))

describe('InboxPage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.lang = 'en'
  })

  it('renders watch sources and inbox scan results', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <I18nProvider>
          <Routes>
            <Route element={<InboxPage />} path="/" />
            <Route element={<div>Analyze placeholder</div>} path="/analyze" />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: 'Fileorganize Inbox' })).toBeInTheDocument()
    expect(screen.getByText(/Inbox is only the intake desk/i)).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Source name'), { target: { value: 'Inbox' } })
    fireEvent.change(screen.getByPlaceholderText('Input root'), { target: { value: '/tmp/inbox' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Source' }))

    await waitFor(() => {
      expect(mocks.upsertWatchSource).toHaveBeenCalledTimes(1)
    })

    const analyzeSourceLink = await screen.findByRole('link', { name: 'Start Analyze' })
    expect(analyzeSourceLink).toHaveAttribute('href', expect.stringContaining('/analyze?'))
    expect(analyzeSourceLink).toHaveAttribute('href', expect.stringContaining('source=inbox'))
    expect(analyzeSourceLink).toHaveAttribute('href', expect.stringContaining('strategyPack=travel'))

    fireEvent.click(screen.getByRole('button', { name: 'Scan Fileorganize Inbox' }))
    expect(await screen.findByText('Inbox')).toBeInTheDocument()
    expect(screen.getByText(/naming template preview/i)).toBeInTheDocument()
    const analyzeBatchLink = screen.getByRole('link', { name: 'Open Analyze Checklist' })
    expect(analyzeBatchLink).toHaveAttribute('href', expect.stringContaining('batchId=batch-1'))

    fireEvent.click(screen.getByRole('button', { name: 'Analyze This Batch' }))

    await waitFor(() => {
      expect(mocks.startInboxAnalyze).toHaveBeenCalledWith({
        watchSourceId: 'source-1',
        strategyPackId: 'travel',
      })
    })
    expect(await screen.findByText('Analyze placeholder')).toBeInTheDocument()
  })

  it('renders localized inbox copy when the locale is switched to zh-CN', async () => {
    window.localStorage.setItem('fileorganize.locale', 'zh-CN')

    render(
      <MemoryRouter initialEntries={['/']}>
        <I18nProvider>
          <Routes>
            <Route element={<InboxPage />} path="/" />
            <Route element={<div>Analyze placeholder</div>} path="/analyze" />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'Fileorganize Inbox' })).toBeInTheDocument()
    expect(screen.getByText(/你可以把 Fileorganize Inbox 理解成收件台/)).toBeInTheDocument()
    expect(screen.getByPlaceholderText('来源名称')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存来源' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '扫描 Fileorganize Inbox' })).toBeInTheDocument()
  })
})
