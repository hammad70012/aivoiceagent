import os
import json
import asyncio
import sys
import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
import asyncpg
from dotenv import load_dotenv

# 1. CONFIGURATION
load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

# 2. APP SETUP
app = FastAPI(title="Founder Sales AI (Audio Fixed)", version="6.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 3. INFRASTRUCTURE
class Infrastructure:
    def __init__(self):
        self.pool = None
        self.redis = None

    async def connect(self):
        try:
            if REDIS_URL:
                self.redis = redis.from_url(REDIS_URL, decode_responses=True)
                await self.redis.ping()
                print(f"✅ Redis Connected")
        except: pass

        try:
            if DATABASE_URL:
                self.pool = await asyncpg.create_pool(DATABASE_URL)
                print(f"✅ DB Connected")
        except: pass

    async def disconnect(self):
        if self.pool: await self.pool.close()
        if self.redis: await self.redis.close()

infra = Infrastructure()

@app.on_event("startup")
async def startup():
    print("🚀 SERVER STARTING...")
    await infra.connect()

@app.on_event("shutdown")
async def shutdown():
    await infra.disconnect()

# 4. FOUNDER SALES LOGIC
async def process_conversation(session_id: str, user_text: str):
    history_key = f"founder_chat:{session_id}"
    messages = []
    
    # --- FOUNDER PERSONA ---
    system_prompt = (
        "You are the Founder of a high-tech company. You are closing a deal."
        "1. Be confident, direct, and slightly aggressive."
        "2. Response MUST be less than 15 words."
        "3. Always end with a question."
        "4. Do not use special characters or markdown."
    )

    if infra.redis:
        try:
            raw = await infra.redis.get(history_key)
            if raw: messages = json.loads(raw)
        except: pass

    if not messages:
        messages = [{"role": "system", "content": system_prompt}]
    
    messages.append({"role": "user", "content": user_text})
    
    print(f"🎤 User: {user_text}")

    ai_response = "I am listening."

    # CALL OLLAMA
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": AI_MODEL, 
                    "messages": messages, 
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 40}
                },
                timeout=30.0 
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'message' in data:
                    ai_response = data['message']['content']
                print(f"🔊 AI: {ai_response}")
            else:
                ai_response = "I'm having trouble connecting."

    except Exception as e:
        print(f"❌ Error: {e}")
        ai_response = "Can you repeat that?"

    # Update History
    messages.append({"role": "assistant", "content": ai_response})
    if infra.redis:
        await infra.redis.set(history_key, json.dumps(messages, default=str), ex=3600)
    
    return ai_response

# 5. WEBSOCKET
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    print(f"🔗 Connected: {session_id}")
    
    try:
        while True:
            data = await websocket.receive_text()
            
            # Handle Ping/Keep-Alive
            if data == "__PING__":
                await websocket.send_text("__PONG__")
                continue
                
            if not data.strip(): continue
            
            response = await process_conversation(session_id, data)
            await websocket.send_text(response)
            
    except WebSocketDisconnect:
        print(f"📴 Disconnected: {session_id}")

