/**
 * Voice Notes Logger - frontend controller.
 *
 * Drives the dictation state machine, client-side VAD (energy-based silence
 * stop-trigger), audio streaming, and rendering of the staged CRM payload /
 * confirmation that the agent produces via tool calls.
 */

// Version the imported modules too, not just app.js.
//
// index.html loads `app.js?v=N`, but that query covers ONLY app.js -- the
// modules it imports were requested at their bare URL and could be served from
// disk cache indefinitely, so a change to audio-recorder.js could be invisible
// while app.js itself was demonstrably fresh. Observed on the VDI: app.js
// fetched 200/65kB, audio-recorder.js "0 B (disk cache)" in the same load.
//
// Keep N in step with the value in index.html whenever either file changes.
// (`new URL("./pcm-recorder-processor.js", import.meta.url)` inside
// audio-recorder.js resolves against the query-stripped path, so the worklet
// module is unaffected.)
import { startAudioPlayerWorklet } from "./audio-player.js?v=10";
import { startAudioRecorderWorklet } from "./audio-recorder.js?v=10";

// ---------------------------------------------------------------------------
// Config / constants
// ---------------------------------------------------------------------------
/**
 * RFC 4122 v4 UUID, with a fallback for non-secure contexts.
 *
 * `crypto.randomUUID` exists ONLY in a secure context -- HTTPS, or localhost.
 * Served over plain HTTP (an internal LAN deployment without a cert, which is
 * plausible for an internal sales tool) it is `undefined`, and calling it here
 * throws at module load, taking the whole frontend down before anything
 * renders. `crypto.getRandomValues` has no such restriction, so it carries the
 * fallback; `Math.random` is the last resort and is only ever reached in an
 * environment where Web Crypto is absent entirely.
 *
 * These ids only have to be unique, not unguessable -- they key an in-memory
 * session store, so a weaker source in the fallback path costs nothing.
 */
function uuid() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();

  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"));
  return (
    hex.slice(0, 4).join("") +
    "-" +
    hex.slice(4, 6).join("") +
    "-" +
    hex.slice(6, 8).join("") +
    "-" +
    hex.slice(8, 10).join("") +
    "-" +
    hex.slice(10, 16).join("")
  );
}

let userId = localStorage.getItem("sellntell_rep_id");
if (!userId) {
  userId = "rep-" + uuid();
  localStorage.setItem("sellntell_rep_id", userId);
}
// Regenerated whenever the campaign or planned topics change so the backend
// seeds a fresh session with the new selection (in-memory sessions are keyed
// by id and their seeded state is otherwise sticky).
let sessionId = null;
function newSessionId() {
  sessionId = null;
}

async function ensureSession() {
  if (sessionId) {
    return sessionId;
  }
  const MAX_RETRIES = 3;
  const DELAYS = [500, 1000, 1500];

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const planned = typeof selectedTopics !== "undefined" ? selectedTopics : [];
      const campaign = typeof campaignSelect !== "undefined" && campaignSelect ? campaignSelect.value : "standard_sales";
      const resp = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          planned_topics: planned,
          campaign_type: campaign,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.status === "ok" && data.session_id) {
          sessionId = String(data.session_id);
          return sessionId;
        }
        console.warn(`Server returned non-ok status on session create (attempt ${attempt + 1}):`, data);
      } else {
        console.warn(`POST /api/sessions HTTP ${resp.status} on attempt ${attempt + 1}`);
      }
    } catch (err) {
      console.warn(`POST /api/sessions network error on attempt ${attempt + 1}:`, err);
    }
    if (attempt < MAX_RETRIES - 1) {
      await new Promise((resolve) => setTimeout(resolve, DELAYS[attempt]));
    }
  }

  // Retries exhausted. Do NOT fall back to local client UUID --
  // Vertex AI strictly rejects client-minted IDs with 4404 Session Not Found,
  // which would wedge the client into an infinite reconnection loop.
  sessionId = null;
  return null;
}

// Client-side VAD tuning. The browser's VAD is the authoritative stop-trigger
// (the Live API's server-side VAD caps at 2000ms, below the spec's 2.5-3.0s),
// so we run the session in manual activity-detection mode. The threshold is
// set here is only for informational purpose in UI , since /api/v1/client-config was removed 
//for contract simplification , it no longer fetches value from backend to display

