/**
 * Voice Notes Logger - frontend controller.
 *
 * Drives the dictation state machine, client-side VAD (energy-based silence
 * stop-trigger), audio streaming, and rendering of the staged CRM payload /
 * confirmation that the agent produces via tool calls.
 */

import { startAudioPlayerWorklet } from "./audio-player.js";
import { startAudioRecorderWorklet } from "./audio-recorder.js";

// ---------------------------------------------------------------------------
// Config / constants
// ---------------------------------------------------------------------------
let userId = localStorage.getItem("sellntell_rep_id");
if (!userId) {
  userId = "rep-" + crypto.randomUUID();
  localStorage.setItem("sellntell_rep_id", userId);
}
// Regenerated whenever the campaign or planned topics change so the backend
// seeds a fresh session with the new selection (in-memory sessions are keyed
// by id and their seeded state is otherwise sticky).
let sessionId = "sess-" + crypto.randomUUID();
function newSessionId() {
  sessionId = "sess-" + crypto.randomUUID();
}

// Client-side VAD tuning. The browser's VAD is the authoritative stop-trigger
// (the Live API's server-side VAD caps at 2000ms, below the spec's 2.5-3.0s),
// so we run the session in manual activity-detection mode. The threshold is
// fetched from the backend (VOICE_NOTES_VAD_SILENCE_MS) and defaults to 2800ms.
let SILENCE_MS = 2800;            // stop-trigger window (spec: 2.5-3.0s)
const VOICE_RMS_THRESHOLD = 0.022; // above this = speech present
const MIN_SPEECH_MS = 400;        // require some speech before arming silence

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let websocket = null;
let audioPlayerNode = null;
let audioRecorderNode = null;
let micStream = null;
let audioStarted = false;

let micActive = false;       // are we streaming mic audio right now?
let audioBackpressureWarned = false; // log the "uplink behind" warning once per episode
let phase = "idle";          // idle | listening | processing | confirm | saved
let committed = false;
let agentTurnActive = false; // true while the agent is taking its turn

// The Live model reliably speaks a guessed filler/summary immediately after
// the rep finishes a turn, BEFORE it has actually called the extraction tool
// (stage_visit_notes/commit_*) -- confirmed non-fixable via prompting after
// several attempts. Rather than let the rep hear that guess, mute playback
// (audio + live caption) for whatever the agent says between "rep just
// finished talking" and "the next real tool call fires" -- the real,
// tool-grounded readback always comes right after and plays normally.
let suppressAgentSpeech = false;

// VAD bookkeeping
let speechStartTs = 0;
let lastVoiceTs = 0;
let hadSpeech = false;

// Audio quality detection.
// The browser's autoGainControl in getUserMedia normalizes mic peaks before
// they reach our JavaScript, so a raw peak-clipping check (Math.max vs 30000)
// is defeated. Instead we detect SUSTAINED HIGH-ENERGY audio post-AGC:
// if normalized RMS stays above HIGH_RMS_THRESHOLD for HIGH_ENERGY_STREAK_MAX
// consecutive chunks, the audio is genuinely saturated/distorted even after
// the browser's own normalization.
const HIGH_RMS_THRESHOLD = 0.90; // Raised from 0.85
const HIGH_ENERGY_STREAK_MAX = 100; // Raised from 50 (now ~12.8 seconds of sustained noise)
let highEnergyStreak = 0;

// Max bytes allowed to sit unsent in the WebSocket's buffer before we start
// dropping chunks -- ~2s of audio at 16kHz 16-bit mono (32000 B/s).
const MAX_BUFFERED_BYTES = 64000;
let reconnectAttempts = 0;
let agentResponseWatchdog = null;

// Live transcription buffers (accumulate streaming deltas per speaker)
let liveUserText = "";
let liveAgentText = "";

// Disposition code -> label map (from dynamic config)
let dispositionLabels = {};

// Pre-call planning: catalog of selectable topics + the rep's selection.
let plannedTopicCatalog = [];
let selectedTopics = []; // array of label strings

// ---------------------------------------------------------------------------
// Run metrics (display-only): wall-clock time from "mic click" to "CRM saved"
// plus an estimated $ cost from the Live model's own usageMetadata events.
// Purely observational -- reads data already flowing over the existing
// WebSocket event stream and never touches the agent/session/execution path.
// ---------------------------------------------------------------------------
// Published Vertex AI pricing for gemini-live-2.5-flash-native-audio,
// per token (source: ai.google.dev/gemini-api/docs/pricing, paid tier).
const TOKEN_PRICE_PER_UNIT = {
  input: { TEXT: 0.5 / 1e6, AUDIO: 3.0 / 1e6, VIDEO: 3.0 / 1e6, IMAGE: 3.0 / 1e6, DOCUMENT: 3.0 / 1e6 },
  output: { TEXT: 2.0 / 1e6, AUDIO: 12.0 / 1e6 },
};
const FALLBACK_INPUT_RATE = TOKEN_PRICE_PER_UNIT.input.AUDIO; // dictation is audio-heavy
const FALLBACK_OUTPUT_RATE = TOKEN_PRICE_PER_UNIT.output.AUDIO; // agent replies are spoken

let runTimerStartTs = null;
let runTimerHandle = null;

