import os
import json
import asyncio
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from groq import AsyncGroq
import redis.asyncio as redis
import asyncpg
from dotenv import load_dotenv

# 1. LOAD CONFIGURATION
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile") 
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

if not GROQ_API_KEY:
    raise ValueError("❌ .env file missing or GROQ_API_KEY not found!")

# 2. APP SETUP
app = FastAPI(title="Groq Voice Agent", version="2.3.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 3. INITIALIZE CLIENT
client = AsyncGroq(api_key=GROQ_API_KEY)

# 4. INFRASTRUCTURE MANAGER
class Infrastructure:
    def __init__(self):
        self.pool = None
        self.redis = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(DATABASE_URL)
            print(f"✅ PostgreSQL Connected")
            await self.init_db()
        except Exception as e:
            print(f"❌ DB Connection Error: {e}")

        try:
            self.redis = redis.from_url(REDIS_URL, decode_responses=True)
            print(f"✅ Redis Connected")
        except Exception as e:
            print(f"❌ Redis Error: {e}")

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

# 5. INTELLIGENT LAYER
async def process_conversation(session_id: str, user_text: str):
    history_key = f"groq_chat:{session_id}"
    raw_history = await infra.redis.get(history_key)
    
    # IMPROVED SYSTEM PROMPT FOR QUALITY
    messages = json.loads(raw_history) if raw_history else [
        {
            "role": "system", 
            "content": (
                "You are an advanced, highly intelligent voice assistant. "
                "Your responses must be in perfect, high-quality English. "
                "Keep responses concise (1-2 sentences) but engaging, polite, and helpful for a spoken conversation."
            )
        }
    ]
    
    messages.append({"role": "user", "content": user_text})
    
    try:
        completion = await client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            temperature=0.6, # Slightly lower temperature for more coherent English
            max_tokens=250, 
        )
        ai_response_content = completion.choices[0].message.content

    except Exception as e:
        print(f"API Error: {e}")
        return f"I encountered an error: {str(e)}"

    assistant_msg = {"role": "assistant", "content": ai_response_content}
    messages.append(assistant_msg)
    
    await infra.redis.set(history_key, json.dumps(messages, default=str), ex=3600)
    asyncio.create_task(save_log(session_id, user_text, ai_response_content))
    
    return ai_response_content

async def save_log(session_id, user, ai):
    if infra.pool:
        async with infra.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversation_logs (session_id, user_msg, ai_msg, model_used) VALUES ($1, $2, $3, $4)",
                session_id, user, ai, AI_MODEL
            )

# 6. WEBSOCKET HANDLER
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    print(f"🔗 Call Started: {session_id}")
    
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            response = await process_conversation(session_id, data)
            await websocket.send_text(response)
            
    except WebSocketDisconnect:
        print(f"📴 Call Ended: {session_id}")

# 7. REACT UI (Improved Logic)
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Groq Voice AI</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0f172a; color: #fff; font-family: 'Segoe UI', sans-serif; }
        .glow-text { text-shadow: 0 0 20px rgba(249, 115, 22, 0.5); }
        .orb-container {
            width: 150px; height: 150px;
            border-radius: 50%;
            background: radial-gradient(circle, #331f16 0%, #1a0f0a 100%);
            border: 2px solid #552b1b;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            transition: all 0.4s ease;
            box-shadow: 0 0 30px rgba(249, 115, 22, 0.1);
            user-select: none;
        }
        .orb-container:hover { transform: scale(1.05); border-color: #f97316; }
        .orb-container.listening {
            border-color: #ef4444;
            box-shadow: 0 0 50px rgba(239, 68, 68, 0.4);
            animation: pulse-red 1.5s infinite;
        }
        .orb-container.speaking {
            border-color: #f97316;
            box-shadow: 0 0 50px rgba(249, 115, 22, 0.4);
            animation: pulse-orange 1.5s infinite;
        }
        @keyframes pulse-red { 0% {box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7);} 70% {box-shadow: 0 0 0 20px rgba(239, 68, 68, 0);} 100% {box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);} }
        @keyframes pulse-orange { 0% {box-shadow: 0 0 0 0 rgba(249, 115, 22, 0.7);} 70% {box-shadow: 0 0 0 20px rgba(249, 115, 22, 0);} 100% {box-shadow: 0 0 0 0 rgba(249, 115, 22, 0);} }
    </style>
