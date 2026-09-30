/**
 * The single way this app talks to the backend.
 *
 * Every response is unwrapped here, and the documented error envelope
 * (API_SPEC §Conventions) becomes a typed `ApiError`. No component parses a
 * response body or builds a URL — that is what keeps error handling uniform
 * and the API surface swappable.
 */

import { authorizationToken, clearSession } from '@/lib/session';

const API_BASE_URL = process.env.API_BASE_URL ?? 'http://127.0.0.1:8000';

/**
 * Attach the caller's session, if there is one.
 *
 * Absent is normal rather than exceptional: with `AUTH_PROVIDER=dev_stub` the
 * backend ignores the credential entirely, so the offline demo sends no header
 * and works exactly as it did before authentication existed.
 */
async function withAuthorization(headers: Record<string, string>): Promise<Record<string, string>> {
  const token = await authorizationToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

/**
 * A rejected credential means the stored session is dead, whatever the browser
 * still has in `localStorage`. Discarding it here — at the one place every
 * response passes through — is what stops the app from retrying a token the
 * server has already refused.
 */
function forgetSessionIfRejected(code: string): void {
  if (code === 'UNAUTHENTICATED') clearSession();
}

/**
 * Every code the API can actually send, plus `NETWORK` for a request that never
 * arrived. Kept equal to the table in `API_SPEC.md` §Conventions — it used to
 * name `RATE_LIMITED` and `GRAPH_ERROR`, which nothing emits, and omit the
 * provider and storage codes, which it does.
 */
export type ErrorCode =
  | 'VALIDATION_FAILED'
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'PROVIDER_ERROR'
  | 'PROVIDER_UNAVAILABLE'
  | 'PROVIDER_TIMEOUT'
  | 'PROVIDER_RATE_LIMITED'
  | 'PROVIDER_INVALID_RESPONSE'
  /** A vendor's safety filter refused. A normal outcome, not a bug. */
  | 'CONTENT_BLOCKED'
  | 'INVALID_STORAGE_KEY'
  | 'STORAGE_OBJECT_NOT_FOUND'
  | 'INTERNAL'
  /** Not from the API: the request never reached it. */
  | 'NETWORK';

/**
 * Absolute URL for a media path the API returned.
 *
 * The API returns paths like `/v1/campaigns/…/content` — correct, because the
 * backend must not hardcode its own public host. But an `<img src>` resolves a
 * relative path against the *page* origin, which is the Next server, not the
 * API. Every media reference goes through here.
 *
 * **The path already carries a short-lived signature.** An `<img src>` cannot
 * send `Authorization` or `X-Organization-Id`, so the API signs each media
 * path for one row and a few minutes instead. Pass it through untouched: it
 * has a query string, so appending `?anything=…` corrupts the token. Where a
 * variant is needed the API supplies its own field, as `download_url` does.
 */
export function mediaUrl(path: string): string {
  return path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
}

export class ApiError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly status: number,
    readonly details: Record<string, unknown> = {},
    readonly requestId = '',
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /**
   * True when retrying could plausibly succeed — drives the retry button.
   *
   * Provider failures are already covered by the status: every `ProviderError`
   * is served as `502`. `CONTENT_BLOCKED` deliberately is not retryable — a
   * safety filter will refuse the same request again, and offering a button
   * that cannot work is worse than saying so.
   */
  get isRetryable(): boolean {
    return this.status >= 500 || this.code === 'NETWORK';
  }
}

interface ErrorEnvelope {
  error: { code: ErrorCode; message: string; details?: Record<string, unknown>; request_id?: string };
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  organizationId?: string | null;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, organizationId, signal } = options;

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  // Which organization this request acts in. The server still verifies
  // membership — this only disambiguates.
  if (organizationId) headers['X-Organization-Id'] = organizationId;
  await withAuthorization(headers);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      signal,
    });
  } catch (cause) {
    // A dead backend is the most common failure in development, so it gets a
    // sentence a human can act on rather than "Failed to fetch".
    throw new ApiError('NETWORK', `Cannot reach the API at ${API_BASE_URL}. Is it running?`, 0, {
      cause: String(cause),
    });
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const envelope = payload as ErrorEnvelope | null;
    const error = envelope?.error;
    forgetSessionIfRejected(error?.code ?? '');
    throw new ApiError(
      error?.code ?? 'INTERNAL',
      error?.message ?? `Request failed with status ${response.status}.`,
      response.status,
      error?.details ?? {},
      error?.request_id ?? response.headers.get('X-Request-Id') ?? '',
    );
  }
  return payload as T;
}

/* ---------------------------------------------------------------------- *
 * Types mirroring the API. Milestone 1 hand-writes the handful it needs;
 * from Milestone 2 these are generated from the OpenAPI schema
 * (`npm run gen:api`, ADR-010) and this block goes away.
 * ---------------------------------------------------------------------- */

export interface Organization { id: string; name: string; slug: string }
export interface User { id: string; email: string; display_name: string | null }
export interface Project {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
}
export interface Me {
  user: User;
  organizations: { organization: Organization; role: string }[];
  active_organization_id: string | null;
}
export interface ProjectPage { items: Project[]; next_cursor: string | null }
/* --- Milestone 2: Brand Brain ---------------------------------------- */

export type DocumentStatus =
  | 'PENDING'
  | 'EXTRACTING'
  | 'EMBEDDING'
  | 'COMPLETED'
  | 'UPLOAD_FAILED'
  | 'EXTRACTION_FAILED'
  | 'EMBEDDING_FAILED'
  | 'ANALYSIS_FAILED';