function formatElapsed(ms) {
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${(s % 60).toFixed(1)}s`;
}

function renderRunTimer() {
  if (runTimerStartTs == null) return;
  runTimerValue.textContent = formatElapsed(performance.now() - runTimerStartTs);
}

function startRunTimer() {
  logEvent("incoming", "Run timer started", null, "â±ï¸");
  runTimerStartTs = performance.now();
  latestUsageMetadata = null;
  runTimerValue.textContent = "0.0s";
  runCostValue.textContent = "$0.000000";
  runTimerChip.classList.add("running");
  runTimerChip.classList.remove("done");
  runCostChip.classList.add("running");
  runCostChip.classList.remove("done");
  if (runTimerHandle) clearInterval(runTimerHandle);
  runTimerHandle = setInterval(renderRunTimer, 100);
}

function stopRunTimer() {
  if (runTimerHandle) {
    clearInterval(runTimerHandle);
    runTimerHandle = null;
  }
  if (runTimerStartTs != null) renderRunTimer();
  runTimerChip.classList.remove("running");
  runCostChip.classList.remove("running");
}

function resetRunMetrics() {
  stopRunTimer();
  runTimerStartTs = null;
  latestUsageMetadata = null;
  runTimerValue.textContent = "0.0s";
  runCostValue.textContent = "$0.000000";
  runTimerChip.classList.remove("running", "done");
  runCostChip.classList.remove("running", "done");
}

function markRunMetricsDone() {
  stopRunTimer();
  runTimerChip.classList.add("done");
  runCostChip.classList.add("done");
  logEvent(
    "incoming",
    `Run timer stopped: ${runTimerValue.textContent} / ${runCostValue.textContent}`,
    { usage: latestUsageMetadata },
    "â±ï¸"
  );
}

// The Live API's usageMetadata reports cumulative usage "for the session so
// far" on each message, so we replace (not accumulate) on every event and
// just render whatever the latest snapshot says.
let latestUsageMetadata = null;

function sumModalityTokens(details) {
  const byModality = {};
  (details || []).forEach((d) => {
    if (d && d.modality) byModality[d.modality] = (byModality[d.modality] || 0) + (d.tokenCount || 0);
  });
  return byModality;
}

function estimateCostUsd(usage) {
  if (!usage) return 0;
  const inputByModality = sumModalityTokens(usage.promptTokensDetails);
  const outputByModality = sumModalityTokens(usage.candidatesTokensDetails);
  let cost = 0;
  let coveredInput = 0;
  let coveredOutput = 0;
  Object.entries(inputByModality).forEach(([modality, tokens]) => {
    const rate = TOKEN_PRICE_PER_UNIT.input[modality];
    if (rate != null) {
      cost += tokens * rate;
      coveredInput += tokens;
    }
  });
  Object.entries(outputByModality).forEach(([modality, tokens]) => {
    const rate = TOKEN_PRICE_PER_UNIT.output[modality];
    if (rate != null) {
      cost += tokens * rate;
      coveredOutput += tokens;
    }
  });
  // Fall back to a blended audio rate for any tokens not broken down by
  // modality (e.g. tool-use prompt tokens, thinking tokens) so the estimate
  // never silently drops usage the model reported.
  const leftoverInput = Math.max(0, (usage.promptTokenCount || 0) - coveredInput);
  const leftoverOutput = Math.max(
    0,
    (usage.candidatesTokenCount || 0) + (usage.thoughtsTokenCount || 0) + (usage.toolUsePromptTokenCount || 0) - coveredOutput
  );
  cost += leftoverInput * FALLBACK_INPUT_RATE;
  cost += leftoverOutput * FALLBACK_OUTPUT_RATE;
  return cost;
}

function applyUsageMetadata(usage) {
  latestUsageMetadata = usage;
  const cost = estimateCostUsd(usage);
  runCostValue.textContent = `$${cost.toFixed(6)}`;
  logEvent("incoming", `Usage metadata: ${cost.toFixed(6)} so far`, usage, "ðŸ’°");
}

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------
const campaignSelect = document.getElementById("campaignSelect");
const agentModeSelect = document.getElementById("agentModeSelect");
const statusIndicator = document.getElementById("statusIndicator");
const statusText = document.getElementById("statusText");
const phaseBanner = document.getElementById("phaseBanner");
const phaseIcon = document.getElementById("phaseIcon");
const phaseText = document.getElementById("phaseText");
const micButton = document.getElementById("micButton");
const runTimerChip = document.getElementById("runTimerChip");
const runTimerValue = document.getElementById("runTimerValue");
const runCostChip = document.getElementById("runCostChip");
const runCostValue = document.getElementById("runCostValue");
const levelFill = document.getElementById("levelFill");
const silenceCountdown = document.getElementById("silenceCountdown");
const messagesDiv = document.getElementById("messages");
const liveDot = document.getElementById("liveDot");
const userCaption = document.getElementById("userCaption");
const agentCaption = document.getElementById("agentCaption");
const userCaptionRow = document.getElementById("userCaptionRow");
const agentCaptionRow = document.getElementById("agentCaptionRow");
const planningPanel = document.getElementById("planningPanel");
const plannedCount = document.getElementById("plannedCount");
const topicOptions = document.getElementById("topicOptions");
const payloadCard = document.getElementById("payloadCard");
const payloadStatus = document.getElementById("payloadStatus");
const pEventType = document.getElementById("pEventType");
const pSummary = document.getElementById("pSummary");
const pCoverage = document.getElementById("pCoverage");
const pTopics = document.getElementById("pTopics");
const pTranscript = document.getElementById("pTranscript");
const pCrmId = document.getElementById("pCrmId");
const saveButton = document.getElementById("saveButton");
const changeButton = document.getElementById("changeButton");
const correctionUi = document.getElementById("correctionUi");
const correctionInput = document.getElementById("correctionInput");
const submitCorrectionBtn = document.getElementById("submitCorrectionBtn");
const cancelCorrectionBtn = document.getElementById("cancelCorrectionBtn");
const consoleContent = document.getElementById("consoleContent");
const clearConsoleBtn = document.getElementById("clearConsole");
const playbackAudio = document.getElementById("playbackAudio");

let recordingBuffers = []; // Accumulate PCM buffers for playback

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}

function createWavBlob(buffers, sampleRate = 16000) {
  let len = 0;
  for (const b of buffers) len += b.length;
  const wav = new Int16Array(len);
  let offset = 0;
  for (const b of buffers) {
    wav.set(b, offset);
    offset += b.length;
  }
  const buffer = new ArrayBuffer(44 + len * 2);
  const view = new DataView(buffer);
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + len * 2, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, 'data');
  view.setUint32(40, len * 2, true);
  const wavArray = new Int16Array(buffer, 44, len);
  wavArray.set(wav);
  return new Blob([buffer], { type: 'audio/wav' });
}

// F3 / F2 / F7 UI Elements
const repIdInput = document.getElementById("repIdInput");
const historyButton = document.getElementById("historyButton");
const historyModal = document.getElementById("historyModal");
const closeHistoryBtn = document.getElementById("closeHistoryBtn");
const exportCsvBtn = document.getElementById("exportCsvBtn");
const historyTableBody = document.getElementById("historyTableBody");

if (repIdInput) {
  repIdInput.value = userId;
  repIdInput.addEventListener("change", (e) => {
    userId = e.target.value.trim() || userId;
    localStorage.setItem("sellntell_rep_id", userId);
    repIdInput.value = userId;
  });
}

if (historyButton) {
  historyButton.addEventListener("click", async () => {
    historyTableBody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Loading...</td></tr>';
    historyModal.showModal();
    try {
      const res = await fetch("/api/v1/notes/committed");
      const data = await res.json();
      historyTableBody.innerHTML = "";

      const records = data.records || [];
      records.reverse().forEach(record => {
        const tr = document.createElement("tr");
        const dateStr = record.staged_at ? new Date(record.staged_at).toLocaleString() : "â€”";
        const crmId = record.crm_record_id || "â€”";
        const payload = record.payload || {};

        tr.innerHTML = `
          <td>${dateStr}</td>
          <td>${crmId}</td>
          <td>${record.session_id}</td>
          <td>${payload.event_type || "â€”"}</td>
          <td>${payload.executive_summary || "â€”"}</td>
        `;
        historyTableBody.appendChild(tr);
      });

      exportCsvBtn.onclick = () => {
        const rows = [["Date", "CRM ID", "Session ID", "Event Type", "Summary"]];
        records.forEach(record => {
          const payload = record.payload || {};
          rows.push([
            record.staged_at || "",
            record.crm_record_id || "",
            record.session_id || "",
            payload.event_type || "",
            (payload.executive_summary || "").replace(/"/g, '""')
          ]);
        });
        const csv = rows.map(r => r.map(c => `"${c}"`).join(",")).join("\n");
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "sell_n_tell_history.csv";
        a.click();
      };
    } catch (err) {
      historyTableBody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Error loading history</td></tr>';
    }
  });
}

if (closeHistoryBtn) {
  closeHistoryBtn.addEventListener("click", () => historyModal.close());
}

// ---------------------------------------------------------------------------
// Phase / UI helpers
// ---------------------------------------------------------------------------
const PHASES = {
  idle: { cls: "phase-idle", icon: "ðŸŽ¤", text: "Press the mic and start dictating your visit notes." },
  listening: { cls: "phase-listening", icon: "ðŸ”´", text: "Listeningâ€¦ speak your notes. I'll stop automatically when you pause." },
  processing: { cls: "phase-processing", icon: "âš™ï¸", text: "Got it â€” extracting the structured recordâ€¦" },
  confirm: { cls: "phase-confirm", icon: "ðŸŸ¢", text: "Review below. Say â€œSaveâ€ or tell me what to change." },
  saved: { cls: "phase-saved", icon: "âœ…", text: "Saved to CRM. Session complete." },
  error: { cls: "phase-error", icon: "âš ï¸", text: "Something went wrong." },
};

function setPhase(name, customText) {
  phase = name;
  const p = PHASES[name] || PHASES.idle;
  phaseBanner.className = "phase-banner " + p.cls;
  phaseIcon.textContent = p.icon;
  phaseText.textContent = customText || p.text;

  micButton.classList.toggle("recording", name === "listening");
  if (name === "listening") {
    micButton.disabled = false;
  } else if (name === "processing") {
    micButton.disabled = true;
  } else {
    micButton.disabled = false;
  }
}

function setConnected(connected) {
  statusIndicator.classList.toggle("disconnected", !connected);
  statusText.textContent = connected ? "Connected" : "Disconnected";
}

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = "message " + who;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  div.appendChild(bubble);
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
  return bubble;
}

// ---------------------------------------------------------------------------
// Live transcription captions (real-time, both speakers)
// ---------------------------------------------------------------------------
function setLiveDot(active) {
  liveDot.classList.toggle("active", active);
}

function renderCaption(el, text, streaming) {
  el.classList.remove("placeholder");
  el.classList.toggle("streaming", streaming);
  el.textContent = text;
}

function updateUserCaption(text, finished) {
  if (finished) {
    if (text) liveUserText = text; // a finished event may carry the full text
    renderCaption(userCaption, liveUserText, false);
    finalizeUserCaption();
    return;
  }
  liveUserText += text;
  userCaptionRow.classList.add("speaking");
  agentCaptionRow.classList.remove("speaking");
  setLiveDot(true);
  renderCaption(userCaption, liveUserText, true);
}

function finalizeUserCaption() {
  const text = liveUserText.trim();
  if (text) addMessage(text, "user"); // commit the finished turn to history
  liveUserText = "";
  userCaptionRow.classList.remove("speaking");
  // Reset the live strip to its placeholder so the committed line isn't shown
  // twice (once in the caption strip and once in the conversation history).
  userCaption.className = "caption-text placeholder";
  userCaption.textContent = "Waiting for you to speakâ€¦";
}

function updateAgentCaption(text, finished) {
  if (finished) {
    if (text) liveAgentText = text;
    renderCaption(agentCaption, liveAgentText, false);
    finalizeAgentCaption();
    return;
  }
  liveAgentText += text;
  agentCaptionRow.classList.add("speaking");
  userCaptionRow.classList.remove("speaking");
  setLiveDot(true);
  renderCaption(agentCaption, liveAgentText, true);
}

function finalizeAgentCaption() {
  const text = liveAgentText.trim();
  if (text) addMessage(text, "agent");
  liveAgentText = "";
  agentCaptionRow.classList.remove("speaking");
  // Reset the live strip to its placeholder so the committed line isn't shown
  // twice (once in the caption strip and once in the conversation history).
  agentCaption.className = "caption-text placeholder";
  agentCaption.textContent = "Waiting for the agentâ€¦";
}

function finalizeAllCaptions() {
  finalizeUserCaption();
  finalizeAgentCaption();
  setLiveDot(false);
}

function resetCaptions() {
  liveUserText = "";
  liveAgentText = "";
  userCaption.className = "caption-text placeholder";
  agentCaption.className = "caption-text placeholder";
  userCaption.textContent = "Waiting for you to speakâ€¦";
  agentCaption.textContent = "Waiting for the agentâ€¦";
  userCaptionRow.classList.remove("speaking");
  agentCaptionRow.classList.remove("speaking");
  setLiveDot(false);
}

// ---------------------------------------------------------------------------
// Real-time "You" caption via the browser SpeechRecognition API.
//
// The Gemini Live API only emits the rep's INPUT transcription once, at the end
// of the turn (after server VAD finalizes), so it can't drive a live caption.
// We run the browser's local recognizer in parallel purely to show the rep's
// words as they speak. The model's own input transcription remains the
// authoritative record (logged + committed to history on turn end).
// ---------------------------------------------------------------------------
const SpeechRecognitionCls =
  window.SpeechRecognition || window.webkitSpeechRecognition;
const useClientSpeech = !!SpeechRecognitionCls;
let speechRecognition = null;
let speechWantActive = false; // do we want the recognizer running right now?

function startSpeechRecognition() {
  if (!useClientSpeech) return;
  speechWantActive = true;
  if (speechRecognition) return; // already running
  try {
    const rec = new SpeechRecognitionCls();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (e) => {
      // Build the full live transcript from all results in this session.
      let text = "";
      for (let i = 0; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
      }
      liveUserText = text;
      userCaptionRow.classList.add("speaking");
      agentCaptionRow.classList.remove("speaking");
      setLiveDot(true);
      renderCaption(userCaption, liveUserText, true);
    };

    rec.onerror = (e) => {
      // "no-speech"/"aborted" are routine; only surface real failures.
      if (e.error && e.error !== "no-speech" && e.error !== "aborted") {
        logEvent("error", `Speech recognition: ${e.error}`, null, "âš ï¸");
      }
    };

    rec.onend = () => {
      speechRecognition = null;
      // The recognizer stops itself on pauses; restart while we still want it.
      if (speechWantActive) startSpeechRecognition();
    };

    speechRecognition = rec;
    rec.start();
  } catch (err) {
    // A start() while already starting throws; ignore.
    speechRecognition = null;
  }
}

function stopSpeechRecognition() {
  speechWantActive = false;
  if (speechRecognition) {
    try {
      speechRecognition.stop();
    } catch (_) {
      /* no-op */
    }
    speechRecognition = null;
  }
}

// ---------------------------------------------------------------------------
// Event console
// ---------------------------------------------------------------------------
function logEvent(type, summary, data, emoji) {
  const entry = document.createElement("div");
  entry.className = "console-entry " + type;
  const header = document.createElement("div");
  header.className = "console-entry-header";
  const left = document.createElement("span");
  left.textContent = (emoji || "") + " " + (type === "outgoing" ? "â†‘" : type === "incoming" ? "â†“" : "âš ");
  const ts = document.createElement("span");
  ts.textContent = new Date().toLocaleTimeString("en-US", { hour12: false });
  header.appendChild(left);
  header.appendChild(ts);
  const content = document.createElement("div");
  content.className = "console-entry-content";
  content.textContent = summary;
  entry.appendChild(header);
  entry.appendChild(content);
  if (data) {
    const jsonDiv = document.createElement("div");
    jsonDiv.className = "console-entry-json collapsed";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    jsonDiv.appendChild(pre);
    entry.appendChild(jsonDiv);
    entry.classList.add("expandable");
    entry.addEventListener("click", () => jsonDiv.classList.toggle("collapsed"));
  }
  consoleContent.appendChild(entry);
  consoleContent.scrollTop = consoleContent.scrollHeight;
}
clearConsoleBtn.addEventListener("click", () => (consoleContent.innerHTML = ""));

// ---------------------------------------------------------------------------
// Dynamic config (also used to label disposition codes in the UI)
// ---------------------------------------------------------------------------
async function fetchConfig() {
  const campaign = campaignSelect.value;
  try {
    const resp = await fetch(`/api/v1/config/agent-schema?campaign_type=${encodeURIComponent(campaign)}`);
    const cfg = await resp.json();
    dispositionLabels = {};
    (cfg.disposition_registry || []).forEach((r) => (dispositionLabels[r.code] = r.label));
    logEvent("incoming", `Loaded agent config for "${campaign}"`, cfg, "ðŸ§©");
  } catch (e) {
    logEvent("error", "Failed to load agent config", { error: String(e) }, "âš ï¸");
  }
}
campaignSelect.addEventListener("change", () => {
  if (websocket && websocket.readyState === WebSocket.OPEN) closeWebsocketIntentionally();
  // A new session id ensures the backend re-seeds state for this campaign.
  newSessionId();
  resetSession();
  fetchConfig();
});
agentModeSelect.addEventListener("change", () => {
  if (websocket && websocket.readyState === WebSocket.OPEN) websocket.close();
  // A new session id ensures the backend picks a fresh Runner/agent state.
  newSessionId();
  resetSession();
  logEvent("incoming", `Switched solution to "${agentModeSelect.value}"`, {}, "ðŸ”");
});

// ---------------------------------------------------------------------------
// Pre-call planning (selectable planned topics)
// ---------------------------------------------------------------------------
async function fetchPlannedTopics() {
  try {
    const resp = await fetch("/api/v1/config/planned-topics");
    const data = await resp.json();
    plannedTopicCatalog = data.topics || [];
    renderTopicOptions();
    logEvent("incoming", `Loaded ${plannedTopicCatalog.length} planned topics`, data, "ðŸ—‚ï¸");
  } catch (e) {
    topicOptions.textContent = "Failed to load topics.";
    logEvent("error", "Failed to load planned topics", { error: String(e) }, "âš ï¸");
  }
}

function renderTopicOptions() {
  topicOptions.innerHTML = "";
  plannedTopicCatalog.forEach((t) => {
    const label = document.createElement("label");
    label.className = "topic-option";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = t.label;
    cb.checked = selectedTopics.includes(t.label);
    cb.addEventListener("change", onTopicToggle);
    const span = document.createElement("span");
    span.textContent = t.label;
    label.appendChild(cb);
    label.appendChild(span);
    topicOptions.appendChild(label);
  });
  updatePlannedCount();
}

function onTopicToggle(e) {
  const label = e.target.value;
  if (e.target.checked) {
    if (!selectedTopics.includes(label)) selectedTopics.push(label);
  } else {
    selectedTopics = selectedTopics.filter((t) => t !== label);
  }
  // Changing the plan mid-stream means a fresh session is needed so the agent
  // is re-seeded with the new topic list.
  if (websocket && websocket.readyState === WebSocket.OPEN) closeWebsocketIntentionally();
  newSessionId();
  updatePlannedCount();
}

function updatePlannedCount() {
  const n = selectedTopics.length;
  plannedCount.textContent = `${n} selected`;
  plannedCount.classList.toggle("badge-empty", n === 0);
}

function setPlanningEnabled(enabled) {
  planningPanel.classList.toggle("locked", !enabled);
  topicOptions
    .querySelectorAll("input[type=checkbox]")
    .forEach((cb) => (cb.disabled = !enabled));
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
function closeWebsocketIntentionally() {
  if (websocket) {
    const ws = websocket;
    websocket = null;
    try { ws.close(); } catch (_) { }
    setConnected(false);
  }
}

function wsUrl() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const campaign = encodeURIComponent(campaignSelect.value);
  const planned = encodeURIComponent(selectedTopics.join(","));
  const agentMode = encodeURIComponent(agentModeSelect.value);
  return `${proto}//${window.location.host}/ws/${userId}/${sessionId}?campaign_type=${campaign}&planned_topics=${planned}&agent_mode=${agentMode}`;
}

