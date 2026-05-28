import React from 'react';

export default function HealthBadge({ health, onRefresh }) {
  if (!health) {
    return <span className="badge badge-muted">connecting…</span>;
  }

  const dot = (ok) => <span className={`dot ${ok ? 'ok' : 'bad'}`} />;
  const mcp = health.mcp_server || {};
  const gemini = health.gemini || {};
  const github = health.github || {};

  return (
    <div className="health" onClick={onRefresh} title="Click to refresh">
      <span className="health-item">
        {dot(mcp.connected)} MCP <small>({mcp.tools || 0})</small>
      </span>
      <span className="health-item">
        {dot(gemini.configured)} Gemini
      </span>
      <span className="health-item">
        {dot(github.ok)} GitHub
        {github.login ? <small>@{github.login}</small> : null}
      </span>
    </div>
  );
}
