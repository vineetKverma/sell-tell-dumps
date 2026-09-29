# app/static/css

branch: `development`  commit: `85b108c`  files: 1

<!-- FILE: app/static/css/style.css -->
````css
:root {
  --bg: #0f1419;
  --panel: #1a2029;
  --panel-2: #222b36;
  --border: #2c3744;
  --text: #e6edf3;
  --muted: #8b97a3;
  --accent: #4f8cff;
  --accent-2: #2dd4a7;
  --danger: #ff6b6b;
  --warn: #ffb454;
  --radius: 12px;
  --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  display: flex;
  flex-direction: column;
}

header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 22px;
  background: linear-gradient(180deg, #161c24, #11161d);
  border-bottom: 1px solid var(--border);
}

header h1 { margin: 0; font-size: 20px; }
.subtitle { color: var(--muted); font-size: 13px; margin-top: 2px; }

.header-right { display: flex; align-items: center; gap: 18px; }

.campaign-select { display: flex; flex-direction: column; font-size: 11px; color: var(--muted); gap: 3px; }
.campaign-select select {
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 5px 8px;
  font-family: var(--mono);
  font-size: 12px;
}

.connection-status { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.status-indicator { width: 10px; height: 10px; border-radius: 50%; background: var(--accent-2); }
.status-indicator.disconnected { background: var(--danger); }

.main-layout { flex: 1; display: flex; min-height: 0; }

.container {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Phase banner */
.phase-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-radius: var(--radius);
  font-size: 15px;
  border: 1px solid var(--border);
  background: var(--panel);
  transition: background 0.25s, border-color 0.25s;
}
.phase-banner #phaseIcon { font-size: 22px; }
.phase-idle { border-color: var(--border); }
.phase-listening { background: rgba(79,140,255,0.12); border-color: var(--accent); }
.phase-processing { background: rgba(255,180,84,0.12); border-color: var(--warn); }
.phase-confirm { background: rgba(45,212,167,0.10); border-color: var(--accent-2); }
.phase-saved { background: rgba(45,212,167,0.18); border-color: var(--accent-2); }
.phase-error { background: rgba(255,107,107,0.12); border-color: var(--danger); }

/* Run metrics: elapsed time + estimated token cost for the current run */
.run-metrics { display: flex; gap: 12px; }
.metric-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--panel);
  font-family: var(--mono);
  transition: background 0.25s, border-color 0.25s;
}
.metric-label { font-size: 12px; color: var(--muted); letter-spacing: 0.02em; }
.metric-value { font-size: 16px; font-weight: 700; color: var(--text); }
.metric-chip.running { border-color: var(--accent); background: rgba(79,140,255,0.10); }
.metric-chip.running .metric-value { color: var(--accent); }
.metric-chip.done { border-color: var(--accent-2); background: rgba(45,212,167,0.12); }
.metric-chip.done .metric-value { color: var(--accent-2); }

/* Mic area */
.mic-area { display: flex; align-items: center; gap: 20px; }
.mic-button {
  width: 84px; height: 84px;
  border-radius: 50%;
  border: none;
  background: radial-gradient(circle at 30% 30%, #5b97ff, #2f6bdc);
  color: #fff;
  cursor: pointer;
  font-size: 34px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 20px rgba(47,107,220,0.35);
  transition: transform 0.1s, box-shadow 0.2s;
  flex-shrink: 0;
}
.mic-button:hover { transform: scale(1.04); }
.mic-button:disabled { opacity: 0.5; cursor: not-allowed; }
.mic-button.recording {
  background: radial-gradient(circle at 30% 30%, #ff8a8a, #e63e3e);
  animation: pulse 1.4s infinite;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(230,62,62,0.45); }
  70% { box-shadow: 0 0 0 18px rgba(230,62,62,0); }
  100% { box-shadow: 0 0 0 0 rgba(230,62,62,0); }
}

.silence-meter { flex: 1; }
.level-bar {
  height: 10px;
  background: var(--panel-2);
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border);
}
.level-fill {
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, var(--accent-2), var(--accent));
  transition: width 0.08s linear;
}
.silence-countdown { margin-top: 8px; font-family: var(--mono); font-size: 12px; color: var(--muted); }
.silence-countdown.counting { color: var(--warn); }

/* Panels */
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}
.panel-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 12px; }

