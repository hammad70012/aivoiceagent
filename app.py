import os
import json
import asyncio
import sys
import re
import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 1. CONFIGURATION
load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 

# 2. APP SETUP
app = FastAPI(title="Professional AI Sales", version="21.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. PROFESSIONAL KNOWLEDGE BASE ---
# These prompts are engineered for "Consultative Selling" (High Trust).
BUSINESS_PROMPTS = {
    "consultant": (
        "You are James, a Senior Business Consultant. "
        "TONE: Professional, articulate, calm, and authoritative. "
        "GOAL: Uncover the client's specific needs through active listening. "
        "RULES: "
        "1. Speak in full, clear sentences. "
        "2. Do not ramble. Keep responses under 40 words. "
        "3. Always acknowledge what the user said before pivoting. "
        "4. End every turn with a relevant, open-ended question to guide the conversation. "
        "5. Do NOT use bullet points. Speak naturally."
        "OPENER: 'Hello, this is James. I understand you're looking for some strategic guidance. Could you briefly outline your main challenge?'"
    ),
    "luxury_real_estate": (
        "You are Victoria, a Luxury Real Estate Partner. "
        "TONE: Sophisticated, warm, and polished. "
        "GOAL: Qualify the buyer for a private viewing. "
        "RULES: "
        "1. Use elegant language but keep it conversational. "
        "2. Focus on lifestyle and value, not just price. "
        "3. If asked about price, ask about their comfort range instead. "
        "4. Keep it concise. "
        "OPENER: 'Good morning, this is Victoria. I specialize in high-end properties. Are you looking for a primary residence or an investment portfolio addition?'"
    )
}

# 4. MEMORY MANAGEMENT
local_memory = {}

async def get_chat_history(session_id: str):
    if session_id in local_memory: return local_memory[session_id]
    return []

async def update_chat_history(session_id: str, new_messages: list):
    history = await get_chat_history(session_id)
    history.extend(new_messages)
    # Context window: Keep System + Last 10 turns
    if len(history) > 11: 
        history = [history[0]] + history[-10:]
    local_memory[session_id] = history

# 5. SEAMLESS STREAMING LOGIC
async def stream_conversation(session_id: str, user_text: str, websocket: WebSocket, business_id: str):
    base_prompt = BUSINESS_PROMPTS.get(business_id, BUSINESS_PROMPTS["consultant"])
    
    system_instruction = (
        f"{base_prompt} "
        "IMPORTANT: You are conversing via voice. "
        "Write naturally as if speaking. "
        "Avoid special characters like asterisks or dashes."
    )

    history = await get_chat_history(session_id)
    if not history: 
        history = [{"role": "system", "content": system_instruction}]

    messages = history + [{"role": "user", "content": user_text}]
    full_resp = ""
    
    # Buffer to hold words until we form a complete sentence
    sentence_buffer = ""
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", 
                f"{OLLAMA_URL}/api/chat", 
                json={
                    "model": AI_MODEL, 
                    "messages": messages, 
                    "stream": True,
                    "options": {
                        "temperature": 0.7, # Lower temp = More focused/professional
                        "num_predict": 100,
                        "top_p": 0.9
                    }
                },
                timeout=45.0
            ) as response:
                async for line in response.aiter_lines():
                    if not line: continue
                    try:
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            word = chunk["message"]["content"]
                            full_resp += word
                            sentence_buffer += word
                            
                            # CRITICAL FIX: Only send when we have a COMPLETE sentence.
                            # This prevents the "choppy" start/stop effect.
                            if re.search(r'[.!?:]\s*$', sentence_buffer):
                                # Send the clean sentence
                                await websocket.send_json({
                                    "type": "audio_sentence", 
                                    "content": sentence_buffer.strip()
                                })
                                sentence_buffer = "" # Reset buffer for next sentence
                        
                        if chunk.get("done", False): break
                    except: pass
        
        # If there is any leftover text (e.g. no punctuation at very end), send it.
        if sentence_buffer.strip():
            await websocket.send_json({"type": "audio_sentence", "content": sentence_buffer.strip()})

        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_resp}
        ])
        
        # Signal that the AI is fully done thinking
        await websocket.send_json({"type": "turn_complete"})

    except Exception as e:
        print(f"Error: {e}")
        err = "I apologize, the connection was interrupted. Could you repeat that?"
        await websocket.send_json({"type": "audio_sentence", "content": err})

