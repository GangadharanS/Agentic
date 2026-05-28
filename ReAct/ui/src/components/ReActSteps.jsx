import React from 'react';

export default function ReActSteps({ steps }) {
  return (
    <div className="steps">
      <h4>ReAct loop ({steps.length} round{steps.length !== 1 ? 's' : ''})</h4>
      <ol className="step-list">
        {steps.map((s) => (
          <li key={s.round} className="step">
            <div className="step-header">Round {s.round}</div>
            {s.thought && (
              <div className="step-row">
                <span className="step-label thought">Thought</span>
                <div className="step-text">{s.thought}</div>
              </div>
            )}
            {s.action && (
              <div className="step-row">
                <span className="step-label action">Action</span>
                <div className="step-text">
                  <code>{s.action}</code>
                  {s.action_input && Object.keys(s.action_input).length > 0 && (
                    <pre className="code-block">{JSON.stringify(s.action_input, null, 2)}</pre>
                  )}
                </div>
              </div>
            )}
            {s.observation && (
              <div className="step-row">
                <span className="step-label observe">Observe</span>
                <div className="step-text observe-text">{s.observation}</div>
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
