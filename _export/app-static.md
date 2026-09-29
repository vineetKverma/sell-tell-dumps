# app/static

branch: `development`  commit: `85b108c`  files: 1

<!-- FILE: app/static/index.html -->
````html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Voice Notes Logger</title>
    <link rel="stylesheet" href="/static/css/style.css?v=3" />
    <script src="/static/js/app.js?v=16" type="module"></script>
  </head>

  <body>
    <header>
      <div class="header-left">
        <h1>🎙️ Voice Notes Logger</h1>
        <div class="subtitle">Agentic CRM dictation for field sales reps</div>
      </div>
      <div class="header-right">
        <label class="rep-identity">
          <span>Rep:</span>
          <input type="text" id="repIdInput" class="rep-id-input" />
        </label>
  
        <label class="campaign-select">
          <span>Campaign</span>
          <select id="campaignSelect">
            <option value="standard_sales">standard_sales</option>
            <option value="enterprise_field">enterprise_field</option>
            <option value="renewals">renewals</option>
          </select>
        </label>
        <div class="connection-status">
          <span class="status-indicator disconnected" id="statusIndicator"></span>
          <span id="statusText">Disconnected</span>
        </div>
      </div>
    </header>

    <div class="main-layout">
      <div id="offlineIndicator" class="offline-indicator hidden">You are currently offline. Some features may not be available.</div>
      <div class="container">
        <!-- Phase / status banner -->
        <div id="phaseBanner" class="phase-banner phase-idle">
          <span id="phaseIcon">🎤</span>
          <span id="phaseText">Plan your call, then press the mic to start dictating.</span>
        </div>

        <!-- Run metrics: wall-clock time + estimated token cost for this dictation run -->
        <div id="runMetrics" class="run-metrics">
          <div id="runTimerChip" class="metric-chip metric-timer">
            <span class="metric-label">⏱ Time to save</span>
            <span id="runTimerValue" class="metric-value">0.0s</span>
          </div>
          <div id="runCostChip" class="metric-chip metric-cost">
            <span class="metric-label">💰 Est. cost</span>
            <span id="runCostValue" class="metric-value">$0.000000</span>
          </div>
        </div>

        <!-- Pre-call planning: select planned topics (multi-select) -->
        <div id="planningPanel" class="panel planning-panel">
          <div class="panel-title">
            Plan your call
            <span id="plannedCount" class="badge">0 selected</span>
          </div>
          <div class="planning-hint">
            Select one or more topics you intend to cover. The agent will extract
            an outcome for each and remind you about any you don't mention.
          </div>
          <div id="topicOptions" class="topic-options">Loading topics…</div>
        </div>

        <!-- Mic + silence meter -->
        <div class="mic-area">
          <button id="micButton" class="mic-button">
            <span class="mic-glyph">🎤</span>
          </button>
          <div class="silence-meter">
            <div class="level-bar"><div id="levelFill" class="level-fill"></div></div>
            <div id="silenceCountdown" class="silence-countdown">VAD idle</div>
          </div>
        </div>

        <!-- Live transcription (real-time captions for both speakers) -->
        <div class="panel live-captions">
          <div class="panel-title">
            Live Transcription
            <span id="liveDot" class="live-dot"></span>
          </div>
          <div id="userCaptionRow" class="caption-row">
            <span class="caption-speaker speaker-user">You</span>
            <span id="userCaption" class="caption-text placeholder">Waiting for you to speak…</span>
          </div>
          <div id="agentCaptionRow" class="caption-row">
            <span class="caption-speaker speaker-agent">Agent</span>
            <span id="agentCaption" class="caption-text placeholder">Waiting for the agent…</span>
          </div>
        </div>

        <!-- Transcript / conversation history -->
        <div class="panel">
          <div class="panel-title">Conversation</div>
          <div id="messages" class="messages"></div>
        </div>

        <!-- Staged payload card -->
        <div id="payloadCard" class="panel payload-card hidden">
          <div class="panel-title">Staged CRM Record <span id="payloadStatus" class="badge">staged</span></div>
          <dl class="payload-grid">
            <dt>Event type</dt><dd id="pEventType">—</dd>
            <dt>Call summary</dt><dd id="pSummary">—</dd>
          </dl>
          <div class="topics-label">Planned-topic coverage</div>
          <div id="pCoverage" class="coverage"></div>
          <div class="topics-label">Discussion topics</div>
          <div id="pTopics" class="topics"></div>
          <dl class="payload-grid">
            <dt>Raw transcript</dt><dd id="pTranscript" class="muted">—</dd>
            <dt>CRM record id</dt><dd id="pCrmId" class="muted">—</dd>
            <dt>Audio playback</dt><dd><audio id="playbackAudio" controls style="height: 30px;"></audio></dd>
          </dl>
          <div class="confirm-actions">
            <button id="saveButton" class="btn-primary" disabled>✔ Save</button>
            <button id="changeButton" class="btn-secondary" disabled>✎ Change</button>
            <span class="hint">…or just say “Save” / “Change the event type to a phone call”.</span>
          </div>
          <div id="correctionUi" class="correction-ui hidden">
            <input type="text" id="correctionInput" placeholder="What should I change? (e.g. 'change the event type to a phone call')" />
            <button id="submitCorrectionBtn" class="btn-primary">Submit</button>
            <button id="cancelCorrectionBtn" class="btn-secondary">Cancel</button>
          </div>
        </div>
      </div>

      <div class="console-panel">
        <div class="console-header">
          <h2>Event Console</h2>
          <button id="clearConsole" class="console-clear-btn">Clear</button>
        </div>
        <div id="consoleContent" class="console-content"></div>
      </div>
    </div>
  </body>
</html>
````
<!-- END: app/static/index.html -->

