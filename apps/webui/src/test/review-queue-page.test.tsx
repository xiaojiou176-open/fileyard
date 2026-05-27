import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/lib/i18n'
import { ReviewQueuePage } from '@/pages/review-queue-page'

const baseQueuePayload = {
  job: null,
  job_id: 'job-1',
  manifest_path: '/tmp/manifest.jsonl',
  overlay_path: '/tmp/overlay.json',
  summary: { total: 3, auto_safe: 1, needs_review: 1, conflict: 1, blocked: 0 },
  copilot_summary: {
    mode: 'deterministic-review-summary',
    headline: 'Review Copilot found 1 conflict, 1 human-review rows, 1 rule opportunity.',
    reasons: [
      {
        key: 'conflicts',
        title: 'Conflicts still need a decision',
        count: 1,
        detail: 'These rows point at competing targets or duplicate outcomes and should be resolved before execution.',
      },
    ],
    priorities: [
      {
        row_id: '1',
        file_name: 'b.png',
        bucket: 'needs_review',
        reason: 'A learned suggestion already exists for this row.',
        suggested_action: 'Inspect the learned suggestion and decide whether to accept or promote it.',
        confidence: 0.55,
      },
    ],
    rule_opportunities: [
      {
        key: 'trip-images',
        title: 'Trip images may form a reusable rule',
        reason: 'Multiple rows share the same learned category suggestion.',
        row_ids: ['0', '1'],
        suggested_action: 'Create a draft rule from these examples.',
      },
    ],
    batch_triage: [
      {
        id: 'collection:col-1',
        kind: 'collection',
        label: 'Trip / 2026-03-29',
        review_bucket: 'needs_review',
        collection_id: 'col-1',
        count: 2,
        row_ids: ['0', '1'],
        reason: 'Collection requires grouped review.',
        next_step: 'Use this batch for one grouped review pass.',
      },
    ],
    guardrails: {
      review_only: true,
      draft_only: true,
      overlay_only: true,
      execute_allowed: false,
      auto_apply: false,
      allowed_routes: ['/api/jobs/{job_id}/review-queue/batch-triage'],
    },
  },
  collections: [
    {
      id: 'col-1',
      title: 'Trip / 2026-03-29',
      reason: 'grouped by capture day + source root, with batch hint kept as an explanation signal',
      confidence: 0.9,
      row_ids: ['0', '1'],
      kind: 'travel_batch',
      primary_media_type: 'image',
      dominant_category: '旅行',
      shared_keywords: ['trip'],
      next_step: 'Review this trip batch together, then promote repeated edits into a draft rule if the pattern holds.',
      capture_day: '2026-03-29',
      batch_hint: 'trip',
      source_root: 'trip',
      dominant_media_type: 'image',
      media_types: ['image', 'pdf'],
      explainability: ['capture_day:2026-03-29', 'batch_hint:trip', 'source_root:trip'],
    },
  ],
  rows: [
    { id: '0', file_name: 'a.png', media_type: 'image', category: '旅行', title: 'Trip shot', tags: [], status: 'pending', error_code: '', target_path: '', target_suggestion: '', confidence: 0.91, original_path: '/tmp/a.png', notes: '', ignore: false, metadata: {}, review_bucket: 'auto_safe', collection_id: 'col-1', collection_title: 'Trip / 2026-03-29', collection_kind: 'travel_batch', collection_next_step: 'Review this trip batch together, then promote repeated edits into a draft rule if the pattern holds.', learned_suggestions: [{ signal_key: 'media_type', signal_value: 'image', suggestion_type: 'category', suggestion_value: '旅行', confidence: 0.8, confidence_label: 'high', reuse_scope: 'reusable', source: 'workspace_review_learning_v1', explanation: 'Observed 3 accepted review edit(s) mapping media_type=image to 旅行.', count: 3 }] },
    { id: '1', file_name: 'b.png', media_type: 'image', category: '工作', title: 'Needs review', tags: [], status: 'pending', error_code: '', target_path: '', target_suggestion: '', confidence: 0.55, original_path: '/tmp/b.png', notes: '', ignore: false, metadata: {}, review_bucket: 'needs_review', collection_id: 'col-1', collection_title: 'Trip / 2026-03-29', collection_kind: 'travel_batch', collection_next_step: 'Review this trip batch together, then promote repeated edits into a draft rule if the pattern holds.', learned_suggestions: [{ signal_key: 'media_type', signal_value: 'image', suggestion_type: 'category', suggestion_value: '旅行', confidence: 0.8, confidence_label: 'high', reuse_scope: 'reusable', source: 'workspace_review_learning_v1', explanation: 'Observed 3 accepted review edit(s) mapping media_type=image to 旅行.', count: 3 }] },
    { id: '2', file_name: 'c.png', media_type: 'image', category: '工作', title: 'Conflict row', tags: [], status: 'duplicate', error_code: '', target_path: '', target_suggestion: '', confidence: 0.9, original_path: '/tmp/c.png', notes: '', ignore: false, metadata: {}, review_bucket: 'conflict' },
  ],
  returned: 3,
}

