// AUTO-GENERATED from contracts/api/web_api.openapi.yaml. Do not edit manually.
export type JobKind = 'analyze' | 'apply' | 'rollback'
export type JobStatus = 'queued' | 'running' | 'cancelling' | 'succeeded' | 'failed' | 'cancelled'
export type InputMode = 'directory' | 'upload'

export interface JobSummary {
  total: number
  with_error: number
  by_media_type: Record<string, number>
  by_category: Record<string, number>
  by_status: Record<string, number>
  error_codes: Record<string, number>
  by_review_bucket?: Record<string, number>
  collection_count?: number
  collection_ids?: string[]
  manifest_path?: string
  report_path?: string
  rollback_manifest_path?: string
  input_mode?: InputMode
  input_root?: string
  output_root?: string
  dry_run?: boolean
  allowed_root?: string
}

export interface Job {
  id: string
  kind: JobKind
  status: JobStatus
  phase: string
  progress: number
  started_at?: string
  finished_at?: string
  retry_of?: string
  cancel_requested_at?: string
  summary?: JobSummary
  latest_error?: string
  manifest_path?: string
  report_path?: string
  rollback_manifest_path?: string
  dry_run_verified?: boolean
  strict_integrity_ready?: boolean
}

export interface JobEvent {
  id?: string
  timestamp: string
  level: string
  message: string
  fields?: Record<string, unknown>
}

export interface ReviewExplainability {
  bucket: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  reason_codes: string[]
  reasons: string[]
  collection_confidence: number
  learned_suggestion_count: number
  edited: boolean
  has_conflict: boolean
}

export interface ManifestRow {
  row_id: string
  id: string
  file_name: string
  media_type: string
  category: string
  title: string
  tags: string[]
  status: string
  error_code: string
  target_path: string
  target_suggestion: string
  dedupe_of?: string
  confidence: number
  original_path: string
  notes: string
  ignore: boolean
  review_bucket?: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  has_conflict?: boolean
  edited?: boolean
  collection_id?: string
  collection_title?: string
  collection_reason?: string
  collection_confidence?: number
  collection_capture_day?: string
  collection_batch_hint?: string
  collection_source_root?: string
  collection_kind?: string
  collection_next_step?: string
  collection_explainability?: string[]
  learned_suggestions?: LearnedSuggestion[]
  review_explainability?: ReviewExplainability
  metadata: Record<string, string>
}

export interface ManifestRowPatch {
  row_id: string
  category?: string
  title?: string
  tags?: string[]
  notes?: string
  target_suggestion?: string
  ignore?: boolean
}

export interface ManifestConflict {
  id: string
  row_id: string
  type: string
  severity: 'warning' | 'error'
  source_path: string
  target_path: string
  reason: string
  suggested_target?: string
  status: 'open' | 'resolved' | 'ignored'
}

export interface PreviewPayload {
  row_id: string
  media_type: string
  thumbnail_url?: string
  summary?: string
  duration_s?: number
  pages?: number
  mime?: string
  extra?: Record<string, string>
}

export interface SavedView {
  id: string
  name: string
  scope: 'manifest' | 'report' | 'jobs'
  query: Record<string, string>
  created_at: string
}

export interface NamingTemplate {
  id: string
  name: string
  pattern: string
  description?: string
  created_at: string
}

export interface ReviewQueueSummary {
  total: number
  auto_safe: number
  needs_review: number
  conflict: number
  blocked: number
}

export interface CollectionSummary {
  id: string
  title: string
  reason: string
  confidence: number
  row_ids: string[]
  kind: string
  next_step: string
  capture_day: string
  batch_hint: string
  source_root: string
  dominant_media_type: string
  media_types: string[]
  explainability: string[]
}

export interface ReviewRuleCondition {
  query?: string
  statuses?: string[]
  media_types?: string[]
  categories?: string[]
  review_buckets?: string[]
  min_confidence?: number
  max_confidence?: number
  has_conflict?: boolean
  ignore_state?: boolean
}

export interface ReviewRuleAction {
  set_category?: string
  set_ignore?: boolean
  target_pattern?: string
}

export interface ReviewRule {
  id: string
  name: string
  scope: 'manifest' | 'report' | 'jobs'
  description?: string
  version: number
  conditions: ReviewRuleCondition
  actions: ReviewRuleAction
  created_at?: string
  updated_at?: string
}

export interface RulePreview {
  matched_row_ids: string[]
  matched_count: number
  patch_preview: Record<string, Record<string, unknown>>
}

export interface LearnedSuggestion {
  signal_key: string
  signal_value: string
  suggestion_type: string
  suggestion_value: string
  confidence: number
  count: number
  confidence_label: string
  strength: string
  reuse_scope: 'transient' | 'reusable'
  source: string
  reason: string
  explanation: string
  scope_reason: string
}

export interface LearnedRule extends LearnedSuggestion {
  id: string
  updated_at: string
}

export interface ReviewQueueBatchSuggestion {
  id: string
  kind: 'bucket' | 'collection'
  label: string
  review_bucket: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  collection_id?: string
  count: number
  row_ids: string[]
  reason: string
  next_step: string
}

export interface ReviewCopilotReason {
  key: string
  title: string
  count: number
  detail: string
}

export interface ReviewCopilotPriority {
  row_id: string
  file_name: string
  bucket: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  reason: string
  suggested_action: string
  confidence: number
}

export interface ReviewCopilotRuleOpportunity {
  key: string
  title: string
  reason: string
  row_ids: string[]
  suggested_action: string
}

