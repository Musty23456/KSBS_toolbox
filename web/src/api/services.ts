import type {
  AIStatus,
  AITestConnectionResult,
  EditPreview,
  EditProposal,
  ReviewReport,
  EditSnapshot,
  GeneratedQuestionnairePreview,
  QuestionnaireAvailability,
  QuestionnaireBrief,
  ContextQuestion,
  Question,
  RegeneratedQuestion,
  RegeneratedSection,
  PasswordResetRequestItem,
  PasswordResetRequestStatus,
  Role,
  Submission,
  SubmissionStatus,
  SurveyDetail,
  SurveyVersionDetail,
  SurveyVersionSummary,
  SurveySummary,
  ShareTarget,
  UserAccount,
  Device,
} from "./types";
import { apiClient, setStoredToken } from "./client"
import type {
  HausaReport,
  I18nCompareRow,
  I18nLanguage,
  I18nLanguageData,
  I18nLocalized,
  I18nOverview,
  I18nSaveItem,
  I18nSummary,
  I18nTranslateRequest,
  I18nTranslateResult,
  I18nUnit,
} from "./types";

/* =========================================================
   AUTH API
========================================================= */

export const authApi = {
  async register(payload: {
    full_name: string;
    email: string;
    password: string;
  }): Promise<UserAccount> {
    const { data } = await apiClient.post("/api/auth/register", payload);
    return data;
  },

  async login(email: string, password: string) {
    const { data } = await apiClient.post("/api/auth/login-json", {
      email,
      password,
    });

    setStoredToken(data.access_token);
    return data;
  },

  async logout() {
    try {
      await apiClient.post("/api/auth/logout");
    } finally {
      setStoredToken(null);
    }
  },

  async me(): Promise<UserAccount> {
    const { data } = await apiClient.get("/api/auth/me");
    return data;
  },

  async forgotPassword(email: string) {
    const { data } = await apiClient.post(
      "/api/auth/forgot-password",
      {
        email,
      }
    );

    return data;
  },

  
async listPasswordResetRequests(
    statusFilter?: PasswordResetRequestStatus
  ): Promise<PasswordResetRequestItem[]> {
    const { data } = await apiClient.get(
      "/api/auth/password-reset-requests",
      {
        params: statusFilter
          ? { status_filter: statusFilter }
          : undefined,
      }
    );

    return data;
  },

  async resolvePasswordResetRequest(
    requestId: string,
    newPassword: string
  ): Promise<PasswordResetRequestItem> {
    const { data } = await apiClient.post(
      `/api/auth/password-reset-requests/${requestId}/resolve`,
      {
        new_password: newPassword,
      }
    );

    return data;
  },
};

/* =========================================================
   SURVEYS API
========================================================= */

export const surveysApi = {
  async list(
    statusFilter?: string
  ): Promise<SurveySummary[]> {
    const { data } = await apiClient.get("/api/surveys", {
      params: statusFilter
        ? { status_filter: statusFilter }
        : undefined,
    });

    return data;
  },

  async get(id: string): Promise<SurveyDetail> {
    const { data } = await apiClient.get(
      `/api/surveys/${id}`
    );

    return data;
  },

  async create(payload: {
    title: string;
    description?: string;
    scope?: "GLOBAL" | "PERSONAL";
    questions: any[];
    sections?: any[];
    groups?: any[];
    assigned_enumerator_ids?: string[];
    ai_generated?: boolean;
  }): Promise<SurveyDetail> {
    const { data } = await apiClient.post(
      "/api/surveys",
      payload
    );

    return data;
  },

  async update(
    id: string,
    payload: {
      title?: string;
      description?: string;
      questions?: any[];
      sections?: any[];
      groups?: any[];
      assigned_enumerator_ids?: string[];
      ai_generated?: boolean;
      /** Stored on the new version in the version history. */
      change_summary?: string;
      change_source?: "MANUAL" | "AI_EDIT";
    }
  ): Promise<SurveyDetail> {
    const { data } = await apiClient.put(
      `/api/surveys/${id}`,
      payload
    );

    return data;
  },

  /** AI-generated surveys need confirmReview=true (the server refuses otherwise). */
  async publish(id: string, confirmReview = false): Promise<SurveyDetail> {
    const { data } = await apiClient.post(
      `/api/surveys/${id}/publish`,
      confirmReview ? { confirm_ai_review: true } : undefined
    );

    return data;
  },

  async unpublish(id: string): Promise<SurveyDetail> {
    const { data } = await apiClient.post(
      `/api/surveys/${id}/unpublish`
    );

    return data;
  },

  /** Version history, newest first. Only people who can edit the survey may call this. */
  async versions(id: string): Promise<SurveyVersionSummary[]> {
    const { data } = await apiClient.get(`/api/surveys/${id}/versions`);
    return data;
  },

  async getVersion(id: string, versionId: string): Promise<SurveyVersionDetail> {
    const { data } = await apiClient.get(`/api/surveys/${id}/versions/${versionId}`);
    return data;
  },

  async archive(id: string): Promise<void> {
    await apiClient.delete(`/api/surveys/${id}`);
  },

  /** Active enumerators (other than me) a personal survey can be shared with. */
  async shareTargets(): Promise<ShareTarget[]> {
    const { data } = await apiClient.get("/api/surveys/share-targets");
    return data;
  },

  async getShares(id: string): Promise<string[]> {
    const { data } = await apiClient.get(`/api/surveys/${id}/shares`);
    return data.user_ids;
  },

  async setShares(id: string, userIds: string[]): Promise<string[]> {
    const { data } = await apiClient.put(`/api/surveys/${id}/shares`, { user_ids: userIds });
    return data.user_ids;
  },
};


