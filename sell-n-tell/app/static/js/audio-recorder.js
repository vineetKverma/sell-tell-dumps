/**
 * Audio Recorder Worklet
 *
 * Captures the microphone and emits 16 kHz, 16-bit, mono PCM in ~20ms chunks,
 * which is exactly what the server labels the blob as
 * (`audio/pcm;rate=16000` in main.py) and what the Gemini Live API expects.
 *
 * The resampling here is NOT optional. `new AudioContext({sampleRate})` is a
 * request, not a guarantee: on many Windows machines the context comes back at
 * 44100 or 48000 regardless. Forwarding those samples while telling the Live
 * API they are 16 kHz means sending ~3x more audio per second than real time,
 * and the server eventually kills the socket with:
 *
 *     APIError: 1011 Input data processing failed. This is likely due to the
 *     client sending data too fast. Please review your flow control mechanism.
 *
 * So we read the rate the context ACTUALLY got and resample down to 16 kHz.
 */

let micStream;

const TARGET_SAMPLE_RATE = 16000;
// ~20ms per chunk. The worklet hands us 128-frame buffers (~2.7ms at 48kHz),
// and sending each one individually means ~375 tiny WebSocket messages per
// second -- mostly framing overhead, and bursty through a tunnel. Batching to
// 20ms keeps latency imperceptible while cutting message count ~8x.
const CHUNK_SAMPLES = (TARGET_SAMPLE_RATE * 20) / 1000; // 320 samples = 640 bytes

export async function startAudioRecorderWorklet(audioRecorderHandler) {
  // Ask for 16 kHz. We may not get it -- see below.
  const audioRecorderContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
  const inputRate = audioRecorderContext.sampleRate;
  console.log(
    "AudioContext sample rate:",
    inputRate,
    inputRate === TARGET_SAMPLE_RATE
      ? "(native 16kHz, pass-through)"
      : `(resampling ${inputRate} -> ${TARGET_SAMPLE_RATE})`
  );

  // Load the AudioWorklet module
  const workletURL = new URL("./pcm-recorder-processor.js", import.meta.url);
  await audioRecorderContext.audioWorklet.addModule(workletURL);

  // Request access to the microphone. Echo cancellation + noise suppression
  // are important here: the agent speaks its confirmation aloud while the mic
  // is (re)opened for the rep's "save / change" reply, so without AEC the mic
  // captures the agent's own playback and feeds garbage back to the model.
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const source = audioRecorderContext.createMediaStreamSource(micStream);

  // Create an AudioWorkletNode that uses the PCMProcessor
  const audioRecorderNode = new AudioWorkletNode(
    audioRecorderContext,
    "pcm-recorder-processor"
  );

  const resampler = createResampler(inputRate, audioRecorderHandler);

  // Connect the microphone source to the worklet.
  source.connect(audioRecorderNode);
  audioRecorderNode.port.onmessage = (event) => {
    resampler.push(event.data);
  };
  return [audioRecorderNode, audioRecorderContext, micStream];
}

/**
 * Stop the microphone.
 */
export function stopMicrophone(micStream) {
  micStream.getTracks().forEach((track) => track.stop());
  console.log("stopMicrophone(): Microphone stopped.");
}

/**
 * Streaming linear-interpolation resampler + Int16 chunk batcher.
 *
 * Linear interpolation (not naive decimation) because the common input rates
 * don't divide evenly: 44100/16000 = 2.75625. Dropping to "every Nth sample"
 * only works for integer ratios and would drift and alias badly at 44.1kHz.
 *
 * State is carried ACROSS worklet buffers -- `cursor` keeps its fractional
 * position and `prevSample` holds the last input sample -- so no samples are
 * lost or duplicated at buffer boundaries, which would otherwise produce a
 * periodic click at ~375 Hz.
 */
function createResampler(inputRate, onChunk) {
  const ratio = inputRate / TARGET_SAMPLE_RATE;
  let cursor = 0; // fractional read position, in input samples
  let prevSample = 0; // last sample of the previous buffer (index -1)
  let out = new Int16Array(CHUNK_SAMPLES);
  let outLen = 0;

  function emit(sample) {
    // Clamp before scaling: getUserMedia with autoGainControl can transiently
    // exceed +/-1.0, and Int16Array wraps on overflow, turning a loud syllable
    // into full-scale noise.
    const s = sample < -1 ? -1 : sample > 1 ? 1 : sample;
    out[outLen++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    if (outLen === CHUNK_SAMPLES) {
      onChunk(out.buffer);
      out = new Int16Array(CHUNK_SAMPLES);
      outLen = 0;
    }
  }

  return {
    push(input) {
      const n = input.length;
      if (n === 0) return;
      for (;;) {
        const i = Math.floor(cursor);
        // Need input[i+1] to interpolate; if it's past the end of this buffer,
        // stop and pick up here on the next one.
        if (i + 1 >= n) break;
        const frac = cursor - i;
        const s0 = i < 0 ? prevSample : input[i];
        const s1 = input[i + 1];
        emit(s0 + (s1 - s0) * frac);
        cursor += ratio;
      }
      prevSample = input[n - 1];
      cursor -= n; // rebase into the next buffer's coordinates (>= -1)
    },
  };
}