const mocks = vi.hoisted(() => ({
  getReviewQueue: vi.fn(async () => ({ ...baseQueuePayload })),
  draftReviewRuleFromExamples: vi.fn(async (jobId: string, rowIds: string[]) => {
    void jobId
    void rowIds
    return {
    job_id: 'job-1',
    selected_count: 2,
    selected_row_ids: ['0', '1'],
    mode: 'draft_only',
    save_allowed: false,
    apply_allowed: false,
    draft: {
      name: 'Draft from trip examples',
      scope: 'manifest',
      description: 'Generated from 2 reviewed examples. Review the inferred conditions before saving or applying the draft.',
      version: 1,
      draft_source: 'review_examples_v1',
      conditions: { query: 'trip', statuses: [], media_types: ['image'], categories: [], review_buckets: [] },
      actions: { set_category: '旅行' },
      warnings: ['Examples span multiple review buckets, so the draft leaves review_buckets open for manual review.'],
      explainability: {
        selected_count: 2,
        selected_row_ids: ['0', '1'],
        shared_media_types: ['image'],
        shared_review_buckets: ['auto_safe', 'needs_review'],
        shared_query: 'trip',
        inferred_actions: ['set_category'],
        save_allowed: false,
        apply_allowed: false,
      },
    },
    warnings: ['Backend draft is draft-only.'],
  }
  }),
  applyReviewQueueBatchTriage: vi.fn(async (jobId: string, payload: { rowIds: string[]; setCategory?: string; setIgnore?: boolean }) => {
    void jobId
    void payload
    return {
      ...baseQueuePayload,
      applied_count: 1,
      mode: 'overlay_only',
      execute_allowed: false,
    }
  }),
  listReviewRules: vi.fn(async () => []),
  deleteReviewRule: vi.fn(async () => undefined),
  applyReviewRule: vi.fn(async () => ({ ...baseQueuePayload })),
  createReviewRule: vi.fn(),
  previewReviewRule: vi.fn(),
  listLearnedRules: vi.fn(async () => [
    {
      id: 'learned-1',
      signal_key: 'media_type',
      signal_value: 'image',
      suggestion_type: 'category',
      suggestion_value: '旅行',
      confidence: 0.8,
      count: 3,
      confidence_label: 'high',
      strength: 'strong',
      reuse_scope: 'reusable',
      source: 'workspace_review_learning_v1',
      reason: 'Observed 3 accepted review edit(s) mapping media_type=image to 旅行.',
      explanation: 'Observed 3 accepted review edit(s) mapping media_type=image to 旅行.',
      scope_reason: 'Reusable because the same correction was accepted multiple times.',
      updated_at: '2026-03-29T10:00:00Z',
    },
  ]),
  resetLearnedRules: vi.fn(async () => undefined),
}))

vi.mock('@/lib/api', () => ({
  getReviewQueue: mocks.getReviewQueue,
  draftReviewRuleFromExamples: mocks.draftReviewRuleFromExamples,
  applyReviewQueueBatchTriage: mocks.applyReviewQueueBatchTriage,
  listReviewRules: mocks.listReviewRules,
  deleteReviewRule: mocks.deleteReviewRule,
  applyReviewRule: mocks.applyReviewRule,
  createReviewRule: mocks.createReviewRule,
  previewReviewRule: mocks.previewReviewRule,
  listLearnedRules: mocks.listLearnedRules,
  resetLearnedRules: mocks.resetLearnedRules,
}))

function renderPage(initialEntry = '/review/job-1') {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <I18nProvider>
        <Routes>
          <Route element={<ReviewQueuePage />} path="/review/:jobId" />
        </Routes>
      </I18nProvider>
    </MemoryRouter>,
  )
}

