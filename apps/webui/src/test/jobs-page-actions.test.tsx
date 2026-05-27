import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/lib/i18n'
import { JobsPage } from '@/pages/jobs-page'
import type { Job } from '@/lib/types'

const mocks = vi.hoisted(() => ({
  refreshJobsMock: vi.fn(async () => undefined),
  refreshSelectedMock: vi.fn(async () => undefined),
  cancelJobMock: vi.fn(async () => undefined),
  retryJobMock: vi.fn(async () => undefined),
  mockJobs: [] as Job[],
  mockSelectedJob: null as Job | null,
}))

vi.mock('@/hooks/use-live-jobs', () => ({
  useLiveJobs: () => ({
    jobs: mocks.mockJobs,
    state: 'open' as const,
    error: '',
    refresh: mocks.refreshJobsMock,
  }),
}))

vi.mock('@/hooks/use-live-job', () => ({
  useLiveJob: () => ({
    job: mocks.mockSelectedJob,
    events: [],
    state: 'open' as const,
    refresh: mocks.refreshSelectedMock,
    error: '',
  }),
}))

vi.mock('@/lib/api', () => ({
  cancelJob: mocks.cancelJobMock,
  retryJob: mocks.retryJobMock,
}))

vi.mock('@/routes/lazy-routes', () => ({
  createRouteIntentPrefetchHandlers: () => ({}),
}))

function createDeferred<T>() {
  let resolve: (value: T) => void = () => undefined
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

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

function renderJobsPage() {
  render(
    <I18nProvider>
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

describe('JobsPage status actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.mockJobs = []
    mocks.mockSelectedJob = null
    window.localStorage.clear()
    document.documentElement.lang = 'en'
  })

  it('shows cancelling state and keeps cancel action disabled', async () => {
    const job = makeJob({ id: 'job-cancelling', status: 'cancelling', phase: 'cancel_requested', progress: 0.6 })
    mocks.mockJobs = [job]
    mocks.mockSelectedJob = job

    renderJobsPage()

    expect((await screen.findAllByText('cancelling')).length).toBeGreaterThan(0)
    expect(await screen.findByRole('button', { name: 'Cancelling...' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Retry Job' })).not.toBeInTheDocument()
  })

  it('prevents repeated cancel clicks while request is in flight', async () => {
    const job = makeJob({ id: 'job-running', status: 'running', phase: 'apply' })
    const pendingCancel = createDeferred<undefined>()
    mocks.mockJobs = [job]
    mocks.mockSelectedJob = job
    mocks.cancelJobMock.mockReturnValueOnce(pendingCancel.promise)

    renderJobsPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Cancel Job' }))
    expect(mocks.cancelJobMock).toHaveBeenCalledTimes(1)

    const cancellingButton = await screen.findByRole('button', { name: 'Cancelling...' })
    expect(cancellingButton).toBeDisabled()
    fireEvent.click(cancellingButton)
    expect(mocks.cancelJobMock).toHaveBeenCalledTimes(1)

    pendingCancel.resolve(undefined)
    await waitFor(() => {
      expect(mocks.refreshJobsMock).toHaveBeenCalledTimes(1)
    })
  })

  it('prevents repeated retry clicks while request is in flight', async () => {
    const job = makeJob({ id: 'job-failed', status: 'failed', phase: 'apply' })
    const pendingRetry = createDeferred<undefined>()
    mocks.mockJobs = [job]
    mocks.mockSelectedJob = job
    mocks.retryJobMock.mockReturnValueOnce(pendingRetry.promise)

    renderJobsPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Retry Job' }))
    expect(mocks.retryJobMock).toHaveBeenCalledTimes(1)

    const retryingButton = await screen.findByRole('button', { name: 'Retrying...' })
    expect(retryingButton).toBeDisabled()
    fireEvent.click(retryingButton)
    expect(mocks.retryJobMock).toHaveBeenCalledTimes(1)

    pendingRetry.resolve(undefined)
    await waitFor(() => {
      expect(mocks.refreshJobsMock).toHaveBeenCalledTimes(1)
    })
  }, 10000)

  it('renders localized jobs copy when locale switches to zh-CN', async () => {
    const job = makeJob({ id: 'job-running', status: 'running', phase: 'apply' })
    mocks.mockJobs = [job]
    mocks.mockSelectedJob = job
    window.localStorage.setItem('fileorganize.locale', 'zh-CN')

    renderJobsPage()

    expect(await screen.findByRole('heading', { name: '作业与历史' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索 job id / phase / status')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '刷新' }).length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: '当前作业' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消作业' })).toBeInTheDocument()
  })
})
