export type PasswordResetRequestStatus = "PENDING" | "RESOLVED";

export interface PasswordResetRequestItem {
  id: string;
  user_id: string;
  user_full_name: string;
  user_email: string;
  status: PasswordResetRequestStatus;
  created_at: string;
  resolved_at: string | null;
  resolved_by_id: string | null;
  resolved_by_name: string | null;
}

export type Role = "ADMINISTRATOR" | "SUPERVISOR" | "ENUMERATOR";

export type SurveyStatus = "DRAFT" | "PUBLISHED" | "ARCHIVED";

export type QuestionType =
  | "SHORT_TEXT"
  | "LONG_TEXT"
  | "INTEGER"
  | "DECIMAL"
  | "DATE"
  | "TIME"
  | "DATETIME"
  | "SINGLE_CHOICE"
  | "MULTIPLE_CHOICE"
  | "DROPDOWN"
  | "YES_NO"
  | "GPS"
  | "PHOTO"
  | "AUDIO"
  | "SIGNATURE"
  | "BARCODE";

export const QUESTION_TYPE_LABELS: Record<QuestionType, string> = {
  SHORT_TEXT: "Short text",
  LONG_TEXT: "Long text",
  INTEGER: "Integer",
  DECIMAL: "Decimal",
  DATE: "Date",
  TIME: "Time",
  DATETIME: "Date and time",
  SINGLE_CHOICE: "Single choice",
  MULTIPLE_CHOICE: "Multiple choice",
  DROPDOWN: "Dropdown",
  YES_NO: "Yes / No",
  GPS: "GPS location",
  PHOTO: "Photo",
  AUDIO: "Audio",
  SIGNATURE: "Signature",
  BARCODE: "Barcode / QR code",
};

export const CHOICE_TYPES: QuestionType[] = ["SINGLE_CHOICE", "MULTIPLE_CHOICE", "DROPDOWN"];

export interface Choice {
  id?: string;
  value: string;
  label: string;
  order_index: number;
  cascade_parent_value?: string | null;
}

export interface QuestionGroup {
  id?: string;
  title: string;
  description?: string | null;
  order_index: number;
  section_id?: string | null;
  repeatable: boolean;
  min_repeats: number;
  max_repeats?: number | null;
}

export interface SurveySection {
  id?: string;
  title: string;
  description?: string | null;
  order_index: number;
}

export interface Question {
  id?: string;
  code: string;
  label: string;
  hint?: string | null;
  type: QuestionType;
  order_index: number;
  is_required: boolean;
  min_value?: number | null;
  max_value?: number | null;
  min_length?: number | null;
  max_length?: number | null;
  regex_pattern?: string | null;
  relevance_expression?: string | null;
  calculation_expression?: string | null;
  default_value?: string | null;
  cascade_parent_question_id?: string | null;
  choices: Choice[];
  section_id?: string | null;
  group_id?: string | null;
}

export interface SurveySummary {
  id: string;
  title: string;
  description: string | null;
  status: SurveyStatus;
  created_at: string;
  current_version_number: number | null;
  current_version_id: string | null;
  assigned_enumerator_ids: string[];
  scope: "GLOBAL" | "PERSONAL";
  created_by_id: string | null;
  /** True once any content came from the AI questionnaire generator. */
  ai_generated?: boolean;
}

export interface ShareTarget {
  id: string;
  full_name: string;
  email: string;
}

export interface SurveyDetail extends SurveySummary {
  sections: SurveySection[];
  groups: QuestionGroup[];
  questions: Question[];
}