# 6. FRONTEND (FIXED AUDIO)
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Founder Sales AI</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0f172a; color: #fff; font-family: 'Segoe UI', sans-serif; }
        .glow-text { text-shadow: 0 0 20px rgba(56, 189, 248, 0.5); }
        .orb-container {
            width: 160px; height: 160px;
            border-radius: 50%;
            background: radial-gradient(circle, #0f2e4a 0%, #020617 100%);
            border: 2px solid #1e3a8a;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            transition: all 0.4s ease;
            box-shadow: 0 0 30px rgba(56, 189, 248, 0.1);
            position: relative;
            z-index: 10;
        }
        .orb-container:hover { transform: scale(1.05); border-color: #38bdf8; }
        .orb-container.listening { border-color: #ef4444; background: radial-gradient(circle, #450a0a 0%, #020617 100%); box-shadow: 0 0 50px rgba(239, 68, 68, 0.4); animation: pulse-red 1.5s infinite; }
        .orb-container.speaking { border-color: #22c55e; background: radial-gradient(circle, #052e16 0%, #020617 100%); box-shadow: 0 0 50px rgba(34, 197, 94, 0.4); animation: pulse-green 1.5s infinite; }
        .orb-container.processing { border-color: #f59e0b; animation: spin 1s linear infinite; }
        @keyframes pulse-red { 0% {box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7);} 70% {box-shadow: 0 0 0 20px rgba(239, 68, 68, 0);} }
        @keyframes pulse-green { 0% {box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7);} 70% {box-shadow: 0 0 0 20px rgba(34, 197, 94, 0);} }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body class="h-screen flex items-center justify-center overflow-hidden">
    <div id="root" class="w-full max-w-lg"></div>

    <script type="text/babel">
        function App() {
            const [status, setStatus] = React.useState("Disconnected");
            const [mode, setMode] = React.useState("idle");
            const [transcript, setTranscript] = React.useState("");
            const [response, setResponse] = React.useState("");
            
            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const isConversationActive = React.useRef(false);
            const pingInterval = React.useRef(null);

            React.useEffect(() => {
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(protocol + window.location.host + "/ws");
                
                ws.current.onopen = () => {
                    setStatus("Connected");
                    // Keep Alive Ping every 10 seconds
                    pingInterval.current = setInterval(() => {
                        if(ws.current.readyState === 1) ws.current.send("__PING__");
                    }, 10000);
                };
                
                ws.current.onclose = () => {
                    setStatus("Disconnected");
                    if(pingInterval.current) clearInterval(pingInterval.current);
                };
                
                ws.current.onmessage = (e) => {
                    const text = e.data;
                    if (text === "__PONG__") return;
                    
                    console.log("AI SAID:", text);
                    setResponse(text);
                    speakResponse(text);
                };

                // PRE-LOAD VOICES
                window.speechSynthesis.getVoices();

                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = true; 
                    recognition.current.interimResults = false;
                    recognition.current.lang = 'en-US';

                    recognition.current.onstart = () => { if (isConversationActive.current) setMode("listening"); };
                    
                    recognition.current.onend = () => {
                        if (isConversationActive.current && mode !== "speaking" && mode !== "processing") {
                            try { recognition.current.start(); } catch(e) {}
                        } else if (!isConversationActive.current) { setMode("idle"); }
                    };

                    recognition.current.onresult = (event) => {
                        const resultsLength = event.results.length - 1;
                        const text = event.results[resultsLength][0].transcript;
                        if (text.trim() && isConversationActive.current) {
                            setTranscript(text);
                            setMode("processing");
                            recognition.current.stop();
                            ws.current.send(text);
                        }
                    };
                }
                return () => { 
                    if (ws.current) ws.current.close(); 
                    if (pingInterval.current) clearInterval(pingInterval.current);
                };
            }, [mode]);

            const speakResponse = (text) => {
                setMode("speaking");
                window.speechSynthesis.cancel();
                
                const utterance = new SpeechSynthesisUtterance(text);
                
                // IMPORTANT: Prevent Garbage Collection
                window.currentUtterance = utterance;

                // Voice Logic
                let voices = window.speechSynthesis.getVoices();
                const setVoice = () => {
                    utterance.voice = voices.find(v => v.name === "Google US English") || 
                                      voices.find(v => v.name.includes("Zira")) || 
                                      voices.find(v => v.lang.startsWith("en-US")) || 
                                      voices[0];
                };

                if (!voices.length) {
                    window.speechSynthesis.onvoiceschanged = () => {
                        voices = window.speechSynthesis.getVoices();
                        setVoice();
                        window.speechSynthesis.speak(utterance);
                    };
                } else {
                    setVoice();
                    window.speechSynthesis.speak(utterance);
                }

                utterance.rate = 1.0;
                
                utterance.onend = () => {
                    console.log("Speech finished");
                    if (isConversationActive.current) {
                        setMode("listening");
                        try { recognition.current.start(); } catch(e) {}
                    } else {
                        setMode("idle");
                    }
                };

                utterance.onerror = (e) => {
                    console.error("Speech Error:", e);
                    // If audio fails, force go back to listening so we don't get stuck
                    if (isConversationActive.current) setMode("listening");
                };
            };

            const toggleConversation = () => {
                if (isConversationActive.current) {
                    isConversationActive.current = false;
                    recognition.current.stop();
                    window.speechSynthesis.cancel();
                    setMode("idle");
                } else {
                    isConversationActive.current = true;
                    // Unlock Audio Context on Mobile/Safari
                    window.speechSynthesis.resume();
                    setMode("listening");
                    try { recognition.current.start(); } catch(e) {}
                }
            };

            return (
                <div className="flex flex-col items-center">
                    <div className="mb-12 text-center">
                        <h1 className="text-4xl font-bold glow-text tracking-widest text-sky-400">FOUNDER AI</h1>
                        <p className="text-gray-500 text-sm mt-3 uppercase tracking-widest font-semibold">{status}</p>
                    </div>
                    <div className={`orb-container ${mode}`} onClick={toggleConversation}>
                        <i className={`fas fa-${
                            mode === 'listening' ? 'microphone' : mode === 'speaking' ? 'comments' : 
                            mode === 'processing' ? 'sync' : 'power-off'
                        } text-5xl text-white`}></i>
                    </div>
                    <div className="mt-8 text-center h-8">
                        {mode === 'listening' && <span className="text-red-400 animate-pulse font-mono">LISTENING...</span>}
                        {mode === 'speaking' && <span className="text-green-400 animate-pulse font-mono">FOUNDER SPEAKING...</span>}
                        {mode === 'processing' && <span className="text-amber-400 animate-pulse font-mono">PROCESSING...</span>}
                        {mode === 'idle' && <span className="text-gray-600 font-mono">TAP TO START CALL</span>}
                    </div>
                    <div className="w-full max-w-md mt-8 p-6 bg-slate-900 bg-opacity-90 rounded-xl border border-slate-800 min-h-[150px] flex flex-col justify-end shadow-2xl">
                        {transcript && <div className="self-end bg-slate-800 text-sky-100 px-4 py-2 rounded-2xl rounded-tr-none mb-3 max-w-[85%] text-sm shadow-md">{transcript}</div>}
                        {response && <div className="self-start text-white font-medium text-lg leading-relaxed">{response}</div>}
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
