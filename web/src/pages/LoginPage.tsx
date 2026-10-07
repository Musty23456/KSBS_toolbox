import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { extractErrorMessage } from "../api/client";
import { markWelcomeAudioForNextVisit } from "../components/WelcomeAudio";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
markWelcomeAudioForNextVisit();
navigate("/");
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
          <small>by Musty — field survey administration</small>
        </div>

        <form onSubmit={handleSubmit} style={{ marginTop: 24 }}>
          {error && <div className="form-error">{error}</div>}

          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
            />
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          <div
  style={{
    textAlign: "right",
    marginBottom: 16,
  }}
>
  <Link to="/forgot-password">
    Forgot password?
  </Link>
</div>

          <button type="submit" className="btn btn-primary" disabled={isSubmitting} style={{ width: "100%" }}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="login-demo-hint">
          Demo administrator: admin@kbstoolbox.app / ChangeMe123!
          <br />
          (Set up by running the backend's seed script.)
        </div>
        <div className="login-demo-hint">
          New enumerator? <Link to="/register">Create an account</Link>
        </div>
      </div>
    </div>
  );
}
