import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RollbackPage } from '@/pages/rollback-page'
import { I18nProvider } from '@/lib/i18n'
import type { Job } from '@/lib/types'

const mocks = vi.hoisted(() => ({
  createRollbackJobMock: vi.fn(async () => undefined),
  getJobMock: vi.fn<() => Promise<Job | undefined>>(async () => undefined),
  getRuntimeSettingsMock: vi.fn(async () => ({
    workspace_root: '/tmp/workspace',
    runtime_env_path: '/tmp/workspace/.fileman/env/runtime.env',
    input_root: '/tmp/workspace/data/raw',
    output_root: '/tmp/workspace/data/organized',
    allowed_root: '/tmp/workspace/data/raw,/tmp/workspace/data/organized',
    manifest_root: '/tmp/workspace/.fileman/manifests',
    artifact_root: '/tmp/workspace/.fileman/artifacts',
    has_api_key: true,
    api_key_masked: '***',
    api_key_source: 'env', // pragma: allowlist secret
    api_key_status: 'configured', // pragma: allowlist secret
    model: 'gemini-3-flash-preview',
    model_source: 'env',
    active_strategy_pack_id: '',
    input_root_exists: true,
    output_root_exists: true,
    ready: true,
    analyze_defaults: {
      workers: 1,
      categories: ['work'],
      max_files: 500,
      max_total_mb: 4096,
      max_file_mb: 128,
    },
    missing: [],
    warnings: [],
    checked_at: '2026-04-01T00:00:00Z',
  })),
  refreshMock: vi.fn(async () => undefined),
  liveJob: null as Job | null,
}))

vi.mock('@/lib/api', () => ({
  createRollbackJob: mocks.createRollbackJobMock,
  getJob: mocks.getJobMock,
  getRuntimeSettings: mocks.getRuntimeSettingsMock,
}))

vi.mock('@/hooks/use-live-job', () => ({
  useLiveJob: () => ({
    job: mocks.liveJob,
    events: [],
    state: 'open' as const,
    refresh: mocks.refreshMock,
  }),
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

function renderRollbackPage(initialEntry: string) {
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<RollbackPage />} path="/rollback/:jobId" />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
}

describe('RollbackPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.liveJob = null
    window.localStorage.clear()
    document.documentElement.lang = 'en'
  })

  it('surfaces rollback context while keeping real rollback locked by default', async () => {
    mocks.getJobMock.mockResolvedValueOnce(
      makeJob({
        id: 'source-job',
        status: 'succeeded',
        manifest_path: '/tmp/workspace/.fileman/manifests/manifest.jsonl',
        rollback_manifest_path: '/tmp/workspace/.fileman/manifests/rollback.jsonl',
        summary: {
          total: 2,
          with_error: 0,
          by_media_type: {},
          by_category: {},
          by_status: {},
          error_codes: {},
          dry_run: true,
          allowed_root: '/tmp/workspace/data/raw,/tmp/workspace/data/organized',
        },
      }),
    )

    renderRollbackPage('/rollback/source-job')

    expect(await screen.findByRole('heading', { name: 'Rollback Recovery' })).toBeInTheDocument()
    expect(await screen.findByText('Preview Approved')).toBeInTheDocument()
    expect(screen.getByText('Rollback Is Locked')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Roll Back Files' })).toBeDisabled()
  })
})