/* =========================================================
   SUBMISSIONS API
========================================================= */

export const submissionsApi = {
  async review(
    id: string,
    payload: {
      status: string;
      comment?: string;
    }
  ) {
    const { data } = await apiClient.post(
      `/api/submissions/${id}/review`,
      payload
    );

    return data;
  },

  async create(payload: {
    client_submission_uuid: string;
    survey_id: string;
    survey_version_id: string;
    collected_at?: string;
    gps_latitude?: number | null;
    gps_longitude?: number | null;
    answers: {
      question_id: string;
      value_text?: string | null;
    }[];
  }): Promise<Submission> {
    const { data } = await apiClient.post(
      "/api/submissions",
      payload
    );

    return data;
  },

  async list(filters: {
    survey_id?: string;
    status?: SubmissionStatus;
  }): Promise<Submission[]> {
    const { data } = await apiClient.get(
      "/api/submissions",
      {
        params: filters,
      }
    );

    return data;
  },

  async get(id: string): Promise<Submission> {
    const { data } = await apiClient.get(
      `/api/submissions/${id}`
    );

    return data;
  },
};


/* =========================================================
   USERS API
========================================================= */

export const usersApi = {
  async list(): Promise<UserAccount[]> {
    const { data } = await apiClient.get("/api/users");
    return data;
  },

  async create(payload: {
    full_name: string;
    email: string;
    password: string;
    role: Role;
  }): Promise<UserAccount> {
    const { data } = await apiClient.post(
      "/api/users",
      payload
    );

    return data;
  },

  async update(
    id: string,
    payload: Partial<{
      full_name: string;
      role: Role;
      is_active: boolean;
      password: string;
    }>
  ) {
    const { data } = await apiClient.put(
      `/api/users/${id}`,
      payload
    );

    return data;
  },

  async deactivate(id: string): Promise<void> {
    await apiClient.delete(`/api/users/${id}`);
  },
};


/* =========================================================
   DEVICES API
========================================================= */

export const devicesApi = {
  async list(): Promise<Device[]> {
    const { data } = await apiClient.get("/api/devices");
    return data;
  },

  async requestSync(deviceId: string): Promise<Device> {
    const { data } = await apiClient.post(
      `/api/devices/${deviceId}/request-sync`
    );

    return data;
  },

  async deactivate(deviceId: string): Promise<Device> {
    const { data } = await apiClient.post(
      `/api/devices/${deviceId}/deactivate`
    );

    return data;
  },
};


/* =========================================================
   MAP API
========================================================= */

export const mapApi = {
  async submissionPoints(
    filters?: {
      survey_id?: string;
      status?: string;
    }
  ): Promise<
    import("./types").SubmissionMapPoint[]
  > {
    const { data } = await apiClient.get(
      "/api/map/submissions",
      {
        params: filters,
      }
    );

    return data;
  },
};


/* =========================================================
   EXPORTS API
========================================================= */