let SILENCE_MS = 2000;            // stop-trigger window (spec: 2.5-3.0s)
const VOICE_RMS_THRESHOLD = 0.022; // above this = speech present
const MIN_SPEECH_MS = 400;        // require some speech before arming silence

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let websocket = null;
let audioPlayerNode = null;
let audioRecorderNode = null;
let micStream = null;
let audioRecorderFlush = null; // drains the resampler's partial chunk; see stopMicStreaming
let audioStarted = false;

let micActive = false;       // are we streaming mic audio right now?
let audioBackpressureWarned = false; // log the "uplink behind" warning once per episode
let phase = "idle";          // idle | listening | processing | confirm | saved
let committed = false;
let agentTurnActive = false; // true while the agent is taking its turn
let reconnectSameSession = false; // configured by server_config handshake event
let autoCloseDelayS = 10;         // configured by server_config handshake or defaults to 10s
let autoCloseTimer = null;        // countdown timer id for auto-closing websocket after commit
let awaitingClosingAudio = false; // true once commit_visit_notes succeeds, until agent speaks closing
let hasDeliveredClosingAudio = false; // true once audio chunks or closing text have arrived

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

// ===========================================================================
// Disposition label lookup, hardcoded client-side.
//
// Replaces fetchConfig()'s only remaining purpose. The endpoint it called
// (GET /api/v1/config/agent-schema?campaign_type=...) is deleted along with
// campaign_type entirely (see PR: "Contract Simplification & Audit
// Logging") -- there is now one universal disposition registry, so the
// labels below are copied verbatim from the deleted
// mock_db._FULL_DISPOSITION_REGISTRY / _NOT_COVERED_RULE (now
// resources/dispositions.yaml) and never change per call.
//
// NOTE: campaign_type's removal from validation rules (event types /
// disposition codes) is confirmed by the PR. Whether campaign context
// should still be captured as CRM metadata is a separate, open business
// question -- flagged, not resolved here. This patch only fixes the
// label-lookup break; it does not touch the campaignSelect dropdown.
// ===========================================================================
const DISPOSITION_LABELS = {
  1: "Create Opportunity",
  2: "Order Placed",
  3: "No current need - revisit in the future",
  4: "Contracted to buy from competitor",
  5: "Buying from preferred vendor already",
  6: "Not a product or service they use/need",
  7: "Does not meet brand/property guidelines",
  8: "Pricing concerns",
  9: "Recently discussed",
  10: "Customer recently purchased related item(s)",
  99: "Outcome not covered - needs manual review",
};

// dispositionLabels was previously populated async by fetchConfig(); it's
// now a plain constant available synchronously from module load, so no
// init call is needed anywhere.
let dispositionLabels = DISPOSITION_LABELS;

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
  logEvent("incoming", "Run timer started", null, "⏱️");
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
    "⏱️"
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
  logEvent("incoming", `Usage metadata: ${cost.toFixed(6)} so far`, usage, "💰");
}

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------
const campaignSelect = document.getElementById("campaignSelect");
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


if (repIdInput) {
  repIdInput.value = userId;
  repIdInput.addEventListener("change", (e) => {
    userId = e.target.value.trim() || userId;
    localStorage.setItem("sellntell_rep_id", userId);
    repIdInput.value = userId;
  });
}


