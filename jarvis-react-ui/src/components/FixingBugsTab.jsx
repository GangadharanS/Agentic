import { useState, useEffect } from 'react';
import api from '../services/api';

function FixingBugsTab({ showToast }) {
  const [bugs, setBugs] = useState([]);
  const [selectedBug, setSelectedBug] = useState(null);
  const [loadingBugs, setLoadingBugs] = useState(true);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isApplyingFix, setIsApplyingFix] = useState(false);
  const [isRaisingPR, setIsRaisingPR] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [fixResult, setFixResult] = useState(null);
  const [prResult, setPrResult] = useState(null);
  const [targetRepo, setTargetRepo] = useState('');
  const [repos, setRepos] = useState([]);
  const [branches, setBranches] = useState([]);
  const [selectedBaseBranch, setSelectedBaseBranch] = useState('');
  const [loadingBranches, setLoadingBranches] = useState(false);

  useEffect(() => {
    loadBugs();
    loadRepos();
  }, []);

  useEffect(() => {
    if (targetRepo) {
      loadBranches();
    }
  }, [targetRepo]);

  const loadRepos = async () => {
    try {
      const result = await api.getRepos();
      setRepos(result.repos || []);
      if (result.repos?.length > 0) {
        setTargetRepo(result.repos[0].full_name);
      }
    } catch (error) {
      console.error('Failed to load repos:', error);
    }
  };

  const loadBranches = async () => {
    if (!targetRepo) return;
    setLoadingBranches(true);
    try {
      const result = await api.getBranches(targetRepo);
      const branchList = result.branches || [];
      setBranches(branchList);
      if (branchList.length > 0 && !selectedBaseBranch) {
        const defaultBranch = branchList.find(b => b.includes('QA/Common')) || branchList.find(b => b === 'main') || branchList[0];
        setSelectedBaseBranch(defaultBranch);
      }
    } catch (error) {
      console.error('Failed to load branches:', error);
    } finally {
      setLoadingBranches(false);
    }
  };

  const loadBugs = async () => {
    setLoadingBugs(true);
    try {
      const result = await api.getOpenBugs();
      if (result.error) {
        showToast(result.error, 'error');
        setBugs([]);
      } else {
        setBugs(result.bugs || []);
      }
    } catch (error) {
      console.error('Failed to load bugs:', error);
      showToast('Failed to load bug tickets', 'error');
      setBugs([]);
    } finally {
      setLoadingBugs(false);
    }
  };

  const handleSelectBug = (bugKey) => {
    const bug = bugs.find(b => b.key === bugKey);
    setSelectedBug(bug);
    setAnalysis(null);
    setFixResult(null);
    setPrResult(null);
  };

  const handleAnalyzeBug = async () => {
    if (!selectedBug) {
      showToast('Please select a bug first', 'warning');
      return;
    }

    setIsAnalyzing(true);
    setAnalysis(null);
    try {
      const result = await api.analyzeBug(selectedBug.key, targetRepo);
      if (result.error) {
        showToast(result.error, 'error');
        return;
      }
      setAnalysis(result);
      showToast('Bug analysis complete', 'success');
    } catch (error) {
      showToast('Failed to analyze bug: ' + error.message, 'error');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleApplyFix = async () => {
    if (!selectedBug || !targetRepo || !selectedBaseBranch) {
      showToast('Please select a bug, target repository, and base branch', 'warning');
      return;
    }

    setIsApplyingFix(true);
    setFixResult(null);
    setPrResult(null);
    try {
      const result = await api.applyBugFix(selectedBug.key, targetRepo, selectedBaseBranch, analysis);
      if (result.error) {
        showToast(result.error, 'error');
        return;
      }
      setFixResult(result);
      showToast(`Fix applied on branch '${result.branch_name}' from '${result.base_branch}'`, 'success');
    } catch (error) {
      showToast('Failed to apply fix: ' + error.message, 'error');
    } finally {
      setIsApplyingFix(false);
    }
  };

  const handleRaisePR = async () => {
    if (!fixResult || !fixResult.branch_name) {
      showToast('Please apply the fix first', 'warning');
      return;
    }

    setIsRaisingPR(true);
    setPrResult(null);
    try {
      const result = await api.raiseBugPR(
        selectedBug.key,
        targetRepo,
        fixResult.branch_name,
        fixResult.base_branch
      );
      if (result.error) {
        showToast(result.error, 'error');
        return;
      }
      setPrResult(result);
      showToast('PR created successfully!', 'success');
    } catch (error) {
      showToast('Failed to raise PR: ' + error.message, 'error');
    } finally {
      setIsRaisingPR(false);
    }
  };

  const getPriorityClass = (priority) => {
    const p = priority?.toLowerCase() || '';
    if (p.includes('critical') || p.includes('blocker')) return 'priority-critical';
    if (p.includes('high')) return 'priority-high';
    if (p.includes('medium')) return 'priority-medium';
    return 'priority-low';
  };

  return (
    <div className="tab-content active">
      <div className="search-section">
        <h2>🐛 Fixing Bugs</h2>
        <p className="section-description">
          Select an open bug ticket, analyze it, and automatically apply a fix with a new PR.
        </p>
        
        <div className="search-row">
          <div className="search-field">
            <label>Open Bug Tickets</label>
            <select
              className="search-select"
              value={selectedBug?.key || ''}
              onChange={(e) => handleSelectBug(e.target.value)}
              disabled={loadingBugs}
            >
              <option value="">
                {loadingBugs ? 'Loading bugs...' : bugs.length === 0 ? 'No open bugs found' : 'Select a bug...'}
              </option>
              {bugs.map((bug) => (
                <option key={bug.key} value={bug.key}>
                  {bug.key}: {bug.summary?.substring(0, 60)}{bug.summary?.length > 60 ? '...' : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="search-field">
            <label>Target Repository</label>
            <select
              className="search-select"
              value={targetRepo}
              onChange={(e) => setTargetRepo(e.target.value)}
            >
              {repos.map((repo, i) => (
                <option key={i} value={repo.full_name}>
                  {repo.full_name}
                </option>
              ))}
            </select>
          </div>
          <div className="search-field">
            <label>Base Branch</label>
            <select
              className="search-select"
              value={selectedBaseBranch}
              onChange={(e) => setSelectedBaseBranch(e.target.value)}
              disabled={loadingBranches || branches.length === 0}
            >
              {loadingBranches ? (
                <option value="">Loading branches...</option>
              ) : branches.length === 0 ? (
                <option value="">No branches found</option>
              ) : (
                branches.map((branch, i) => (
                  <option key={i} value={branch}>{branch}</option>
                ))
              )}
            </select>
          </div>
          <button 
            className="search-btn"
            onClick={loadBugs}
            disabled={loadingBugs}
          >
            {loadingBugs ? <span className="loading-spinner"></span> : '🔍'} Search
          </button>
        </div>
      </div>

      {selectedBug && (
        <div className="bug-details-section">
          <div className="bug-info-card">
            <div className="bug-header">
              <div className="bug-title-row">
                <span className="bug-key">{selectedBug.key}</span>
                <span className={`bug-priority ${getPriorityClass(selectedBug.priority)}`}>
                  {selectedBug.priority || 'Medium'}
                </span>
                <span className="bug-status">{selectedBug.status || 'Open'}</span>
              </div>
              <h3 className="bug-title">{selectedBug.summary}</h3>
            </div>
            
            {selectedBug.description && (
              <div className="bug-description">
                <h4>Description</h4>
                <p>{selectedBug.description.substring(0, 500)}{selectedBug.description.length > 500 ? '...' : ''}</p>
              </div>
            )}

            <div className="bug-meta">
              {selectedBug.assignee && <span>👤 {selectedBug.assignee}</span>}
              {selectedBug.reporter && <span>📝 Reporter: {selectedBug.reporter}</span>}
              {selectedBug.created && <span>📅 {new Date(selectedBug.created).toLocaleDateString()}</span>}
            </div>

            <div className="bug-actions">
              <button
                className="analyze-btn"
                onClick={handleAnalyzeBug}
                disabled={isAnalyzing || isApplyingFix || isRaisingPR}
              >
                {isAnalyzing ? <span className="loading-spinner"></span> : '🔍'} Analyze Bug
              </button>
              <button
                className="apply-fix-btn"
                onClick={handleApplyFix}
                disabled={isApplyingFix || isAnalyzing || isRaisingPR || !selectedBaseBranch}
              >
                {isApplyingFix ? <span className="loading-spinner"></span> : '🔧'} Apply Fix
              </button>
              <button
                className="apply-fix-btn raise-pr-btn"
                onClick={handleRaisePR}
                disabled={isRaisingPR || isApplyingFix || !fixResult}
                title={!fixResult ? 'Apply fix first to enable this' : ''}
              >
                {isRaisingPR ? <span className="loading-spinner"></span> : '🚀'} Raise PR
              </button>
            </div>
          </div>

          {analysis && (
            <div className="analysis-section">
              <h3>📊 Bug Analysis</h3>
              <div className="analysis-content">
                {analysis.root_cause && (
                  <div className="analysis-item">
                    <h4>🎯 Root Cause</h4>
                    <p>{analysis.root_cause}</p>
                  </div>
                )}
                {analysis.affected_files && analysis.affected_files.length > 0 && (
                  <div className="analysis-item">
                    <h4>📁 Affected Files</h4>
                    <ul>
                      {analysis.affected_files.map((file, i) => (
                        <li key={i}><code>{file}</code></li>
                      ))}
                    </ul>
                  </div>
                )}
                {analysis.proposed_fix && (
                  <div className="analysis-item">
                    <h4>💡 Proposed Fix</h4>
                    <pre className="code-block">{analysis.proposed_fix}</pre>
                  </div>
                )}
              </div>
            </div>
          )}

          {fixResult && (
            <div className="fix-result-section">
              <h3>🔧 Fix Applied</h3>
              <div className="fix-result-content">
                <div className="result-item">
                  <span className="result-label">Branch:</span>
                  <code>{fixResult.branch_name}</code>
                </div>
                <div className="result-item">
                  <span className="result-label">Base Branch:</span>
                  <code>{fixResult.base_branch}</code>
                </div>
                {fixResult.files_modified > 0 && (
                  <div className="result-item">
                    <span className="result-label">Files Committed:</span>
                    <span>{fixResult.files_modified} file(s)</span>
                  </div>
                )}
                <div className="result-item">
                  <span className="result-label">Status:</span>
                  <span className="status-badge success">Ready for PR</span>
                </div>
              </div>
            </div>
          )}

          {prResult && (
            <div className="fix-result-section pr-result-section">
              <h3>🚀 PR Created</h3>
              <div className="fix-result-content">
                {prResult.pr_url && (
                  <div className="result-item">
                    <span className="result-label">Pull Request:</span>
                    <a href={prResult.pr_url} target="_blank" rel="noopener noreferrer" className="pr-link">
                      {prResult.pr_url}
                    </a>
                  </div>
                )}
                {prResult.pr_number && (
                  <div className="result-item">
                    <span className="result-label">PR Number:</span>
                    <span>#{prResult.pr_number}</span>
                  </div>
                )}
                <div className="result-item">
                  <span className="result-label">Target:</span>
                  <code>{prResult.branch_name}</code> → <code>{prResult.base_branch}</code>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {!selectedBug && !loadingBugs && (
        <div className="empty-state">
          <div className="empty-state-icon">🐛</div>
          <h3>Select a Bug to Fix</h3>
          <p>Choose an open bug ticket from the dropdown to analyze and apply an automated fix.</p>
        </div>
      )}
    </div>
  );
}

export default FixingBugsTab;
