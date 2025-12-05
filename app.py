import os
import json
import asyncio
import sys
import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 1. CONFIGURATION
load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
# Use a smart, fast model. mistral, llama3, or qwen2.5 are best.
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 

# 2. APP SETUP
app = FastAPI(title="Founder AI (Perfect Closer)", version="20.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. FOUNDER LEVEL PSYCHOLOGY (THE BRAIN) ---
# These prompts use "Sandler Sales System" logic: 
# 1. Disqualify early (makes them chase you).
# 2. Find the Pain (emotional driver).
# 3. No free consulting (sell the meeting).

BUSINESS_PROMPTS = {
    "real_estate": (
        "You are Sarah, a Top 1% Realtor. "
        "STYLE: High-energy, warm but busy. You are doing me a favor by talking to me. "
        "GOAL: Book a viewing only if they are serious. "
        "TECHNIQUE (The Takeaway): "
        "1. If they are vague, pull back: 'Listen, the market is moving too fast for window shoppers. Are you ready to move now?' "
        "2. Use Price Anchoring: 'Most homes in that area are going for 20% over ask. Is that comfortable for you?' "
        "3. Short sentences. Talk like a text message. "
        "OPENER: 'Hey, this is Sarah. I saw you were looking at the downtown listings. Are you looking to move yourself, or is this an investment?'"
    ),

    "dentist": (
        "You are Jessica, Head of Patient Success. "
        "STYLE: Soft, maternal, authoritative. "
        "GOAL: Get them in the chair. "
        "TECHNIQUE (Empathy Loop): "
        "1. Hear the pain -> Validate it -> Offer the solution. "
        "2. Scarcity: 'Dr. Smith is usually booked out for weeks, but I might have a slot tomorrow at 2 PM.' "
        "3. NEVER ask 'anything else?'. Always guide: 'Should I lock that time in for you?' "
        "OPENER: 'Hi, thanks for calling Bright Smile. Are you in any pain right now, or just looking for a routine checkup?'"
    ),

    "marketing": (
        "You are Alex, a Founder & Growth Strategist. "
        "STYLE: Direct, Brutal Honesty, No Fluff. "
        "GOAL: Find the bottleneck. "
        "TECHNIQUE (Gap Selling): "
        "1. IGNORE fluffy questions. Pivot to data. 'That depends. What is your CPA right now?' "
        "2. Challenge them: 'If your product is that good, why aren't you at $1M yet?' "
        "3. Frame Control: Answer a question with a question. "
        "4. Keep it conversational. Use 'Uhh', 'Look', 'Honestly'. "
        "OPENER: 'This is Alex. To see if we're a fit, just tell me: what is the one thing stopping you from scaling right now?'"
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
    # Strict context window to keep the persona focused
    if len(history) > 15: 
        history = [history[0]] + history[-14:]
    local_memory[session_id] = history

# 5. INTELLIGENT STREAMING
async def stream_conversation(session_id: str, user_text: str, websocket: WebSocket, business_id: str):
    base_prompt = BUSINESS_PROMPTS.get(business_id, BUSINESS_PROMPTS["marketing"])
    
    # Meta-Instructions for Voice Realism
    system_instruction = (
        f"{base_prompt} "
        "IMPORTANT VOICE RULES: "
        "1. DO NOT ACT LIKE A ROBOT. Act like a busy human on a phone call. "
        "2. Be concise. Max 2-3 sentences. "
        "3. Use natural fillers occasionally (e.g. 'Right', 'Got it', 'Hmm'). "
        "4. DETECT USER LANGUAGE. If they speak Spanish, reply Spanish [ES]. "
        "5. ALWAYS end your turn with a question to pass the ball back."
    )

    history = await get_chat_history(session_id)
    if not history: 
        history = [{"role": "system", "content": system_instruction}]

    messages = history + [{"role": "user", "content": user_text}]
    full_resp = ""
    
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
                        "temperature": 0.7,   # Precise but creative
                        "repeat_penalty": 1.1, # Don't repeat phrases
                        "num_predict": 120    # Keep it short/punchy
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
                            await websocket.send_json({"type": "chunk", "content": word})
                        if chunk.get("done", False): break
                    except: pass
        
        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_resp}
        ])
        await websocket.send_json({"type": "end", "full_text": full_resp})

    except Exception as e:
        # Fallback for realism
        err = "Sorry, you cut out there. Can you say that again?"
        await websocket.send_json({"type": "end", "full_text": err})

# 6. WEBSOCKET ENDPOINT
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, biz: str = Query("marketing")):
    await websocket.accept()
    session_id = str(id(websocket))
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            await stream_conversation(session_id, data, websocket, biz)
    except WebSocketDisconnect:
        if session_id in local_memory: del local_memory[session_id]

