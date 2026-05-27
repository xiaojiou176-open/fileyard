import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApplyPage } from '@/pages/apply-page'
import { I18nProvider } from '@/lib/i18n'
import type { Job } from '@/lib/types'

const mocks = vi.hoisted(() => ({
  getJobMock: vi.fn<() => Promise<Job | undefined>>(async () => undefined),
  createApplyJobMock: vi.fn(async () => undefined),
  refreshMock: vi.fn(async () => undefined),
  preloadRouteMock: vi.fn(async () => undefined),
  liveJob: null as Job | null,
}))

vi.mock('@/lib/api', () => ({
  createApplyJob: mocks.createApplyJobMock,
  getJob: mocks.getJobMock,
}))

vi.mock('@/hooks/use-live-job', () => ({
  useLiveJob: () => ({
    job: mocks.liveJob,
    events: [],
    state: 'open' as const,
    refresh: mocks.refreshMock,
    error: '',
  }),
}))

vi.mock('@/routes/lazy-routes', () => ({
  createRouteIntentPrefetchHandlers: () => ({}),
  preloadRoute: mocks.preloadRouteMock,
}))

function makeJob(overrides: Partial<Job>): Job {
  return {
    id: 'job-1',
    kind: 'analyze',
    status: 'queued',
    phase: 'queued',
    progress: 0,
    ...overrides,
  }
}

function renderApplyPage(initialEntry: string) {
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<ApplyPage />} path="/apply/:jobId" />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
}

describe('ApplyPage actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.liveJob = null
    window.localStorage.clear()
    document.documentElement.lang = 'en'
  })

  it('disables execute and dry-run actions when current job is cancelling', async () => {
    mocks.getJobMock.mockResolvedValueOnce(
      makeJob({
        id: 'source-job',
        status: 'succeeded',
        summary: {
          total: 1,
          with_error: 0,
          by_media_type: {},
          by_category: {},
          by_status: {},
          error_codes: {},
          dry_run: true,
        },
      }),
    )
    mocks.liveJob = makeJob({
      id: 'apply-live',
      kind: 'apply',
      status: 'cancelling',
      phase: 'cancel_requested',
      progress: 0.4,
    })

    renderApplyPage('/apply/source-job')

    expect(await screen.findByRole('button', { name: 'Preview Changes' })).toBeDisabled()
    expect(await screen.findByRole('button', { name: 'Organize Now' })).toBeDisabled()
  })

  it('renders translated apply copy when locale switches to zh-CN', async () => {
    window.localStorage.setItem('fileman.locale', 'zh-CN')
    mocks.getJobMock.mockResolvedValueOnce(
      makeJob({
        id: 'source-job',
        status: 'succeeded',
        summary: {
          total: 3,
          with_error: 1,
          by_media_type: {},
          by_category: {},
          by_status: {},
          error_codes: {},
          dry_run: true,
        },
      }),
    )

    renderApplyPage('/apply/source-job')

    expect(await screen.findByRole('heading', { name: '执行确认' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预览变更' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '立即整理' })).toBeInTheDocument()
    expect(screen.getByText('安全护栏')).toBeInTheDocument()
  })
})
