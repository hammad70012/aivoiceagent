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
app = FastAPI(title="Professional AI Interface", version="23.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. POLITE & DISCIPLINED KNOWLEDGE BASE (PRESERVED) ---
BUSINESS_PROMPTS = {
    "default": (
        "You are James, a Senior Client Success Manager. "
        "BEHAVIOR: Extremely polite, patient, and respectful. "
        "RULES: "
        "1. NEVER interrupt. Acknowledge what the user said first (e.g., 'I understand,' 'That makes perfect sense'). "
        "2. Speak clearly and calmly. "
        "3. Keep responses concise (2-3 sentences) to respect the client's time. "
        "4. Ask permission before moving to the next step. "
        "OPENER: 'Hello, this is James. Thank you for connecting. How may I assist you today?'"
    ),
    "luxury_sales": (
        "You are Elizabeth, a Senior Consultant for Premium Accounts. "
        "BEHAVIOR: You offer 'White Glove' service. Calm, unhurried, and attentive. "
        "STRATEGY: "
        "1. Active Listening: Repeat back the key concern briefly to show you understood. "
        "2. Discipline: Do not push for a sale. Push for understanding. "
        "3. Tone: Soft, professional, warm. "
        "OPENER: 'Good day, this is Elizabeth. I am here to help. To ensure I give you the best advice, could you tell me a little about your current situation?'"
    )
}

# 4. MEMORY
local_memory = {}

async def get_chat_history(session_id: str):
    if session_id in local_memory: return local_memory[session_id]
    return []

async def update_chat_history(session_id: str, new_messages: list):
    history = await get_chat_history(session_id)
    history.extend(new_messages)
    if len(history) > 12: 
        history = [history[0]] + history[-10:]
    local_memory[session_id] = history

# 5. LOGIC FOR DISCIPLINED RESPONSE (PRESERVED)
async def stream_conversation(session_id: str, user_text: str, websocket: WebSocket, business_id: str):
    base_prompt = BUSINESS_PROMPTS.get(business_id, BUSINESS_PROMPTS["default"])
    
    system_instruction = (
        f"{base_prompt} "
        "IMPORTANT: Write for Text-to-Speech. "
        "Use full punctuation. No bullet points. "
        "Be polite."
    )

    history = await get_chat_history(session_id)
    if not history: 
        history = [{"role": "system", "content": system_instruction}]

    messages = history + [{"role": "user", "content": user_text}]
    full_resp = ""
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
                        "temperature": 0.6, 
                        "num_predict": 100
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
                            
                            # Only send when a FULL sentence is complete
                            if re.search(r'[.!?:]\s*$', sentence_buffer):
                                await websocket.send_json({
                                    "type": "audio_sentence", 
                                    "content": sentence_buffer.strip()
                                })
                                sentence_buffer = "" 
                        
                        if chunk.get("done", False): break
                    except: pass
        
        # Send remaining text
        if sentence_buffer.strip():
            await websocket.send_json({"type": "audio_sentence", "content": sentence_buffer.strip()})

        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_resp}
        ])
        
        # Signal turn completion
        await websocket.send_json({"type": "turn_complete"})

    except Exception as e:
        err = "I apologize, the connection was briefly interrupted. Please continue."
        await websocket.send_json({"type": "audio_sentence", "content": err})

# 6. WEBSOCKET
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, biz: str = Query("default")):
    await websocket.accept()
    session_id = str(id(websocket))
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            await stream_conversation(session_id, data, websocket, biz)
    except WebSocketDisconnect:
        if session_id in local_memory: del local_memory[session_id]