# 7. THE PERFECT UI (React + Tailwind)
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Founder AI | The Closer</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    
    <style>
        body { background-color: #000; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        
        /* The Halo Interface */
        .halo-container {
            position: relative;
            width: 200px; height: 200px;
            display: flex; justify-content: center; align-items: center;
        }
        
        .halo-ring {
            position: absolute;
            width: 100%; height: 100%;
            border-radius: 50%;
            border: 2px solid rgba(255,255,255,0.1);
            transition: all 0.3s ease;
        }
        
        .core {
            width: 140px; height: 140px;
            border-radius: 50%;
            background: #111;
            display: flex; justify-content: center; align-items: center;
            z-index: 10;
            transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            cursor: pointer;
            box-shadow: 0 0 30px rgba(0,0,0,0.5);
        }

        /* STATES */
        .state-idle .halo-ring { transform: scale(0.9); border-color: #333; }
        .state-idle .core { border: 1px solid #333; }

        .state-listening .halo-ring { border-color: #ef4444; animation: ripple 1.5s infinite; }
        .state-listening .core { background: radial-gradient(circle, #331111, #000); box-shadow: 0 0 20px #ef4444; }

        .state-thinking .halo-ring { border-color: #eab308; animation: spin 2s linear infinite; border-top-color: transparent; }
        .state-thinking .core { transform: scale(0.95); }

        .state-speaking .halo-ring { border-color: #22c55e; transform: scale(1.1); }
        .state-speaking .core { animation: pulse-speak 0.4s infinite alternate; background: radial-gradient(circle, #002200, #000); box-shadow: 0 0 30px #22c55e; }

        @keyframes ripple { 0% { transform: scale(1); opacity: 1; } 100% { transform: scale(1.5); opacity: 0; } }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        @keyframes pulse-speak { 0% { transform: scale(1); } 100% { transform: scale(1.05); } }

        .transcript-box {
            mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
            -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
        }
    </style>
</head>
<body class="h-screen flex flex-col items-center justify-center overflow-hidden">
    <div id="root" class="w-full max-w-lg"></div>

    <script type="text/babel">
        const { useState, useEffect, useRef } = React;

        function App() {
            const [connection, setConnection] = useState("Disconnected");
            const [mode, setMode] = useState("marketing"); // marketing, real_estate, dentist
            const [aiState, setAiState] = useState("idle"); 
            const [userTranscript, setUserTranscript] = useState("");
            const [aiResponse, setAiResponse] = useState("");

            const ws = useRef(null);
            const recognition = useRef(null);
            const synth = window.speechSynthesis;
            const silenceTimer = useRef(null);
            const activeRef = useRef(false);

            // 1. WebSocket Management
            const setupWebSocket = (bizType) => {
                if(ws.current) ws.current.close();
                const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(`${proto}${window.location.host}/ws?biz=${bizType}`);
                
                ws.current.onopen = () => setConnection("Online");
                ws.current.onclose = () => setConnection("Offline");
                
                ws.current.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    if (data.type === "chunk") {
                        if (aiState !== "speaking") setAiState("speaking");
                        setAiResponse(prev => prev + data.content);
                    } else if (data.type === "end") {
                        speak(data.full_text, bizType);
                    }
                };
            };

            useEffect(() => {
                setupWebSocket(mode);
                return () => ws.current?.close();
            }, [mode]);

            // 2. Speech Recognition (The Ears)
            useEffect(() => {
                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = true;
                    recognition.current.interimResults = true;
                    
                    recognition.current.onstart = () => { if(activeRef.current) setAiState("listening"); };
                    
                    recognition.current.onend = () => {
                        if (activeRef.current && aiState !== "speaking" && aiState !== "thinking") {
                            try { recognition.current.start(); } catch(e){}
                        }
                    };

                    recognition.current.onresult = (event) => {
                        // CRITICAL: Interruption Logic
                        if (synth.speaking) {
                            synth.cancel(); // Shut up immediately
                            setAiState("listening");
                        }

                        let finalTxt = "";
                        let interimTxt = "";
                        
                        for (let i = event.resultIndex; i < event.results.length; ++i) {
                            if (event.results[i].isFinal) finalTxt += event.results[i][0].transcript;
                            else interimTxt += event.results[i][0].transcript;
                        }

                        if (finalTxt || interimTxt) {
                            setUserTranscript(finalTxt || interimTxt);
                            
                            // Debounce: Wait for user to stop talking
                            if (silenceTimer.current) clearTimeout(silenceTimer.current);
                            silenceTimer.current = setTimeout(() => {
                                if ((finalTxt || interimTxt).trim().length > 1) {
                                    sendToAI(finalTxt || interimTxt);
                                }
                            }, 1000); // 1 second silence = User finished turn
                        }
                    };
                }
            }, [aiState]);

            const sendToAI = (text) => {
                recognition.current.stop();
                setAiState("thinking");
                setAiResponse("");
                ws.current.send(text);
            };

            // 3. Text to Speech (The Voice)
            const speak = (text, currentMode) => {
                const cleanText = text.replace(/\[.*?\]/g, '').trim(); // Remove [ES] tags
                if (!cleanText) return;

                const u = new SpeechSynthesisUtterance(cleanText);
                const voices = synth.getVoices();
                
                // --- DYNAMIC VOICE TUNING ---
                // Marketer = Fast, Confident. Dentist = Slower, Softer.
                let targetVoice = voices.find(v => v.name.includes("Google US English")) || 
                                  voices.find(v => v.lang === "en-US");

                if (targetVoice) u.voice = targetVoice;

                if (currentMode === "marketing") {
                    u.rate = 1.25; // High energy
                    u.pitch = 1.0;
                } else if (currentMode === "dentist") {
                    u.rate = 0.95; // Calming
                    u.pitch = 1.1;
                } else {
                    u.rate = 1.1; // Professional
                }

                u.onend = () => {
                    setAiState("listening");
                    setUserTranscript(""); // Clear display for next turn
                    if (activeRef.current) {
                        try { recognition.current.start(); } catch(e){}
                    }
                };

                synth.speak(u);
            };

            // 4. Interaction Toggle
            const toggle = () => {
                if (activeRef.current) {
                    activeRef.current = false;
                    recognition.current.stop();
                    synth.cancel();
                    setAiState("idle");
                    setUserTranscript("");
                } else {
                    // Pre-load voices
                    synth.getVoices();
                    activeRef.current = true;
                    setAiState("listening");
                    try { recognition.current.start(); } catch(e){}
                }
            };

            return (
                <div className="flex flex-col items-center justify-between h-[90vh] w-full p-6">
                    
                    {/* Header */}
                    <div className="text-center space-y-2">
                        <div className="text-[10px] font-mono text-gray-500 uppercase tracking-widest">
                            Founder AI v20.0 • {connection}
                        </div>
                        <h1 className="text-3xl font-bold tracking-tight text-white">
                            {mode === 'marketing' ? 'GROWTH PARTNER' : 
                             mode === 'real_estate' ? 'ESTATE AGENT' : 'CLINIC SUCCESS'}
                        </h1>
                    </div>

                    {/* The Core Interface */}
                    <div className={`halo-container state-${aiState}`} onClick={toggle}>
                        <div className="halo-ring"></div>
                        <div className="core">
                            <i className={`fas fa-${
                                aiState === 'listening' ? 'microphone' :
                                aiState === 'speaking' ? 'waveform' :
                                aiState === 'thinking' ? 'bolt' : 'power-off'
                            } text-4xl text-white transition-all duration-300`}></i>
                        </div>
                    </div>

                    {/* Dynamic Text Display */}
                    <div className="w-full max-w-md space-y-6 text-center h-48 flex flex-col justify-end">
                        {/* User Text */}
                        <div className={`transition-opacity duration-500 ${aiState === 'listening' ? 'opacity-100' : 'opacity-40'}`}>
                            {userTranscript && (
                                <p className="text-gray-400 text-lg font-medium">"{userTranscript}"</p>
                            )}
                        </div>

                        {/* AI Text */}
                        <div className="min-h-[60px]">
                            {aiResponse ? (
                                <p className="text-white text-xl font-semibold leading-relaxed drop-shadow-lg">
                                    {aiResponse}
                                </p>
                            ) : aiState === 'thinking' ? (
                                <p className="text-yellow-500 animate-pulse font-mono text-sm">PROCESSING STRATEGY...</p>
                            ) : null}
                        </div>
                    </div>

                    {/* Mode Switcher */}
                    <div className="flex gap-2 bg-gray-900 p-1.5 rounded-xl border border-gray-800">
                        {['marketing', 'real_estate', 'dentist'].map((m) => (
                            <button
                                key={m}
                                onClick={() => { setMode(m); setUserTranscript(""); setAiResponse(""); }}
                                className={`px-4 py-2 rounded-lg text-xs font-bold uppercase transition-all ${
                                    mode === m ? 'bg-white text-black shadow-lg' : 'text-gray-500 hover:text-white'
                                }`}
                            >
                                {m.replace('_', ' ')}
                            </button>
                        ))}
                    </div>

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
