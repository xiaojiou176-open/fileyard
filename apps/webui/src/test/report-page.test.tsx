import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/lib/i18n'
import { ReportPage } from '@/pages/report-page'

const mocks = vi.hoisted(() => ({
  getJob: vi.fn(async () => ({ id: 'job-1', kind: 'analyze', status: 'succeeded', phase: 'done', progress: 100 })),
  getReport: vi.fn(async () => ({
    total: 4,
    with_error: 0,
    by_media_type: { image: 4 },
    by_category: { travel: 2, work: 2 },
    by_status: { pending: 4 },
    error_codes: {},
    by_review_bucket: { auto_safe: 1, needs_review: 2, conflict: 1, blocked: 0 },
    collection_count: 2,
  })),
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
      review_bucket: 'needs_review',
      learned_suggestions: [
        {
          signal_key: 'media_type',
          signal_value: 'image',
          suggestion_type: 'category',
          suggestion_value: 'travel',
          confidence: 0.8,
          count: 3,
        },
      ],
    },
    {
      id: 'row-2',
      row_id: 'row-2',
      file_name: 'trip-b.png',
      media_type: 'image',
      category: 'travel',
      title: 'Trip B',
      tags: [],
      status: 'pending',
      error_code: '',
      target_path: '',
      target_suggestion: '',
      confidence: 0.6,
      original_path: '/tmp/trip-b.png',
      notes: '',
      ignore: false,
      metadata: {},
      review_bucket: 'conflict',
      learned_suggestions: [],
    },
  ]),
}))

vi.mock('@/lib/api', () => ({
  getJob: mocks.getJob,
  getReport: mocks.getReport,
  getManifestRows: mocks.getManifestRows,
}))

vi.mock('@/components/report/report-charts-grid', () => ({
  ReportChartsGrid: () => <div>Report charts</div>,
}))

describe('ReportPage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.lang = 'en'
  })

  it('surfaces high-value links back into review', async () => {
    render(
      <MemoryRouter initialEntries={['/report/job-1']}>
        <I18nProvider>
          <Routes>
            <Route element={<ReportPage />} path="/report/:jobId" />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Report to Review Loop')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Review conflicts in Fileorganize Review' })).toHaveAttribute(
      'href',
      '/review/job-1?from=report&bucket=conflict',
    )
    expect(screen.getByRole('link', { name: 'Review human-check rows' })).toHaveAttribute(
      'href',
      '/review/job-1?from=report&bucket=needs_review',
    )
    expect(screen.getByRole('link', { name: 'Review learned suggestions' })).toHaveAttribute(
      'href',
      '/review/job-1?from=report&learned=1',
    )
  })

  it('renders localized report copy when the locale is switched to zh-CN', async () => {
    window.localStorage.setItem('fileorganize.locale', 'zh-CN')

    render(
      <MemoryRouter initialEntries={['/report/job-1']}>
        <I18nProvider>
          <Routes>
            <Route element={<ReportPage />} path="/report/:jobId" />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('从 Report 回到 Review 的闭环')).toBeInTheDocument()
    expect(screen.getByText(/统计图本身就等于动作/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '清空筛选' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('筛选报告行')).toBeInTheDocument()
  })
})
