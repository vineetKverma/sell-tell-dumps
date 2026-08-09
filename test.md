Agentic AI Voice Notes Logger — Backend Architecture & ADK Workflow
This document outlines the technical architecture of the Voice Notes Logger backend, detailing how the FastAPI server bridges the frontend WebSockets to the Google Agent Development Kit (ADK) and Vertex AI's Gemini Live API.

1. System Overview
The system is a real-time, bi-directional audio pipeline that enables hands-free CRM data extraction. It relies on the Agent Development Kit (ADK) to orchestrate the LLM and tool execution, wrapping the Gemini Live API with a deterministic, structured workflow.

Frontend: Vanilla JS (app.js) handling getUserMedia, local VAD (Voice Activity Detection), distortion detection, and WebSocket streaming.

Backend: FastAPI handling REST endpoints (for config/DB logic) and WebSocket routing.

Agent Orchestrator: Google ADK Runner managing the gemini-live-2.5-flash-native-audio model on Vertex AI.

Database/State: A simulated CRM backend (db_interface.py) maintaining session state across tool calls.

2. The ADK Agent Workflow
The core intelligence is defined in app/voice_notes_agent/agent.py. The agent is designed to be highly deterministic and strictly controlled.

Dynamic Context Injection (before_agent_callback)
We avoid hardcoding prompts. At the start of every session:

The WebSocket URL accepts query parameters like campaign_type and planned_topics.

The ADK triggers the before_agent_callback (load_campaign_config).

This callback makes an HTTP request to our own API (/api/v1/config/agent-schema) to fetch the campaign's specific system instructions, allowed event types, and the disposition code registry.

The config is saved into the ADK CallbackContext.state and merged into the base behavioral rules via the dynamic voice_notes_instruction provider.

Deterministic Constraint
To force the model to behave as a data-extraction pipeline rather than a conversational chatbot, we apply strict generation parameters:

temperature=0.1

top_p=0.8

The "Mega-Payload" Tool Strategy
Instead of traditional conversational ping-pong, the agent is instructed to listen in silence and eventually output exactly one massive function call to stage_visit_notes. This payload contains the full CRM record, executive summaries, and all extracted topics matching the user's pre-selected planned_topics.

3. Streaming Architecture (WebSocket Bridge)
The live streaming logic lives in app/main.py under the /ws/{user_id}/{session_id} endpoint.

Audio Ingestion (upstream_task)
The browser streams raw Int16 PCM audio chunks (16kHz) to the WebSocket.

The FastAPI server reads these chunks and pushes them into an ADK LiveRequestQueue.

Vertex AI Cold-Start Buffering: Because establishing a connection to Vertex AI (us-central1) can take 6-10 seconds, the LiveRequestQueue acts as a crucial buffer. The client can start speaking immediately, and the audio is queued server-side until the ADK Runner successfully opens the stream to the model.

Agent Response & Tool Execution (downstream_task)
Once the user stops speaking (detected by Server VAD of 2000ms), the ADK evaluates the stream.

The model emits a function call (stage_visit_notes).

The ADK intercepts this, executes the local Python function in app/voice_notes_agent/tools.py, and posts the data to the mock CRM database (db_interface.py).

The tool returns a confirmation_text string to the ADK.

The ADK feeds this tool response back to the Gemini Live model.

The model synthesizes the confirmation into native TTS audio and streams it back to the ADK.

The ADK yields AgentAudioEvent chunks, which FastAPI serializes and pushes down the WebSocket to the browser for playback.

4. State Machine & Execution Flow
The full lifecycle of a standard interaction works like this:

Connect: Client opens WebSocket. ADK initializes the agent, fetches dynamic schema, and starts the Vertex AI handshake.

Dictate: Client streams audio. ADK buffers and forwards it to Vertex AI.

Process: User stops dictating (or presses Stop). LiveRequestQueue finishes sending audio. Model analyzes the speech against the schema.

Stage: Model invokes stage_visit_notes. Tool validates against planned_topics and returns a dynamic confirmation text (e.g., "I staged the notes, but you missed topic X. What happened?").

Confirm/Coverage: Model reads the confirmation text out loud via TTS.

Finalize: The user speaks their final confirmation (e.g., "Save it"). The model invokes commit_visit_notes. The session ends, and the WebSocket is cleanly closed with a closing statement.