function connectWebsocket() {
  const ws = new WebSocket(wsUrl());
  websocket = ws;

  ws.onopen = () => {
    if (websocket !== ws) return; // a newer socket superseded this one
    setConnected(true);
    logEvent(
      "incoming",
      "WebSocket connected",
      { userId, sessionId, campaign: campaignSelect.value, agentMode: agentModeSelect.value },
      "ðŸ”Œ",
    );
  };

  ws.onmessage = (event) => {
    if (websocket !== ws) return;
    const ev = JSON.parse(event.data);

    if (ev.type === "ui_event" && ev.event === "tool_error") {
      const banner = document.createElement("div");
      banner.className = "ui-error-banner";
      banner.style.position = "fixed";
      banner.style.top = "0";
      banner.style.width = "100%";
      banner.style.backgroundColor = "red";
      banner.style.color = "white";
      banner.style.textAlign = "center";
      banner.style.padding = "10px";
      banner.style.zIndex = "9999";
      banner.textContent = ev.message;
      document.body.prepend(banner);
      setTimeout(() => banner.remove(), 5000);
      return;
    }

    handleAdkEvent(ev);
  };

  ws.onclose = () => {
    // Ignore close events for sockets we've already replaced (reconnects).
    if (websocket !== ws) return;
    setConnected(false);
    logEvent("error", "WebSocket closed", null, "ðŸ”Œ");

    // Attempt WebSocket reconnection with exponential backoff.
    // IMPORTANT: we generate a NEW sessionId on each attempt so the backend
    // creates a fresh Gemini Live session rather than reusing the one that is
    // still tearing down (which triggers APIError 1000 on the server).
    const backoffs = [800, 1200, 2000, 3500];
    if (reconnectAttempts < backoffs.length) {
      setPhase("processing", "Connection lost. Reconnecting...");
      setTimeout(() => {
        reconnectAttempts++;
        newSessionId(); // fresh session so the server starts a clean Gemini Live session
        connectWebsocket();
      }, backoffs[reconnectAttempts]);
      return;
    }

    // Don't leave the UI stuck on "agent respondingâ€¦" if the stream dropped
    // mid-turn. Recover to a usable state (unless we already finished).
    stopSpeechRecognition();
    micActive = false;
    agentTurnActive = false;
    if (phase !== "saved" && phase !== "processing") {
      setPhase("error", "Connection dropped. Press the mic to start again.");
    }
  };

  ws.onerror = (e) => {
    if (websocket !== ws) return;
    setConnected(false);
    logEvent("error", "WebSocket error", { type: e.type }, "âš ï¸");
  };
}

