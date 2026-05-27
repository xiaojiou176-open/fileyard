import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { AnalyzePage } from '@/pages/analyze-page'

const mocks = vi.hoisted(() => ({
  createAnalyzeJob: vi.fn(),
  getRuntimeSettings: vi.fn(async () => ({
    workspace_root: '/tmp/workspace',
    runtime_env_path: '/tmp/workspace/.env',
    input_root: '/tmp/default-inbox',
    output_root: '/tmp/output',
    allowed_root: '/tmp',
    manifest_root: '/tmp/workspace/.fileorganize/manifests',
    artifact_root: '/tmp/workspace/.fileorganize/artifacts',
    has_api_key: true,
    api_key_masked: '***',
    api_key_source: 'env', // pragma: allowlist secret
    api_key_status: 'configured', // pragma: allowlist secret
    model: 'gemini-3-flash-preview',
    model_source: 'env',
    active_strategy_pack_id: 'travel',
    input_root_exists: true,
    output_root_exists: true,
    ready: true,
    analyze_defaults: {
      workers: 1,
      categories: ['travel', 'docs'],
      max_files: 500,
      max_total_mb: 4096,
      max_file_mb: 128,
    },
    missing: [],
    warnings: [],
    checked_at: '2026-03-31T10:00:00Z',
  })),
  listStrategyPacks: vi.fn(async () => ({
    items: [
      {
        id: 'travel',
        name: 'Travel Pack',
        description: 'Optimized for trip photos and short travel documents.',
        categories: ['travel', 'receipts'],
        model: 'gemini-3.1-pro-preview',
        workers: 2,
        review_confidence_threshold: 0.85,
        default_rule_ids: [],
        default_template_patterns: [],
      },
    ],
    active_strategy_pack_id: 'travel',
  })),
  useLiveJob: vi.fn(() => ({
    job: null,
    events: [],
    state: 'unsupported',
    refresh: vi.fn(),
  })),
}))

vi.mock('@/lib/api', () => ({
  createAnalyzeJob: mocks.createAnalyzeJob,
  getRuntimeSettings: mocks.getRuntimeSettings,
  listStrategyPacks: mocks.listStrategyPacks,
}))

vi.mock('@/hooks/use-live-job', () => ({
  useLiveJob: mocks.useLiveJob,
}))

describe('AnalyzePage', () => {
  it('loads inbox handoff context and strategy-pack explanation', async () => {
    render(
      <MemoryRouter initialEntries={['/analyze?source=inbox&inputRoot=/tmp/inbox&strategyPack=travel&batchId=batch-1']}>
        <Routes>
          <Route element={<AnalyzePage />} path="/analyze" />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Handoff from Fileorganize Inbox')).toBeInTheDocument()
    expect(screen.getByDisplayValue('/tmp/inbox')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    expect(await screen.findByText('Optimized for trip photos and short travel documents.')).toBeInTheDocument()
    expect(screen.getByText(/the pack shapes how Fileorganize drafts the first pass/i)).toBeInTheDocument()
  })

  it('resumes an inbox-launched analyze job when jobId is present in the URL', async () => {
    mocks.useLiveJob.mockReturnValueOnce({
      job: { id: 'job-1', kind: 'analyze', status: 'running', phase: 'analyze.start', progress: 0.35, summary: { total: 0, with_error: 0, by_media_type: {}, by_category: {}, by_status: {}, error_codes: {} } },
      events: [],
      state: 'open',
      refresh: vi.fn(),
    } as never)

    render(
      <MemoryRouter initialEntries={['/analyze?source=inbox&inputRoot=/tmp/inbox&strategyPack=travel&batchId=batch-1&jobId=job-1']}>
        <Routes>
          <Route element={<AnalyzePage />} path="/analyze" />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Step 3 - Run Analyze')).toBeInTheDocument()
    expect(screen.getByText(/Waiting to start job|SSE connected|SSE fallback/i)).toBeInTheDocument()
  })
})