export const exportsApi = {
  async download(
    format: "csv" | "json" | "xlsx" | "pdf",
    filters: {
      survey_id?: string;
      status?: string;
      submitted_by_id?: string;
      date_from?: string;
      date_to?: string;
    } = {}
  ) {
    const response = await apiClient.get(
      `/api/exports/${format}`,
      {
        params: filters,
        responseType: "blob",
      }
    );

    const contentType = String(
      response.headers["content-type"] ||
        "application/octet-stream"
    );

    const blob = new Blob(
      [response.data],
      {
        type: contentType,
      }
    );

    const url =
      window.URL.createObjectURL(blob);

    const link =
      document.createElement("a");

    link.href = url;

    link.download =
      `kbs-submissions.${
        format === "xlsx"
          ? "xlsx"
          : format
      }`;

    document.body.appendChild(link);
    link.click();
    link.remove();

    window.URL.revokeObjectURL(url);
  },
};


/* =========================================================
   ANALYTICS API
========================================================= */

export const analyticsApi = {
  async overview(
    filters: {
      survey_id?: string;
      date_from?: string;
      date_to?: string;
    } = {}
  ) {
    const { data } = await apiClient.get(
      "/api/analytics/overview",
      {
        params: filters,
      }
    );

    return data;
  },

  async questions(
    surveyId: string,
    questionId?: string
  ) {
    const { data } = await apiClient.get(
      "/api/analytics/questions",
      {
        params: {
          survey_id: surveyId,
          question_id: questionId,
        },
      }
    );

    return data;
  },
};


/* =========================================================
   TRANSLATIONS API
========================================================= */

export const translationsApi = {
  async languages(): Promise<
    {
      code: string;
      name: string;
    }[]
  > {
    const { data } = await apiClient.get(
      "/api/surveys/languages"
    );

    return data;
  },

  async list(
    surveyId: string
  ): Promise<
    import("./types").Translation[]
  > {
    const { data } = await apiClient.get(
      `/api/surveys/${surveyId}/translations`
    );

    return data;
  },

  async upsert(
    surveyId: string,
    payload: Omit<
      import("./types").Translation,
      "id"
    >
  ): Promise<
    import("./types").Translation
  > {
    const { data } = await apiClient.put(
      `/api/surveys/${surveyId}/translations`,
      payload
    );

    return data;
  },
};


/* =========================================================
   MULTILINGUAL QUESTIONNAIRES (Phase 5)
========================================================= */

export const i18nApi = {
  async overview(surveyId: string): Promise<I18nOverview> {
    return (await apiClient.get(`/api/surveys/${surveyId}/i18n/overview`)).data;
  },
  async available(surveyId: string): Promise<(I18nLanguage & { percent_complete: number })[]> {
    return (await apiClient.get(`/api/surveys/${surveyId}/i18n/available`)).data;
  },
  async language(surveyId: string, code: string): Promise<I18nLanguageData> {
    return (await apiClient.get(`/api/surveys/${surveyId}/i18n/${code}`)).data;
  },
  async localized(surveyId: string, code: string): Promise<I18nLocalized> {
    return (await apiClient.get(`/api/surveys/${surveyId}/i18n/${code}/localized`)).data;
  },
  async compare(surveyId: string, codes: string[]): Promise<{ languages: I18nLanguage[]; rows: I18nCompareRow[] }> {
    return (await apiClient.get(`/api/surveys/${surveyId}/i18n/compare`, { params: { languages: codes.join(",") } })).data;
  },
  async save(
    surveyId: string,
    code: string,
    units: I18nSaveItem[]
  ): Promise<{ saved: number; removed: number; summary: I18nSummary; units: I18nUnit[] }> {
    return (await apiClient.put(`/api/surveys/${surveyId}/i18n/${code}/units`, { units })).data;
  },
  async translate(surveyId: string, code: string, body: I18nTranslateRequest): Promise<I18nTranslateResult> {
    return (await apiClient.post(`/api/surveys/${surveyId}/i18n/${code}/translate`, body)).data;
  },
  async remove(surveyId: string, code: string): Promise<void> {
    await apiClient.delete(`/api/surveys/${surveyId}/i18n/${code}`);
  },
  async hausaReview(surveyId: string, useAi: boolean): Promise<HausaReport> {
    return (await apiClient.post(`/api/surveys/${surveyId}/i18n/ha/review`, { use_ai: useAi })).data;
  },
  async importLegacy(surveyId: string): Promise<{ imported: number; skipped_existing: number; not_matched: number }> {
    return (await apiClient.post(`/api/surveys/${surveyId}/i18n/import-legacy`)).data;
  },
};


