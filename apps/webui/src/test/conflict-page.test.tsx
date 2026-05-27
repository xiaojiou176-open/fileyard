import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/lib/i18n'
import { ConflictPage } from '@/pages/conflict-page'

const mocks = vi.hoisted(() => ({
  getManifestRows: vi.fn(async () => [
    {
      id: 'row-1',
      row_id: 'row-1',
      file_name: 'trip-a.png',
      media_type: 'image',
      category: 'travel',
      title: 'Trip A',
      tags: [],
      status: 'pending',
      error_code: '',
      target_path: '',
      target_suggestion: '',
      confidence: 0.9,
      original_path: '/tmp/trip-a.png',
      notes: '',
      ignore: false,
      metadata: {},
      review_bucket: 'conflict',
    },
  ]),
  getManifestConflicts: vi.fn(async () => [
    {
      id: 'conflict-1',
      row_id: 'row-1',
      type: 'duplicate_target',
      severity: 'error',
      status: 'open',
      reason: 'Two rows point to the same target path.',
      source_path: '/tmp/raw/trip-a.png',
      target_path: '/tmp/organized/trip-a.png',
      suggested_target: '/tmp/organized/trip-a__dedupe.png',
    },
  ]),
  resolveManifestConflict: vi.fn(async () => true),
}))

vi.mock('@/lib/api', () => ({
  getManifestRows: mocks.getManifestRows,
  getManifestConflicts: mocks.getManifestConflicts,
  resolveManifestConflict: mocks.resolveManifestConflict,
}))

vi.mock('@/routes/lazy-routes', () => ({
  createRouteIntentPrefetchHandlers: () => ({}),
}))

vi.mock('@/components/manifest/preview-drawer', () => ({
  PreviewDrawer: () => null,
}))

function renderConflictPage(initialEntry = '/conflicts/job-1') {
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<ConflictPage />} path="/conflicts/:jobId" />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
}

describe('ConflictPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    document.documentElement.lang = 'en'
  })

  it('renders localized conflict controls when locale switches to zh-CN', async () => {
    window.localStorage.setItem('fileman.locale', 'zh-CN')

    renderConflictPage()

    expect(await screen.findByRole('heading', { name: '冲突中心' })).toBeInTheDocument()
    expect(screen.getByText('冲突总数')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索冲突原因或路径')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新冲突' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接受选中项' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '忽略选中项' })).toBeInTheDocument()
  })
})