export const TERMINAL_STATUSES: DocumentStatus[] = [
  'COMPLETED',
  'UPLOAD_FAILED',
  'EXTRACTION_FAILED',
  'EMBEDDING_FAILED',
  'ANALYSIS_FAILED',
];

export function isFailure(status: DocumentStatus): boolean {
  return status.endsWith('_FAILED');
}

export interface BrandColor { name: string; hex: string; role: string }
export interface BrandVoice {
  tone_attributes: string[];
  person: string | null;
  writing_rules: string[];
  avoid: string[];
}
export interface BrandTypography {
  heading_font: string | null;
  body_font: string | null;
  fallback_stack: string[];
  notes: string | null;
}

export interface Brand {
  id: string;
  organization_id: string;
  name: string;
  industry: string | null;
  description: string | null;
  website: string | null;
  positioning: string | null;
  mission: string | null;
  values: string[];
  audience_description: string | null;
  voice: BrandVoice;
  colors: BrandColor[];
  typography: BrandTypography;
  approved_claims: string[];
  prohibited_claims: string[];
  visual_dos: string[];
  visual_donts: string[];
  logo_rules: string[];
  legal_line: string | null;
}

export interface BrandDocument {
  id: string;
  brand_id: string;
  title: string;
  source_type: string;
  filename: string | null;
  mime_type: string | null;
  bytes: number | null;
  status: DocumentStatus;
  page_count: number | null;
  chunk_count: number;
  error: string | null;
  created_at: string;
}

export interface BrandAsset {
  id: string;
  brand_id: string;
  kind: string;
  filename: string | null;
  mime_type: string;
  bytes: number | null;
  url: string;
}

export interface Provenance {
  kind: 'human' | 'document' | 'inferred';
  document_id: string | null;
  document_title: string | null;
  page: number | null;
  quote: string | null;
}

export interface BrandFact {
  id: string;
  field: string;
  value: string;
  confidence: number;
  status: 'proposed' | 'accepted' | 'rejected';
  provenance: Provenance;
  rationale: string | null;
}

export interface FieldStatus {
  field: string;
  knowledge: 'known' | 'inferred' | 'unknown';
  proposal_count: number;
}

export interface BrandBrain {
  brand: Brand;
  documents: BrandDocument[];
  assets: BrandAsset[];
  proposed_facts: BrandFact[];
  field_status: FieldStatus[];
  chunk_count: number;
  knowledge_ready: boolean;
  processing_errors: string[];
}

export interface KnowledgeHit {
  chunk_id: string;
  document_id: string;
  document_title: string;
  content: string;
  score: number;
  chunk_index: number;
  page: number | null;
}

/* --- Milestone 3: campaign discovery ---------------------------------- */

export type CampaignStatus =
  | 'DRAFT'
  | 'INTERVIEWING'
  | 'SPECIFICATION_READY'
  | 'SPECIFICATION_CONFIRMED'
  | 'FAILED'
  | 'CANCELLED';

export interface Campaign {
  id: string;
  organization_id: string;
  brand_id: string;
  project_id: string | null;
  title: string;
  status: CampaignStatus;
  created_at: string;
}

export interface InterviewQuestion {
  id: string;
  field: string;
  question: string;
  why: string;
  priority: 'HIGH' | 'MEDIUM' | 'LOW';
  options: string[];
  required: boolean;
  /** Set when the brand already answers this — the question then asks whether
   *  this campaign differs, rather than asking cold. */
  brand_default: string | null;
}

export type Certainty = 'stated' | 'brand_default' | 'inferred' | 'unresolved';
export type Availability = 'known' | 'unknown' | 'not_applicable';

export interface FieldAssertion {
  field: string;
  availability: Availability;
  certainty: Certainty;
  source: string | null;
  edited_by_human: boolean;
}

export interface CampaignInputs {
  campaign_objective: string | null;
  target_audience: string | null;
  product: string | null;
  key_message: string | null;
  region: string | null;
  channels: string[];
  cta: string | null;
  desired_emotional_response: string | null;
  campaign_tone: string[];
  key_offer: string | null;
  timing_occasion: string | null;
  required_elements: string[];
  avoid_restrictions: string[];
  assertions: Record<string, FieldAssertion>;
}

/** The CAMPAIGN SPECIFICATION — the source of truth for all later work. */
export interface CampaignSpecification {
  id: string;
  campaign_id: string;
  version: number;
  title: string;
  objective: string;
  audience: string;
  audience_insight: string | null;
  product: string;
  key_message: string;
  supporting_messages: string[];
  cta: string;
  region: string | null;
  language: string;
  channels: string[];
  tone: string[];
  desired_emotional_response: string | null;
  campaign_tone: string[];
  key_offer: string | null;
  timing_occasion: string | null;
  required_elements: string[];
  avoid_restrictions: string[];
  brand_requirements: string[];
  constraints: string[];
  field_assertions: Record<string, FieldAssertion>;
  rationale: string | null;
  assumptions_made: string[];
}

export interface DiscoveryTurn {
  campaign_id: string;
  status: CampaignStatus;
  question: InterviewQuestion | null;
  missing: string[];
  turn: number;
  interview_complete: boolean;
  specification: CampaignSpecification | null;
  known: CampaignInputs;
}

export interface CampaignMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  targets_field: string | null;
  created_at: string;
}