/* =========================================================
   AUDIT API
========================================================= */

export const auditApi = {
  async summary(
    filters: {
      date_from?: string;
      date_to?: string;
    } = {}
  ) {
    const { data } = await apiClient.get(
      "/api/audit/summary",
      {
        params: filters,
      }
    );

    return data;
  },

  async logs(
    filters: {
      action?: string;
      entity_type?: string;
      actor_id?: string;
      search?: string;
      date_from?: string;
      date_to?: string;
      page?: number;
      page_size?: number;
    } = {}
  ) {
    const { data } = await apiClient.get(
      "/api/audit/logs",
      {
        params: filters,
      }
    );

    return data;
  },

  async filters() {
    const { data } = await apiClient.get(
      "/api/audit/filters"
    );

    return data;
  },
};


/* =========================================================
   AI API
========================================================= */

export const aiApi = {
  async status(): Promise<AIStatus> {
    const { data } = await apiClient.get("/api/ai/status");
    return data;
  },

  async testConnection(): Promise<AITestConnectionResult> {
    const { data } = await apiClient.post("/api/ai/test-connection");
    return data;
  },
};


/* ---------------- AI questionnaire generator (Phase 2) ----------------
   These calls only ever return PREVIEWS. Nothing is saved until the user
   confirms in the Survey Builder and the normal surveysApi.create/update runs. */

// Generation can take a while (a full questionnaire is a long answer).
const GENERATION_TIMEOUT_MS = 180_000;

export const aiQuestionnaireApi = {
  async availability(): Promise<QuestionnaireAvailability> {
    const { data } = await apiClient.get("/api/ai/questionnaire/availability");
    return data;
  },

  async generate(brief: QuestionnaireBrief): Promise<GeneratedQuestionnairePreview> {
    const { data } = await apiClient.post("/api/ai/questionnaire/generate", brief, { timeout: GENERATION_TIMEOUT_MS });
    return data;
  },

  async regenerateQuestion(payload: {
    brief: QuestionnaireBrief;
    section_title?: string | null;
    question: Question;
    instruction?: string | null;
    preceding_questions: ContextQuestion[];
    other_codes: string[];
  }): Promise<RegeneratedQuestion> {
    const { data } = await apiClient.post("/api/ai/questionnaire/regenerate-question", payload, { timeout: GENERATION_TIMEOUT_MS });
    return data;
  },

  async regenerateSection(payload: {
    brief: QuestionnaireBrief;
    section_title: string;
    section_description?: string | null;
    current_questions: ContextQuestion[];
    preceding_questions: ContextQuestion[];
    other_codes: string[];
    question_count?: number | null;
    instruction?: string | null;
  }): Promise<RegeneratedSection> {
    const { data } = await apiClient.post("/api/ai/questionnaire/regenerate-section", payload, { timeout: GENERATION_TIMEOUT_MS });
    return data;
  },
};


/* ---------------- AI questionnaire editor (Phase 3) ----------------
   Both calls only return PREVIEWS of structured operations. Nothing is saved: the person applies
   a preview to the builder's draft and saves through surveysApi.update (a new version). */

export const aiEditApi = {
  async propose(payload: {
    instruction: string;
    snapshot: EditSnapshot;
    survey_title?: string | null;
    survey_description?: string | null;
  }): Promise<EditProposal> {
    const { data } = await apiClient.post("/api/ai/questionnaire/edit/propose", payload, { timeout: GENERATION_TIMEOUT_MS });
    return data;
  },

  /** Re-validate a chosen set of operations (no AI call). */
  async preview(snapshot: EditSnapshot, operations: Record<string, unknown>[]): Promise<EditPreview> {
    const { data } = await apiClient.post("/api/ai/questionnaire/edit/preview", { snapshot, operations });
    return data;
  },
};

/* ---------------------------------------------------------------- AI questionnaire reviewer (Phase 4)
   Read-only: returns a report. Applying a suggestion goes through aiEditApi.preview and the builder's
   normal apply / undo / save flow. */

export const aiReviewApi = {
  async review(payload: {
    snapshot: EditSnapshot;
    objectives?: string | null;
    survey_title?: string | null;
    survey_description?: string | null;
    use_ai?: boolean;
  }): Promise<ReviewReport> {
    const { data } = await apiClient.post("/api/ai/questionnaire/review", payload, { timeout: GENERATION_TIMEOUT_MS });
    return data;
  },
};