export interface ReviewCopilotGuardrails {
  review_only: boolean
  draft_only: boolean
  overlay_only: boolean
  execute_allowed: boolean
  auto_apply: boolean
  allowed_routes: string[]
}

export interface ReviewCopilotSummary {
  mode: string
  headline: string
  reasons: ReviewCopilotReason[]
  priorities: ReviewCopilotPriority[]
  rule_opportunities: ReviewCopilotRuleOpportunity[]
  batch_triage: ReviewQueueBatchSuggestion[]
  guardrails: ReviewCopilotGuardrails
}

export interface ReviewBridge {
  mode: string
  next_step: string
  review_queue_path: string
  batch_triage_path: string
  rule_from_examples_path: string
  needs_review_count: number
  conflict_count: number
  blocked_count: number
  collection_focus_ids: string[]
  rule_opportunity_keys: string[]
  execute_allowed: boolean
}

export interface ReviewQueueResponse {
  job: Job | null
  job_id: string
  manifest_path: string
  overlay_path: string
  overlay_updated_at?: string
  summary: ReviewQueueSummary
  copilot_summary?: ReviewCopilotSummary
  collections: CollectionSummary[]
  rows: ManifestRow[]
  returned: number
}

export interface ReviewRuleDraftExplainability {
  selected_count: number
  selected_row_ids: string[]
  shared_media_types: string[]
  shared_review_buckets: string[]
  shared_query: string
  inferred_actions: string[]
  save_allowed: boolean
  apply_allowed: boolean
}

export interface ReviewRuleDraft extends Omit<ReviewRule, 'id'> {
  id?: string
  mode: 'draft_only'
  draft_source: string
  warnings: string[]
  example_row_ids: string[]
  explainability: ReviewRuleDraftExplainability
}

export interface ReviewRuleDraftResponse {
  job_id: string
  selected_count: number
  selected_row_ids: string[]
  mode: 'draft_only'
  save_allowed: false
  apply_allowed: false
  execute_allowed: false
  draft: ReviewRuleDraft
  warnings: string[]
}

export interface ReviewRuleApplyResponse extends ReviewQueueResponse {
  applied_rule_id: string
  matched_count: number
  mode: 'overlay_only'
  execute_allowed: false
}

export interface ReviewQueueBatchTriageResponse extends ReviewQueueResponse {
  applied_count: number
  mode: 'overlay_only'
  execute_allowed: false
}

export interface JobReportPayload extends Record<string, unknown> {
  total?: number
  by_review_bucket?: ReviewQueueSummary
  collection_count?: number
  collection_ids?: string[]
  collection_summaries?: CollectionSummary[]
  rows_with_learning_suggestions?: number
  learned_rule_count?: number
  reusable_learning_rule_count?: number
  review_copilot_summary?: ReviewCopilotSummary
  review_bridge?: ReviewBridge
}

export interface JobReportResponse {
  job_id: string
  report_path: string
  report: JobReportPayload
}

export interface StrategyPack {
  id: string
  name: string
  description: string
  categories: string[]
  model?: string
  workers: number
  review_confidence_threshold: number
  default_rule_ids: string[]
  default_template_patterns: string[]
  defaults: Record<string, unknown>
  explainability: Record<string, string>
}

export interface WatchSource {
  id: string
  name: string
  input_root: string
  enabled: boolean
  strategy_pack_id: string
  created_at: string
  updated_at: string
  strategy_pack?: StrategyPack
}

export interface InboxBatch {
  id: string
  watch_source_id: string
  source_name: string
  input_root: string
  file_count: number
  file_paths: string[]
  strategy_pack_id: string
  analyze_job_id: string
  analyze_ready: boolean
  discovery_mode: string
  strategy_pack?: StrategyPack
  analyze_defaults: {
    model: string
    categories: string
    workers: number
    max_files: number
    max_total_mb: number
    max_file_mb: number
    offline: boolean
  }
  analyze_action: {
    method: string
    path: string
    payload: Record<string, unknown>
  }
}

export interface InboxScanResponse {
  items: InboxBatch[]
  count: number
  mode: string
  analyze_route: string
}

export interface InboxAnalyzeRequest {
  watch_source_id: string
  batch_id?: string
  strategy_pack_id?: string
  model?: string
  categories?: string
  workers?: number
  max_files?: number
  max_total_mb?: number
  max_file_mb?: number
  offline?: boolean
}

export interface InboxAnalyzeResponse {
  job: Job
  job_id: string
  mode: string
  batch: InboxBatch
  strategy_pack?: StrategyPack
  review_next: Record<string, unknown>
}

export interface RuntimeSettings {
  workspace_root: string
  runtime_env_path: string
  input_root: string
  output_root: string
  allowed_root: string
  manifest_root: string
  artifact_root: string
  has_api_key: boolean
  api_key_masked: string
  api_key_source: 'env' | 'runtime_env' | 'missing' // pragma: allowlist secret
  api_key_status: 'configured' | 'missing' | 'placeholder' // pragma: allowlist secret
  model: string
  model_source: 'env' | 'runtime_env' | 'default'
  active_strategy_pack_id: string
  input_root_exists: boolean
  output_root_exists: boolean
  ready: boolean
  analyze_defaults: {
    workers: number
    categories: string[]
    max_files: number
    max_total_mb: number
    max_file_mb: number
  }
  missing: string[]
  warnings: string[]
  checked_at: string
}

export interface JobsQuery {
  q?: string
  kind?: string
  status?: string
  from?: string
  to?: string
}