5. Key Engineering Safeguards
VAD Cap (2000ms): The Live API limits silence_duration_ms to 2000ms. We configure SERVER_VAD_SILENCE_MS = min(VAD_SILENCE_MS, 2000) to respect this boundary while giving the field rep as much breathing room as possible between sentences.

Frontend Watchdog: To protect against Vertex AI stream stalls, the client implements a 30-second watchdog. If the connection hangs after the user is done dictating, the watchdog kills the socket gracefully instead of hanging indefinitely.

REST Boundary Maintenance: ADK tools never interact with the database directly. They are strictly wrappers that format data and make HTTP POST requests to the FastAPI REST layer (/api/v1/notes/stage). This guarantees that API validation, logging, and state management happen consistently regardless of whether the input is Voice (ADK) or Text (Standard REST).



SalesCast, SalesNotes, Note2Sell, SalesReplay, SellNTell

Current Challenges Faced by FARs
Situation 1: Notes Taken Immediately After Each Visit
A Field Account Representative (FAR) visits a customer and, immediately after the meeting, takes out their laptop or iPhone to capture notes.

Using a laptop:
The FAR manually types the meeting notes, which is time-consuming.

Using an iPhone:
The FAR uses the phone’s voice-to-text feature to dictate notes. However, this approach is often inaccurate, does not summarize the conversation, and still requires manual cleanup.

In both cases, the FAR must then:

Navigate to Salesforce

Open the relevant account

Add the notes in the appropriate fields

Estimated time spent per visit: 5–10 minutes

Before visiting the next customer, the FAR typically reviews pre-call planning notes.

Time taken: ~2 minutes if notes already exist

If additional preparation is needed: ~5 minutes

The FAR then visits the next customer, and the same process repeats throughout the day.

Situation 2: Notes Added at the End of the Day
In this scenario, FARs complete all their customer visits for the day (typically 5–10 visits) and add their notes later, once they return home.

The time required depends on the number of accounts and visits.

FARs often forget key discussion points, action items, or even the correct point of contact.

Important information is lost and sometimes only recovered during the next meeting.

This leads to:

Missed or delayed action items

Lost sales opportunities

Weakened seller–customer relationships

Proposed Solution
Our project introduces a hands-free, voice-first experience that allows FARs to capture and consume meeting notes seamlessly while driving between customer visits.

After a Customer Visit
Once a FAR leaves a customer meeting and starts driving to the next location:

They call a dedicated phone number.

Using Apple CarPlay, in-car Bluetooth, or hands-free calling, they:

State the name of the customer they just met

Freely “dump” their thoughts, including:

What was discussed

Key insights

Action items

Topics to follow up on in the next meeting

Backend Processing
Generative AI processes the voice input.

The conversation is:

Transcribed

Summarized

Structured in the required format

The summarized notes are automatically saved in the relevant Salesforce fields for that customer account.

These notes are:

Instantly accessible to the FAR

Available for manager or leader review

Stored consistently and accurately

Preparing for the Next Customer
Before visiting the next customer, the FAR can:

Call the same number

Mention the customer they are about to visit

Listen to a podcast-style audio summary that includes:

Notes from the previous visit

Open action items

Key discussion points for the upcoming meeting

This allows FARs to prepare while driving, without needing to stop, type, or manually review Salesforce.

Key Benefits
Eliminates manual typing and inaccurate voice-to-text workflows

Saves approximately 45 minutes to 1.5 hours per day

Improves recall of customer conversations and commitments

Strengthens seller–customer relationships

Reduces missed action items and lost sales opportunities

Frees up time for FARs to schedule 1–2 additional customer visits per day

Directly supports increased productivity and revenue contribution

Additionally, summarized notes from all customer visits for the day can be automatically emailed to the FAR, if needed.

Future Enhancements
In future versions, we plan to:

Integrate this capability with Next Best Action (NBA) recommendations

Make the call experience more interactive, allowing FARs to:

Ask follow-up questions

Get AI-driven suggestions on what to discuss next

Cross-question AI recommendations in real time

This interactive loop will:

Improve decision-making in the field

Generate richer feedback

Continuously enhance the underlying AI model

Overall, this solution aims to save time, preserve critical customer insights, strengthen relationships, and ultimately drive higher sales and revenue impact.


