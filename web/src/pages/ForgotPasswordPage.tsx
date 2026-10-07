import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { authApi } from "../api/services";
import { extractErrorMessage } from "../api/client";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    setMessage(null);
    setError(null);
    setIsSubmitting(true);

    try {
      const response = await authApi.forgotPassword(email);
      setMessage(response.message);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-panel">
        <div className="login-brand">
          KSBS TOOLBOX
          <small>Request a password reset</small>
        </div>

        <p style={{ marginTop: 12, color: "#6b7280", fontSize: 14 }}>
          Enter your account email below. An administrator will see your
          request and get in touch with a new password.
        </p>

        <form onSubmit={handleSubmit} style={{ marginTop: 24 }}>
          {message && <div className="form-success">{message}</div>}
          {error && <div className="form-error">{error}</div>}

          <div className="field">
            <label htmlFor="email">Email</label>

            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="Enter your account email"
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSubmitting}
            style={{ width: "100%" }}
          >
            {isSubmitting ? "Sending…" : "Notify an administrator"}
          </button>
        </form>

        <div className="login-demo-hint">
          Remember your password?{" "}
          <Link to="/login">Back to sign in</Link>
        </div>
      </div>
    </div>
  );
}