// ---------------------------------------------------------------------------
// Phase / UI helpers
// ---------------------------------------------------------------------------
const PHASES = {
  idle: { cls: "phase-idle", icon: "🎤", text: "Press the mic and start dictating your visit notes." },
  listening: { cls: "phase-listening", icon: "🔴", text: "Listening — you can speak now. I'll stop automatically when you pause." },
  processing: { cls: "phase-processing", icon: "⚙️", text: "Got it — extracting the structured record…" },
  confirm: { cls: "phase-confirm", icon: "🟢", text: "Review below. Say “Save” or tell me what to change." },
  saved: { cls: "phase-saved", icon: "✅", text: "Saved to CRM. Session complete." },
  error: { cls: "phase-error", icon: "⚠️", text: "Something went wrong." },
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
  userCaption.textContent = "Waiting for you to speak…";
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
  agentCaption.textContent = "Waiting for the agent…";
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
  userCaption.textContent = "Waiting for you to speak…";
  agentCaption.textContent = "Waiting for the agent…";
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
// Browser SpeechRecognition removed (transcription handled via Gemini Live)
// ---------------------------------------------------------------------------
function startSpeechRecognition() {}
function stopSpeechRecognition() {}

// ---------------------------------------------------------------------------
// Event console
// ---------------------------------------------------------------------------
function logEvent(type, summary, data, emoji) {
  const entry = document.createElement("div");
  entry.className = "console-entry " + type;
  const header = document.createElement("div");
  header.className = "console-entry-header";
  const left = document.createElement("span");
  left.textContent = (emoji || "") + " " + (type === "outgoing" ? "↑" : type === "incoming" ? "↓" : "⚠");
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

campaignSelect.addEventListener("change", () => {
  if (websocket && websocket.readyState === WebSocket.OPEN) closeWebsocketIntentionally();
  // A new session id ensures the backend re-seeds state for this campaign.
  newSessionId();
  resetSession();
});

// ---------------------------------------------------------------------------
// Pre-call planning (selectable planned topics)
//
// Hardcoded client-side per the contract-simplification pass: the backend's
// GET /api/v1/config/planned-topics route and its PLANNED_TOPIC_CATALOG were
// deleted (verified: this route's only consumer anywhere in the codebase was
// this fetch, and nothing server-side actually validated submitted topics
// against the catalog -- it just fuzzy-matched whatever strings the client
// sent). Values below are copied verbatim from the deleted
// mock_db.PLANNED_TOPIC_CATALOG so the rep-facing list doesn't change.
// ---------------------------------------------------------------------------
const PLANNED_TOPIC_CATALOG = [
  { id: "appliances", label: "Appliances" },
  { id: "cleaning_janitorial", label: "Cleaning & Janitorial" },
  { id: "electrical", label: "Electrical" },
  { id: "hardware", label: "Hardware" },
  { id: "hvac", label: "HVAC" },
  { id: "lighting_ceiling_fans", label: "Lighting & Ceiling Fans" },
  { id: "linens_towels", label: "Linens & Towels" },
  { id: "office_supplies", label: "Office Supplies" },
  { id: "paint_supplies", label: "Paint & Supplies" },
  { id: "plumbing", label: "Plumbing" },
  { id: "pool_supplies", label: "Pool Supplies" },
  { id: "storage", label: "Storage" },
  { id: "tools", label: "Tools" },
];

function loadPlannedTopics() {
  plannedTopicCatalog = PLANNED_TOPIC_CATALOG;
  renderTopicOptions();
  logEvent("incoming", `Loaded ${plannedTopicCatalog.length} planned topics (client-side catalog)`, { topics: plannedTopicCatalog }, "🗂️");
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

// ===========================================================================
// wsUrl() -- campaign_type re-added per business decision: send it from the
// frontend so the pipeline is ready end-to-end, even though the backend
// currently stores it as inert session-state metadata and does not use it
// for any validation/config decision. See main.py's websocket_endpoint
// docstring for the backend side of this contract.
// ===========================================================================
function wsUrl() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const planned = encodeURIComponent(selectedTopics.join(","));
  const campaign = encodeURIComponent(campaignSelect.value);
  return `${proto}//${window.location.host}/ws/${userId}/${sessionId}?planned_topics=${planned}&campaign_type=${campaign}`;
}


async function connectWebsocket() {
  const sid = await ensureSession();
  if (!sid) {
    setConnected(false);
    stopMicStreaming();
    setPhase("error", "Couldn't start a session -- check your connection and try again.");
    logEvent("error", "Failed to start session on server after retries", null, "⚠️");
    return;
  }
  const ws = new WebSocket(wsUrl());
  websocket = ws;

  ws.onopen = () => {
    if (websocket !== ws) return; // a newer socket superseded this one
    setConnected(true);
    logEvent(
      "incoming",
      "WebSocket connected",
      { userId, sessionId, campaign: campaignSelect.value },
      "🔌",
    );
  };

  ws.onmessage = (event) => {
    if (websocket !== ws) return;
    const ev = JSON.parse(event.data);

    if (ev.type === "server_config") {
      reconnectSameSession = Boolean(ev.reconnect_same_session);
      if (typeof ev.auto_close_delay_s === "number") {
        autoCloseDelayS = ev.auto_close_delay_s;
      }
      logEvent(
        "incoming",
        `Server policy: reconnect_same_session=${reconnectSameSession}, auto_close_delay_s=${autoCloseDelayS}`,
        ev,
        "⚙️"
      );
      return;
    }

    if (ev.type === "live_ready") {
      // Reset retry budget only when session reaches a verified stable state
      reconnectAttempts = 0;
      logEvent("incoming", "Gemini Live model connected and ready", ev, "🟢");
      setPhase("listening", "Listening — you can speak now");
      armVad();
      micActive = true;
      startSpeechRecognition();
      return;
    }

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

  ws.onclose = (event) => {
    // Ignore close events for sockets we've already replaced (reconnects).
    if (websocket !== ws) return;
    setConnected(false);
    logEvent("error", "WebSocket closed", { code: event?.code, reason: event?.reason }, "🔌");

    // Session not found on server (e.g. 4404 from Vertex AI or nonexistent session).
    // Reset session ID and do not enter reconnection backoff loop on a dead session!
    if (event?.code === 4404) {
      logEvent("error", "Session expired or not found on server", null, "❌");
      newSessionId();
      reconnectAttempts = 0;
      stopSpeechRecognition();
      stopMicStreaming();
      agentTurnActive = false;
      setPhase("error", "Session expired or not found. Tap the mic to start again.");
      return;
    }

    // Gemini Live connection timed out during cold start (code 4430).
    // The server tore down the hung connection and freed the session slot.
    // Reset session ID and show a clear message instead of entering reconnection loop.
    if (event?.code === 4430) {
      logEvent("error", "Gemini Live connection timed out", null, "❌");
      newSessionId();
      reconnectAttempts = 0;
      stopSpeechRecognition();
      stopMicStreaming();
      agentTurnActive = false;
      setPhase("error", "Couldn't connect to Gemini Live — please try again.");
      return;
    }

    // AIML-2806: If rejected because the lock is temporarily held by previous teardown
    // (code 4409 session_busy), back off and retry same session.
    if (event?.code === 4409) {
      logEvent("warning", "Session slot busy on server; retrying...", null, "⏳");
      setTimeout(() => {
        connectWebsocket();
      }, 1000);
      return;
    }

    // Inactivity timeout (reason: "inactivity_timeout"): session closed cleanly
    // by SilenceWatchdog. Do NOT enter reconnection backoff loop. Cleanly reset state.
    // Note: stopMicStreaming only halts mic input; audioPlayerNode is left untouched
    // so any queued goodbye audio finishes playback through Web Audio cleanly.
    // Code 1000 is intentionally not checked alone to avoid intercepting normal stream ends.
    if (event?.reason === "inactivity_timeout") {
      logEvent("incoming", "Session closed due to inactivity", null, "⏱️");
      newSessionId();
      reconnectAttempts = 0;
      stopSpeechRecognition();
      stopMicStreaming();
      agentTurnActive = false;
      setPhase("idle", "Session ended due to inactivity. Tap the mic to start again.");
      return;
    }

    // Attempt WebSocket reconnection with exponential backoff.
    const backoffs = [800, 1200, 2000, 3500];
    if (reconnectAttempts < backoffs.length) {
      setPhase("processing", "Connection lost. Reconnecting...");
      setTimeout(() => {
        reconnectAttempts++;
        if (!reconnectSameSession) {
          newSessionId(); // fresh session so the server starts a clean Gemini Live session
        }
        connectWebsocket();
      }, backoffs[reconnectAttempts]);
      return;
    }

    // Don't leave the UI stuck on "agent responding…" if the stream dropped
    // mid-turn. Recover to a usable state (unless we already finished).
    stopSpeechRecognition();
    stopMicStreaming();
    agentTurnActive = false;
    if (phase !== "saved" && phase !== "processing") {
      setPhase("error", "Connection dropped. Press the mic to start again.");
    }
  };

  ws.onerror = (e) => {
    if (websocket !== ws) return;
    setConnected(false);
    logEvent("error", "WebSocket error", { type: e.type }, "⚠️");
  };
}

// ---------------------------------------------------------------------------
// ADK event handling
// ---------------------------------------------------------------------------
function handleAdkEvent(ev) {
  // Display-only: track the model's own reported token usage for the cost
  // estimate. Does not affect any agent/session/execution behavior.
  if (agentResponseWatchdog) {
      clearTimeout(agentResponseWatchdog);
      agentResponseWatchdog = null;
  }
  if (ev.usageMetadata) applyUsageMetadata(ev.usageMetadata);

  // Console summary
  let summary = "event";
  let emoji = "📨";
  if (ev.turnComplete) { summary = "Turn complete"; emoji = "✅"; }
  else if (ev.interrupted) { summary = "Interrupted"; emoji = "⏸️"; }
  else if (ev.inputTranscription) { summary = `Input: "${ev.inputTranscription.text || ""}"`; emoji = "📝"; }
  else if (ev.outputTranscription) { summary = `Output: "${ev.outputTranscription.text || ""}"`; emoji = "🗣️"; }
  else if (ev.content && ev.content.parts) {
    const p = ev.content.parts;
    if (p.some((x) => x.functionCall)) { const fc = p.find((x) => x.functionCall).functionCall; summary = `Tool call: ${fc.name}`; emoji = "🛠️"; }
    else if (p.some((x) => x.functionResponse)) { const fr = p.find((x) => x.functionResponse).functionResponse; summary = `Tool result: ${fr.name}`; emoji = "📦"; }
    else if (p.some((x) => x.inlineData)) { summary = "Audio chunk"; emoji = "🔊"; }
    else if (p.some((x) => x.text)) { summary = `Text: "${(p.find((x) => x.text).text || "").slice(0, 60)}"`; emoji = "💭"; }
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
    updateUserCaption(
      ev.inputTranscription.text || "",
      !!ev.inputTranscription.finished
    );
    // The rep just said something real -- arm the mute gate. Whatever the
    // agent says next is suppressed until a real tool call proves it's done
    // guessing (see the `suppressAgentSpeech` declaration above).
    //
    // The gate is lifted only by a real tool call, so any agent turn that is
    // pure speech with NO tool call leaves it armed -- that speech and its
    // caption are dropped, and the session looks like it has hung.
    //
    // KNOWN GAP (predates the guided removal, not fixed here): behavioral_rules
    // .yaml instructs exactly such a turn -- "if the transcription is empty or
    // contains no speech, DO NOT call stage_visit_notes; tell them you couldn't
    // hear anything and ask them to record again". So the one message designed
    // to recover from a no-speech turn is the one message this gate swallows.
    // Lifting it needs a second trigger (a turn_complete carrying speech but no
    // tool call, or a timeout); that is a behaviour change and wants its own
    // ticket.
    //
    // This used to be conditional on agent_mode because the retired guided
    // flow had many pure-speech turns. Unconditional is right for the one
    // remaining flow -- it just isn't the guarantee the old comment claimed.
    if (
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
          if (committed) hasDeliveredClosingAudio = true;
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
        if (committed) hasDeliveredClosingAudio = true;
      }
    }
  }

  if (ev.outputTranscription && ev.outputTranscription.text && committed) {
    hasDeliveredClosingAudio = true;
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
      // If notes were committed and agent has not yet delivered the spoken closing statement,
      // this turnComplete is for the commit_visit_notes tool response execution itself!
      // Do NOT close the socket yet -- let the agent speak the closing statement aloud.
      if (awaitingClosingAudio && !hasDeliveredClosingAudio) {
        logEvent("status", "Notes committed; waiting for agent closing speech...", null, "⏳");
        // Safety watchdog: if agent remains silent for 6s, start countdown anyway
        setTimeout(() => {
          if (committed && !autoCloseTimer && phase !== "idle") {
            startAutoCloseCountdown(autoCloseDelayS);
          }
        }, 6000);
        return;
      }

      // Agent has delivered closing speech (or safety fallback tripped) ->
      // start the graceful auto-close countdown.
      awaitingClosingAudio = false;
      if (!autoCloseTimer) {
        startAutoCloseCountdown(autoCloseDelayS);
      }
      return;
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
  // Stop streaming while the agent speaks. This is the turn boundary that
  // matters most for the tail flush -- the rep just stopped talking, so the end
  // of their last word is exactly what is sitting in the resampler's buffer.
  stopMicStreaming();
  stopSpeechRecognition(); // don't transcribe the agent's own playback
  levelFill.style.width = "0%";
  silenceCountdown.textContent = "agent responding…";
  silenceCountdown.classList.remove("counting");
  setPhase("processing");
}

function handleFunctionCall(fc) {
  if (fc.name === "stage_visit_notes") {
    const args = fc.args || {};
    renderPayload(args);
    payloadStatus.textContent = "staged";
    payloadStatus.className = "badge";
  } else if (fc.name === "commit_visit_notes") {
    payloadStatus.textContent = "committing…";
  }
}

function handleFunctionResponse(fr) {
  const resp = fr.response || {};
  if (fr.name === "stage_visit_notes") {
    // Confirmation text is spoken by the model; surface it in the log too.
    if (resp.confirmation_text) {
      logEvent("incoming", `Confirmation: ${resp.confirmation_text}`, resp, "🗣️");
    }
    // The actual phase switch to "confirm" happens on turnComplete (after the
    // model has finished speaking the confirmation aloud).
  } else if (fr.name === "commit_visit_notes") {
    // A commit can be refused for several reasons, each with its own status:
    // turn_guard ("error"), planned-topic coverage ("blocked"), campaign-rule
    // violation ("rejected") -- and more may be added. Matching status strings
    // means a new refusal silently falls through to the saved state and the UI
    // claims "Saved to CRM" for a record that was never written. Test for the
    // only thing that actually proves a CRM write instead: a record id.
    //
    // Output2 has no crm_record_id -- session_id is the only identifier
    // (see schemas.CommitResult). Success/failure must be read from
    // resp.status, which tools.py always sets ("success" | "blocked" | "error").
    if (resp.status !== "success") {
      const why = resp.error || resp.status || "unknown";
      const missing = Array.isArray(resp.missing_topics)
        ? resp.missing_topics
        : [];
      const detail = missing.length
        ? `${why} (still needed: ${missing.join(", ")})`
        : why;
      logEvent("incoming", `Commit refused: ${detail}`, resp, "🚫");
      payloadStatus.textContent = "staged";
      payloadStatus.className = "badge";
      return;
    }
    // The card was already populated by stage_visit_notes' mega-payload, so
    // there is nothing to render here -- commit only reveals it.

    // Setting committed here also matters for the mic: otherwise
    // turnComplete's fallback branch would just re-arm it forever.

    committed = true;
    awaitingClosingAudio = true;
    hasDeliveredClosingAudio = false;

    // Stop mic streaming so rep background sounds do not interrupt the closing audio
    stopMicStreaming();
    micActive = false;

    payloadCard.classList.remove("hidden");
    // Output2 has no crm_record_id -- display session_id instead, the one
    // identifier Output2 actually carries.
    if (resp.session_id) pCrmId.textContent = resp.session_id;
    payloadStatus.textContent = "committed";
    payloadStatus.className = "badge committed";
    saveButton.disabled = true;
    changeButton.disabled = true;
    if (resp.closing_statement) {
      logEvent("incoming", `Closing: ${resp.closing_statement}`, resp, "🗣️");
    }
  }
}

// Same rule as the server's coverage check (notes_workflow._topic_key): a
// planned topic is covered only by a row with its own label, ignoring case
// and spacing -- an off-plan "Plumbing leak" does not cover "Plumbing".
function topicKey(label) {
  return (label || "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

function topicsMatch(a, b) {
  const x = topicKey(a);
  return x !== "" && x === topicKey(b);
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
    const icon = state === "covered" ? "✓" : state === "skipped" ? "—" : "…";
    chip.textContent = `${icon} ${label}`;
    pCoverage.appendChild(chip);
  });
}

function renderPayload(args) {
  payloadCard.classList.remove("hidden");
  // A newly staged record has not been written to the CRM, so it has no record
  // id. Clear any id left over from a previous commit in this page session --
  // otherwise the card shows a "staged" badge next to a real CRM id.
  pCrmId.textContent = "—";

  pEventType.textContent = args.event_type || "—";
  pSummary.textContent = args.executive_summary || "—";

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
        code != null ? `${code}${label ? " — " + label : ""}` : "—";
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

  const transcript = args.raw_transcript_backup || "—";
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

function startAutoCloseCountdown(seconds) {
  if (autoCloseTimer) {
    clearInterval(autoCloseTimer);
    autoCloseTimer = null;
  }
  let remaining = seconds;
  setPhase("saved");
  silenceCountdown.classList.remove("counting");
  silenceCountdown.textContent = `saved (closing in ${remaining}s)`;

  autoCloseTimer = setInterval(() => {
    remaining--;
    if (remaining > 0) {
      silenceCountdown.textContent = `saved (closing in ${remaining}s)`;
    } else {
      clearInterval(autoCloseTimer);
      autoCloseTimer = null;
      logEvent("status", "Auto-closing session after save", null, "🏁");
      finishSession();
    }
  }, 1000);
}

function finishSession() {
  if (autoCloseTimer) {
    clearInterval(autoCloseTimer);
    autoCloseTimer = null;
  }
  awaitingClosingAudio = false;
  hasDeliveredClosingAudio = false;

  setPhase("saved");
  stopMicStreaming();
  stopSpeechRecognition();
  silenceCountdown.textContent = "done";
  silenceCountdown.classList.remove("counting");
  levelFill.style.width = "0%";
  markRunMetricsDone(); // "CRM saved successfully" moment -> stop the run timer

  // Unlock the topic list for the rep's NEXT visit.
  //
  // startDictation locks it and only endSession unlocked it again, so after a
  // successful save the checkboxes stayed disabled and the rep had to reload
  // the page to plan a different call. That was survivable while a second
  // dictation in the same page wasn't really a supported flow -- but rotating
  // session_id below is precisely what makes it one, so the lock has to lift
  // here too.
  setPlanningEnabled(true);

  // Retire this dictation's session id now that the record is committed.
  //
  // Server-side session state is keyed by session id, and the commit result in
  // particular is sticky: reusing the id for the rep's next visit of the shift
  // makes the next commit replay THIS visit's result, so the agent says "saved"
  // and reads back this CRM id while nothing for the new visit was staged.
  // A fresh id makes that state empty by construction.
  //
  // The campaign-change and reconnect paths already do exactly this. Cost: the
  // next dictation pays Vertex's cold-start handshake again, which is why the
  // socket was being held open between dictations -- worth it against silently
  // losing a visit.
  //
  // Note this guarantee now rests on the client alone: the retired guided
  // flow's capture_dictation also cleared the state server-side, and the
  // implicit flow has no equivalent entry-point tool.
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    closeWebsocketIntentionally();
  }
  newSessionId();
}

// ---------------------------------------------------------------------------
// Audio + client-side VAD
// ---------------------------------------------------------------------------
async function ensureAudio() {
  if (audioStarted) return;

  // Check the context ONCE, before touching any audio API.
  //
  // Three separate things this app needs are secure-context-only: getUserMedia,
  // AudioWorklet, and crypto.randomUUID. Guarding only the mic was not enough --
  // the PLAYER worklet is constructed first, so on plain HTTP the rep got
  // "Cannot read properties of undefined (reading 'addModule')" from
  // audioContext.audioWorklet before the mic guard was ever reached. Observed
  // on the VDI over http://<lan-ip>:8000, 2026-08-20.
  //
  // Deliberately NOT at module load: the page must still render over plain HTTP
  // (that is the A7 fix), and this is the first point where the missing
  // capability actually matters.
  if (!window.isSecureContext) {
    throw new Error(
      "Microphone and audio playback require HTTPS (or localhost). This page " +
        "is served over plain HTTP, so the browser blocks both. Serve the app " +
        "over HTTPS."
    );
  }

  const [pNode] = await startAudioPlayerWorklet();
  audioPlayerNode = pNode;
  const [rNode, , stream, flush] = await startAudioRecorderWorklet(
    audioRecorderHandler
  );
  audioRecorderNode = rNode;
  micStream = stream;
  audioRecorderFlush = flush;
  audioStarted = true;
}

// Stop streaming mic audio to the server. Always use this instead of assigning
// `micActive = false` directly.
//
// The resampler batches ~20ms of samples before emitting a chunk, so when the
// rep stops talking the trailing edge of their last word is still sitting in
// that partial buffer. Clearing the gate first would make audioRecorderHandler
// drop it -- the model never hears the end of the sentence, and those stale
// samples get spliced onto the front of the next turn. So flush while the gate
// is still open, then close it.
function stopMicStreaming() {
  if (micActive && audioRecorderFlush) audioRecorderFlush();
  micActive = false;
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
      // Reset the streak BEFORE stopping: stopMicStreaming flushes the
      // resampler, which re-enters this handler with the tail chunk. Clearing
      // first means that chunk starts a fresh streak instead of tripping this
      // same branch a second time.
      highEnergyStreak = 0;
      stopMicStreaming();
      agentTurnActive = false;
      setPhase("error", "Audio distortion detected. Please check your microphone and try again.");
      return;
    }
  } else {
    // Reset on any chunk that falls below the threshold — normal speech has
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
    silenceCountdown.textContent = "🎙️ speaking…";
    silenceCountdown.classList.remove("counting");
  } else if (hadSpeech && now - speechStartTs > MIN_SPEECH_MS) {
    const silentFor = now - lastVoiceTs;
    if (silentFor >= SILENCE_MS) {
      // Informational only. Do NOT stop the mic here -- the server's automatic
      // VAD needs to keep RECEIVING audio (including this trailing silence) to
      // detect end-of-speech and finalize the turn. Stopping the stream now
      // starves the server VAD and the turn never completes. The mic is closed
      // by beginAgentResponse() once the agent actually starts replying.
      silenceCountdown.textContent = "pause detected — wrapping up…";
      silenceCountdown.classList.remove("counting");
    } else {
      const remaining = Math.max(0, SILENCE_MS - silentFor);
      silenceCountdown.textContent = `pausing… ${(remaining / 1000).toFixed(1)}s`;
      silenceCountdown.classList.add("counting");
    }
  }
}


function endSession() {
  if (autoCloseTimer) {
    clearInterval(autoCloseTimer);
    autoCloseTimer = null;
  }
  awaitingClosingAudio = false;
  hasDeliveredClosingAudio = false;

  // Stop streaming and tear down the live session.
  stopMicStreaming();
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
  if (autoCloseTimer) {
    clearInterval(autoCloseTimer);
    autoCloseTimer = null;
    finishSession();
  }
  if (selectedTopics.length === 0) {
    setPhase("error", "Select at least one planned topic before you start.");
    return;
  }
  resetForNewDictation();
  setPlanningEnabled(false);
  startRunTimer(); // rep clicked the mic to start speaking -- start the clock
  try {
    await ensureAudio();
  } catch (err) {
    // Unhandled, this left the UI frozen with planning disabled and the run
    // timer running, and no visible reason. The realistic cause is a denied
    // mic permission or a non-HTTPS deployment (see startAudioRecorderWorklet).
    console.error("Audio init failed:", err);
    stopRunTimer();
    setPlanningEnabled(true);
    setPhase("error", err.message || "Could not start the microphone.");
    return;
  }
  if (!websocket || websocket.readyState !== WebSocket.OPEN) {
    // Drop any stale (closing/closed) socket before reconnecting so we never
    // wait on a dead connection.
    closeWebsocketIntentionally();
    setPhase("processing", "Connecting to Gemini Live…");
    await connectWebsocket();
    const opened = await waitForOpen(8000);
    if (!opened) {
      setPhase("error", "Couldn't connect. Press the mic to try again.");
      resetRunMetrics(); // never actually started talking to the agent
      return;
    }
  }

  // Keep mic inactive and status in "processing" until Gemini Live signals it is ready.
  // This prevents any microphone audio from buffering before the upstream TLS handshake completes.
  micActive = false;
  setPhase("processing", "Connecting to Gemini Live…");
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
    // "Done dictating" — stop sending mic audio but keep the WebSocket OPEN
    // so the model can process the buffered audio in the server's
    // LiveRequestQueue. DO NOT call endSession() here: closing the socket
    // kills the Vertex AI Live session before it can respond.
    //
    // WHY THIS MATTERS: Vertex AI's cold-start handshake takes 6-10 seconds.
    // During that time, audio chunks are buffered server-side. Closing the
    // socket immediately (old behaviour) always raced against the handshake
    // and killed the session before the model saw the audio — producing the
    // "1000 None / client disconnected" error observed in logs.
    //
    // New behaviour: silence the mic, show "processing", and let the 30-second
    // watchdog close the connection only if the model genuinely stalls.
    stopMicStreaming();
    stopSpeechRecognition();
    levelFill.style.width = "0%";
    silenceCountdown.classList.remove("counting");
    silenceCountdown.textContent = "processing…";
    setPhase("processing", "Processing your notes — please wait…");
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
    logEvent("outgoing", `Text: ${text}`, null, "💬");
    setPhase("processing", "Processing your response…");
  }
}

function resetForNewDictation() {
  // Narrow reset: keeps audio context and connection alive, clears payload
  committed = false;
  recordingBuffers = [];
}

function resetSession() {
  if (autoCloseTimer) {
    clearInterval(autoCloseTimer);
    autoCloseTimer = null;
  }
  awaitingClosingAudio = false;
  hasDeliveredClosingAudio = false;
  stopMicStreaming();
  committed = false;
  suppressAgentSpeech = false;
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

setPhase("idle");
loadPlannedTopics();

// ---------------------------------------------------------------------------
// Dev/test hook — exposes key internal functions on window.__snTest so they
// can be called from the browser DevTools console even though this file runs
// as an ES module (module scope is private and unreachable from the console).
//
// Usage (DevTools console):
//   window.__snTest.simulateAgentStall()   → triggers watchdog test (Test 3)
//   window.__snTest.simulateToolError()    → injects a tool-error banner (Test 4)
//   window.__snTest.getPhase()             → returns current phase string
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