export type ReferenceStatus = 'PENDING' | 'ANALYZING' | 'COMPLETED' | 'FAILED';

export interface ColorProfile {
  dominant_palette: string[];
  brightness: number;
  saturation: number;
  contrast: number;
  temperature: string | null;
}

export interface TypographyCharacter {
  scale: string | null;
  weight: string | null;
  classification: string | null;
  case: string | null;
  text_density: string | null;
}

export interface LayoutProfile {
  image_text_balance: string | null;
  subject_placement: string | null;
  hierarchy: string | null;
}

export interface ReferenceAnalysis {
  reference_id: string;
  style_families: string[];
  composition: string | null;
  lighting: string | null;
  imagery_style: string[];
  color: ColorProfile;
  typography: TypographyCharacter;
  layout: LayoutProfile;
  visual_density: string | null;
  mood: string[];
  subject_treatment: string | null;
  style_takeaways: string[];
  /** What the system will deliberately NOT reuse from this reference. */
  not_transferable: string[];
  confidence: number;
  summary: string | null;
}

export interface CampaignReference {
  id: string;
  filename: string | null;
  mime_type: string;
  bytes: number | null;
  note: string | null;
  url: string;
  status: ReferenceStatus;
  analysis: ReferenceAnalysis | null;
  error: string | null;
  accepted: boolean;
}

export interface StyleOption {
  style: string;
  label: string;
  description: string;
}

export interface StyleWeight {
  style: string;
  weight: number;
}

export interface CreativePreferences {
  selected_styles: string[];
  liked_reference_ids: string[];
  disliked_reference_ids: string[];
  color_preference: string[];
  avoid: string[];
  free_text: string | null;
  style_profile: { weights: Record<string, number> };
}

export interface PreferencesView {
  preferences: CreativePreferences;
  profile: StyleWeight[];
  summary: string;
}

export interface AggregateReferenceStyle {
  dominant_styles: string[];
  shared_palette: string[];
  shared_takeaways: string[];
  tensions: string[];
  common_composition: string | null;
  common_lighting: string | null;
  common_density: string | null;
  average_color: ColorProfile;
  reference_count: number;
}

export interface BrandGuardrails {
  palette: string[];
  tone_attributes: string[];
  approved_claims: string[];
  prohibited_claims: string[];
  visual_dos: string[];
  visual_donts: string[];
  logo_rules: string[];
  legal_line: string | null;
}

export interface CreativeContext {
  campaign_id: string;
  brand_id: string | null;
  specification: CampaignSpecification | null;
  brand_name: string | null;
  guardrails: BrandGuardrails;
  reference_style: AggregateReferenceStyle;
  reference_analyses: ReferenceAnalysis[];
  preferences: CreativePreferences;
  style_profile: { weights: Record<string, number> };
  gaps: string[];
}

export interface CreativeContextView {
  context: CreativeContext;
  summary: string;
  ready: boolean;
}

/* --- Milestone 5: creative directions and the execution plan ---------- */

export interface TypographyGuidance {
  headline_treatment: string | null;
  hierarchy: string | null;
  max_headline_chars: number;
}

export interface NegativeConstraints {
  forbidden_elements: string[];
  forbidden_text: string[];
  avoid_styles: string[];
  no_text_in_image: boolean;
}

/** A strategic route. What we would say and why — not yet how to build it. */
export interface CreativeDirection {
  id: string;
  campaign_id: string;
  ordinal: number;
  title: string;
  big_idea: string;
  strategic_rationale: string;
  emotional_angle: string;
  audience_connection: string;
  key_message: string;
  headline: string;
  subhead: string | null;
  cta: string;
  cta_direction: string;
  visual_metaphor: string;
  composition: string;
  subject: string;
  environment: string;
  lighting: string;
  palette: string[];
  style_families: string[];
  color_direction: string;
  brand_integration: string;
  product_integration: string;
  regional_considerations: string[];
  negative_constraints: NegativeConstraints;
  reference_characteristics_used: string[];
  reference_characteristics_avoided: string[];
  distinctness_note: string | null;
}

/** The deterministic distinctness check — no clustering, just overlap. */
export interface DiversityVerdict {
  passed: boolean;
  /** [ordinal, ordinal, similarity] for every pair that was too close. */
  collisions: [number, number, number][];
  weakest_pair_similarity: number;
}

export interface CreativeDirectionSet {
  campaign_id: string;
  version: number;
  directions: CreativeDirection[];
  recommended_ordinal: number | null;
  recommendation_reasons: string[];
  diversity: DiversityVerdict;
  revision_of_version: number | null;
}

/** The approved plan. Everything generation needs, nothing it does not. */
/**
 * Words written for one channel, where the default does not fit it.
 *
 * A sparse diff: an absent field means "inherit the specification's default",
 * not "this channel has no headline". The complete answer for a channel is
 * what the backend's `copy_for` resolves.
 */
export interface ChannelCopy {
  headline?: string | null;
  subhead?: string | null;
  cta?: string | null;
}

