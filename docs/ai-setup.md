# AI integration (Phase 1) — setup and troubleshooting

Phase 1 adds the *infrastructure* for AI features: a Gemini connection, a
status endpoint, a connection test, security controls, usage logging and a
dashboard status card. The questionnaire generator built on top of it (Phase 2) is described in
[`ai-questionnaire.md`](ai-questionnaire.md).

The Gemini API key lives **only on the backend**. It is never sent to the web
dashboard or the Android app, never returned by any endpoint, and never logged.

## 1. Get a Gemini API key

1. Sign in at <https://aistudio.google.com/apikey> with a Google account.
2. Choose **Create API key** (create or pick a Google Cloud project when asked).
3. Copy the key. Treat it like a password; do not commit it or paste it into chats.

Check the current free-tier limits and pricing for your account in Google AI
Studio, since they change over time.

## 2. Configure the backend

Add to `backend/.env` (git-ignored) or to your host's environment variables
(e.g. Render → Environment):

| Variable | Default | Meaning |
|---|---|---|
| `AI_ENABLED` | `false` | Master switch. AI does nothing unless `true`. |
| `AI_PROVIDER` | `gemini` | Only `gemini` is implemented. |
| `GEMINI_API_KEY` | *(empty)* | Your key. Required when `AI_ENABLED=true`. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model id. Change if Google retires or renames it. |
| `AI_REQUEST_TIMEOUT` | `30` | Seconds per call (1–120). |
| `AI_MAX_RETRIES` | `2` | Retries for network/timeout/5xx errors (0–5). |
| `AI_RATE_LIMIT_PER_MINUTE` | `10` | Per-user limit on AI endpoints. |
| `AI_MAX_REQUEST_BYTES` | `16384` | Largest request body AI endpoints accept. |
| `AI_MAX_PROMPT_CHARS` | `8000` | Longest prompt the AI service forwards. |

Invalid values (e.g. `AI_REQUEST_TIMEOUT=0`, a malformed `GEMINI_MODEL`) make
the backend refuse to start with a clear message instead of failing later.

Install the SDK (already in `requirements.txt`): `pip install -r requirements.txt`.

## 3. Enable AI

Set `AI_ENABLED=true` and `GEMINI_API_KEY=...`, then restart the backend.
If AI is enabled without a key, the app still starts (a warning is logged) and
the status card shows **Not configured**.

## 4. Test the connection

- **Dashboard:** log in as an Administrator, open Overview, and press
  **Test connection** on the *AI assistant* card.
- **API:**
  ```bash
  curl -X POST http://localhost:8000/api/ai/test-connection \
       -H "Authorization: Bearer <admin access token>"
  ```
- `GET /api/ai/status` (Administrator or Supervisor) shows enabled / provider /
  model and the **last** test result. It never calls Google, so it costs no quota.
- `POST /api/ai/test-connection` is Administrator-only and makes one tiny call.

## 5. Errors and troubleshooting

Every AI error returns `{"detail": "<safe message>", "code": "<CODE>"}`.

| Code | HTTP | Likely cause / fix |
|---|---|---|
| `AI_DISABLED` | 503 | `AI_ENABLED` is not `true`. |
| `AI_NOT_CONFIGURED` | 503 | `GEMINI_API_KEY` is empty. |
| `AI_INVALID_API_KEY` | 502 | Key wrong, revoked, or restricted. Create a new key. |
| `AI_QUOTA_EXCEEDED` | 429 | Provider quota/rate limit hit. Wait, or raise your quota. |
| `AI_MODEL_NOT_FOUND` | 502 | `GEMINI_MODEL` is wrong or retired. Pick a current model id. |
| `AI_NETWORK_ERROR` | 502 | Server cannot reach Google (firewall/DNS/outage). |
| `AI_TIMEOUT` | 504 | Slow response. Raise `AI_REQUEST_TIMEOUT` or retry. |
| `AI_SERVICE_UNAVAILABLE` | 503 | Google-side outage, or the `google-genai` package is missing. |
| `AI_INVALID_RESPONSE` | 502 | Empty or oversized reply from the model. |
| `AI_RATE_LIMITED` | 429 | Per-user limit; honour the `Retry-After` header. |
| `AI_REQUEST_TOO_LARGE` | 413 | Body exceeds `AI_MAX_REQUEST_BYTES`. |

Detailed (secret-free) diagnostics are in the server log under `app.ai.*`.
Raw provider error text is never returned to clients.

## 6. Usage monitoring

Each provider call writes one row to `ai_usage_logs`: user id, provider, model,
request type, timestamp, success flag, error **code**, duration (ms). Prompts,
responses and questionnaire data are never stored. The table is created
automatically at startup (`create_all`), so no migration is needed.

Example: `SELECT request_type, success, count(*) FROM ai_usage_logs GROUP BY 1,2;`

## 7. Adding another provider later

Implement `AIProvider` (`app/ai/providers/base.py`), register it in
`app/ai/providers/__init__.py`, and allow its name in the `AI_PROVIDER`
validator in `app/config.py`. `AIService`, the endpoints and the dashboard do
not need to change.