/* Pre-call planning panel */
.planning-panel { border-color: var(--accent); }
.planning-panel.locked { opacity: 0.6; }
.planning-hint { color: var(--muted); font-size: 12px; margin-bottom: 12px; line-height: 1.4; }
.badge-empty { background: var(--danger); color: #fff; }
.topic-options {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
}
.topic-option {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 11px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.topic-option:hover { border-color: var(--accent); }
.topic-option input { accent-color: var(--accent); width: 16px; height: 16px; cursor: pointer; flex-shrink: 0; }
.topic-option:has(input:checked) { border-color: var(--accent); background: rgba(79,140,255,0.12); }
.topic-option:has(input:disabled) { cursor: not-allowed; }

/* Planned-topic coverage chips */
.coverage { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px; }
.coverage-chip {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--muted);
}
.coverage-chip.cov-covered { border-color: var(--accent-2); color: var(--accent-2); background: rgba(45,212,167,0.12); }
.coverage-chip.cov-skipped { border-color: var(--muted); color: var(--muted); }
.coverage-chip.cov-pending { border-color: var(--warn); color: var(--warn); background: rgba(255,180,84,0.12); }
.topic-disposition.not-discussed { background: rgba(139,151,163,0.18); color: var(--muted); }

/* Live transcription captions */
.live-captions { border-color: var(--accent); }
.live-dot {
  display: inline-block;
  width: 9px; height: 9px;
  border-radius: 50%;
  background: var(--border);
  margin-left: 8px;
  vertical-align: middle;
}
.live-dot.active {
  background: var(--danger);
  animation: livepulse 1.1s infinite;
}
@keyframes livepulse {
  0% { box-shadow: 0 0 0 0 rgba(255,107,107,0.5); }
  70% { box-shadow: 0 0 0 8px rgba(255,107,107,0); }
  100% { box-shadow: 0 0 0 0 rgba(255,107,107,0); }
}
.caption-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.caption-row:last-child { border-bottom: none; }
.caption-row.speaking { background: rgba(79,140,255,0.06); border-radius: 8px; padding-left: 8px; padding-right: 8px; }
.caption-speaker {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 3px 9px;
  border-radius: 10px;
  margin-top: 2px;
}
.speaker-user { background: var(--accent); color: #fff; }
.speaker-agent { background: var(--accent-2); color: #06281f; }
.caption-text {
  flex: 1;
  font-size: 17px;
  line-height: 1.5;
  color: var(--text);
  word-break: break-word;
  min-height: 1.5em;
}
.caption-text.placeholder { color: var(--muted); font-style: italic; font-size: 14px; }
.caption-text.streaming::after {
  content: "▍";
  color: var(--accent);
  animation: blink 1s step-start infinite;
}

.messages { display: flex; flex-direction: column; gap: 10px; max-height: 280px; overflow-y: auto; }

.message { display: flex; }
.message.user { justify-content: flex-end; }
.message.agent { justify-content: flex-start; }
.message.system { justify-content: center; }
.bubble {
  max-width: 80%;
  padding: 9px 13px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.4;
}
.message.user .bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.message.agent .bubble { background: var(--panel-2); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
.message.system .bubble { background: transparent; color: var(--muted); font-size: 12px; font-style: italic; }
.bubble.interrupted { opacity: 0.6; }
.typing-indicator::after { content: "▍"; animation: blink 1s step-start infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* Payload card */
.payload-card { border-color: var(--accent-2); }
.payload-grid { display: grid; grid-template-columns: 160px 1fr; gap: 8px 16px; margin: 0; }
.payload-grid dt { color: var(--muted); font-size: 13px; }
.payload-grid dd { margin: 0; font-size: 14px; }
.payload-grid dd.muted { color: var(--muted); font-family: var(--mono); font-size: 12px; }
.badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: var(--warn); color: #1a1a1a; text-transform: none; letter-spacing: 0;
  margin-left: 6px;
}
.badge.committed { background: var(--accent-2); }

.topics-label { font-size: 13px; color: var(--muted); margin: 14px 0 8px; text-transform: uppercase; letter-spacing: 0.05em; }
.topics { display: flex; flex-direction: column; gap: 10px; }
.topic-item {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent-2);
  border-radius: 8px;
  padding: 10px 12px;
}
.topic-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 4px; }
.topic-title { font-size: 14px; font-weight: 600; text-transform: capitalize; }
.topic-disposition {
  flex-shrink: 0;
  font-size: 12px;
  font-family: var(--mono);
  background: rgba(45,212,167,0.15);
  color: var(--accent-2);
  padding: 2px 8px;
  border-radius: 10px;
}
.topic-summary { font-size: 13px; color: var(--text); line-height: 1.4; }

.confirm-actions { display: flex; align-items: center; gap: 12px; margin-top: 16px; flex-wrap: wrap; }
.btn-primary, .btn-secondary {
  padding: 9px 18px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 600;
}
.btn-primary { background: var(--accent-2); color: #06281f; }
.btn-secondary { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); }
.btn-primary:disabled, .btn-secondary:disabled { opacity: 0.45; cursor: not-allowed; }
.hint { color: var(--muted); font-size: 12px; }

.hidden { display: none; }

/* Console */
.console-panel {
  width: 380px;
  border-left: 1px solid var(--border);
  background: #0c1117;
  display: flex;
  flex-direction: column;
}
.console-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.console-header h2 { font-size: 14px; margin: 0; }
.console-clear-btn {
  background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px;
}
.console-content { flex: 1; overflow-y: auto; padding: 10px; font-family: var(--mono); font-size: 11px; }
.console-entry { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; background: var(--panel); }
.console-entry.incoming { border-left: 3px solid var(--accent); }
.console-entry.outgoing { border-left: 3px solid var(--accent-2); }
.console-entry.error { border-left: 3px solid var(--danger); }
.console-entry-header { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); margin-bottom: 4px; }
.console-entry-content { color: var(--text); word-break: break-word; white-space: pre-wrap; }
.console-entry.expandable { cursor: pointer; }
.console-entry-json { margin-top: 6px; max-height: 220px; overflow: auto; }
.console-entry-json.collapsed { display: none; }
.console-entry-json pre { margin: 0; color: var(--muted); white-space: pre-wrap; word-break: break-word; }

/* F3: Rep Identity */
.rep-identity { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text); }
.rep-id-input {
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 8px;
  font-family: var(--mono);
  font-size: 12px;
  width: 120px;
}

