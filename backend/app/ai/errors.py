"""
AI error hierarchy.

Every error carries a stable machine-readable ``code`` and a *safe* message
written for end users. Raw provider exception text is never exposed, because
it can contain request details or key fragments.
"""

from __future__ import annotations


class AIError(Exception):
    code: str = "AI_ERROR"
    status_code: int = 502
    safe_message: str = "The AI service could not complete the request."
    retryable: bool = False

    def __init__(self, safe_message: str | None = None):
        self.safe_message = safe_message or type(self).safe_message
        super().__init__(self.safe_message)


class AIDisabledError(AIError):
    code = "AI_DISABLED"
    status_code = 503
    safe_message = "AI features are disabled on this server."


class AINotConfiguredError(AIError):
    code = "AI_NOT_CONFIGURED"
    status_code = 503
    safe_message = "AI is enabled but no API key is configured on the server."


class AIInvalidRequestError(AIError):
    code = "AI_INVALID_REQUEST"
    status_code = 422
    safe_message = "The AI request was not valid."


class AIRequestTooLargeError(AIError):
    code = "AI_REQUEST_TOO_LARGE"
    status_code = 413
    safe_message = "The AI request is too large."


class AIRateLimitedError(AIError):
    code = "AI_RATE_LIMITED"
    status_code = 429
    safe_message = "Too many AI requests. Please wait a moment and try again."

    def __init__(self, safe_message: str | None = None, retry_after: int = 60):
        super().__init__(safe_message)
        self.retry_after = retry_after


class AIAuthenticationError(AIError):
    code = "AI_INVALID_API_KEY"
    status_code = 502
    safe_message = "The AI provider rejected the configured API key."


class AIQuotaExceededError(AIError):
    code = "AI_QUOTA_EXCEEDED"
    status_code = 429
    safe_message = "The AI provider quota has been exceeded. Try again later."


class AIModelNotFoundError(AIError):
    code = "AI_MODEL_NOT_FOUND"
    status_code = 502
    safe_message = "The configured AI model was not found or is not available."


class AINetworkError(AIError):
    code = "AI_NETWORK_ERROR"
    status_code = 502
    safe_message = "Could not reach the AI provider."
    retryable = True


class AITimeoutError(AIError):
    code = "AI_TIMEOUT"
    status_code = 504
    safe_message = "The AI provider took too long to respond."
    retryable = True


class AIServiceUnavailableError(AIError):
    code = "AI_SERVICE_UNAVAILABLE"
    status_code = 503
    safe_message = "The AI provider is temporarily unavailable."
    retryable = True


class AIInvalidResponseError(AIError):
    code = "AI_INVALID_RESPONSE"
    status_code = 502
    safe_message = "The AI provider returned a response that could not be used."


class AIBlockedContentError(AIError):
    code = "AI_CONTENT_BLOCKED"
    status_code = 422
    safe_message = "The AI provider declined to process this content."


class AIResponseTruncatedError(AIError):
    """The model hit its output-token limit mid-answer, so the JSON is incomplete."""

    code = "AI_RESPONSE_TRUNCATED"
    status_code = 422
    safe_message = (
        "The AI response was cut off because the questionnaire was too long. "
        "Ask for fewer questions, or generate one section at a time."
    )


class AIInvalidJsonError(AIInvalidResponseError):
    code = "AI_INVALID_JSON"
    safe_message = "The AI returned a response that was not valid JSON. Please try again."


class AIInvalidQuestionnaireError(AIInvalidResponseError):
    """Valid JSON, but it does not describe a usable questionnaire."""

    code = "AI_INVALID_QUESTIONNAIRE"
    safe_message = "The AI returned a questionnaire that failed validation. Please try again."
