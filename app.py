import os
import json
import asyncio
import sys
import httpx # PIP INSTALL HTTPX
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
import asyncpg
from dotenv import load_dotenv

# 1. LOAD CONFIGURATION
load_dotenv()

# KEYS & URLS
# We use 127.0.0.1 to avoid localhost resolution issues
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

# 2. APP SETUP
app = FastAPI(title="Ollama Sales Agent", version="3.1.0")

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
            if DATABASE_URL:
                self.pool = await asyncpg.create_pool(DATABASE_URL)
                print(f"✅ PostgreSQL Connected")
        except Exception as e:
            print(f"⚠️ DB Warning: {e}")

        try:
            if REDIS_URL:
                self.redis = redis.from_url(REDIS_URL, decode_responses=True)
                await self.redis.ping()
                print(f"✅ Redis Connected")
        except Exception as e:
            print(f"⚠️ Redis Warning: {e}")

    async def disconnect(self):
        if self.pool: await self.pool.close()
        if self.redis: await self.redis.close()

infra = Infrastructure()

@app.on_event("startup")
async def startup():
    await infra.connect()

@app.on_event("shutdown")
async def shutdown():
    await infra.disconnect()

# 4. INTELLIGENT LAYER (ROBUST HTTP CLIENT)
async def process_conversation(session_id: str, user_text: str):
    history_key = f"ollama_sales_chat:{session_id}"
    messages = []
    
    # System Prompt
    system_prompt = (
        "You are Alex, a professional Sales Closer. "
        "Your goal is to book a meeting. "
        "Reply in 1 short sentence. "
        "Always ask a question."
    )

    # 1. Load History
    try:
        if infra.redis:
            raw_history = await infra.redis.get(history_key)
            if raw_history:
                messages = json.loads(raw_history)
    except:
        pass

    if not messages:
        messages = [{"role": "system", "content": system_prompt}]
    
    messages.append({"role": "user", "content": user_text})
    
    ai_response_content = "I am processing your request..."

    # 2. Call Ollama directly
    print(f"🔹 Sending to Ollama: {user_text}")
    
    try:
        async with httpx.AsyncClient() as client:
            # We use a 30 second timeout because CPU inference can be slow
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": AI_MODEL,
                    "messages": messages,
                    "stream": False, 
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 100
                    }
                },
                timeout=30.0 
            )
            
            if response.status_code == 200:
                data = response.json()
                # support both 'message' and 'response' keys depending on version
                if 'message' in data:
                    ai_response_content = data['message']['content']
                elif 'response' in data:
                    ai_response_content = data['response']
                else:
                    ai_response_content = str(data)
                
                print(f"✅ Ollama Output: {ai_response_content}")
            else:
                print(f"❌ Ollama Error Status: {response.status_code}")
                ai_response_content = "I am having trouble connecting to my brain."

    except httpx.ConnectError:
        print("❌ Connection Refused. Is 'ollama serve' running?")
        ai_response_content = "Please start the Ollama server."
    except httpx.TimeoutException:
        print("❌ Timeout. Model is too slow.")
        ai_response_content = "I am thinking too slowly. Please try again."
    except Exception as e:
        print(f"❌ Error: {e}")
        ai_response_content = "System error occurred."

    # 3. Update History
    messages.append({"role": "assistant", "content": ai_response_content})
    if infra.redis:
        await infra.redis.set(history_key, json.dumps(messages, default=str), ex=3600)
    
    return ai_response_content

# 5. WEBSOCKET HANDLER
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    print(f"🔗 Connected: {session_id}")
    
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            
            # Get Response
            response = await process_conversation(session_id, data)
            
            # FORCE SEND - Ensure data is sent back
            print(f"📤 Sending to UI: {response}")
            await websocket.send_text(response)
            
    except WebSocketDisconnect:
        print(f"📴 Disconnected: {session_id}")