/* F2/F7: History Modal */
.history-modal {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0;
  width: 80%;
  max-width: 800px;
  max-height: 80vh;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}
.history-modal::backdrop {
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(3px);
}
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}
.modal-header h2 { margin: 0; font-size: 18px; }
.modal-body {
  padding: 20px;
  overflow-y: auto;
  max-height: calc(80vh - 70px);
}
.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.history-table th, .history-table td {
  padding: 10px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.history-table th { color: var(--muted); font-weight: normal; }

/* F4: Correction UI */
.correction-ui {
  display: flex;
  gap: 10px;
  margin-top: 15px;
  padding-top: 15px;
  border-top: 1px solid var(--border);
}
.correction-ui input {
  flex: 1;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.caption-row:last-child { border-bottom: none; }
.caption-row.speaking { background: rgba(79,140,255,0.06); border-radius: 8px; padding-left: 8px; padding-right: 8px; }
.caption-speaker {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 3px 9px;
  border-radius: 10px;
  margin-top: 2px;
}
.speaker-user { background: var(--accent); color: #fff; }
.speaker-agent { background: var(--accent-2); color: #06281f; }
.caption-text {
  flex: 1;
  font-size: 17px;
  line-height: 1.5;
  color: var(--text);
  word-break: break-word;
  min-height: 1.5em;
}
.caption-text.placeholder { color: var(--muted); font-style: italic; font-size: 14px; }
.caption-text.streaming::after {
  content: "▍";
  color: var(--accent);
  animation: blink 1s step-start infinite;
}

.messages { display: flex; flex-direction: column; gap: 10px; max-height: 280px; overflow-y: auto; }

.message { display: flex; }
.message.user { justify-content: flex-end; }
.message.agent { justify-content: flex-start; }
.message.system { justify-content: center; }
.bubble {
  max-width: 80%;
  padding: 9px 13px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.4;
}
.message.user .bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.message.agent .bubble { background: var(--panel-2); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
.message.system .bubble { background: transparent; color: var(--muted); font-size: 12px; font-style: italic; }
.bubble.interrupted { opacity: 0.6; }
.typing-indicator::after { content: "▍"; animation: blink 1s step-start infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* Payload card */
.payload-card { border-color: var(--accent-2); }
.payload-grid { display: grid; grid-template-columns: 160px 1fr; gap: 8px 16px; margin: 0; }
.payload-grid dt { color: var(--muted); font-size: 13px; }
.payload-grid dd { margin: 0; font-size: 14px; }
.payload-grid dd.muted { color: var(--muted); font-family: var(--mono); font-size: 12px; }
.badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: var(--warn); color: #1a1a1a; text-transform: none; letter-spacing: 0;
  margin-left: 6px;
}
.badge.committed { background: var(--accent-2); }

.topics-label { font-size: 13px; color: var(--muted); margin: 14px 0 8px; text-transform: uppercase; letter-spacing: 0.05em; }
.topics { display: flex; flex-direction: column; gap: 10px; }
.topic-item {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent-2);
  border-radius: 8px;
  padding: 10px 12px;
}
.topic-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 4px; }
.topic-title { font-size: 14px; font-weight: 600; text-transform: capitalize; }
.topic-disposition {
  flex-shrink: 0;
  font-size: 12px;
  font-family: var(--mono);
  background: rgba(45,212,167,0.15);
  color: var(--accent-2);
  padding: 2px 8px;
  border-radius: 10px;
}
.topic-summary { font-size: 13px; color: var(--text); line-height: 1.4; }

.confirm-actions { display: flex; align-items: center; gap: 12px; margin-top: 16px; flex-wrap: wrap; }
.btn-primary, .btn-secondary {
  padding: 9px 18px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 600;
}
.btn-primary { background: var(--accent-2); color: #06281f; }
.btn-secondary { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); }
.btn-primary:disabled, .btn-secondary:disabled { opacity: 0.45; cursor: not-allowed; }
.hint { color: var(--muted); font-size: 12px; }

.hidden { display: none; }

/* Console */
.console-panel {
  width: 380px;
  border-left: 1px solid var(--border);
  background: #0c1117;
  display: flex;
  flex-direction: column;
}
.console-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.console-header h2 { font-size: 14px; margin: 0; }
.console-clear-btn {
  background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px;
}
.console-content { flex: 1; overflow-y: auto; padding: 10px; font-family: var(--mono); font-size: 11px; }
.console-entry { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; background: var(--panel); }
.console-entry.incoming { border-left: 3px solid var(--accent); }
.console-entry.outgoing { border-left: 3px solid var(--accent-2); }
.console-entry.error { border-left: 3px solid var(--danger); }
.console-entry-header { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); margin-bottom: 4px; }
.console-entry-content { color: var(--text); word-break: break-word; white-space: pre-wrap; }
.console-entry.expandable { cursor: pointer; }
.console-entry-json { margin-top: 6px; max-height: 220px; overflow: auto; }
.console-entry-json.collapsed { display: none; }
.console-entry-json pre { margin: 0; color: var(--muted); white-space: pre-wrap; word-break: break-word; }

/* F3: Rep Identity */
.rep-identity { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text); }
.rep-id-input {
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 8px;
  font-family: var(--mono);
  font-size: 12px;
  width: 120px;
}

/* F2/F7: History Modal */
.history-modal {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0;
  width: 80%;
  max-width: 800px;
  max-height: 80vh;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}
.history-modal::backdrop {
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(3px);
}
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}
.modal-header h2 { margin: 0; font-size: 18px; }
.modal-body {
  padding: 20px;
  overflow-y: auto;
  max-height: calc(80vh - 70px);
}
.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.history-table th, .history-table td {
  padding: 10px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.history-table th { color: var(--muted); font-weight: normal; }

/* F4: Correction UI */
.correction-ui {
  display: flex;
  gap: 10px;
  margin-top: 15px;
  padding-top: 15px;
  border-top: 1px solid var(--border);
}
.correction-ui input {
  flex: 1;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 14px;
}

/* F8: Uncertainty highlighting */
.uncertainty-tag {
  background-color: rgba(255, 180, 84, 0.15);
  color: var(--warn);
  border: 1px dotted var(--warn);
  border-radius: 4px;
  padding: 1px 4px;
  font-weight: 500;
}

body.offline .offline-indicator {
  display: block;
}
.offline-indicator {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  background: var(--warn);
  color: #000;
  text-align: center;
  padding: 5px;
  font-size: 13px;
  font-weight: 500;
  z-index: 9999;
}
````
<!-- END: app/static/css/style.css -->