// ---------------------------------------------------------------------------
// ADK event handling
// ---------------------------------------------------------------------------
function handleAdkEvent(ev) {
  // Display-only: track the model's own reported token usage for the cost
  // estimate. Does not affect any agent/session/execution behavior.
  if (ev.usageMetadata) applyUsageMetadata(ev.usageMetadata);

  // Console summary
  let summary = "event";
  let emoji = "ðŸ“¨";
  if (ev.turnComplete) { summary = "Turn complete"; emoji = "âœ…"; }
  else if (ev.interrupted) { summary = "Interrupted"; emoji = "â¸ï¸"; }
  else if (ev.inputTranscription) { summary = `Input: "${ev.inputTranscription.text || ""}"`; emoji = "ðŸ“"; }
  else if (ev.outputTranscription) { summary = `Output: "${ev.outputTranscription.text || ""}"`; emoji = "ðŸ—£ï¸"; }
  else if (ev.content && ev.content.parts) {
    const p = ev.content.parts;
    if (p.some((x) => x.functionCall)) { const fc = p.find((x) => x.functionCall).functionCall; summary = `Tool call: ${fc.name}`; emoji = "ðŸ› ï¸"; }
    else if (p.some((x) => x.functionResponse)) { const fr = p.find((x) => x.functionResponse).functionResponse; summary = `Tool result: ${fr.name}`; emoji = "ðŸ“¦"; }
    else if (p.some((x) => x.inlineData)) { summary = "Audio chunk"; emoji = "ðŸ”Š"; }
    else if (p.some((x) => x.text)) { summary = `Text: "${(p.find((x) => x.text).text || "").slice(0, 60)}"`; emoji = "ðŸ’­"; }
  }
  // Don't spam the console with every audio chunk.
  const isAudioOnly = ev.content && ev.content.parts &&
    ev.content.parts.some((x) => x.inlineData) && !ev.content.parts.some((x) => x.text);
  if (!isAudioOnly) logEvent("incoming", summary, sanitize(ev), emoji);

  // As soon as the agent starts its turn, gate the mic so it doesn't hear its
  // own spoken playback. The mic re-opens on turnComplete.
  const agentActivity =
    !!(ev.outputTranscription && ev.outputTranscription.text) ||
    !!(ev.content && ev.content.parts && ev.content.parts.some(
      (p) => p.functionCall || p.functionResponse || p.inlineData ||
        (p.text && !p.thought)));
  if (agentActivity && !agentTurnActive &&
    (phase === "listening" || phase === "confirm")) {
    beginAgentResponse();
  }

  // Input transcription (rep's spoken notes) -> live "You" caption.
  // When the browser recognizer is driving the live caption we let it own the
  // streaming text and only use the model's FINAL transcription to lock in the
  // authoritative wording before the turn is committed to history.
  if (ev.inputTranscription) {
    if (useClientSpeech) {
      if (ev.inputTranscription.finished && ev.inputTranscription.text) {
        liveUserText = ev.inputTranscription.text;
        renderCaption(userCaption, liveUserText, false);
      }
    } else {
      updateUserCaption(
        ev.inputTranscription.text || "",
        !!ev.inputTranscription.finished
      );
    }
    // The rep just said something real -- arm the mute gate. Whatever the
    // agent says next is suppressed until a real tool call proves it's done
    // guessing (see the `suppressAgentSpeech` declaration above).
    //
    // IMPLICIT MODE ONLY: the pre-tool-call guess bug this gate hides is
    // specific to the implicit flow's stage_visit_notes turn. The guided
    // flow has many legitimate turns that are pure speech with NO tool call
    // at all (e.g. "I think you mean X -- is that correct?", the numbered
    // disposition retry list) -- if armed there, the gate would never lift
    // (nothing to lift it on) and that speech/caption would be silently
    // dropped forever, even though it's the real, correct thing to say.
    if (
      agentModeSelect.value === "implicit" &&
      ev.inputTranscription.finished &&
      (ev.inputTranscription.text || "").trim()
    ) {
      suppressAgentSpeech = true;
    }
  }

  // Output transcription (agent's spoken reply) -> live "Agent" caption
  if (ev.outputTranscription && !suppressAgentSpeech) {
    updateAgentCaption(
      ev.outputTranscription.text || "",
      !!ev.outputTranscription.finished
    );
  }

  // Content parts: audio playback + function call/response
  if (ev.content && ev.content.parts) {
    for (const part of ev.content.parts) {
      if (part.inlineData && part.inlineData.mimeType &&
        part.inlineData.mimeType.startsWith("audio/pcm") && audioPlayerNode) {
        if (!suppressAgentSpeech) {
          audioPlayerNode.port.postMessage(base64ToArray(part.inlineData.data));
        }
      }
      // Any real tool call means the agent is done guessing -- lift the mute
      // so the tool-grounded readback that follows plays normally.
      if (part.functionCall) suppressAgentSpeech = false;
      if (part.functionCall) handleFunctionCall(part.functionCall);
      if (part.functionResponse) handleFunctionResponse(part.functionResponse);
      if (part.text && !part.thought) {
        // Half-cascade / text-only fallback: stream agent text into caption.
        updateAgentCaption(part.text, false);
      }
    }
  }

  if (ev.interrupted) {
    finalizeAllCaptions();
    agentTurnActive = false;
    micActive = true; // rep barged in; keep listening
    startSpeechRecognition();
  }

  if (ev.turnComplete) {
    finalizeAllCaptions();
    agentTurnActive = false;

    // Check if the agent completely ignored the user's speech
    const userSpoke = !!liveUserText;
    const agentResponded = !!agentActivity || !payloadCard.classList.contains("hidden");

    if (committed) {
      // Notes saved -> end the session.
      finishSession();
    } else if (!payloadCard.classList.contains("hidden")) {
      // Agent finished speaking the confirmation -> re-open the mic so the rep
      // can simply say "Save" or a correction.
      enterConfirmPhase();
    } else if (userSpoke && !agentResponded) {
      // The user spoke, but the agent emitted turnComplete WITHOUT staging notes 
      // or saying anything. This is a model glitch (empty turn).
      setPhase("error", "The agent didn't catch that. Please press the mic and try dictating again.");
      endSession();
    } else {
      // No staged payload yet -> keep listening for the rep's dictation.
      armVad();
      micActive = true;
      startSpeechRecognition();
      setPhase("listening");
    }
  }
}