export interface CreativeSpecification {
  id: string;
  campaign_id: string;
  direction_id: string;
  version: number;
  concept: string;
  visual_story: string;
  emotional_angle: string;
  headline: string;
  headline_guidance: string;
  subhead: string | null;
  cta: string;
  cta_guidance: string;
  body_copy: string | null;
  visual_metaphor: string;
  composition: string;
  focal_point: string;
  subject: string;
  environment: string;
  lighting: string;
  camera: string | null;
  palette: string[];
  color_direction: string;
  style_families: string[];
  mood: string[];
  typography_guidance: TypographyGuidance;
  product_integration: string;
  people_guidance: string;
  brand_integration: string;
  regional_cues: string[];
  negative_constraints: NegativeConstraints;
  /** Fields a human changed. A regeneration must not undo these. */
  human_edited_fields: string[];
  /** Per-channel overrides. Empty for a specification that has none. */
  channel_copy: Partial<Record<Channel, ChannelCopy>>;
  locked_fields: string[];
}

/** Which gate is open, if any. */
export type CreativeGate = 'strategy_gate' | 'specification_gate';

export interface CreativeStageView {
  campaign_id: string;
  gate: CreativeGate | null;
  direction_set: CreativeDirectionSet | null;
  selected_direction_id: string | null;
  specification: CreativeSpecification | null;
  diversity: DiversityVerdict | null;
  approved: boolean;
  gaps: string[];
  /** Channels the Campaign Specification declares — the only ones an override may name. */
  channels: Channel[];
}

export type StrategyDecision = 'APPROVE' | 'REJECT' | 'REQUEST_REVISION';
export type SpecificationDecision = 'APPROVE' | 'EDIT' | 'REQUEST_REVISION';

/* --- Milestone 6: compiled prompts, generation jobs, plates ----------- */

export type JobStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

/** `VISUAL_PLATE` — a raw model output, not a brand-ready creative. */
export type AssetKind = 'VISUAL_PLATE' | 'FINAL_COMPOSITION';

/** The provider-neutral compiled prompt. Structured, so it can be read. */
export interface CanonicalPrompt {
  id: string;
  campaign_id: string;
  specification_id: string;
  specification_version: number;
  version: number;
  subject: string;
  environment: string;
  visual_story: string;
  composition: string;
  focal_point: string;
  camera: string | null;
  lighting: string;
  color_direction: string;
  palette: string[];
  mood: string[];
  style_families: string[];
  product_integration: string;
  people_guidance: string;
  brand_integration: string;
  regional_cues: string[];
  typography_guidance: TypographyGuidance;
  /** Where the plate stays quiet so type can be composited later. */
  text_safe_area: string;
  negative_constraints: NegativeConstraints;
  reference_characteristics: string[];
  aspect_ratio: string;
  source_fingerprint: string;
}

/** One provider's rendering of the canonical prompt. */
export interface ModelPromptView {
  id: string;
  provider: string;
  model: string;
  version: number;
  text: string;
  negative_text: string | null;
  aspect_ratio: string;
  specification_version: number;
  /** One line naming everything this prompt descends from. */
  trace: string;
}

