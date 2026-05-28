import React from 'react';

const SEVERITY_CLASS = {
  blocking: 'sev-blocking',
  major: 'sev-major',
  minor: 'sev-minor',
};

export default function ReviewResult({ result }) {
  const comments = result.comments || [];
  const summary = result.summary || {};

  return (
    <div className="review-result">
      <h4>Review Result</h4>
      {summary && Object.keys(summary).length > 0 && (
        <div className="summary">
          {summary.pr_title && <div><b>PR:</b> {summary.pr_title}</div>}
          {summary.files_analyzed != null && (
            <div><b>Files analyzed:</b> {summary.files_analyzed}</div>
          )}
          {summary.source_branch && summary.destination_branch && (
            <div><b>Branch:</b> {summary.source_branch} → {summary.destination_branch}</div>
          )}
        </div>
      )}

      {comments.length === 0 ? (
        <div className="empty success">No logic failures found. Looks good for approval.</div>
      ) : (
        <ul className="comments">
          {comments.map((c, i) => (
            <li key={i} className={`comment ${SEVERITY_CLASS[c.severity] || 'sev-minor'}`}>
              <div className="comment-header">
                <span className="severity">{(c.severity || 'minor').toUpperCase()}</span>
                {c.file && <span className="file">{c.file}{c.line != null ? `:${c.line}` : ''}</span>}
                {c.category && <span className="chip">{c.category}</span>}
              </div>
              <div className="comment-text">{c.text}</div>
            </li>
          ))}
        </ul>
      )}

      {result.raw_response && comments.length === 0 && (
        <details className="raw">
          <summary>Raw LLM response</summary>
          <pre>{result.raw_response}</pre>
        </details>
      )}
    </div>
  );
}
