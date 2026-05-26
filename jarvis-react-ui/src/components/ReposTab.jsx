import { useState, useEffect } from 'react';
import api from '../services/api';

function ReposTab({ showToast }) {
  const [repos, setRepos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [architecture, setArchitecture] = useState(null);
  const [generatingArch, setGeneratingArch] = useState(false);

  useEffect(() => {
    loadRepos();
  }, []);

  const loadRepos = async () => {
    setLoading(true);
    try {
      const result = await api.getRepos();
      setRepos(result.repos || []);
    } catch (error) {
      showToast('Failed to load repositories', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateArchitecture = async (repo) => {
    setSelectedRepo(repo);
    setGeneratingArch(true);
    try {
      const result = await api.generateArchitecture(repo.full_name || repo.name);
      setArchitecture(result);
      showToast('Architecture generated successfully', 'success');
    } catch (error) {
      showToast('Failed to generate architecture: ' + error.message, 'error');
    } finally {
      setGeneratingArch(false);
    }
  };

  return (
    <div className="tab-content active">
      <div className="repos-section">
        <h2>📁 Repositories</h2>
        <p className="repos-description">
          Browse repositories and generate architecture diagrams.
        </p>

        {loading ? (
          <div className="loading">
            <div className="loading-spinner"></div>
            <span>Loading repositories...</span>
          </div>
        ) : repos.length > 0 ? (
          <div className="repos-grid">
            {repos.map((repo, index) => (
              <div key={index} className="repo-card">
                <div className="repo-header">
                  <h3 className="repo-name">{repo.name || repo.full_name}</h3>
                  <span className={`repo-visibility ${repo.private ? 'private' : 'public'}`}>
                    {repo.private ? '🔒 Private' : '🌐 Public'}
                  </span>
                </div>
                {repo.description && (
                  <p className="repo-description">{repo.description}</p>
                )}
                <div className="repo-meta">
                  <span>⭐ {repo.stars || repo.stargazers_count || 0}</span>
                  <span>🍴 {repo.forks || repo.forks_count || 0}</span>
                  <span>📝 {repo.language || 'Unknown'}</span>
                </div>
                <div className="repo-actions">
                  <button 
                    className="repo-action-btn"
                    onClick={() => handleGenerateArchitecture(repo)}
                    disabled={generatingArch && selectedRepo?.name === repo.name}
                  >
                    {generatingArch && selectedRepo?.name === repo.name ? (
                      <><span className="loading-spinner"></span> Generating...</>
                    ) : (
                      <>🏗️ Generate Architecture</>
                    )}
                  </button>
                  <a 
                    href={repo.html_url || repo.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="repo-action-btn secondary"
                  >
                    🔗 View on GitHub
                  </a>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">📁</div>
            <h3>No Repositories Found</h3>
            <p>Configure your GitHub token to see repositories</p>
          </div>
        )}

        {architecture && (
          <div className="architecture-output">
            <div className="architecture-header">
              <h3>🏗️ Architecture - {selectedRepo?.name}</h3>
              <button 
                className="close-btn"
                onClick={() => setArchitecture(null)}
              >
                ✕
              </button>
            </div>
            <div className="architecture-content">
              <pre>{JSON.stringify(architecture, null, 2)}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default ReposTab;
