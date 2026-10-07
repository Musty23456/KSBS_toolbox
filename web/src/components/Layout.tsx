import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { authApi } from "../api/services";

export function Layout() {
  const { user, logout } = useAuth();

  const canManageSurveys = user?.role === "ADMINISTRATOR" || user?.role === "SUPERVISOR";
  const canManageUsers = user?.role === "ADMINISTRATOR" || user?.role === "SUPERVISOR";
  const isAdmin = user?.role === "ADMINISTRATOR";

  const [pendingResetCount, setPendingResetCount] = useState(0);

  useEffect(() => {
    if (!isAdmin) return;

    let cancelled = false;

    async function loadPendingCount() {
      try {
        const requests = await authApi.listPasswordResetRequests("PENDING");
        if (!cancelled) setPendingResetCount(requests.length);
      } catch {
        // Non-critical: the badge just won't update this cycle.
      }
    }

    loadPendingCount();
    const interval = setInterval(loadPendingCount, 60000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [isAdmin]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <div className="sidebar-brand">
            KSBS TOOLBOX
            <small>Field survey registry</small>
          </div>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            Overview
          </NavLink>
          <NavLink to="/surveys" className={({ isActive }) => (isActive ? "active" : "")}>
            Surveys
          </NavLink>
          <NavLink to="/map" className={({ isActive }) => (isActive ? "active" : "")}>
            Map
          </NavLink>
          <NavLink to="/submissions" className={({ isActive }) => (isActive ? "active" : "")}>
            Submissions
          </NavLink>
          <NavLink to="/exports" className={({ isActive }) => (isActive ? "active" : "")}>
            Export Center
          </NavLink>
          {canManageSurveys && (
            <NavLink to="/translations" className={({ isActive }) => (isActive ? "active" : "")}>
              Languages
            </NavLink>
          )}
          <NavLink to="/analytics" className={({ isActive }) => (isActive ? "active" : "")}>
            Analytics
          </NavLink>
          {canManageUsers && (
            <NavLink to="/online-enumerators" className={({ isActive }) => (isActive ? "active" : "")}>
              Online enumerators
            </NavLink>
          )}
          {canManageUsers && (
            <NavLink to="/devices" className={({ isActive }) => (isActive ? "active" : "")}>
              Devices &amp; sync
            </NavLink>
          )}
          {canManageUsers && (
            <NavLink to="/audit" className={({ isActive }) => (isActive ? "active" : "")}>
              Audit Dashboard
            </NavLink>
          )}
          {canManageUsers && (
            <NavLink to="/users" className={({ isActive }) => (isActive ? "active" : "")}>
              Enumerators &amp; staff
            </NavLink>
          )}
          {isAdmin && (
            <NavLink
              to="/password-reset-requests"
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              Password reset requests
              {pendingResetCount > 0 && (
                <span
                  style={{
                    marginLeft: 8,
                    display: "inline-block",
                    minWidth: 18,
                    padding: "0 5px",
                    borderRadius: 9,
                    background: "#dc2626",
                    color: "#fff",
                    fontSize: 12,
                    textAlign: "center",
                    lineHeight: "18px",
                  }}
                >
                  {pendingResetCount}
                </span>
              )}
            </NavLink>
          )}
          <NavLink
  to="/about"
  className={({ isActive }) => (isActive ? "active" : "")}
>
  About
</NavLink>
        </nav>
        <div className="sidebar-footer">
          <div className="who">{user?.full_name}</div>
          <div className="role">{user?.role.toLowerCase()}</div>
          <button onClick={() => logout()}>Log out</button>
        </div>
      </aside>
      <main className="main">
        <Outlet context={{ canManageSurveys, canManageUsers }} />
      </main>
    </div>
  );
}