function beginAgentResponse() {
  agentTurnActive = true;
  micActive = false; // stop streaming while the agent speaks
  stopSpeechRecognition(); // don't transcribe the agent's own playback
  levelFill.style.width = "0%";
  silenceCountdown.textContent = "agent respondingâ€¦";
  silenceCountdown.classList.remove("counting");
  // The "extracting the structured record" wording only makes sense for the
  // implicit flow's post-dictation moment -- the guided flow's very first
  // agent turn is just the Stage 0 greeting, not an extraction. Use a
  // mode-neutral label there instead so the banner doesn't imply something
  // is being extracted when the agent is just talking/asking a question.
  const text =
    agentModeSelect.value === "guided" ? "Agent is respondingâ€¦" : undefined;
  setPhase("processing", text);
}

function handleFunctionCall(fc) {
  if (fc.name === "stage_visit_notes") {
    const args = fc.args || {};
    renderPayload(args);
    payloadStatus.textContent = "staged";
    payloadStatus.className = "badge";
  } else if (fc.name === "commit_visit_notes" || fc.name === "commit_guided_notes") {
    payloadStatus.textContent = "committingâ€¦";
  } else if (fc.name === "capture_dictation") {
    // Guided flow builds its record incrementally across several small tool
    // calls (no single Mega-Payload). Accumulate the pieces client-side as
    // they stream by so the Staged CRM Record card can show the full record
    // once it's revealed at commit -- same reveal moment as before, just
    // populated now. Purely a display accumulator; doesn't affect the flow.
    const args = fc.args || {};
    resetGuidedPayload();
    guidedPayload.raw_transcript_backup = args.raw_transcript || "";
    guidedPayload.executive_summary = args.executive_summary || "";
  } else if (fc.name === "set_event_type") {
    const args = fc.args || {};
    if (!guidedPayload) resetGuidedPayload();
    guidedPayload.event_type = args.event_type || "";
  } else if (fc.name === "record_topic_disposition") {
    const args = fc.args || {};
    if (!guidedPayload) resetGuidedPayload();
    guidedPayload.topics.push({
      topic: args.topic,
      disposition_code: args.disposition_code,
      executive_summary: args.executive_summary,
      discussed: args.discussed,
    });
  }
}