</head>
<body class="h-screen flex items-center justify-center overflow-hidden">
    <div id="root" class="w-full max-w-lg"></div>

    <script type="text/babel">
        function App() {
            const [status, setStatus] = React.useState("Offline");
            // Mode: idle, listening, processing, speaking
            const [mode, setMode] = React.useState("idle");
            const [transcript, setTranscript] = React.useState("");
            const [response, setResponse] = React.useState("");
            
            // Refs to manage state inside event listeners without closure issues
            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const isUserIntentListening = React.useRef(false); // Tracks if the user WANTs it listening

            React.useEffect(() => {
                // Initialize WebSocket
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(protocol + window.location.host + "/ws");
                
                ws.current.onopen = () => setStatus("Online");
                ws.current.onclose = () => setStatus("Offline");
                
                ws.current.onmessage = (e) => {
                    const text = e.data;
                    setResponse(text);
                    speak(text);
                };

                // Initialize Speech Recognition
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                if (SpeechRecognition) {
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = true; // Key change: Keep listening
                    recognition.current.interimResults = false;
                    recognition.current.lang = 'en-US';

                    recognition.current.onstart = () => {
                        console.log("Mic started");
                        if(isUserIntentListening.current) setMode("listening");
                    };

                    recognition.current.onend = () => {
                        console.log("Mic stopped");
                        // If user wants it listening but it stopped (e.g. silence timeout), restart it
                        if (isUserIntentListening.current && mode !== "speaking") {
                            console.log("Restarting mic...");
                            try { recognition.current.start(); } catch(e) {}
                        } else if (!isUserIntentListening.current) {
                            setMode("idle");
                        }
                    };

                    recognition.current.onresult = (e) => {
                        const current = e.resultIndex;
                        const text = e.results[current][0].transcript;
                        if(text.trim()) {
                            setTranscript(text);
                            setMode("processing");
                            
                            // Stop mic strictly to avoid hearing self, will restart after speak
                            recognition.current.stop(); 
                            
                            ws.current.send(text);
                        }
                    };
                }

                return () => {
                    if(ws.current) ws.current.close();
                }
            }, []);

            // Helper to get the best sounding English voice
            const getBestVoice = (voices) => {
                // Priority list for "Good Accent"
                const priorities = ["Google US English", "Microsoft Zira", "Natural", "Premium"];
                
                for (let p of priorities) {
                    const found = voices.find(v => v.name.includes(p) && v.lang.startsWith("en"));
                    if (found) return found;
                }
                return voices.find(v => v.lang.startsWith("en")) || voices[0];
            };

            const speak = (text) => {
                setMode("speaking");
                const utterance = new SpeechSynthesisUtterance(text);
                const voices = window.speechSynthesis.getVoices();
                
                utterance.voice = getBestVoice(voices);
                utterance.rate = 1.0; 
                utterance.pitch = 1.0;

                utterance.onend = () => {
                    // Resume listening if intent is still true
                    if (isUserIntentListening.current) {
                        setMode("listening");
                        try { recognition.current.start(); } catch(e) {}
                    } else {
                        setMode("idle");
                    }
                };

                window.speechSynthesis.speak(utterance);
            };

            const toggleMic = () => {
                if (isUserIntentListening.current) {
                    // Turn OFF
                    isUserIntentListening.current = false;
                    recognition.current.stop();
                    window.speechSynthesis.cancel(); // Stop talking if talking
                    setMode("idle");
                } else {
                    // Turn ON
                    isUserIntentListening.current = true;
                    setMode("listening");
                    // Ensure voices are loaded (Chrome quirk)
                    window.speechSynthesis.getVoices();
                    try { recognition.current.start(); } catch(e) {}
                }
            };

            return (
                <div className="flex flex-col items-center">
                    
                    <div className="mb-10 text-center">
                        <h1 className="text-3xl font-bold glow-text tracking-widest">GROQ AI</h1>
                        <p className="text-gray-400 text-sm mt-2 uppercase tracking-widest">{status}</p>
                        <p className="text-xs text-orange-500 mt-1">
                            {mode === 'listening' ? 'Listening...' : 
                             mode === 'speaking' ? 'Speaking...' : 
                             mode === 'processing' ? 'Thinking...' : 'Tap to Start'}
                        </p>
                    </div>

                    <div className={`orb-container ${mode}`} onClick={toggleMic}>
                        <i className={`fas fa-${mode === 'listening' ? 'microphone' : mode === 'speaking' ? 'volume-up' : mode === 'processing' ? 'bolt' : 'power-off'} text-4xl text-white`}></i>
                    </div>

                    <div className="w-full mt-12 p-6 bg-slate-900 bg-opacity-80 rounded-xl border border-slate-700 min-h-[200px] flex flex-col justify-end shadow-2xl">
                        {transcript && (
                            <div className="self-end bg-slate-800 text-gray-200 px-4 py-2 rounded-lg mb-3 max-w-[80%] text-sm">
                                {transcript}
                            </div>
                        )}
                        {response && (
                            <div className="self-start text-orange-400 font-medium text-lg leading-relaxed animate-pulse">
                                {response}
                            </div>
                        )}
                        {!transcript && !response && (
                            <div className="text-center text-gray-600 text-sm italic">
                                "Tap the orb to start a continuous conversation."
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