export interface UserAccount {
  id: string;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export type SubmissionStatus = "PENDING" | "UPLOADING" | "UPLOADED" | "SYNCED" | "FAILED";
export type ReviewStatus = "RECEIVED" | "UNDER_REVIEW" | "HAS_ISSUES" | "APPROVED" | "REJECTED" | "RESUBMIT";

export interface SubmissionAnswer {
  id: string;
  question_id: string;
  value_text: string | null;
  media_reference: string | null;
  group_instance_index?: number | null;
}

export interface SubmissionReview {
  id: string;
  submission_id: string;
  reviewer_id: string;
  status: ReviewStatus;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface Submission {
  id: string;
  survey_id: string;
  survey_version_id: string;
  submitted_by_id: string;
  submitted_by_name?: string | null;
  client_submission_uuid: string;
  status: SubmissionStatus;
  gps_latitude: number | null;
  gps_longitude: number | null;
  collected_at: string | null;
  synced_at: string | null;
  created_at: string;
  answers: SubmissionAnswer[];
  review_status: ReviewStatus;
  reviews: SubmissionReview[];
}


export interface Device {
  id: string; device_id: string; user_id: string; app_version: string | null; platform: string;
  last_seen_at: string | null; last_sync_at: string | null; last_sync_status: string | null;
  failed_sync_count: number; sync_requested_at: string | null; is_active: boolean; note: string | null;
}

export interface SubmissionMapPoint {
  id: string;
  survey_id: string;
  survey_title: string;
  submitted_by_id: string;
  latitude: number;
  longitude: number;
  collected_at: string | null;
  status: string;
}


export interface Translation {
  id: string;
  entity_type: "SURVEY" | "SECTION" | "GROUP" | "QUESTION" | "CHOICE";
  entity_id: string;
  field: "title" | "description" | "label" | "hint";
  language_code: string;
  value: string;
}

export type AIConnectionState = "unknown" | "connected" | "failed";

export interface AIStatus {
  enabled: boolean;
  configured: boolean;
  provider: string;
  model: string;
  available: boolean;
  connection_status: AIConnectionState;
  last_checked_at: string | null;
  last_error_code: string | null;
  message: string;
}

export interface AITestConnectionResult {
  success: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  message: string;
}


/* ---------------- AI questionnaire generator (Phase 2) ---------------- */

export interface QuestionnaireBrief {
  research_topic: string;
  survey_title?: string | null;
  research_objectives?: string | null;
  target_respondents?: string | null;
  study_location?: string | null;
  expected_question_count: number;
  language: string;
  methodology?: string | null;
  additional_instructions?: string | null;
}

export interface SkipLogicSuggestion {
  question_code: string;
  expression: string;
  explanation: string;
}

export interface GeneratedQuestionnairePreview {
  title: string;
  description: string | null;
  introduction: string | null;
  respondent_instructions: string | null;
  composed_description: string;
  sections: SurveySection[];
  groups: QuestionGroup[];
  questions: Question[];
  skip_logic: SkipLogicSuggestion[];
  warnings: string[];
  model: string;
  requested_question_count: number | null;
}

export interface ContextQuestion {
  code: string;
  label: string;
  type: QuestionType;
  choice_values: string[];
}

export interface RegeneratedQuestion {
  question: Question;
  skip_logic: SkipLogicSuggestion[];
  warnings: string[];
  model: string;
}

export interface RegeneratedSection {
  section: SurveySection;
  groups: QuestionGroup[];
  questions: Question[];
  skip_logic: SkipLogicSuggestion[];
  warnings: string[];
  model: string;
}

export interface QuestionnaireAvailability {
  available: boolean;
  enabled: boolean;
  configured: boolean;
  max_questions: number;
  message: string;
}


/* ---------------- AI questionnaire editor (Phase 3) ---------------- */

/** The part of the questionnaire the editor works on: exactly what the builder holds. */
export interface EditSnapshot {
  sections: SurveySection[];
  groups: QuestionGroup[];
  questions: Question[];
}

export interface EditOperationView {
  index: number;
  op: string;
  summary: string;
  reason: string | null;
  /** Re-sent verbatim to /preview when the person ticks or unticks operations. */
  raw: Record<string, unknown>;
}

export interface EditRejectedView {
  index: number;
  op: string;
  summary: string;
  reason: string;
  no_change: boolean;
  raw: unknown;
}

export interface EditFieldChange {
  field: string;
  label: string;
  before: unknown;
  after: unknown;
}

export interface EditChoiceChange {
  kind: "ADDED" | "REMOVED" | "CHANGED";
  value: string;
  before_label: string | null;
  after_label: string | null;
}

export interface EditItemChange {
  item_type: "question" | "section";
  change: "ADDED" | "MODIFIED" | "DELETED";
  key: string;
  title: string;
  code: string | null;
  position_before: number | null;
  position_after: number | null;
  fields: EditFieldChange[];
  choices: EditChoiceChange[];
  before: Record<string, any> | null;
  after: Record<string, any> | null;
}

export interface EditOrderChange {
  item_type: "question" | "section";
  key: string;
  title: string;
  from_position: number;
  to_position: number;
}

export interface EditChangeSummary {
  added_questions: number;
  modified_questions: number;
  deleted_questions: number;
  added_sections: number;
  modified_sections: number;
  deleted_sections: number;
  reordered_questions: number;
  reordered_sections: number;
  questions_before: number;
  questions_after: number;
}

export interface EditPreview {
  operations: EditOperationView[];
  rejected: EditRejectedView[];
  warnings: string[];
  added: EditItemChange[];
  modified: EditItemChange[];
  deleted: EditItemChange[];
  order_changes: EditOrderChange[];
  summary: EditChangeSummary;
  has_changes: boolean;
  blocked: string | null;
  requires_confirmation: boolean;
  confirmation_reasons: string[];
  /** The questionnaire as it would be after the changes. */
  result: EditSnapshot;
}

export interface EditProposal extends EditPreview {
  message: string;
  model: string;
}

export interface SurveyVersionSummary {
  id: string;
  version_number: number;
  is_current: boolean;
  created_at: string;
  created_by_id: string | null;
  created_by_name: string | null;
  change_source: "MANUAL" | "AI_EDIT" | null;
  change_summary: string | null;
  question_count: number;
  section_count: number;
}

export interface SurveyVersionDetail extends SurveyVersionSummary {
  sections: SurveySection[];
  groups: QuestionGroup[];
  questions: Question[];
}

// ---------------------------------------------------------------- AI questionnaire reviewer (Phase 4)

export type ReviewSeverity = "CRITICAL" | "WARNING" | "SUGGESTION" | "GOOD";

export interface ReviewFinding {
  id: string;
  severity: ReviewSeverity;
  category: string;
  question_code: string | null;
  question_label: string | null;
  title: string;
  explanation: string;
  recommendation: string;
  /** An edit operation implementing the recommendation (already checked on the server), or null. */
  fix: Record<string, unknown> | null;
  fix_summary: string | null;
  source: "RULE" | "AI";
}

export interface ReviewCoverageItem {
  objective: string;
  covered: boolean;
  question_codes: string[];
  note: string;
}

export interface ReviewReport {
  score: number;
  grade: string;
  summary: string;
  counts: Record<ReviewSeverity, number>;
  findings: ReviewFinding[];
  coverage: ReviewCoverageItem[];
  objectives_checked: boolean;
  stats: {
    questions: number;
    sections: number;
    required_questions: number;
    questions_with_hints: number;
    choice_questions: number;
    questions_with_skip_logic: number;
  };
  score_breakdown: {
    critical_penalty: number;
    warning_penalty: number;
    suggestion_penalty: number;
    good_practice_bonus: number;
    size_scale: number;
  };
  ai_used: boolean;
  ai_error: string | null;
  model: string;
  generated_at: string;
  limitations: string[];
}


/* ---------- Phase 5: multilingual questionnaires ---------- */

export type TranslationStatus = "MISSING" | "OUTDATED" | "AI_DRAFT" | "EDITED" | "REVIEWED";

export interface I18nLanguage {
  code: string;
  name: string;
  native_name: string;
  rtl: boolean;
}

export interface I18nIssue {
  severity: "BLOCK" | "WARN";
  code: string;
  message: string;
}

export interface I18nSummary {
  total: number;
  translated: number;
  missing: number;
  outdated: number;
  ai_draft: number;
  edited: number;
  reviewed: number;
  with_issues: number;
  blocked: number;
  orphaned: number;
  usable: number;
  percent_complete: number;
  needs_attention: number;
}

export interface I18nOverview {
  survey_id: string;
  version_number: number | null;
  total_units: number;
  languages: (I18nLanguage & I18nSummary)[];
}

export interface I18nUnit {
  entity_type: "SURVEY" | "SECTION" | "GROUP" | "QUESTION" | "CHOICE" | "SYSTEM";
  entity_key: string;
  field: "title" | "description" | "label" | "hint" | "text";
  label: string;
  context: string;
  multiline: boolean;
  max_len: number;
  source: string;
  value: string | null;
  status: TranslationStatus;
  issues: I18nIssue[];
}

export interface I18nLanguageData {
  language: I18nLanguage;
  summary: I18nSummary;
  units: I18nUnit[];
}

export interface I18nSaveItem {
  entity_type: I18nUnit["entity_type"];
  entity_key: string;
  field: I18nUnit["field"];
  value?: string;
  status?: "EDITED" | "REVIEWED";
}

export interface I18nTranslateRequest {
  scope?: "missing" | "outdated" | "missing_and_outdated" | "all";
  entity_types?: I18nUnit["entity_type"][];
  units?: { entity_type: I18nUnit["entity_type"]; entity_key: string; field: I18nUnit["field"] }[];
  overwrite_manual?: boolean;
  max_units?: number;
}

export interface I18nTranslateResult {
  selected: number;
  attempted: number;
  translated: number;
  remaining: number;
  protected_skipped: number;
  rejected: { label: string; reason: string }[];
  not_returned: number;
  ai_error: string | null;
  model: string;
  summary: I18nSummary;
}

export interface I18nCompareRow {
  entity_type: string;
  entity_key: string;
  field: string;
  label: string;
  source: string;
  translations: Record<string, { value: string | null; status: TranslationStatus; issues: I18nIssue[] }>;
}

export interface I18nLocalized {
  language: string;
  rtl: boolean;
  percent_complete: number;
  survey: { title?: string; description?: string };
  sections: Record<string, { title?: string; description?: string }>;
  groups: Record<string, { title?: string; description?: string }>;
  questions: Record<string, { label?: string; hint?: string }>;
  choices: Record<string, string>;
  messages: Record<string, string>;
}

export interface HausaFinding {
  entity_type: string;
  entity_key: string;
  field: string;
  label: string;
  severity: "WARNING" | "SUGGESTION";
  category: string;
  message: string;
  suggestion: string | null;
  source: "RULE" | "AI";
}

export interface HausaReport {
  score: number;
  grade: string;
  summary: string;
  findings: HausaFinding[];
  reviewed_units: number;
  skipped_outdated: number;
  skipped_human_reviewed: number;
  ai_used: boolean;
  ai_units: number;
  ai_error: string | null;
  model: string;
  limitations: string[];
}
