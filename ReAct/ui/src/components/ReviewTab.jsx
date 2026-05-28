import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import ReActSteps from './ReActSteps.jsx';
import ReviewResult from './ReviewResult.jsx';

export default function ReviewTab() {
  const [repos, setRepos] = useState([]);
  const [repoFilter, setRepoFilter] = useState('');
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [prs, setPrs] = useState([]);
  const [prState, setPrState] = useState('open');
  const [selectedPR, setSelectedPR] = useState(null);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [loadingPRs, setLoadingPRs] = useState(false);
  const [error, setError] = useState(null);

  const [steps, setSteps] = useState([]);
  const [reviewResult, setReviewResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [statusLog, setStatusLog] = useState([]);
  const [postAfter, setPostAfter] = useState(false);

  const filteredRepos = useMemo(() => {
    if (!repoFilter) return repos;
    const q = repoFilter.toLowerCase();
    return repos.filter((r) => r.full_name.toLowerCase().includes(q));
  }, [repos, repoFilter]);

  const loadRepos = async () => {
    setLoadingRepos(true);
    setError(null);
    try {
      const data = await api.listRepos();
      setRepos(data.repos || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingRepos(false);
    }
  };

  const loadPRs = async (repo, state) => {
    setLoadingPRs(true);
    setError(null);
    setPrs([]);
    setSelectedPR(null);
    try {
      const data = await api.listPRs(repo.owner, repo.name, state);
      setPrs(data.prs || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingPRs(false);
    }
  };

  useEffect(() => {
    loadRepos();
  }, []);

  useEffect(() => {
    if (selectedRepo) loadPRs(selectedRepo, prState);
  }, [selectedRepo, prState]);

  const runReview = async () => {
    if (!selectedRepo || !selectedPR) return;
    setRunning(true);
    setSteps([]);
    setReviewResult(null);
    setStatusLog([]);

    try {
      await api.reviewStream(
        {
          owner: selectedRepo.owner,
          repo: selectedRepo.name,
          pr_id: selectedPR.number,
          post: postAfter,
        },
        ({ type, data }) => {
          if (type === 'step') setSteps((prev) => [...prev, data]);
          else if (type === 'review') setReviewResult(data);
          else if (type === 'status') setStatusLog((p) => [...p, data.message]);
          else if (type === 'posted') setStatusLog((p) => [...p, `Posted: ${data.review_action}`]);
          else if (type === 'error') setStatusLog((p) => [...p, `ERROR: ${data.message}`]);
          else if (type === 'done') setStatusLog((p) => [...p, 'Done.']);
        }
      );
    } catch (e) {
      setStatusLog((p) => [...p, `Stream error: ${e.message}`]);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="review-grid">
      <section className="panel repo-panel">
        <header className="panel-header">
          <h3>Repositories</h3>
          <button className="link-btn" onClick={loadRepos} disabled={loadingRepos}>
            {loadingRepos ? '…' : 'Refresh'}
          </button>
        </header>
        <input
          className="search"
          placeholder={`Filter ${repos.length} repos…`}
          value={repoFilter}
          onChange={(e) => setRepoFilter(e.target.value)}
        />
        <ul className="list">
          {filteredRepos.map((r) => (
            <li
              key={r.full_name}
              className={`list-item ${selectedRepo?.full_name === r.full_name ? 'selected' : ''}`}
              onClick={() => setSelectedRepo(r)}
            >
              <div className="list-title">{r.full_name}</div>
              <div className="list-meta">
                {r.private ? <span className="chip">private</span> : null}
                <span className="chip">{r.default_branch}</span>
                {r.open_issues ? <span className="chip warn">{r.open_issues} issues</span> : null}
              </div>
              {r.description && <div className="list-desc">{r.description}</div>}
            </li>
          ))}
          {!filteredRepos.length && !loadingRepos && (
            <li className="empty">No repos. Check GITHUB_TOKEN in backend .env.</li>
          )}
        </ul>
      </section>

      <section className="panel pr-panel">
        <header className="panel-header">
          <h3>Pull Requests {selectedRepo ? `— ${selectedRepo.full_name}` : ''}</h3>
          <select value={prState} onChange={(e) => setPrState(e.target.value)} disabled={!selectedRepo}>
            <option value="open">open</option>
            <option value="closed">closed</option>
            <option value="all">all</option>
          </select>
        </header>
        {!selectedRepo && <div className="hint">Pick a repository to load PRs.</div>}
        {selectedRepo && loadingPRs && <div className="hint">Loading PRs…</div>}
        <ul className="list">
          {prs.map((pr) => (
            <li
              key={pr.number}
              className={`list-item ${selectedPR?.number === pr.number ? 'selected' : ''}`}
              onClick={() => setSelectedPR(pr)}
            >
              <div className="list-title">
                #{pr.number} · {pr.title}
              </div>
              <div className="list-meta">
                <span className="chip">{pr.author}</span>
                <span className="chip">{pr.source_branch} → {pr.destination_branch}</span>
                {pr.draft && <span className="chip warn">draft</span>}
              </div>
            </li>
          ))}
          {selectedRepo && !loadingPRs && !prs.length && (
            <li className="empty">No {prState} PRs.</li>
          )}
        </ul>
      </section>

      <section className="panel review-panel">
        <header className="panel-header">
          <h3>ReAct Review</h3>
          <div className="controls">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={postAfter}
                onChange={(e) => setPostAfter(e.target.checked)}
              />
              <span>Post to GitHub</span>
            </label>
            <button
              className="primary-btn"
              onClick={runReview}
              disabled={!selectedPR || running}
            >
              {running ? 'Running…' : 'Run ReAct'}
            </button>
          </div>
        </header>

        {!selectedPR && (
          <div className="hint">Select a PR, then click <b>Run ReAct</b>.</div>
        )}

        {selectedPR && (
          <div className="pr-card">
            <div className="pr-title">#{selectedPR.number} · {selectedPR.title}</div>
            <a className="link" href={selectedPR.html_url} target="_blank" rel="noreferrer">
              Open on GitHub ↗
            </a>
          </div>
        )}

        {error && <div className="error">{error}</div>}

        {statusLog.length > 0 && (
          <div className="status-log">
            {statusLog.map((m, i) => <div key={i}>{m}</div>)}
          </div>
        )}

        {steps.length > 0 && <ReActSteps steps={steps} />}
        {reviewResult && <ReviewResult result={reviewResult} />}
      </section>
    </div>
  );
}
