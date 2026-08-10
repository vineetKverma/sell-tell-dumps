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
const userId = "rep-" + Math.random().toString(36).substring(7);
// Regenerated whenever the campaign or planned topics change so the backend
// seeds a fresh session with the new selection (in-memory sessions are keyed
// by id and their seeded state is otherwise sticky).
let sessionId = "sess-" + Math.random().toString(36).substring(7);
function newSessionId() {
  sessionId = "sess-" + Math.random().toString(36).substring(7);
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

// Live transcription buffers (accumulate streaming deltas per speaker)
let liveUserText = "";
let liveAgentText = "";

// Disposition code -> label map (from dynamic config)
let dispositionLabels = {};

// Pre-call planning: catalog of selectable topics + the rep's selection.
let plannedTopicCatalog = [];
let selectedTopics = []; // array of label strings

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
const consoleContent = document.getElementById("consoleContent");
const clearConsoleBtn = document.getElementById("clearConsole");

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
  if (websocket && websocket.readyState === WebSocket.OPEN) websocket.close();
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
  if (websocket && websocket.readyState === WebSocket.OPEN) websocket.close();
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
    handleAdkEvent(ev);
  };

  ws.onclose = () => {
    // Ignore close events for sockets we've already replaced (reconnects).
    if (websocket !== ws) return;
    setConnected(false);
    logEvent("error", "WebSocket closed", null, "ðŸ”Œ");
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
    if (committed) {
      // Notes saved -> end the session.
      finishSession();
    } else if (!payloadCard.classList.contains("hidden")) {
      // Agent finished speaking the confirmation -> re-open the mic so the rep
      // can simply say "Save" or a correction.
      enterConfirmPhase();
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
  }
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
  } else if (fr.name === "commit_visit_notes" || fr.name === "commit_guided_notes") {
    // A commit can be refused for several reasons, each with its own status:
    // turn_guard ("error"), planned-topic coverage ("blocked"), campaign-rule
    // violation ("rejected") -- and more may be added. Matching status strings
    // means a new refusal silently falls through to the saved state and the UI
    // claims "Saved to CRM" for a record that was never written. Test for the
    // only thing that actually proves a CRM write instead: a record id.
    if (!resp.crm_record_id) {
      const why = resp.error || resp.status || "unknown";
      const missing = Array.isArray(resp.missing_topics)
        ? resp.missing_topics
        : [];
      const detail = missing.length
        ? `${why} (still needed: ${missing.join(", ")})`
        : why;
      logEvent("incoming", `Commit refused: ${detail}`, resp, "\u{1F6AB}");
      // Nothing was saved: keep the record staged and leave the rep in the
      // confirm phase so they can answer the agent and try again.
      payloadStatus.textContent = "staged";
      payloadStatus.className = "badge";
      return;
    }
    // Guided flow never populates the payload card (it has no single
    // mega-payload staging step), so mark it visible here too, otherwise
    // turnComplete's fallback branch would just re-arm the mic forever.
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
  pCrmId.textContent = "—";
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

  pTranscript.textContent = args.raw_transcript_backup || "â€”";
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
  if (!micActive || !websocket || websocket.readyState !== WebSocket.OPEN) return;

  // Stream the chunk to the server.
  websocket.send(pcmData);

  // --- Client-side energy VAD ---
  const int16 = new Int16Array(pcmData);
  let sum = 0;
  for (let i = 0; i < int16.length; i++) {
    const v = int16[i] / 32768;
    sum += v * v;
  }
  const rms = Math.sqrt(sum / Math.max(int16.length, 1));
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
  if (websocket && websocket.readyState === WebSocket.OPEN) websocket.close();
  silenceCountdown.textContent = "VAD idle";
  silenceCountdown.classList.remove("counting");
  levelFill.style.width = "0%";
  // A finished/ended session can't reuse its seeded state -> fresh id next run.
  newSessionId();
  setPlanningEnabled(true);
  setPhase("idle");
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
  await ensureAudio();
  if (!websocket || websocket.readyState !== WebSocket.OPEN) {
    // Drop any stale (closing/closed) socket before reconnecting so we never
    // wait on a dead connection.
    if (websocket) {
      try { websocket.close(); } catch (_) { /* no-op */ }
      websocket = null;
    }
    setPhase("processing", "Connectingâ€¦");
    connectWebsocket();
    const opened = await waitForOpen(8000);
    if (!opened) {
      setPhase("error", "Couldn't connect. Press the mic to try again.");
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
  if (phase === "listening" || phase === "confirm") {
    // End the live session.
    endSession();
  } else {
    startDictation();
  }
});

saveButton.addEventListener("click", () => sendText("Save it."));
changeButton.addEventListener("click", () => {
  const change = prompt("What should I change? (e.g. 'change the event type to a phone call')");
  if (change) sendText(change);
});

function sendText(text) {
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    addMessage(text, "user");
    websocket.send(JSON.stringify({ type: "text", text }));
    logEvent("outgoing", `Text: ${text}`, null, "ðŸ’¬");
    setPhase("processing", "Processing your responseâ€¦");
  }
}

function resetForNewDictation() {
  committed = false;
}

function resetSession() {
  micActive = false;
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