export interface GenerationJobView {
  id: string;
  provider: string;
  model: string;
  status: JobStatus;
  attempt: number;
  can_retry: boolean;
  error_message: string | null;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface GeneratedAssetView {
  id: string;
  generation_job_id: string;
  provider: string;
  model: string;
  kind: AssetKind;
  width: number;
  height: number;
  mime_type: string;
  /** API path — resolve with `mediaUrl()`, never used as a storage URL. */
  url: string;
  specification_version: number;
  created_at: string;
}

export interface GenerationView {
  campaign_id: string;
  batch_id: string | null;
  canonical_prompt: CanonicalPrompt | null;
  prompts: ModelPromptView[];
  jobs: GenerationJobView[];
  assets: GeneratedAssetView[];
  /** "2/3 providers succeeded — 1 failed." */
  outcome: string;
  complete: boolean;
  specification_version: number | null;
  can_generate: boolean;
  blocked_reason: string | null;
}

/* --- Milestone 7: evaluation, ranking, selection ---------------------- */

export type Disposition = 'PASS' | 'NEEDS_REVIEW' | 'REJECT';

export interface DimensionScoreView {
  dimension: string;
  label: string;
  score: number;
  note: string;
  /** How much this dimension moved the overall score. */
  weight: number;
}

export interface EvaluationDetailView {
  id: string;
  generated_asset_id: string;
  status: JobStatus;
  evaluator_version: string;
  evaluator_model: string | null;
  specification_version: number;
  dimensions: DimensionScoreView[];
  overall_score: number | null;
  disposition: Disposition | null;
  /** The threshold rules that produced the disposition, in words. */
  disposition_reasons: string[];
  strengths: string[];
  concerns: string[];
  rationale: string;
  error_message: string | null;
  error_code: string | null;
  can_retry: boolean;
  evaluated_at: string | null;
}

export interface RankedAssetView {
  rank: number;
  generated_asset_id: string;
  evaluation_id: string;
  overall_score: number;
  disposition: Disposition;
  reason: string;
  recommended: boolean;
  asset: GeneratedAssetView | null;
}

export interface RecommendationView {
  generated_asset_id: string | null;
  rank: number | null;
  overall_score: number | null;
  reason: string;
  /** Said out loud when the best available asset is not actually good. */
  caveat: string | null;
}

export interface EvaluationView {
  campaign_id: string;
  evaluator_version: string;
  ranked: RankedAssetView[];
  recommendation: RecommendationView | null;
  /** Every row, including failures — so nothing is a silent gap. */
  evaluations: EvaluationDetailView[];
  outcome: string;
  in_flight: number;
  unevaluated_asset_ids: string[];
  selected_asset_id: string | null;
  can_evaluate: boolean;
  blocked_reason: string | null;
}

/* --- Milestone 8: Brand Guardian and the revision loop ---------------- */

export type GuardianVerdict = 'PASS' | 'NEEDS_REVISION' | 'REJECT' | 'UNKNOWN';
export type CheckStatus = 'PASS' | 'WARN' | 'FAIL' | 'NOT_APPLICABLE';
export type Severity = 'minor' | 'major' | 'blocking';

export interface GuardianCheckView {
  check: string;
  label: string;
  status: CheckStatus;
  severity: Severity | null;
  detail: string;
  suggested_fix: string | null;
  /** True when code decided this, not a model. The two carry different weight. */
  deterministic: boolean;
}

export interface GuardianResultView {
  id: string;
  generated_asset_id: string;
  status: JobStatus;
  guardian_version: string;
  guardian_model: string | null;
  specification_version: number;
  verdict: GuardianVerdict | null;
  checks: GuardianCheckView[];
  critical_issues: string[];
  warnings: string[];
  summary: string;
  error_message: string | null;
  error_code: string | null;
  can_retry: boolean;
  evaluated_at: string | null;
  asset: GeneratedAssetView | null;
}

export interface GuardianView {
  campaign_id: string;
  guardian_version: string;
  results: GuardianResultView[];
  in_flight: number;
  unchecked_asset_ids: string[];
  can_check: boolean;
  blocked_reason: string | null;
}

export type RevisionAction = 'KEEP' | 'CHANGE' | 'ADD' | 'REMOVE';
export type RevisionStatus = 'PROPOSED' | 'APPLIED' | 'APPROVED' | 'REJECTED';

export interface FieldChangeView {
  field: string;
  label: string;
  action: RevisionAction;
  reason: string;
  new_value: string | null;
  /** What the field says now, so the UI can show before and after. */
  current_value: string | null;
}

export interface RevisionDeltaView {
  iteration: number;
  user_feedback: string;
  interpretation: string;
  keep: string[];
  change: FieldChangeView[];
  add: FieldChangeView[];
  remove: FieldChangeView[];
  explicit_unlocks: string[];
  /** Why this revision was proposed. Never a reasoning trace. */
  rationale: string;
}

export interface SpecificationDiffView {
  field: string;
  label: string;
  before: string;
  after: string;
}

export interface RevisionRecordView {
  id: string;
  iteration: number;
  status: RevisionStatus;
  user_feedback: string;
  delta: RevisionDeltaView;
  changed_fields: string[];
  from_version: number;
  to_version: number | null;
  source_asset_id: string | null;
  created_at: string;
}

export interface RevisionView {
  campaign_id: string;
  current: RevisionRecordView | null;
  history: RevisionRecordView[];
  diff: SpecificationDiffView[];
  can_revise: boolean;
  blocked_reason: string | null;
}

export interface EditFieldChange {
  field: string;
  action?: RevisionAction;
  reason: string;
  new_value?: string | null;
}

// --------------------------------------------------------------- composition
/**
 * Output channels, named exactly as the backend names them.
 *
 * The print sizes exist in the domain but final composition does not offer
 * them: print production is not built, and the API refuses them. They are
 * listed here only so a channel string from an older record still types.
 */
export type Channel =
  | 'instagram_post'
  | 'instagram_portrait'
  | 'instagram_story'
  | 'linkedin'
  | 'facebook'
  | 'web_banner'
  | 'print_a3'
  | 'print_a4';

/** How a channel is written for a person. */
export const CHANNEL_LABELS: Record<Channel, string> = {
  instagram_post: 'Instagram post',
  instagram_portrait: 'Instagram portrait',
  instagram_story: 'Instagram story',
  linkedin: 'LinkedIn',
  facebook: 'Facebook',
  web_banner: 'Web banner',
  print_a3: 'Print A3',
  print_a4: 'Print A4',
};

/** Where a layout element sits, as a fraction of the canvas. */
export interface BoxView {
  x: number;
  y: number;
  width: number;
  height: number;
  anchor: string;
}

export interface TextStyleView {
  font_family: string | null;
  font_weight: string;
  size: number;
  color: string;
  align: string;
  line_height: number;
  letter_spacing: number;
  max_lines: number;
  uppercase: boolean;
  scrim: boolean;
  scrim_opacity: number;
}

export interface LayoutElementView {
  id: string;
  type: 'text' | 'image' | 'logo' | 'shape';
  box: BoxView;
  z: number;
  visible: boolean;
  content: string | null;
  text_style: TextStyleView | null;
  role: string | null;
  storage_key: string | null;
  fit: string;
  fill: string | null;
  opacity: number;
  radius: number;
}

export interface SafeAreaView {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/**
 * The source of truth for a composition.
 *
 * The rendered image is an *output* of this. Every editor control changes a
 * field here and the picture is regenerated — which is what makes an edit
 * reversible and a re-render reproducible.
 */
export interface LayoutSpecView {
  id: string;
  campaign_id: string;
  channel: Channel;
  version: number;
  width: number;
  height: number;
  source_asset_id: string | null;
  specification_version: number;
  plate_storage_key: string | null;
  background_color: string;
  safe_area: SafeAreaView;
  elements: LayoutElementView[];
}

export interface LayoutIssueView {
  element_id: string | null;
  role: string | null;
  severity: 'blocking' | 'warning';
  detail: string;
  suggested_fix: string | null;
}

export interface LayoutReportView {
  verdict: 'PASS' | 'NEEDS_ADJUSTMENT';
  issues: LayoutIssueView[];
}

export interface FinalAssetView {
  id: string;
  campaign_id: string;
  channel: Channel;
  kind: 'FINAL_BRANDED_ASSET';
  version: number;
  width: number;
  height: number;
  mime_type: string;
  size_bytes: number | null;
  url: string;
  /**
   * The same bytes as a file attachment.
   *
   * A separate field rather than `url + '?download=true'`: `url` carries a
   * short-lived signature in its query string, so appending another `?` folds
   * the flag into the token value and the link 404s. The server builds both.
   */
  download_url: string;
  source_asset_id: string | null;
  specification_version: number;
  layout_version: number;
  renderer_version: string;
  created_at: string;
}

export interface CompositionView {
  campaign_id: string;
  channel: Channel;
  layout: LayoutSpecView | null;
  report: LayoutReportView | null;
  final_assets: FinalAssetView[];
  composed_channels: Channel[];
  available_channels: Channel[];
  can_compose: boolean;
  blocked_reason: string | null;
}

/** What the constrained editor may change about one element. */
export interface ElementEdit {
  content?: string;
  visible?: boolean;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  size?: number;
  align?: string;
  color?: string;
  uppercase?: boolean;
}

// ----------------------------------------------------------- command centre
/** What a stage of the campaign is doing right now. */
export type StageState = 'PENDING' | 'BLOCKED' | 'ATTENTION' | 'RUNNING' | 'DONE' | 'FAILED';

export interface StageStateView {
  key: string;
  label: string;
  state: StageState;
  detail: string;
}

/**
 * The campaign command centre.
 *
 * A read model: every field is read from the service that owns it, so this can
 * never disagree with the screen it summarises.
 */
export interface CampaignOverview {
  campaign_id: string;
  title: string;
  status: string;
  brand_id: string;
  brand_name: string;
  stages: StageStateView[];
  campaign_specification_version: number | null;
  creative_specification_version: number | null;
  creative_specification_approved: boolean;
  latest_batch_assets: number;
  failed_generations: number;
  recommended_asset_id: string | null;
  recommended_score: number | null;
  recommended_reason: string;
  selected_asset_id: string | null;
  ranked: RankedAssetView[];
  guardian_verdict: GuardianVerdict | null;
  guardian_checked: number;
  revision_rounds: number;
  composed_channels: Channel[];
  available_channels: Channel[];
  final_assets: FinalAssetView[];
  latest_layout_version: number | null;
  next_stage: string | null;
  next_action: string | null;
}

export interface Health {
  status: string;
  database: string;
  providers: Record<string, string>;
  /** True when this instance is a declared demo: mock providers, no network. */
  demo_mode: boolean;
}

/**
 * Multipart upload. Kept separate from `apiFetch` because a body of FormData
 * must not carry a JSON content-type — the browser sets the boundary itself.
 */
export async function apiUpload<T>(
  path: string,
  form: FormData,
  organizationId: string | null,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (organizationId) headers['X-Organization-Id'] = organizationId;
  await withAuthorization(headers);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/v1${path}`, {
      method: 'POST',
      headers,
      body: form,
      cache: 'no-store',
    });
  } catch (cause) {
    throw new ApiError('NETWORK', `Cannot reach the API at ${API_BASE_URL}. Is it running?`, 0, {
      cause: String(cause),
    });
  }

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const error = (payload as ErrorEnvelope | null)?.error;
    forgetSessionIfRejected(error?.code ?? '');
    throw new ApiError(
      error?.code ?? 'INTERNAL',
      error?.message ?? `Upload failed with status ${response.status}.`,
      response.status,
      error?.details ?? {},
      error?.request_id ?? '',
    );
  }
  return payload as T;
}

export const api = {
  me: (signal?: AbortSignal) => apiFetch<Me>('/me', { signal }),
  health: (signal?: AbortSignal) => apiFetch<Health>('/health', { signal }),
  listProjects: (organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<ProjectPage>('/projects', { organizationId, signal }),
  getProject: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<Project>(`/projects/${id}`, { organizationId, signal }),
  createProject: (organizationId: string | null, body: { name: string; description?: string }) =>
    apiFetch<Project>('/projects', { method: 'POST', body, organizationId }),
  deleteProject: (id: string, organizationId: string | null) =>
    apiFetch<void>(`/projects/${id}`, { method: 'DELETE', organizationId }),

  /* --- brands --------------------------------------------------------- */
  listBrands: (organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<{ items: Brand[] }>('/brands', { organizationId, signal }),
  createBrand: (organizationId: string | null, body: Record<string, unknown>) =>
    apiFetch<Brand>('/brands', { method: 'POST', body, organizationId }),
  getBrand: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<Brand>(`/brands/${id}`, { organizationId, signal }),
  updateBrand: (id: string, organizationId: string | null, body: Record<string, unknown>) =>
    apiFetch<Brand>(`/brands/${id}`, { method: 'PATCH', body, organizationId }),

  /* --- brand brain ---------------------------------------------------- */
  getBrain: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<BrandBrain>(`/brands/${id}/brain`, { organizationId, signal }),
  uploadDocument: (id: string, organizationId: string | null, file: File, title?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (title) form.append('title', title);
    return apiUpload<BrandDocument>(`/brands/${id}/documents`, form, organizationId);
  },
  addTextDocument: (id: string, organizationId: string | null, title: string, content: string) =>
    apiFetch<BrandDocument>(`/brands/${id}/documents/text`, {
      method: 'POST',
      body: { title, content },
      organizationId,
    }),
  uploadAsset: (id: string, organizationId: string | null, file: File, kind: string) => {
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    return apiUpload<BrandAsset>(`/brands/${id}/assets`, form, organizationId);
  },
  queryKnowledge: (id: string, organizationId: string | null, query: string, topK = 5) =>
    apiFetch<{ query: string; hits: KnowledgeHit[] }>(`/brands/${id}/knowledge/query`, {
      method: 'POST',
      body: { query, top_k: topK },
      organizationId,
    }),
  /* --- campaigns ------------------------------------------------------ */
  listCampaigns: (organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<{ items: Campaign[] }>('/campaigns', { organizationId, signal }),
  createCampaign: (organizationId: string | null, brandId: string, title: string) =>
    apiFetch<Campaign>('/campaigns', {
      method: 'POST',
      body: { brand_id: brandId, title },
      organizationId,
    }),
  getCampaign: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<Campaign>(`/campaigns/${id}`, { organizationId, signal }),
  startDiscovery: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<DiscoveryTurn>(`/campaigns/${id}/discovery/start`, {
      method: 'POST',
      organizationId,
      signal,
    }),
  answerQuestion: (id: string, organizationId: string | null, answer: string) =>
    apiFetch<DiscoveryTurn>(`/campaigns/${id}/discovery/answer`, {
      method: 'POST',
      body: { answer },
      organizationId,
    }),
  getConversation: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<{ items: CampaignMessage[] }>(`/campaigns/${id}/conversation`, {
      organizationId,
      signal,
    }),
  updateSpecification: (
    id: string,
    organizationId: string | null,
    edits: Record<string, unknown>,
  ) =>
    apiFetch<CampaignSpecification>(`/campaigns/${id}/specification`, {
      method: 'PATCH',
      body: edits,
      organizationId,
    }),
  confirmSpecification: (id: string, organizationId: string | null) =>
    apiFetch<CampaignSpecification>(`/campaigns/${id}/specification/confirm`, {
      method: 'POST',
      organizationId,
    }),
  listReferences: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<{ items: CampaignReference[] }>(`/campaigns/${id}/references`, {
      organizationId,
      signal,
    }),
  uploadReference: (id: string, organizationId: string | null, file: File, note?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (note) form.append('note', note);
    return apiUpload<CampaignReference>(`/campaigns/${id}/references`, form, organizationId);
  },
  reanalyzeReference: (id: string, referenceId: string, organizationId: string | null) =>
    apiFetch<CampaignReference>(`/campaigns/${id}/references/${referenceId}/analyze`, {
      method: 'POST',
      organizationId,
    }),
  acceptReference: (id: string, referenceId: string, organizationId: string | null) =>
    apiFetch<CampaignReference>(`/campaigns/${id}/references/${referenceId}/accept`, {
      method: 'POST',
      organizationId,
    }),
  listStyleOptions: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<{ items: StyleOption[] }>(`/campaigns/${id}/preferences/options`, {
      organizationId,
      signal,
    }),
  getPreferences: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<PreferencesView>(`/campaigns/${id}/preferences`, { organizationId, signal }),
  setPreferences: (id: string, organizationId: string | null, selected: string[]) =>
    apiFetch<PreferencesView>(`/campaigns/${id}/preferences`, {
      method: 'PUT',
      body: { selected_styles: selected },
      organizationId,
    }),
  getCreativeContext: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<CreativeContextView>(`/campaigns/${id}/creative-context`, {
      organizationId,
      signal,
    }),

  getCreativeStage: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<CreativeStageView>(`/campaigns/${id}/creative`, { organizationId, signal }),
  startCreative: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<CreativeStageView>(`/campaigns/${id}/creative/start`, {
      method: 'POST',
      organizationId,
      signal,
    }),
  decideStrategy: (
    id: string,
    organizationId: string | null,
    body: { decision: StrategyDecision; direction_id?: string; feedback?: string },
  ) =>
    apiFetch<CreativeStageView>(`/campaigns/${id}/creative/strategy`, {
      method: 'POST',
      body,
      organizationId,
    }),
  updateCreativeSpecification: (
    id: string,
    organizationId: string | null,
    edits: Record<string, string> | { channel_copy: Partial<Record<Channel, ChannelCopy>> },
  ) =>
    apiFetch<CreativeSpecification>(`/campaigns/${id}/creative/specification`, {
      method: 'PATCH',
      body: edits,
      organizationId,
    }),
  decideCreativeSpecification: (
    id: string,
    organizationId: string | null,
    body: { decision: SpecificationDecision; feedback?: string },
  ) =>
    apiFetch<CreativeStageView>(`/campaigns/${id}/creative/specification/decide`, {
      method: 'POST',
      body,
      organizationId,
    }),

  getGeneration: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<GenerationView>(`/campaigns/${id}/generation`, { organizationId, signal }),
  compilePrompts: (id: string, organizationId: string | null) =>
    apiFetch<GenerationView>(`/campaigns/${id}/generation/compile`, {
      method: 'POST',
      organizationId,
    }),
  startGeneration: (id: string, organizationId: string | null) =>
    apiFetch<GenerationView>(`/campaigns/${id}/generation/start`, {
      method: 'POST',
      organizationId,
    }),
  retryGenerationJob: (id: string, jobId: string, organizationId: string | null) =>
    apiFetch<GenerationView>(`/campaigns/${id}/generation/jobs/${jobId}/retry`, {
      method: 'POST',
      organizationId,
    }),
  listGeneratedAssets: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<GenerationView>(`/campaigns/${id}/assets`, { organizationId, signal }),
  getGeneratedAsset: (id: string, assetId: string, organizationId: string | null) =>
    apiFetch<GeneratedAssetView>(`/campaigns/${id}/assets/${assetId}`, { organizationId }),

  getEvaluation: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<EvaluationView>(`/campaigns/${id}/evaluation`, { organizationId, signal }),
  startEvaluation: (id: string, organizationId: string | null, assetIds?: string[]) =>
    apiFetch<EvaluationView>(`/campaigns/${id}/evaluation/start`, {
      method: 'POST',
      body: assetIds ? { asset_ids: assetIds } : {},
      organizationId,
    }),
  retryEvaluation: (id: string, evaluationId: string, organizationId: string | null) =>
    apiFetch<EvaluationView>(`/campaigns/${id}/evaluation/${evaluationId}/retry`, {
      method: 'POST',
      organizationId,
    }),
  selectCreative: (
    id: string,
    organizationId: string | null,
    body: { generated_asset_id: string; note?: string },
  ) =>
    apiFetch<EvaluationView>(`/campaigns/${id}/evaluation/select`, {
      method: 'POST',
      body,
      organizationId,
    }),

  getGuardian: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<GuardianView>(`/campaigns/${id}/guardian`, { organizationId, signal }),
  startGuardian: (id: string, organizationId: string | null, assetIds?: string[]) =>
    apiFetch<GuardianView>(`/campaigns/${id}/guardian/start`, {
      method: 'POST',
      body: assetIds ? { asset_ids: assetIds } : {},
      organizationId,
    }),
  retryGuardian: (id: string, resultId: string, organizationId: string | null) =>
    apiFetch<GuardianView>(`/campaigns/${id}/guardian/${resultId}/retry`, {
      method: 'POST',
      organizationId,
    }),

  getRevision: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<RevisionView>(`/campaigns/${id}/revision`, { organizationId, signal }),
  proposeRevision: (
    id: string,
    organizationId: string | null,
    body: { feedback: string; source_asset_id?: string },
  ) =>
    apiFetch<RevisionView>(`/campaigns/${id}/revision`, {
      method: 'POST',
      body,
      organizationId,
    }),
  editRevisionDelta: (
    id: string,
    organizationId: string | null,
    body: {
      interpretation?: string;
      keep?: string[];
      change?: EditFieldChange[];
      add?: EditFieldChange[];
      remove?: EditFieldChange[];
      rationale?: string;
    },
  ) =>
    apiFetch<RevisionView>(`/campaigns/${id}/revision/delta`, {
      method: 'PATCH',
      body,
      organizationId,
    }),
  approveRevisionDelta: (id: string, organizationId: string | null) =>
    apiFetch<RevisionView>(`/campaigns/${id}/revision/approve-delta`, {
      method: 'POST',
      organizationId,
    }),
  approveRevisedSpecification: (id: string, organizationId: string | null) =>
    apiFetch<RevisionView>(`/campaigns/${id}/revision/approve`, {
      method: 'POST',
      organizationId,
    }),
  rejectRevision: (id: string, organizationId: string | null) =>
    apiFetch<RevisionView>(`/campaigns/${id}/revision/reject`, {
      method: 'POST',
      organizationId,
    }),

  getComposition: (
    id: string,
    organizationId: string | null,
    channel: string,
    signal?: AbortSignal,
  ) =>
    apiFetch<CompositionView>(`/campaigns/${id}/composition?channel=${channel}`, {
      organizationId,
      signal,
    }),
  compose: (id: string, organizationId: string | null, channel: string) =>
    apiFetch<CompositionView>(`/campaigns/${id}/composition`, {
      method: 'POST',
      body: { channel },
      organizationId,
    }),
  addCompositionVariant: (
    id: string,
    organizationId: string | null,
    channel: string,
    source: string,
  ) =>
    apiFetch<CompositionView>(`/campaigns/${id}/composition/variants`, {
      method: 'POST',
      body: { channel, source },
      organizationId,
    }),
  editComposition: (
    id: string,
    organizationId: string | null,
    channel: string,
    body: { elements?: Record<string, ElementEdit>; background_color?: string },
  ) =>
    apiFetch<CompositionView>(`/campaigns/${id}/composition?channel=${channel}`, {
      method: 'PATCH',
      body,
      organizationId,
    }),
  renderComposition: (
    id: string,
    organizationId: string | null,
    channel: string,
    format: 'PNG' | 'JPEG' = 'PNG',
  ) =>
    apiFetch<FinalAssetView>(`/campaigns/${id}/composition/render`, {
      method: 'POST',
      body: { channel, format },
      organizationId,
    }),

  getCampaignOverview: (id: string, organizationId: string | null, signal?: AbortSignal) =>
    apiFetch<CampaignOverview>(`/campaigns/${id}/overview`, { organizationId, signal }),
  getHealth: (signal?: AbortSignal) =>
    apiFetch<Health>('/health', { organizationId: null, signal }),

  decideFact: (
    id: string,
    factId: string,
    organizationId: string | null,
    status: 'accepted' | 'rejected',
  ) =>
    apiFetch<BrandFact>(`/brands/${id}/facts/${factId}`, {
      method: 'PATCH',
      body: { status },
      organizationId,
    }),
};
