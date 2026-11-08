import { useCallback, useEffect, useState } from "react";
import { aiApi } from "../api/services";
import { extractErrorMessage } from "../api/client";
import type { AIStatus } from "../api/types";

interface Props {
  /** Only administrators may run the connection test. */
  canTest: boolean;
}

const CONNECTION_LABEL: Record<AIStatus["connection_status"], string> = {
  unknown: "Not tested",
  connected: "Connected",
  failed: "Failed",
};

const CONNECTION_BADGE: Record<AIStatus["connection_status"], string> = {
  unknown: "badge-draft",
  connected: "badge-synced",
  failed: "badge-failed",
};

export function AIStatusCard({ canTest }: Props) {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [testMessage, setTestMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await aiApi.status());
      setLoadError(null);
    } catch (error) {
      setLoadError(extractErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  async function runTest() {
    setIsTesting(true);
    setTestMessage(null);
    try {
      const result = await aiApi.testConnection();
      setTestMessage({ ok: true, text: `${result.message} (${result.latency_ms} ms)` });
    } catch (error) {
      setTestMessage({ ok: false, text: extractErrorMessage(error) });
    } finally {
      setIsTesting(false);
      await loadStatus();
    }
  }

  return (
    <div className="panel" style={{ marginBottom: 40 }}>
      <h2 style={{ marginTop: 0 }}>AI assistant</h2>

      {loadError && <p className="form-error">{loadError}</p>}
      {!status && !loadError && <p className="loading-text">Loading…</p>}

      {status && (
        <>
          <table className="registry-table" style={{ marginBottom: 16 }}>
            <tbody>
              <tr>
                <th>Availability</th>
                <td>
                  <span className={`badge ${status.available ? "badge-published" : "badge-archived"}`}>
                    {status.available ? "Available" : status.enabled ? "Not configured" : "Disabled"}
                  </span>
                </td>
              </tr>
              <tr>
                <th>Provider</th>
                <td className="mono">{status.provider}</td>
              </tr>
              <tr>
                <th>Model</th>
                <td className="mono">{status.model}</td>
              </tr>
              <tr>
                <th>Connection</th>
                <td>
                  <span className={`badge ${CONNECTION_BADGE[status.connection_status]}`}>
                    {CONNECTION_LABEL[status.connection_status]}
                  </span>
                  {status.last_checked_at && (
                    <span className="builder-meta" style={{ marginLeft: 10 }}>
                      checked {new Date(status.last_checked_at).toLocaleString()}
                    </span>
                  )}
                </td>
              </tr>
            </tbody>
          </table>

          <p className="builder-meta">{status.message}</p>

          {canTest && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={runTest}
              disabled={isTesting || !status.available}
              title={status.available ? undefined : "Enable AI and set the API key on the server first"}
            >
              {isTesting ? "Testing…" : "Test connection"}
            </button>
          )}

          {testMessage && (
            <p className={testMessage.ok ? "builder-meta" : "form-error"} role="status" style={{ marginTop: 12 }}>
              {testMessage.text}
            </p>
          )}
        </>
      )}
    </div>
  );
}