describe('ReviewQueuePage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.lang = 'en'
  })

  it('renders copilot guidance, learned explainability, and bucket sections', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Fileorganize Review' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Fileorganize Copilot v1' })).toBeInTheDocument()
    expect(screen.getByText('Review Copilot found 1 conflict, 1 human-review rows, 1 rule opportunity.')).toBeInTheDocument()
    expect(screen.getByText('Trip images may form a reusable rule')).toBeInTheDocument()
    expect(screen.getByText('Batch suggestions')).toBeInTheDocument()
    expect(screen.getByText('review-only')).toBeInTheDocument()
    expect(screen.getByText('Rule from Examples v1')).toBeInTheDocument()
    expect(screen.getByText('Batch Triage')).toBeInTheDocument()
    expect(screen.getByText('Collection Intelligence v2 groups rows into reviewable batch slices. Think of it like sorting one tray at a time instead of judging the whole messy desk at once.')).toBeInTheDocument()
    expect(screen.getAllByText('Why Copilot is surfacing this row').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/source=workspace_review_learning_v1/).length).toBeGreaterThan(0)
    expect(screen.getByText(/auto safe/i)).toBeInTheDocument()
    expect(screen.getAllByText('Needs review').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Trip / 2026-03-29').length).toBeGreaterThan(0)
  })

  it('accepts a learned rule into the overlay from the learned suggestions panel', async () => {
    renderPage()

    expect(await screen.findByText('category: 旅行')).toBeInTheDocument()
    fireEvent.click((await screen.findAllByRole('button', { name: 'Accept into Overlay' }))[0])

    await waitFor(() => {
      expect(mocks.applyReviewRule).toHaveBeenCalledTimes(1)
    })
  }, 15000)

  it('generates a rule draft from selected examples', async () => {
    renderPage()

    const exampleButtons = await screen.findAllByRole('button', { name: 'Use as Example' })
    fireEvent.click(exampleButtons[0])
    fireEvent.click(exampleButtons[1])
    expect(await screen.findByText('Current selection: 2 row(s). Backend v1 accepts 2 to 5 reviewed examples.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Generate Draft in Rule Studio' }))

    await waitFor(() => {
      expect(mocks.draftReviewRuleFromExamples).toHaveBeenCalledTimes(1)
    })
    expect(mocks.draftReviewRuleFromExamples.mock.calls[0]?.[0]).toBe('job-1')
    expect(mocks.draftReviewRuleFromExamples.mock.calls[0]?.[1]).toHaveLength(2)
    expect(screen.getByText('Example draft loaded')).toBeInTheDocument()
    expect(screen.getByText('This draft came from the backend review examples route. It is draft-only and was not saved or applied for you.')).toBeInTheDocument()
    expect(screen.getByLabelText('Set category')).toHaveValue('旅行')
  })

  it('applies batch triage changes through the batch triage route', async () => {
    renderPage()

    const input = await screen.findByLabelText('Batch triage category')
    fireEvent.change(input, { target: { value: '旅行' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply Category via Batch Triage' }))

    await waitFor(() => {
      expect(mocks.applyReviewQueueBatchTriage).toHaveBeenCalledWith(
        'job-1',
        expect.objectContaining({ rowIds: ['1'], setCategory: '旅行' }),
      )
    })
  })

  it('honors report focus filters and collection context', async () => {
    render(
      <MemoryRouter initialEntries={['/review/job-1?from=report&bucket=needs_review&learned=1&collection=col-1']}>
        <Routes>
          <Route element={<ReviewQueuePage />} path="/review/:jobId" />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Focused from Report')).toBeInTheDocument()
    expect(screen.getByText('learning only')).toBeInTheDocument()
    expect(screen.getByText('kind=travel_batch')).toBeInTheDocument()
    expect(screen.getByText(/next step:/i)).toBeInTheDocument()
  })

  it('shows clear review focus when report sends the user back with learned filters', async () => {
    renderPage('/review/job-1?from=report&learned=1')

    expect(await screen.findByText('Focused from Report')).toBeInTheDocument()
    expect(screen.getByText('learning only')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear focus' })).toBeInTheDocument()
  })

  it('renders localized review workbench copy when locale switches to zh-CN', async () => {
    window.localStorage.setItem('fileorganize.locale', 'zh-CN')

    renderPage()

    expect(await screen.findByRole('heading', { name: 'Fileorganize 审核台' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: '正在加载 Review Queue' })).not.toBeInTheDocument()
    })
    expect(await screen.findByRole('heading', { name: 'Fileorganize Copilot v1' }, { timeout: 5000 })).toBeInTheDocument()
    expect(await screen.findByText('后端审核摘要')).toBeInTheDocument()
    expect(screen.getByText('批量分诊')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '清空示例' })).toBeInTheDocument()
  })
})