# 6. WEBSOCKET ROUTE
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, biz: str = Query("consultant")):
    await websocket.accept()
    session_id = str(id(websocket))
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            await stream_conversation(session_id, data, websocket, biz)
    except WebSocketDisconnect:
        if session_id in local_memory: del local_memory[session_id]

# 7. PROFESSIONAL UI
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Professional AI Agent</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8fafc; color: #1e293b; font-family: 'Inter', sans-serif; }
        
        /* Professional Card */
        .card {
            background: white;
            box-shadow: 0 10px 40px -10px rgba(0,0,0,0.1);
            border-radius: 24px;
            overflow: hidden;
            width: 100%;
            max-width: 450px;
            border: 1px solid #e2e8f0;
        }

        .status-dot {
            height: 8px; width: 8px; border-radius: 50%;
            display: inline-block; margin-right: 6px;
        }
        .status-dot.active { background-color: #22c55e; box-shadow: 0 0 10px #22c55e; }
        .status-dot.thinking { background-color: #f59e0b; animation: pulse 1s infinite; }
        .status-dot.offline { background-color: #ef4444; }

        @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
        
        .mic-btn {
            background: #0f172a; color: white;
            width: 70px; height: 70px;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 24px;
            transition: all 0.3s ease;
            cursor: pointer;
            box-shadow: 0 10px 25px rgba(15, 23, 42, 0.2);
        }
        .mic-btn:hover { transform: scale(1.05); background: #1e293b; }
        .mic-btn.listening { background: #ef4444; animation: breathe 2s infinite; }
        .mic-btn.disabled { opacity: 0.5; cursor: not-allowed; }

        @keyframes breathe { 0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); } 70% { box-shadow: 0 0 0 15px rgba(239, 68, 68, 0); } 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); } }

        .wave-container { height: 40px; display: flex; align-items: center; justify-content: center; gap: 3px; }
        .wave-bar { width: 4px; height: 100%; background: #3b82f6; border-radius: 10px; animation: wave 1s infinite ease-in-out; }
        .wave-bar:nth-child(2) { animation-delay: 0.1s; }
        .wave-bar:nth-child(3) { animation-delay: 0.2s; }
        .wave-bar:nth-child(4) { animation-delay: 0.3s; }
        .wave-bar:nth-child(5) { animation-delay: 0.4s; }
        @keyframes wave { 0%, 100% { height: 20%; opacity: 0.5; } 50% { height: 100%; opacity: 1; } }
    </style>
</head>
<body class="h-screen flex items-center justify-center p-4">
    <div id="root"></div>

    <script type="text/babel">
        function App() {
            const [state, setState] = React.useState("idle"); // idle, listening, thinking, speaking
            const [transcript, setTranscript] = React.useState("Click microphone to start");
            const [role, setRole] = React.useState("consultant");
            
            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const synth = window.speechSynthesis;
            const audioQueue = React.useRef([]);
            const isSpeaking = React.useRef(false);
            const silenceTimer = React.useRef(null);

            React.useEffect(() => {
                // Initialize WebSocket
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(`${protocol}${window.location.host}/ws?biz=${role}`);
                
                ws.current.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    
                    if (data.type === "audio_sentence") {
                        // Backend sent a COMPLETE sentence. Add to queue.
                        addToAudioQueue(data.content);
                    } 
                    else if (data.type === "turn_complete") {
                        // AI is done thinking.
                        // We rely on the queue to finish playing.
                    }
                };

                return () => { if (ws.current) ws.current.close(); };
            }, [role]);

            React.useEffect(() => {
                // Initialize Speech Recognition
                if (window.SpeechRecognition || window.webkitSpeechRecognition) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = true;
                    recognition.current.interimResults = true;
                    
                    recognition.current.onstart = () => {
                        if (state !== 'speaking') setState("listening");
                    };

                    recognition.current.onresult = (event) => {
                        // Interrupt AI if user speaks
                        if (isSpeaking.current) {
                            synth.cancel();
                            audioQueue.current = [];
                            isSpeaking.current = false;
                        }

                        let interim = "";
                        let final = "";
                        
                        for (let i = event.resultIndex; i < event.results.length; ++i) {
                            if (event.results[i].isFinal) final += event.results[i][0].transcript;
                            else interim += event.results[i][0].transcript;
                        }

                        const currentText = final || interim;
                        setTranscript(currentText);

                        // Professional Pause Detection (1.2s)
                        if (silenceTimer.current) clearTimeout(silenceTimer.current);
                        
                        if (currentText.trim().length > 0) {
                             silenceTimer.current = setTimeout(() => {
                                submitMessage(currentText);
                            }, 1200); 
                        }
                    };
                }
            }, [state]);

            const submitMessage = (text) => {
                recognition.current.stop();
                setState("thinking");
                ws.current.send(text);
            };

            const addToAudioQueue = (text) => {
                audioQueue.current.push(text);
                playQueue();
            };

            const playQueue = () => {
                if (isSpeaking.current || audioQueue.current.length === 0) return;

                isSpeaking.current = true;
                setState("speaking");
                
                const textToSpeak = audioQueue.current.shift();
                setTranscript(textToSpeak); // Show what AI is saying

                const utter = new SpeechSynthesisUtterance(textToSpeak);
                
                // --- HIGH QUALITY VOICE SELECTION ---
                const voices = synth.getVoices();
                // Prefer Google US or Microsoft Online (High Quality)
                let selectedVoice = voices.find(v => v.name.includes("Google US English"));
                if (!selectedVoice) selectedVoice = voices.find(v => v.name.includes("Zira")); // Good Windows Voice
                if (selectedVoice) utter.voice = selectedVoice;

                utter.rate = 1.05; // Slightly faster than default for professional pacing
                utter.pitch = 1.0;

                utter.onend = () => {
                    isSpeaking.current = false;
                    if (audioQueue.current.length > 0) {
                        playQueue(); // Play next sentence immediately
                    } else {
                        // Queue empty, turn over.
                        setState("idle");
                        // Automatically start listening again for seamless flow
                        startListening();
                    }
                };
                
                synth.speak(utter);
            };

            const startListening = () => {
                try {
                    recognition.current.start();
                    setState("listening");
                    setTranscript("Listening...");
                } catch(e) {
                    // Recognition likely already started
                }
            };

            const toggleMic = () => {
                if (state === "idle" || state === "speaking") {
                    synth.cancel(); // Stop talking
                    isSpeaking.current = false;
                    audioQueue.current = [];
                    startListening();
                } else {
                    recognition.current.stop();
                    setState("idle");
                }
            };

            return (
                <div className="card p-8 flex flex-col items-center">
                    <div className="w-full flex justify-between items-center mb-6">
                        <div className="flex items-center">
                            <span className={`status-dot ${state === 'listening' ? 'active' : (state === 'thinking' ? 'thinking' : 'active')}`}></span>
                            <span className="text-sm font-semibold text-slate-500 uppercase tracking-wide">
                                {state === 'listening' ? 'Online' : state}
                            </span>
                        </div>
                        <select 
                            value={role} 
                            onChange={(e) => setRole(e.target.value)}
                            className="text-xs bg-slate-100 border border-slate-200 rounded-lg px-2 py-1 text-slate-600 outline-none"
                        >
                            <option value="consultant">Business Consultant</option>
                            <option value="luxury_real_estate">Luxury Real Estate</option>
                        </select>
                    </div>

                    <div className="h-32 w-full flex items-center justify-center text-center px-4 mb-8">
                        {state === 'speaking' ? (
                            <div className="wave-container">
                                <div className="wave-bar"></div>
                                <div className="wave-bar"></div>
                                <div className="wave-bar"></div>
                                <div className="wave-bar"></div>
                                <div className="wave-bar"></div>
                            </div>
                        ) : (
                            <p className="text-xl text-slate-800 font-medium leading-relaxed transition-all">
                                "{transcript}"
                            </p>
                        )}
                    </div>

                    <button 
                        onClick={toggleMic}
                        className={`mic-btn ${state === 'listening' ? 'listening' : ''}`}
                    >
                        <i className={`fas fa-${state === 'listening' ? 'microphone' : (state === 'speaking' ? 'stop' : 'microphone')}`}></i>
                    </button>
                    
                    <p className="mt-6 text-slate-400 text-xs">
                        {state === 'thinking' ? 'Processing inquiry...' : 'Tap microphone to speak'}
                    </p>
                </div>
            );
        }
        const root = ReactDOM.createRoot(document.getElementById('root'));
        root.render(<App />);
    </script>
</body>
</html>
    """

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5047, reload=True)