# 6. FRONTEND
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>AI Sales Closer</title>
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
        
        .orb-container.listening {
            border-color: #ef4444;
            background: radial-gradient(circle, #450a0a 0%, #020617 100%);
            box-shadow: 0 0 50px rgba(239, 68, 68, 0.4);
            animation: pulse-red 1.5s infinite;
        }
        
        .orb-container.speaking {
            border-color: #22c55e;
            background: radial-gradient(circle, #052e16 0%, #020617 100%);
            box-shadow: 0 0 50px rgba(34, 197, 94, 0.4);
            animation: pulse-green 1.5s infinite;
        }

        .orb-container.processing {
            border-color: #f59e0b;
            animation: spin 1s linear infinite;
        }

        @keyframes pulse-red { 0% {box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7);} 70% {box-shadow: 0 0 0 20px rgba(239, 68, 68, 0);} 100% {box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);} }
        @keyframes pulse-green { 0% {box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7);} 70% {box-shadow: 0 0 0 20px rgba(34, 197, 94, 0);} 100% {box-shadow: 0 0 0 0 rgba(34, 197, 94, 0);} }
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

            React.useEffect(() => {
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(protocol + window.location.host + "/ws");
                
                ws.current.onopen = () => setStatus("Connected");
                ws.current.onclose = () => setStatus("Disconnected");
                
                ws.current.onmessage = (e) => {
                    const text = e.data;
                    console.log("Received from AI:", text); // Debug log
                    setResponse(text);
                    if (text && text.length > 0) {
                        speakResponse(text);
                    } else {
                        // If empty response, go back to listening immediately
                        if (isConversationActive.current) setMode("listening");
                    }
                };

                // Init Speech Recognition
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
                            console.log("Sending:", text);
                            ws.current.send(text);
                        }
                    };
                }
                return () => { if (ws.current) ws.current.close(); };
            }, [mode]);

            const speakResponse = (text) => {
                setMode("speaking");
                
                // Clear any previous speech
                window.speechSynthesis.cancel();

                const utterance = new SpeechSynthesisUtterance(text);
                
                // Voice Selection Logic
                let voices = window.speechSynthesis.getVoices();
                const setVoice = () => {
                    const selected = voices.find(v => v.name === "Google US English") || 
                                     voices.find(v => v.name.includes("Zira")) || 
                                     voices.find(v => v.lang.startsWith("en-US")) || 
                                     voices[0];
                    if (selected) utterance.voice = selected;
                }

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
                utterance.pitch = 1.0;

                utterance.onend = () => {
                    console.log("Speech ended");
                    if (isConversationActive.current) { 
                        setMode("listening"); 
                        try { recognition.current.start(); } catch(e) {} 
                    } else { 
                        setMode("idle"); 
                    }
                };
                
                // Backup: If speech fails to start, reset mode after 3s
                utterance.onerror = () => {
                     console.error("Speech Error");
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
                    setMode("listening");
                    try { recognition.current.start(); } catch(e) {}
                }
            };

            return (
                <div className="flex flex-col items-center">
                    <div className="mb-12 text-center">
                        <h1 className="text-4xl font-bold glow-text tracking-widest text-sky-400">SALES AGENT</h1>
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
                        {mode === 'speaking' && <span className="text-green-400 animate-pulse font-mono">AGENT SPEAKING...</span>}
                        {mode === 'processing' && <span className="text-amber-400 animate-pulse font-mono">PROCESSING...</span>}
                        {mode === 'idle' && <span className="text-gray-600 font-mono">TAP TO START CALL</span>}
                    </div>
                    <div className="w-full max-w-md mt-8 p-6 bg-slate-900 bg-opacity-90 rounded-xl border border-slate-800 min-h-[150px] flex flex-col justify-end shadow-2xl">
                        {transcript && <div className="self-end bg-slate-800 text-sky-100 px-4 py-2 rounded-2xl rounded-tr-none mb-3 max-w-[85%] text-sm shadow-md">{transcript}</div>}
                        {response && <div className="self-start text-white font-medium text-lg leading-relaxed">{response}</div>}
                        {!transcript && !response && <div className="text-center text-gray-700 text-sm italic">Ready to close leads. Click the button to begin.</div>}
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