let guidedPayload = null;

function resetGuidedPayload() {
  guidedPayload = {
    event_type: "",
    executive_summary: "",
    raw_transcript_backup: "",
    topics: [],
  };
}

function handleFunctionResponse(fr) {
  const resp = fr.response || {};
  if (fr.name === "stage_visit_notes") {
    // Confirmation text is spoken by the model; surface it in the log too.
    if (resp.confirmation_text) {
      logEvent("incoming", `Confirmation: ${resp.confirmation_text}`, resp, "ðŸ—£ï¸");
    }
    // The actual phase switch to "confirm" happens on turnComplete (after the
    // model has finished speaking the confirmation aloud).
  } else if (
    fr.name === "commit_visit_notes" ||
    fr.name === "commit_guided_notes" ||
    fr.name === "record_topic_disposition"
  ) {

    // A commit can be refused for several reasons, each with its own status:
    // turn_guard ("error"), planned-topic coverage ("blocked"), campaign-rule
    // violation ("rejected") -- and more may be added. Matching status strings
    // means a new refusal silently falls through to the saved state and the UI
    // claims "Saved to CRM" for a record that was never written. Test for the
    // only thing that actually proves a CRM write instead: a record id.
    // record_topic_disposition returns a commit result ONLY on the final
    // topic (it commits directly -- see tools_guided). Its mid-flow
    // responses are not commit attempts and must not be read as refusals.
    if (resp.status === "next_topic" || resp.error === "no_reply_heard") return;

    if (!resp.crm_record_id) {
      const why = resp.error || resp.status || "unknown";
      const missing = Array.isArray(resp.missing_topics)
        ? resp.missing_topics
        : [];
      const detail = missing.length
        ? `${why} (still needed: ${missing.join(", ")})`
        : why;
      logEvent("incoming", `Commit refused: ${detail}`, resp, "ðŸš«");
      // Nothing was saved: keep the record staged and leave the rep in the
      // confirm phase so they can answer the agent and try again.
      payloadStatus.textContent = "staged";
      payloadStatus.className = "badge";
      return;
    }
    // Guided flow has no single mega-payload staging step -- render the
    // record we accumulated client-side from its incremental tool calls
    // (capture_dictation / set_event_type / record_topic_disposition) at
    // the same moment the card is revealed, otherwise it stays blank.
    //
    // Deliberately no tool-name check: the commit result now arrives under
    // whichever tool performed it, and the last record_topic_disposition
    // commits directly (see tools_guided). guidedPayload is only ever set in
    // guided mode, so its presence is the reliable signal.
    if (guidedPayload) {
      renderPayload(guidedPayload);
    }

    // Setting committed here also matters for the mic: otherwise
    // turnComplete's fallback branch would just re-arm it forever.

    committed = true;
    payloadCard.classList.remove("hidden");
    if (resp.crm_record_id) pCrmId.textContent = resp.crm_record_id;
    payloadStatus.textContent = "committed";
    payloadStatus.className = "badge committed";
    saveButton.disabled = true;
    changeButton.disabled = true;
    if (resp.closing_statement) {
      logEvent("incoming", `Closing: ${resp.closing_statement}`, resp, "ðŸ—£ï¸");
    }
  }
}

function topicsMatch(a, b) {
  const x = (a || "").trim().toLowerCase();
  const y = (b || "").trim().toLowerCase();
  if (!x || !y) return false;
  return x === y || x.includes(y) || y.includes(x);
}

function renderCoverage(topics) {
  if (!pCoverage) return;
  pCoverage.innerHTML = "";
  // Prefer the agent-provided planned list, fall back to the UI selection.
  const planned = selectedTopics;
  if (!planned.length) {
    pCoverage.innerHTML = '<span class="muted">No planned topics.</span>';
    return;
  }
  planned.forEach((label) => {
    const match = topics.find((t) => topicsMatch(t.topic, label));
    const chip = document.createElement("span");
    chip.className = "coverage-chip";
    let state = "pending";
    if (match) state = match.discussed === false ? "skipped" : "covered";
    chip.classList.add("cov-" + state);
    const icon = state === "covered" ? "âœ“" : state === "skipped" ? "â€”" : "â€¦";
    chip.textContent = `${icon} ${label}`;
    pCoverage.appendChild(chip);
  });
}

function renderPayload(args) {
  payloadCard.classList.remove("hidden");
  // A newly staged record has not been written to the CRM, so it has no record
  // id. Clear any id left over from a previous commit in this page session --
  // otherwise the card shows a "staged" badge next to a real CRM id.
  pCrmId.textContent = "â€”";

  pEventType.textContent = args.event_type || "â€”";
  pSummary.textContent = args.executive_summary || "â€”";

  const topics = Array.isArray(args.topics) ? args.topics : [];
  renderCoverage(topics);
  pTopics.innerHTML = "";
  topics.forEach((t, i) => {
    const code = t.disposition_code;
    const label =
      dispositionLabels[code] || dispositionLabels[Number(code)] || "";
    const item = document.createElement("div");
    item.className = "topic-item";

    const head = document.createElement("div");
    head.className = "topic-head";
    const title = document.createElement("span");
    title.className = "topic-title";
    title.textContent = `${i + 1}. ${t.topic || "Topic"}`;
    const disp = document.createElement("span");
    disp.className = "topic-disposition";
    if (t.discussed === false) {
      disp.classList.add("not-discussed");
      disp.textContent = "not discussed";
    } else {
      disp.textContent =
        code != null ? `${code}${label ? " â€” " + label : ""}` : "â€”";
    }
    head.appendChild(title);
    head.appendChild(disp);

    const summary = document.createElement("div");
    summary.className = "topic-summary";
    summary.textContent = t.executive_summary || "";

    item.appendChild(head);
    item.appendChild(summary);
    pTopics.appendChild(item);
  });

  const transcript = args.raw_transcript_backup || "â€”";
  pTranscript.innerHTML = transcript
    .replace(/\[inaudible\]/gi, '<span class="uncertainty-tag">$&</span>')
    .replace(/\[unclear\]/gi, '<span class="uncertainty-tag">$&</span>');

  if (playbackAudio && recordingBuffers.length > 0) {
    playbackAudio.src = URL.createObjectURL(createWavBlob(recordingBuffers));
  }
}

