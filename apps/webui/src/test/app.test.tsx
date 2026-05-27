import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/App'

const mocks = vi.hoisted(() => ({
  listJobs: vi.fn(async () => []),
  getRuntimeSettings: vi.fn(async () => ({
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
      categories: ['work', 'travel'],
      max_files: 500,
      max_total_mb: 4096,
      max_file_mb: 128,
    },
    missing: [],
    warnings: [],
    checked_at: '2026-03-31T00:00:00Z',
  })),
  useLiveJobs: vi.fn(() => ({
    jobs: [],
    state: 'open',
  })),
}))

vi.mock('@/lib/api', () => ({
  getRuntimeSettings: mocks.getRuntimeSettings,
  listJobs: mocks.listJobs,
}))

vi.mock('@/hooks/use-live-jobs', () => ({
  useLiveJobs: mocks.useLiveJobs,
}))

describe('App routes', () => {
  beforeEach(() => {
    document.head.innerHTML = '<meta name="description" content="seed" />'
  })

  it('renders dashboard hero text and syncs route metadata', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(
      await screen.findByRole(
        'heading',
        {
          name: /Use this page like a command center: confirm readiness, take the next step, and keep the current batch in the right stage\./,
        },
        { timeout: 5000 },
      ),
    ).toBeInTheDocument()
    expect(document.title).toBe('Fileman | Review-first local organizer')
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toContain('review-first local file organizer')
    expect(document.querySelector('meta[property="og:title"]')?.getAttribute('content')).toBe('Fileman | Review-first local organizer')
    expect(screen.getByRole('heading', { name: 'Agent & Builder Surfaces' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Main path' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Codex route' })).toHaveAttribute(
      'href',
      expect.stringContaining('/docs/codex_mcp.md'),
    )
  })

  it('keeps English as the default locale and lets the shell switch locales systematically', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    const localeSelect = await screen.findByRole('combobox', { name: 'Language' })
    expect(localeSelect).toHaveValue('en')
    expect(document.documentElement.lang).toBe('en')

    fireEvent.change(localeSelect, { target: { value: 'zh-CN' } })

    expect(document.documentElement.lang).toBe('zh-CN')
    expect(screen.getByRole('option', { name: '简体中文' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '作业中心' })).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', {
        name: /把这里当成当前批次的指挥台：先看是否 ready，再做下一步，并始终知道这批文件现在处在哪一站。/,
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Agent 与 Builder 接入面' })).toBeInTheDocument()
  })
})
