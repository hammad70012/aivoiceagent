import os
import json
import asyncio
import uvicorn
import sys
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from ollama import AsyncClient
import redis.asyncio as redis
import asyncpg
from dotenv import load_dotenv

# 1. LOAD CONFIGURATION
load_dotenv()

# KEYS & URLS
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

# 2. APP SETUP
app = FastAPI(title="Ollama Sales Agent", version="2.6.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 3. CLIENT SETUP
client = AsyncClient(host=OLLAMA_HOST)

# 4. INFRASTRUCTURE (DB & REDIS)
class Infrastructure:
    def __init__(self):
        self.pool = None
        self.redis = None

    async def connect(self):
        # Postgres
        try:
            if DATABASE_URL:
                self.pool = await asyncpg.create_pool(DATABASE_URL)
                print(f"✅ PostgreSQL Connected")
                await self.init_db()
        except Exception as e:
            print(f"⚠️ DB Connection Warning: {e}")

        # Redis
        try:
            if REDIS_URL:
                self.redis = redis.from_url(REDIS_URL, decode_responses=True)
                # Test connection
                await self.redis.ping()
                print(f"✅ Redis Connected")
        except Exception as e:
            print(f"⚠️ Redis Connection Warning (Chat history will be temporary): {e}")
            self.redis = None

    async def init_db(self):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_logs (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT,
                        user_msg TEXT,
                        ai_msg TEXT,
                        model_used TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

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

# 5. INTELLIGENT LAYER (SALES PERSONA)
async def process_conversation(session_id: str, user_text: str):
    history_key = f"ollama_sales_chat:{session_id}"
    messages = []
    
    # --- SALES SYSTEM PROMPT (THE CLOSER) ---
    system_prompt = (
        "You are Alex, an elite Sales Closer. "
        "Your ONLY goal is to qualify this lead and book a meeting or close the deal. "
        "BEHAVIOR:"
        "1. Be direct, confident, and high-energy. Do not be passive."
        "2. Keep responses SHORT (maximum 1 sentence). Use spoken English style."
        "3. Always end with a question to drive the sale forward."
        "4. If they have objections, overcome them quickly and pivot back to the close."
        "5. Do not use robotic lists. Talk like a real person on the phone."
    )

    # 1. Try to get history from Redis
    try:
        if infra.redis:
            raw_history = await infra.redis.get(history_key)
            if raw_history:
                messages = json.loads(raw_history)
    except Exception as e:
        print(f"Error reading Redis: {e}")

    # 2. If no history, initialize
    if not messages:
        messages = [{"role": "system", "content": system_prompt}]
    
    messages.append({"role": "user", "content": user_text})
    
    ai_response_content = ""

    try:
        print(f"🤔 Sending to Ollama ({AI_MODEL})...")
        
        # 3. Call Ollama
        response = await client.chat(
            model=AI_MODEL,
            messages=messages,
            options={
                'temperature': 0.6, # Lower temp for more focused closing
                'num_predict': 60   # Keep it very short for speed
            }
        )

        # 4. ROBUST RESPONSE EXTRACTION (Fixes the "Processing" hang)
        # The library returns an object, but sometimes a dict depending on version.
        if hasattr(response, 'message'):
            ai_response_content = response.message.content
        elif 'message' in response:
            ai_response_content = response['message']['content']
        else:
            ai_response_content = str(response)

        print(f"✅ Ollama replied: {ai_response_content}")

    except Exception as e:
        print(f"❌ Ollama API Error: {e}")
        # IMPORTANT: Return an error message so the UI doesn't hang
        return "I'm having a technical issue connecting to my brain. Can you check my server?"

    # 5. Save History & Log
    messages.append({"role": "assistant", "content": ai_response_content})
    
    # Save to Redis (Async)
    if infra.redis:
        try:
            await infra.redis.set(history_key, json.dumps(messages, default=str), ex=3600)
        except Exception as e:
            print(f"Redis Write Error: {e}")

    # Save to DB (Background Task)
    asyncio.create_task(save_log(session_id, user_text, ai_response_content))
    
    return ai_response_content

async def save_log(session_id, user, ai):
    if infra.pool:
        try:
            async with infra.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO conversation_logs (session_id, user_msg, ai_msg, model_used) VALUES ($1, $2, $3, $4)",
                    session_id, user, ai, AI_MODEL
                )
        except Exception as e:
            print(f"DB Log Error: {e}")

# 6. WEBSOCKET HANDLER
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    print(f"🔗 Lead Connected: {session_id}")
    
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            
            print(f"🎤 User said: {data}")

            # Process with Sales Logic
            response = await process_conversation(session_id, data)
            
            # Send back to UI
            await websocket.send_text(response)
            
    except WebSocketDisconnect:
        print(f"📴 Lead Disconnected: {session_id}")
    except Exception as e:
        print(f"🔥 Critical WebSocket Error: {e}")
        try:
            await websocket.send_text("Connection error. Please refresh.")
        except:
            pass

# 7. FRONTEND
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
                    setResponse(text);
                    speakResponse(text);
                };

                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = true; 
                    recognition.current.interimResults = false;
                    recognition.current.lang = 'en-US';

                    recognition.current.onstart = () => {
                        if (isConversationActive.current) setMode("listening");
                    };

                    recognition.current.onend = () => {
                        if (isConversationActive.current && mode !== "speaking" && mode !== "processing") {
                            try { recognition.current.start(); } catch(e) {}
                        } else if (!isConversationActive.current) {
                            setMode("idle");
                        }
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
                };
            }, [mode]);

            const speakResponse = (text) => {
                setMode("speaking");
                const synth = window.speechSynthesis;
                const utterance = new SpeechSynthesisUtterance(text);
                
                let voices = synth.getVoices();
                const setVoice = () => {
                    utterance.voice = voices.find(v => v.name === "Google US English") || 
                                      voices.find(v => v.name.includes("Zira")) ||
                                      voices.find(v => v.lang.startsWith("en-US")) || 
                                      voices[0];
                }

                if (!voices.length) {
                    synth.onvoiceschanged = () => {
                        voices = synth.getVoices();
                        setVoice();
                        synth.speak(utterance);
                    };
                } else {
                    setVoice();
                    synth.speak(utterance);
                }

                utterance.rate = 1.1; 
                utterance.pitch = 1.0;

                utterance.onend = () => {
                    if (isConversationActive.current) {
                        setMode("listening");
                        try { recognition.current.start(); } catch(e) {}
                    } else {
                        setMode("idle");
                    }
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
                            mode === 'listening' ? 'microphone' : 
                            mode === 'speaking' ? 'comments' : 
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
                        {transcript && (
                            <div className="self-end bg-slate-800 text-sky-100 px-4 py-2 rounded-2xl rounded-tr-none mb-3 max-w-[85%] text-sm shadow-md">
                                {transcript}
                            </div>
                        )}
                        {response && (
                            <div className="self-start text-white font-medium text-lg leading-relaxed">
                                {response}
                            </div>
                        )}
                        {!transcript && !response && (
                            <div className="text-center text-gray-700 text-sm italic">
                                Ready to close leads. Click the button to begin.
                            </div>
                        )}
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
