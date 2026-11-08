const [loadError, setLoadError] = useState<string | null>(null);
import { extractErrorMessage }
import { useEffect, useState } from "react";
import { WelcomeAudio } from "../components/WelcomeAudio";
import { Link } from "react-router-dom";
import { surveysApi, submissionsApi } from "../api/services";
import type { Submission, SurveySummary } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { StatusBadge } from "../components/StatusBadge";
import { AIStatusCard } from "../components/AIStatusCard";

export function DashboardPage() {
  const { user } = useAuth();
  const [surveys, setSurveys] = useState<SurveySummary[]>([]);
  const [recentSubmissions, setRecentSubmissions] = useState<Submission[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const canSeeSubmissions = user?.role === "ADMINISTRATOR" || user?.role === "SUPERVISOR";
  const isAdmin = user?.role === "ADMINISTRATOR";

    useEffect(() => {
    (async () => {
      try {
        const surveyList = await surveysApi.list();
        setSurveys(surveyList);
        if (canSeeSubmissions) {
          try {
            const submissions = await submissionsApi.list({});
            setRecentSubmissions(submissions.slice(0, 6));
          } catch {
            // leave empty
          }
        }
      } catch (err) {
        setLoadError(extractErrorMessage(err));
      } finally {
        setIsLoading(false);
      }
    })();
  }, [canSeeSubmissions]);

  const published = surveys.filter((s) => s.status === "PUBLISHED").length;
  const draft = surveys.filter((s) => s.status === "DRAFT").length;

  return (
    <div>
      <WelcomeAudio />
      <div className="page-header">
        <div>
          <h1>Overview</h1>
          <p>Welcome back, {user?.full_name.split(" ")[0]}.</p>
        </div>
      </div>

      {isLoading ? (
        <p className="loading-text">Loading…</p>
            ) : loadError ? (
        <div className="form-error">Could not load data: {loadError}</div>
      ) : (
      ) : (
        <>
          <div className="stat-row">
            <div className="stat-box">
              <div className="stat-value">{surveys.length}</div>
              <div className="stat-label">Total surveys</div>
            </div>
            <div className="stat-box">
              <div className="stat-value">{published}</div>
              <div className="stat-label">Published &amp; collecting data</div>
            </div>
            <div className="stat-box">
              <div className="stat-value">{draft}</div>
              <div className="stat-label">In draft</div>
            </div>
            {canSeeSubmissions && (
              <div className="stat-box">
                <div className="stat-value">{recentSubmissions.length > 0 ? "—" : "0"}</div>
                <div className="stat-label">Recent submissions shown below</div>
              </div>
            )}
          </div>

          {canSeeSubmissions && <AIStatusCard canTest={isAdmin} />}

          <h2>Surveys</h2>
          {surveys.length === 0 ? (
            <div className="empty-state">
              <h3>No surveys yet</h3>
              <p>Create your first survey to start collecting field data.</p>
              <Link to="/surveys/new" className="btn btn-primary">
                Create a survey
              </Link>
            </div>
          ) : (
            <table className="registry-table" style={{ marginBottom: 40 }}>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Version</th>
                </tr>
              </thead>
              <tbody>
                {surveys.slice(0, 5).map((s) => (
                  <tr key={s.id}>
                    <td>
                      <Link to={`/surveys/${s.id}`}>{s.title}</Link>
                    </td>
                    <td>
                      <StatusBadge status={s.status} />
                    </td>
                    <td className="mono">v{s.current_version_number ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {canSeeSubmissions && recentSubmissions.length > 0 && (
            <>
              <h2>Recent submissions</h2>
              <table className="registry-table">
                <thead>
                  <tr>
                    <th>Submission</th>
                    <th>Status</th>
                    <th>Collected</th>
                  </tr>
                </thead>
                <tbody>
                  {recentSubmissions.map((s) => (
                    <tr key={s.id}>
                      <td className="mono">{s.id.slice(0, 8)}</td>
                      <td>
                        <StatusBadge status={s.status} />
                      </td>
                      <td>{s.collected_at ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}
