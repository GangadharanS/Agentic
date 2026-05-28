import React, { useEffect, useState } from 'react';
import ReviewTab from './components/ReviewTab.jsx';
import ToolsTab from './components/ToolsTab.jsx';
import SettingsTab from './components/SettingsTab.jsx';
import HealthBadge from './components/HealthBadge.jsx';
import { api } from './api.js';

const TABS = [
  { id: 'review', label: 'PR Review' },
  { id: 'tools', label: 'MCP Tools' },
  { id: 'settings', label: 'Settings' },
];

export default function App() {
  const [tab, setTab] = useState('review');
  const [health, setHealth] = useState(null);

  const refreshHealth = async () => {
    try {
      setHealth(await api.health());
    } catch (e) {
      setHealth({ status: 'error', error: e.message });
    }
  };

  useEffect(() => {
    refreshHealth();
    const id = setInterval(refreshHealth, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">ReAct</span>
          <span className="brand-sub">PR Review via MCP</span>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <HealthBadge health={health} onRefresh={refreshHealth} />
      </header>

      <main className="content">
        {tab === 'review' && <ReviewTab />}
        {tab === 'tools' && <ToolsTab />}
        {tab === 'settings' && <SettingsTab onSaved={refreshHealth} />}
      </main>
    </div>
  );
}