function enterConfirmPhase() {
  setPhase("confirm");
  saveButton.disabled = false;
  changeButton.disabled = false;
  // Re-open the mic for the spoken confirmation/correction turn.
  armVad();
  micActive = true;
  startSpeechRecognition();
}

function finishSession() {
  setPhase("saved");
  micActive = false;
  stopSpeechRecognition();
  silenceCountdown.textContent = "done";
  silenceCountdown.classList.remove("counting");
  levelFill.style.width = "0%";
  markRunMetricsDone(); // "CRM saved successfully" moment -> stop the run timer
}

// ---------------------------------------------------------------------------
// Audio + client-side VAD
// ---------------------------------------------------------------------------
async function ensureAudio() {
  if (audioStarted) return;
  const [pNode] = await startAudioPlayerWorklet();
  audioPlayerNode = pNode;
  const [rNode, , stream] = await startAudioRecorderWorklet(audioRecorderHandler);
  audioRecorderNode = rNode;
  micStream = stream;
  audioStarted = true;
}

function armVad() {
  hadSpeech = false;
  speechStartTs = 0;
  lastVoiceTs = performance.now();
}

function audioRecorderHandler(pcmData) {
  // --- Client-side energy VAD ---
  // --- Distortion detection runs UNCONDITIONALLY (before the micActive
  // guard) so a sustained noise burst is caught even after the user has
  // pressed "stop" (micActive = false) while awaiting a model response.
  // Previously the early return on !micActive prevented the streak counter
  // from incrementing, so the distortion error was never shown.
  const int16 = new Int16Array(pcmData);
  let sum = 0;
  for (let i = 0; i < int16.length; i++) {
    const v = int16[i] / 32768;
    sum += v * v;
  }
  const rms = Math.sqrt(sum / Math.max(int16.length, 1));

  // Sustained high-energy detection. The browser's autoGainControl normalizes
  // peaks before they reach JS, so a peak-clipping check (Math.max > 30000)
  // never fires. Instead we count how many consecutive chunks sit at
  // HIGH_RMS_THRESHOLD (0.90) or above AFTER AGC has already normalized them.
  // If audio is genuinely saturated/distorted, it stays pinned near the top
  // even after AGC. Normal speech produces a much more dynamic RMS pattern.
  if (rms >= HIGH_RMS_THRESHOLD) {
    highEnergyStreak++;
    if (highEnergyStreak >= HIGH_ENERGY_STREAK_MAX) {
      closeWebsocketIntentionally();
      stopSpeechRecognition();
      micActive = false;
      agentTurnActive = false;
      highEnergyStreak = 0;
      setPhase("error", "Audio distortion detected. Please check your microphone and try again.");
      return;
    }
  } else {
    // Reset on any chunk that falls below the threshold â€” normal speech has
    // natural dynamic range and will break the streak between words.
    highEnergyStreak = 0;
  }

  // Everything below is only relevant when the mic is actively streaming.
  if (!micActive) return;

  recordingBuffers.push(new Int16Array(pcmData));

  // Stream the chunk to the server if connected, unless we're already backed
  // up. 16kHz 16-bit mono is 32000 B/s, so MAX_BUFFERED_BYTES is ~2s of audio.
  // If the uplink (or a tunnel hop) can't sustain realtime, queueing more only
  // grows a backlog that the Live API reads as "sending data too fast" once it
  // drains -- there is no catching up on a realtime stream, so dropping is the
  // only correct response.
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    if (websocket.bufferedAmount > MAX_BUFFERED_BYTES) {
      if (!audioBackpressureWarned) {
        audioBackpressureWarned = true;
        console.warn(
          "Uplink behind realtime (bufferedAmount=" +
            websocket.bufferedAmount +
            "B) -- dropping audio chunks until it drains."
        );
      }
    } else {
      audioBackpressureWarned = false;
      websocket.send(pcmData);
    }
  }

  levelFill.style.width = Math.min(100, rms * 450).toFixed(0) + "%";

  // Client-side silence countdown is informational only: the server's
  // automatic VAD is what actually finalizes the turn after SILENCE_MS.
  const now = performance.now();
  if (rms >= VOICE_RMS_THRESHOLD) {
    if (!hadSpeech) speechStartTs = now;
    hadSpeech = true;
    lastVoiceTs = now;
    silenceCountdown.textContent = "ðŸŽ™ï¸ speakingâ€¦";
    silenceCountdown.classList.remove("counting");
  } else if (hadSpeech && now - speechStartTs > MIN_SPEECH_MS) {
    const silentFor = now - lastVoiceTs;
    if (silentFor >= SILENCE_MS) {
      silenceCountdown.textContent = "pause detected â€” wrapping upâ€¦";
      silenceCountdown.classList.remove("counting");
    } else {
      const remaining = Math.max(0, SILENCE_MS - silentFor);
      silenceCountdown.textContent = `pausingâ€¦ ${(remaining / 1000).toFixed(1)}s`;
      silenceCountdown.classList.add("counting");
    }
  }
}


function endSession() {
  // Stop streaming and tear down the live session.
  micActive = false;
  agentTurnActive = false;
  stopSpeechRecognition();
  if (websocket && websocket.readyState === WebSocket.OPEN) closeWebsocketIntentionally();
  silenceCountdown.textContent = "VAD idle";
  silenceCountdown.classList.remove("counting");
  levelFill.style.width = "0%";
  // A finished/ended session can't reuse its seeded state -> fresh id next run.
  newSessionId();
  setPlanningEnabled(true);
  setPhase("idle");
  if (!committed) stopRunTimer(); // manually aborted mid-run -- freeze, don't mark "done"
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
async function startDictation() {
  if (selectedTopics.length === 0) {
    setPhase("error", "Select at least one planned topic before you start.");
    return;
  }
  resetForNewDictation();
  setPlanningEnabled(false);
  startRunTimer(); // rep clicked the mic to start speaking -- start the clock
  await ensureAudio();
  if (!websocket || websocket.readyState !== WebSocket.OPEN) {
    // Drop any stale (closing/closed) socket before reconnecting so we never
    // wait on a dead connection.
    closeWebsocketIntentionally();
    setPhase("processing", "Connectingâ€¦");
    connectWebsocket();
    const opened = await waitForOpen(8000);
    if (!opened) {
      setPhase("error", "Couldn't connect. Press the mic to try again.");
      resetRunMetrics(); // never actually started talking to the agent
      return;
    }
  }
  armVad();
  micActive = true;
  startSpeechRecognition();
  setPhase("listening");
}

function waitForOpen(timeoutMs = 8000) {
  return new Promise((resolve) => {
    if (websocket && websocket.readyState === WebSocket.OPEN) return resolve(true);
    const start = performance.now();
    const t = setInterval(() => {
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        clearInterval(t);
        resolve(true);
      } else if (
        !websocket ||
        websocket.readyState === WebSocket.CLOSED ||
        performance.now() - start > timeoutMs
      ) {
        clearInterval(t);
        resolve(false);
      }
    }, 50);
  });
}

