import { useState, useEffect } from 'react';
import api from '../services/api';

const PR_STATUSES = [
  { value: 'open', label: 'Open' },
  { value: 'closed', label: 'Closed' },
  { value: 'merged', label: 'Merged' },
  { value: 'all', label: 'All' }
];

function PRReviewTab({ showToast }) {
  const [repo, setRepo] = useState('');
  const [repos, setRepos] = useState([]);
  const [loadingRepos, setLoadingRepos] = useState(true);
  const [prStatus, setPrStatus] = useState('open');
  const [prList, setPrList] = useState([]);
  const [loadingPRs, setLoadingPRs] = useState(false);
  const [selectedPR, setSelectedPR] = useState(null);
  const [prInfo, setPrInfo] = useState(null);
  const [comments, setComments] = useState([]);
  const [selectedComments, setSelectedComments] = useState(new Set());
  const [isReviewing, setIsReviewing] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [reviewSummary, setReviewSummary] = useState(null);
  const [reviewDone, setReviewDone] = useState(false);

  useEffect(() => {
    loadRepositories();
  }, []);

  useEffect(() => {
    if (repo) {
      loadPRs();
    }
  }, [repo, prStatus]);

  const loadRepositories = async () => {
    setLoadingRepos(true);
    try {
      const result = await api.getRepos();
      const repoList = result.repos || [];
      setRepos(repoList);
      if (repoList.length > 0 && !repo) {
        setRepo(repoList[0].full_name || repoList[0].name);
      }
    } catch (error) {
      console.error('Failed to load repositories:', error);
      showToast('Failed to load repositories', 'error');
    } finally {
      setLoadingRepos(false);
    }
  };

  const loadPRs = async () => {
    if (!repo) return;
    
    setLoadingPRs(true);
    setPrList([]);
    setSelectedPR(null);
    setPrInfo(null);
    setComments([]);
    
    try {
      const result = await api.getPRsByStatus(repo, prStatus);
      if (result.error) {
        showToast(result.error, 'error');
        setPrList([]);
        return;
      }
      const prs = result.prs || [];
      setPrList(prs);
      if (prs.length === 0) {
        showToast(`No ${prStatus} PRs found for this repository`, 'info');
      }
    } catch (error) {
      console.error('Load PRs error:', error);
      showToast('Backend not available. Make sure FastAPI is running on port 8080', 'error');
      setPrList([]);
    } finally {
      setLoadingPRs(false);
    }
  };

  const handleSelectPR = (pr) => {
    setSelectedPR(pr);
    setPrInfo(pr);
    setComments([]);
    setSelectedComments(new Set());
    setReviewSummary(null);
    setReviewDone(false);
  };

  const handleReview = async () => {
    if (!prInfo) return;

    setIsReviewing(true);
    setReviewDone(false);
    setReviewSummary(null);
    try {
      const result = await api.reviewPR(prInfo.number || prInfo.id, repo);
      if (result.error) {
        showToast(result.error, 'error');
        return;
      }
      setComments(result.comments || []);
      setReviewSummary(result.summary || null);
      setReviewDone(true);
      const count = result.comments?.length || 0;
      showToast(count > 0 ? `Found ${count} logic failure(s)` : 'Review complete - No logic failures found', count > 0 ? 'warning' : 'success');
    } catch (error) {
      showToast('Failed to review PR: ' + error.message, 'error');
    } finally {
      setIsReviewing(false);
    }
  };

  const toggleComment = (index) => {
    setSelectedComments(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedComments.size === comments.length) {
      setSelectedComments(new Set());
    } else {
      setSelectedComments(new Set(comments.map((_, i) => i)));
    }
  };

  const handleApplyComments = async (action = 'COMMENT') => {
    // For APPROVE action, don't require selected comments
    if (action === 'COMMENT' && selectedComments.size === 0) {
      showToast('Please select comments to apply', 'warning');
      return;
    }

    setIsApplying(true);
    try {
      const selectedItems = action === 'APPROVE' 
        ? [] 
        : Array.from(selectedComments).map(i => comments[i]);
      const result = await api.applyComments(prInfo.number || prInfo.id, repo, selectedItems, action);
      if (result.error) {
        showToast(result.error, 'error');
        return;
      }
      const message = action === 'APPROVE' 
        ? 'PR approved successfully' 
        : `Successfully applied ${selectedComments.size} comments`;
      showToast(message, 'success');
    } catch (error) {
      showToast('Failed to apply: ' + error.message, 'error');
    } finally {
      setIsApplying(false);
    }
  };

  const getSeverityClass = (type) => {
    switch (type?.toLowerCase()) {
      case 'error': return 'severity-blocking';
      case 'warning': return 'severity-major';
      default: return 'severity-minor';
    }
  };

  const renderCommentText = (text) => {
    if (!text) return null;
    
    const imageRegex = /\[IMAGE:([^\]]+)\]/g;
    const parts = [];
    let lastIndex = 0;
    let match;
    
    while ((match = imageRegex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(
          <pre key={`text-${lastIndex}`} className="comment-pre">
            {text.slice(lastIndex, match.index)}
          </pre>
        );
      }
      parts.push(
        <img 
          key={`img-${match.index}`} 
          src={match[1]} 
          alt="Diagram" 
          className="comment-image"
          style={{ maxWidth: '100%', margin: '10px 0', borderRadius: '8px', border: '1px solid #ddd' }}
        />
      );
      lastIndex = match.index + match[0].length;
    }
    
    if (lastIndex < text.length) {
      parts.push(
        <pre key={`text-${lastIndex}`} className="comment-pre">
          {text.slice(lastIndex)}
        </pre>
      );
    }
    
    return parts.length > 0 ? parts : <pre className="comment-pre">{text}</pre>;
  };

  const getPRStatusClass = (pr) => {
    if (pr.merged || pr.merged_at) return 'merged';
    if (pr.state === 'closed') return 'closed';
    return 'open';
  };

  return (
    <div className="tab-content active">
      <div className="search-section">
        <h2>📝 Pull Request Review</h2>
        
        <div className="search-row">
          <div className="search-field">
            <label>Repository</label>
            <select
              className="search-select"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              disabled={loadingRepos}
            >
              {loadingRepos ? (
                <option value="">Loading repositories...</option>
              ) : repos.length === 0 ? (
                <option value="">No repositories found</option>
              ) : (
                repos.map((r, index) => (
                  <option key={index} value={r.full_name || r.name}>
                    {r.full_name || r.name}
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="search-field search-field--small">
            <label>PR Status</label>
            <select
              className="search-select"
              value={prStatus}
              onChange={(e) => setPrStatus(e.target.value)}
            >
              {PR_STATUSES.map(status => (
                <option key={status.value} value={status.value}>
                  {status.label}
                </option>
              ))}
            </select>
          </div>
          <button 
            className="search-btn"
            onClick={loadPRs}
            disabled={loadingPRs || !repo}
          >
            {loadingPRs ? <span className="loading-spinner"></span> : '🔍'} Search
          </button>
        </div>
      </div>

      <div className="pr-review-container">
        <div className="pr-list-section">
          <h3>📋 Pull Requests ({prList.length})</h3>
          
          {loadingPRs ? (
            <div className="loading">
              <div className="loading-spinner"></div>
              <span>Loading PRs...</span>
            </div>
          ) : prList.length === 0 ? (
            <div className="empty-state-small">
              <span>No {prStatus === 'all' ? '' : prStatus} PRs found</span>
            </div>
          ) : (
            <div className="pr-list">
              {prList.map((pr, index) => (
                <div 
                  key={index}
                  className={`pr-list-item ${selectedPR?.number === pr.number ? 'selected' : ''}`}
                  onClick={() => handleSelectPR(pr)}
                >
                  <div className="pr-list-header">
                    <span className="pr-list-number">#{pr.number}</span>
                    <span className={`pr-status-badge ${getPRStatusClass(pr)}`}>
                      {pr.merged || pr.merged_at ? 'MERGED' : pr.state?.toUpperCase() || 'OPEN'}
                    </span>
                  </div>
                  <div className="pr-list-title">{pr.title}</div>
                  <div className="pr-list-meta">
                    <span>👤 {pr.author || pr.user?.login}</span>
                    <span>📅 {new Date(pr.created_at || pr.createdDate).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="pr-detail-section">
          {prInfo ? (
            <>
              <div className="pr-info-card visible">
                <div className="pr-header">
                  <div>
                    <h3 className="pr-title">
                      <span className="pr-number">#{prInfo.number || prInfo.id}</span> {prInfo.title}
                    </h3>
                    <div className="pr-meta">
                      <span>👤 {prInfo.author || prInfo.user?.login}</span>
                      <span>📅 {new Date(prInfo.created_at || prInfo.createdDate).toLocaleDateString()}</span>
                      <div className="branch-info">
                        <span className="branch-badge source">{prInfo.source?.branch || prInfo.head?.ref}</span>
                        <span className="branch-arrow">→</span>
                        <span className="branch-badge dest">{prInfo.destination?.branch || prInfo.base?.ref}</span>
                      </div>
                    </div>
                  </div>
                  <span className={`pr-status ${getPRStatusClass(prInfo)}`}>
                    {prInfo.merged || prInfo.merged_at ? 'MERGED' : prInfo.state?.toUpperCase() || 'OPEN'}
                  </span>
                </div>
                {prInfo.body && (
                  <div className="pr-description">
                    <p>{prInfo.body.substring(0, 300)}{prInfo.body.length > 300 ? '...' : ''}</p>
                  </div>
                )}
                <button 
                  className="review-btn"
                  onClick={handleReview}
                  disabled={isReviewing}
                >
                  {isReviewing ? <span className="loading-spinner"></span> : '🔬'} Start AI Review
                </button>
              </div>

              {reviewDone && (
                <div className="review-section visible">
                  {/* Section 1: Changes Summary */}
                  {reviewSummary && (reviewSummary.file_changes?.length > 0 || reviewSummary.files?.length > 0) && (
                    <div className="review-changes-section">
                      <h3>📂 Changes in this PR</h3>
                      <div className="changes-stats">
                        <span className="stat-badge additions">+{reviewSummary.additions || 0} additions</span>
                        <span className="stat-badge deletions">-{reviewSummary.deletions || 0} deletions</span>
                        <span className="stat-badge files">{reviewSummary.files_analyzed || reviewSummary.file_changes?.length || 0} file(s)</span>
                      </div>
                      <div className="file-changes-list">
                        {(reviewSummary.file_changes || []).map((file, i) => (
                          <div key={i} className="file-change-item">
                            <span className={`file-status ${file.status}`}>{file.status?.toUpperCase()}</span>
                            <span className="file-name">{file.filename}</span>
                            <span className="file-diff">
                              <span className="diff-add">+{file.additions || 0}</span>
                              <span className="diff-del">-{file.deletions || 0}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Section 2: Logic Failures */}
                  <div className="review-failures-section">
                    <h3>{comments.length > 0 ? '⚠️' : '✅'} Logic Failures ({comments.length})</h3>
                    
                    {comments.length === 0 ? (
                      <div className="no-failures">
                        <p>No logic failures identified in this PR. The code changes appear to be logically consistent.</p>
                      </div>
                    ) : (
                      <>
                        <div className="review-header">
                          <div className="select-all-container">
                            <input
                              type="checkbox"
                              checked={selectedComments.size === comments.length}
                              onChange={toggleAll}
                            />
                            <span>Select All</span>
                          </div>
                        </div>

                        <div className="comments-list">
                          {comments.map((comment, index) => (
                            <div 
                              key={index}
                              className={`comment-item ${selectedComments.has(index) ? 'selected' : ''}`}
                            >
                              <input
                                type="checkbox"
                                className="comment-checkbox"
                                checked={selectedComments.has(index)}
                                onChange={() => toggleComment(index)}
                              />
                              <div className="comment-content">
                                <div className="comment-header">
                                  <span className="comment-priority">P{index}</span>
                                  {comment.file && (
                                    <span className="comment-file-badge">{comment.file}</span>
                                  )}
                                  {comment.line && (
                                    <span className="comment-line-badge">Line {comment.line}</span>
                                  )}
                                  <span className={`comment-severity ${getSeverityClass(comment.type)}`}>
                                    {comment.type?.toUpperCase() || 'SUGGESTION'}
                                  </span>
                                </div>
                                <div className="comment-text">{renderCommentText(comment.text)}</div>
                                {comment.suggestion && (
                                  <div className="comment-suggestion">
                                    <strong>Recommendation:</strong> {comment.suggestion}
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>

                  {/* Section 3: Actions */}
                  <div className="apply-fixes-section">
                    {comments.length > 0 ? (
                      <>
                        <span className="selected-count">
                          <strong>{selectedComments.size}</strong> of {comments.length} selected
                        </span>
                        <div className="action-buttons">
                          <button
                            className="apply-comments-btn"
                            onClick={() => handleApplyComments('COMMENT')}
                            disabled={isApplying || selectedComments.size === 0}
                          >
                            {isApplying ? <span className="loading-spinner"></span> : '💬'} Apply as Comments
                          </button>
                          <button
                            className="apply-comments-btn approval-mode"
                            onClick={() => handleApplyComments('APPROVE')}
                            disabled={isApplying || selectedComments.size === 0}
                          >
                            {isApplying ? <span className="loading-spinner"></span> : '✅'} Approve PR
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="action-buttons">
                        <button
                          className="apply-comments-btn approval-mode"
                          onClick={() => handleApplyComments('APPROVE')}
                          disabled={isApplying}
                        >
                          {isApplying ? <span className="loading-spinner"></span> : '✅'} Post Approval to PR
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">👈</div>
              <h3>Select a Pull Request</h3>
              <p>Choose a PR from the list to view details and start review</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default PRReviewTab;