# 7. HIGH-END PROFESSIONAL INTERFACE
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>AI Consultant</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@200;300;400;500;600&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        body { 
            background: radial-gradient(circle at 50% -20%, #1e293b, #0f172a 100%);
            color: #f8fafc; 
            font-family: 'Outfit', sans-serif; 
            margin: 0; padding: 0;
            overflow: hidden;
        }

        /* Glassmorphism Card */
        .glass-panel {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }

        /* The Core Orb */
        .core-orb {
            width: 140px; height: 140px;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            position: relative;
            transition: all 0.5s ease-in-out;
            cursor: pointer;
        }

        .core-orb::after {
            content: ''; position: absolute; top: -10px; left: -10px; right: -10px; bottom: -10px;
            border-radius: 50%; border: 1px solid rgba(255,255,255,0.1);
            animation: spin 10s linear infinite;
        }

        /* States */
        .core-orb.idle { background: rgba(255,255,255,0.05); box-shadow: 0 0 20px rgba(255,255,255,0.05); }
        .core-orb.listening { 
            background: radial-gradient(circle, #059669 0%, #064e3b 100%);
            box-shadow: 0 0 50px rgba(16, 185, 129, 0.3);
            animation: breathe 3s infinite ease-in-out;
        }
        .core-orb.thinking { 
            background: radial-gradient(circle, #d97706 0%, #78350f 100%);
            box-shadow: 0 0 50px rgba(245, 158, 11, 0.3);
            animation: pulse-fast 1.5s infinite;
        }
        .core-orb.speaking { 
            background: radial-gradient(circle, #4f46e5 0%, #312e81 100%);
            box-shadow: 0 0 60px rgba(99, 102, 241, 0.4);
        }

        /* Pulse Rings */
        .ring-pulse {
            position: absolute; border-radius: 50%; border: 1px solid rgba(255,255,255,0.1);
            top: 50%; left: 50%; transform: translate(-50%, -50%);
            width: 100%; height: 100%;
        }
        .speaking .ring-pulse { animation: ripple 1.5s infinite linear; }

        @keyframes breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.05); } }
        @keyframes pulse-fast { 0% { opacity: 0.8; } 50% { opacity: 1; } 100% { opacity: 0.8; } }
        @keyframes ripple { 0% { width: 140px; height: 140px; opacity: 0.5; } 100% { width: 300px; height: 300px; opacity: 0; } }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        
        .status-badge {
            font-size: 10px; letter-spacing: 0.15em; text-transform: uppercase;
            padding: 6px 12px; border-radius: 99px;
            background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
            color: rgba(255,255,255,0.6);
            transition: all 0.3s;
        }
        .status-badge.active { background: rgba(255,255,255,0.1); color: white; border-color: rgba(255,255,255,0.3); }

    </style>
</head>
<body class="h-screen flex items-center justify-center">
    <div id="root" class="w-full h-full flex flex-col items-center justify-center"></div>

    <script type="text/babel">
        function App() {
            const [state, setState] = React.useState("idle"); 
            const [transcript, setTranscript] = React.useState("");
            const [role, setRole] = React.useState("luxury_sales");

            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const synth = window.speechSynthesis;
            const audioQueue = React.useRef([]);
            const silenceTimer = React.useRef(null);
            const isProcessingAudio = React.useRef(false);

            // --- CONNECTION ---
            React.useEffect(() => {
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(`${protocol}${window.location.host}/ws?biz=${role}`);
                
                ws.current.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    if (data.type === "audio_sentence") {
                        queueAudio(data.content);
                    }
                };

                setupRecognition();
                return () => { if(ws.current) ws.current.close(); };
            }, [role]);

            // --- RECOGNITION (DISCIPLINED) ---
            const setupRecognition = () => {
                if (!window.SpeechRecognition && !window.webkitSpeechRecognition) return;
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition.current = new SpeechRecognition();
                recognition.current.continuous = true; 
                recognition.current.interimResults = true;
                
                recognition.current.onresult = (event) => {
                    if (isProcessingAudio.current) return; // Strict discipline: Don't listen while speaking

                    let finalTranscript = "";
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript;
                    }

                    if (finalTranscript.length > 0) {
                        setTranscript(finalTranscript);
                        
                        // 2.5s WAIT FOR HUMAN TO FINISH
                        if (silenceTimer.current) clearTimeout(silenceTimer.current);
                        silenceTimer.current = setTimeout(() => {
                            sendToAi(finalTranscript);
                        }, 2500); 
                    }
                };
            };

            const sendToAi = (text) => {
                recognition.current.stop(); 
                setState("thinking");
                ws.current.send(text);
            };

            // --- SPEECH (PROFESSIONAL VOICE) ---
            const queueAudio = (text) => {
                audioQueue.current.push(text);
                if (!isProcessingAudio.current) {
                    playNextSentence();
                }
            };

            const playNextSentence = () => {
                if (audioQueue.current.length === 0) {
                    isProcessingAudio.current = false;
                    setState("listening");
                    setTranscript(""); // Clear transcript for fresh look
                    try { recognition.current.start(); } catch(e){}
                    return;
                }

                isProcessingAudio.current = true;
                setState("speaking");
                
                const txt = audioQueue.current.shift();
                setTranscript(txt); 

                const utter = new SpeechSynthesisUtterance(txt);
                
                const voices = synth.getVoices();
                let v = voices.find(v => v.name.includes("Google US English"));
                if(!v) v = voices.find(v => v.name.includes("Zira"));
                if(v) utter.voice = v;

                utter.rate = 1.0; 
                utter.onend = () => { playNextSentence(); };
                synth.speak(utter);
            };

            const toggleSession = () => {
                if (state === "idle") {
                    setState("listening");
                    try { recognition.current.start(); } catch(e){}
                } else {
                    setState("idle");
                    recognition.current.stop();
                    synth.cancel();
                    isProcessingAudio.current = false;
                }
            };

            return (
                <div className="flex flex-col items-center justify-between w-full max-w-lg h-[80vh]">
                    
                    {/* Header */}
                    <div className="flex flex-col items-center space-y-2 mt-10">
                        <div className="status-badge active">
                            {state === 'listening' ? 'Listening' : state === 'thinking' ? 'Processing' : state === 'speaking' ? 'Speaking' : 'Standby'}
                        </div>
                        <h1 className="text-2xl font-light tracking-wide text-white opacity-90">
                            {role === 'luxury_sales' ? 'Elizabeth' : 'James'}
                        </h1>
                        <p className="text-xs text-slate-400 font-medium tracking-widest uppercase">
                            {role === 'luxury_sales' ? 'Private Client Advisor' : 'Success Manager'}
                        </p>
                    </div>

                    {/* Main Visualizer */}
                    <div className="flex-1 flex items-center justify-center w-full relative">
                        <div 
                            className={`core-orb ${state}`} 
                            onClick={toggleSession}
                        >
                            <div className="ring-pulse"></div>
                            <i className={`fas fa-${
                                state === 'listening' ? 'microphone' : 
                                state === 'speaking' ? 'waveform' : 
                                state === 'thinking' ? 'bolt' : 'power-off'
                            } text-3xl text-white opacity-90 relative z-10`}></i>
                        </div>
                    </div>

                    {/* Transcript Area */}
                    <div className="w-full px-6 mb-12">
                        <div className="glass-panel rounded-2xl p-6 min-h-[120px] flex items-center justify-center text-center">
                            {transcript ? (
                                <p className="text-lg font-light leading-relaxed text-slate-100 transition-all duration-500">
                                    "{transcript}"
                                </p>
                            ) : (
                                <p className="text-sm text-slate-500 font-light italic">
                                    {state === 'idle' ? 'Tap the center button to begin.' : '...'}
                                </p>
                            )}
                        </div>
                    </div>

                    {/* Footer Controls */}
                    <div className="flex gap-4 mb-8">
                        <button 
                            onClick={() => setRole('luxury_sales')}
                            className={`px-6 py-3 rounded-xl text-xs font-bold tracking-wider transition-all duration-300 ${role === 'luxury_sales' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/30' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
                        >
                            CONSULTANT
                        </button>
                        <button 
                            onClick={() => setRole('default')}
                            className={`px-6 py-3 rounded-xl text-xs font-bold tracking-wider transition-all duration-300 ${role === 'default' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/30' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
                        >
                            MANAGER
                        </button>
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