micButton.addEventListener("click", () => {
  if (phase === "listening") {
    // "Done dictating" â€” stop sending mic audio but keep the WebSocket OPEN
    // so the model can process the buffered audio in the server's
    // LiveRequestQueue. DO NOT call endSession() here: closing the socket
    // kills the Vertex AI Live session before it can respond.
    //
    // WHY THIS MATTERS: Vertex AI's cold-start handshake takes 6-10 seconds.
    // During that time, audio chunks are buffered server-side. Closing the
    // socket immediately (old behaviour) always raced against the handshake
    // and killed the session before the model saw the audio â€” producing the
    // "1000 None / client disconnected" error observed in logs.
    //
    // New behaviour: silence the mic, show "processing", and let the 30-second
    // watchdog close the connection only if the model genuinely stalls.
    micActive = false;
    stopSpeechRecognition();
    levelFill.style.width = "0%";
    silenceCountdown.classList.remove("counting");
    silenceCountdown.textContent = "processingâ€¦";
    setPhase("processing", "Processing your notes â€” please waitâ€¦");
    if (!agentResponseWatchdog) {
      agentResponseWatchdog = setTimeout(() => {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
          closeWebsocketIntentionally();
        }
        agentResponseWatchdog = null;
        setPhase("error", "The agent took too long to respond. Please try again.");
      }, 30000);
    }
  } else if (phase === "confirm") {
    // User explicitly aborts the confirmation step.
    endSession();
  } else if (phase === "processing") {
    // Escape hatch: user cancels a stalled connection or processing.
    endSession();
  } else {
    startDictation();
  }
});


saveButton.addEventListener("click", () => sendText("Save it."));
changeButton.addEventListener("click", () => {
  correctionUi.classList.remove("hidden");
  correctionInput.value = "";
  correctionInput.focus();
});

if (submitCorrectionBtn) {
  submitCorrectionBtn.addEventListener("click", () => {
    const change = correctionInput.value.trim();
    if (change) {
      sendText(change);
      correctionUi.classList.add("hidden");
    }
  });
}

if (cancelCorrectionBtn) {
  cancelCorrectionBtn.addEventListener("click", () => {
    correctionUi.classList.add("hidden");
  });
}

if (correctionInput) {
  correctionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      submitCorrectionBtn.click();
    } else if (e.key === "Escape") {
      cancelCorrectionBtn.click();
    }
  });
}

function sendText(text) {
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    addMessage(text, "user");
    websocket.send(JSON.stringify({ type: "text", text }));
    logEvent("outgoing", `Text: ${text}`, null, "ðŸ’¬");
    setPhase("processing", "Processing your responseâ€¦");
  }
}

function resetForNewDictation() {
  // Narrow reset: keeps audio context and connection alive, clears payload
  committed = false;
  recordingBuffers = [];
}

function resetSession() {
  micActive = false;
  committed = false;
  suppressAgentSpeech = false;
  guidedPayload = null;
  stopSpeechRecognition();
  payloadCard.classList.add("hidden");
  saveButton.disabled = true;
  changeButton.disabled = true;
  setPlanningEnabled(true);
  if (pCoverage) pCoverage.innerHTML = "";
  messagesDiv.innerHTML = "";
  resetCaptions();
  levelFill.style.width = "0%";
  silenceCountdown.textContent = "VAD idle";
  silenceCountdown.classList.remove("counting");
  setPhase("idle");
  resetRunMetrics();
}

function sanitize(ev) {
  const c = JSON.parse(JSON.stringify(ev));
  if (c.content && c.content.parts) {
    c.content.parts = c.content.parts.map((part) => {
      if (part.inlineData && part.inlineData.data) {
        const bytes = Math.floor(part.inlineData.data.length * 0.75);
        return { ...part, inlineData: { ...part.inlineData, data: `(${bytes} bytes)` } };
      }
      return part;
    });
  }
  return c;
}

function base64ToArray(base64) {
  let s = base64.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = window.atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function fetchClientConfig() {
  try {
    const resp = await fetch("/api/v1/client-config");
    const cfg = await resp.json();
    if (cfg.vad_silence_ms) SILENCE_MS = cfg.vad_silence_ms;
    logEvent("incoming", `Client VAD threshold: ${SILENCE_MS}ms`, cfg, "â±ï¸");
  } catch (e) {
    logEvent("error", "Failed to load client config", { error: String(e) }, "âš ï¸");
  }
}

setPhase("idle");
fetchClientConfig();
fetchConfig();
fetchPlannedTopics();

// ---------------------------------------------------------------------------
// Dev/test hook â€” exposes key internal functions on window.__snTest so they
// can be called from the browser DevTools console even though this file runs
// as an ES module (module scope is private and unreachable from the console).
//
// Usage (DevTools console):
//   window.__snTest.simulateAgentStall()   â†’ triggers watchdog test (Test 3)
//   window.__snTest.simulateToolError()    â†’ injects a tool-error banner (Test 4)
//   window.__snTest.getPhase()             â†’ returns current phase string
// ---------------------------------------------------------------------------
window.__snTest = {
  /** Simulate a Gemini Live API stall: enters "agent responding..." and starts
   *  the 10-second watchdog. If no real events arrive, the watchdog fires and
   *  shows the timeout error, proving Test 3 works correctly. */
  simulateAgentStall() {
    if (phase !== "listening" && phase !== "confirm") {
      console.warn("[__snTest] App must be in listening or confirm phase first. Click the mic and connect.");
      return;
    }
    console.info("[__snTest] Triggering beginAgentResponse(). Watchdog fires in 10s if no events arrive.");
    beginAgentResponse();
  },

  /** Inject a tool-error banner directly without a real tool failure (Test 4). */
  simulateToolError() {
    const banner = document.createElement("div");
    banner.className = "ui-error-banner";
    banner.style.cssText = "position:fixed;top:0;width:100%;background:red;color:white;text-align:center;padding:10px;z-index:9999;";
    banner.textContent = "There was a problem saving your notes. [simulated]";
    document.body.prepend(banner);
    setTimeout(() => banner.remove(), 5000);
    console.info("[__snTest] Tool-error banner injected. It will auto-dismiss in 5s.");
  },

  /** Return the current UI phase. */
  getPhase() { return phase; },
};

window.addEventListener("DOMContentLoaded", () => {
  if ('serviceWorker' in navigator) {
    // Unregister any previously installed service workers. The SW feature was
    // removed because it caused a GET / redirect loop that broke the app.
    navigator.serviceWorker.getRegistrations().then((registrations) => {
      registrations.forEach(r => r.unregister());
    });
  }

  window.addEventListener('online', () => document.body.classList.remove('offline'));
  window.addEventListener('offline', () => document.body.classList.add('offline'));
  if (!navigator.onLine) document.body.classList.add('offline');

  // Offline draft recovery removed (AIML-2703).
  //
  // The staged record lives in server memory, keyed by session_id. A copy kept
  // in localStorage outlives it -- across a server restart, a redeploy, or
  // simply the next session -- so the card came back showing a record the
  // backend had never heard of, with Save enabled and no CRM record id.
  // Committing it could only ever fail (no_staged_notes), and worse, an
  // already-saved record reappeared as a live draft because nothing cleared
  // the key after a successful commit.
  //
  // Server state is authoritative. This purge runs unconditionally so any
  // browser still holding a stale draft is cleaned up on its next load.
  localStorage.removeItem("sellntell_draft");
});
