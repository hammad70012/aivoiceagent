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
# Make sure you have Ollama running: 'ollama run qwen2.5:1.5b' (or llama3 for better results)
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 

# 2. APP SETUP
app = FastAPI(title="Human AI Closer", version="20.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. THE "FOUNDER" BRAIN (Psychological Engineering) ---
# These prompts are designed for "Status" and "Frame Control".
BUSINESS_PROMPTS = {
    "marketing": (
        "You are Alex, a savage Marketing Strategist & Founder. "
        "STYLE: Casual, fast, slightly arrogant but brilliant. Speak in short bursts. "
        "GOAL: Find the 'pain' and sell the 'cure'. "
        "RULES: "
        "1. NEVER use bullet points. "
        "2. Use fillers naturally: 'um', 'look', 'honestly', 'you know'. "
        "3. If they ask price, deflect: 'Depends. Are we doing a band-aid fix or a full scale?' "
        "4. Keep it UNDER 2 sentences. Real people text/talk short. "
        "OPENER: 'Yo, this is Alex. I saw your request. You looking to scale aggressive or just stabilize?'"
    ),
    "real_estate": (
        "You are Sarah, a High-End Real Estate Broker. "
        "STYLE: Warm but busy. You have 3 other calls waiting. "
        "GOAL: Get them to a viewing. "
        "RULES: "
        "1. Use 'Mmhmm', 'I see', 'Right'. "
        "2. Don't answer generic questions directly; ask 'Why do you ask?'. "
        "3. Speak comfortably. "
        "OPENER: 'Hey, Sarah here. I have a few minutes before my next showing. What exactly are you looking for?'"
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
    # Sliding window to keep context but save memory
    if len(history) > 15: 
        history = [history[0]] + history[-14:]
    local_memory[session_id] = history

# 5. SMART STREAMING LOGIC
async def stream_conversation(session_id: str, user_text: str, websocket: WebSocket, business_id: str):
    base_prompt = BUSINESS_PROMPTS.get(business_id, BUSINESS_PROMPTS["marketing"])
    
    # SYSTEM PROMPT INJECTION
    system_instruction = (
        f"{base_prompt} "
        "IMPORTANT: You are speaking via Voice-to-Text. "
        "Do NOT use markdown, bolding, or emojis. "
        "Do NOT write long paragraphs. "
        "Be conversational and punchy."
    )

    history = await get_chat_history(session_id)
    if not history: 
        history = [{"role": "system", "content": system_instruction}]

    messages = history + [{"role": "user", "content": user_text}]
    full_resp = ""
    
    # We buffer tokens to send complete sentences for smoother TTS
    buffer = ""
    
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
                        "temperature": 0.8, # High temp = more natural/unpredictable
                        "num_predict": 120, # Short responses only
                        "top_k": 40
                    }
                },
                timeout=40.0
            ) as response:
                async for line in response.aiter_lines():
                    if not line: continue
                    try:
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            word = chunk["message"]["content"]
                            full_resp += word
                            buffer += word
                            
                            # SEND DATA AS SOON AS WE HAVE A "SPEAKABLE" CHUNK
                            # Punctuation marks that indicate a pause
                            if re.search(r'[.!?;:]', word):
                                await websocket.send_json({"type": "speak_chunk", "content": buffer})
                                buffer = ""
                        
                        if chunk.get("done", False): break
                    except: pass
        
        # Send any remaining text
        if buffer.strip():
            await websocket.send_json({"type": "speak_chunk", "content": buffer})

        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_resp}
        ])
        
        # Signal conversation turn end
        await websocket.send_json({"type": "end_turn"})

    except Exception as e:
        print(f"Error: {e}")
        err = "Connection blip. Say that again?"
        await websocket.send_json({"type": "speak_chunk", "content": err})

# 6. WEBSOCKET HANDLER
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, biz: str = Query("marketing")):
    await websocket.accept()
    session_id = str(id(websocket))
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            # Backend simply processes. Frontend handles the "Thinking" UI.
            await stream_conversation(session_id, data, websocket, biz)
    except WebSocketDisconnect:
        if session_id in local_memory: del local_memory[session_id]

# 7. THE "HUMAN" INTERFACE
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Natural AI Sales</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background-color: #000; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        .visualizer { display: flex; align-items: center; justify-content: center; height: 100px; gap: 4px; }
        .bar { width: 6px; background: #fff; border-radius: 99px; animation: sound 0ms -800ms linear infinite alternate; transition: height 0.1s; height: 10px; }
        .speaking .bar { animation-duration: 400ms; }
        @keyframes sound { 0% { height: 10px; opacity: 0.3; } 100% { height: 60px; opacity: 1; } }
        
        .mic-button {
            width: 80px; height: 80px; border-radius: 50%;
            background: #222; border: 1px solid #333;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; transition: all 0.2s;
            box-shadow: 0 0 20px rgba(0,0,0,0.5);
        }
        .mic-button.active { background: #dc2626; border-color: #ef4444; box-shadow: 0 0 30px rgba(220, 38, 38, 0.4); }
        .mic-button.thinking { background: #ca8a04; border-color: #facc15; animation: pulse 1s infinite; }
        @keyframes pulse { 0% { transform: scale(0.95); } 50% { transform: scale(1.05); } 100% { transform: scale(0.95); } }
    </style>
</head>
<body class="h-screen flex flex-col items-center justify-center">
    <div id="root" class="w-full max-w-md px-6"></div>

    <script type="text/babel">
        function App() {
            // States: idle, listening, thinking, speaking
            const [state, setState] = React.useState("idle"); 
            const [subtitle, setSubtitle] = React.useState("");
            const [role, setRole] = React.useState("marketing");

            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const synth = window.speechSynthesis;
            const silenceTimer = React.useRef(null);
            
            // Queue for sentences to play them in order smoothly
            const audioQueue = React.useRef([]);
            const isPlaying = React.useRef(false);

            React.useEffect(() => {
                connectWs(role);
                setupRecognition();
                return () => { if(ws.current) ws.current.close(); };
            }, [role]);

            const connectWs = (biz) => {
                if (ws.current) ws.current.close();
                const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(proto + window.location.host + "/ws?biz=" + biz);
                ws.current.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    if (data.type === "speak_chunk") {
                        queueAudio(data.content);
                        setState("speaking");
                    } else if (data.type === "end_turn") {
                        // AI finished generating text, but might still be speaking from queue
                    }
                };
            };

            const setupRecognition = () => {
                if (!window.SpeechRecognition && !window.webkitSpeechRecognition) return;
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition.current = new SpeechRecognition();
                recognition.current.continuous = true; 
                recognition.current.interimResults = true;
                
                recognition.current.onresult = (event) => {
                    // IF USER SPEAKS, INTERRUPT AI IMMEDIATELY
                    if (isPlaying.current || state === "speaking") {
                        synth.cancel();
                        audioQueue.current = [];
                        isPlaying.current = false;
                        setState("listening");
                    }

                    const transcript = Array.from(event.results)
                        .map(res => res[0].transcript)
                        .join('');
                    
                    if (event.results[0].isFinal) {
                        // Very fast response trigger (0.8s silence)
                        if (silenceTimer.current) clearTimeout(silenceTimer.current);
                        silenceTimer.current = setTimeout(() => {
                            sendToAi(transcript);
                        }, 800);
                    }
                    setSubtitle(transcript);
                };
            };

            const sendToAi = (text) => {
                if (!text.trim()) return;
                recognition.current.stop();
                setState("thinking");
                setSubtitle(""); // Clear user text
                ws.current.send(text);
            };

            const queueAudio = (text) => {
                audioQueue.current.push(text);
                processQueue();
            };

            const processQueue = () => {
                if (isPlaying.current || audioQueue.current.length === 0) return;
                
                isPlaying.current = true;
                const text = audioQueue.current.shift();
                
                // Add text to UI for reading
                setSubtitle(prev => {
                    // Keep only last sentence in UI to avoid clutter
                    return text; 
                });

                const utter = new SpeechSynthesisUtterance(text);
                // Choose a decent voice
                const voices = synth.getVoices();
                const preferred = voices.find(v => v.name.includes("Google US English")) || voices.find(v => v.lang === "en-US");
                if (preferred) utter.voice = preferred;
                
                utter.rate = 1.1; // Slightly faster = more natural for sales
                utter.pitch = 1.0;

                utter.onend = () => {
                    isPlaying.current = false;
                    if (audioQueue.current.length > 0) {
                        processQueue();
                    } else {
                        // Conversation turn over, listen again
                        setState("listening");
                        try { recognition.current.start(); } catch(e) {}
                    }
                };
                
                synth.speak(utter);
            };

            const toggleMic = () => {
                if (state === "idle") {
                    synth.cancel(); // Reset audio
                    setState("listening");
                    try { recognition.current.start(); } catch(e) {}
                } else {
                    setState("idle");
                    recognition.current.stop();
                    synth.cancel();
                }
            };

            return (
                <div className="flex flex-col items-center">
                    <div className="mb-8 text-center">
                        <p className="text-gray-500 text-xs font-bold tracking-widest uppercase mb-2">
                            {role === 'marketing' ? 'Growth Partner' : 'Luxury Agent'}
                        </p>
                        <h1 className="text-3xl font-light text-white">
                            {role === 'marketing' ? 'Alex' : 'Sarah'}
                        </h1>
                    </div>

                    <div className={`visualizer ${state === 'speaking' ? 'speaking' : ''}`}>
                        {[...Array(5)].map((_, i) => (
                            <div key={i} className="bar" style={{animationDelay: `${i * 100}ms`}}></div>
                        ))}
                    </div>

                    <div className="my-10 h-16 w-full flex justify-center items-center px-4">
                        <p className="text-center text-lg text-gray-300 font-medium leading-relaxed fade-in">
                            {state === 'thinking' ? '...' : subtitle}
                        </p>
                    </div>

                    <div 
                        className={`mic-button ${state !== 'idle' ? (state === 'thinking' ? 'thinking' : 'active') : ''}`}
                        onClick={toggleMic}
                    >
                        <i className={`fas fa-${state === 'idle' ? 'microphone' : (state === 'thinking' ? 'spinner' : 'stop')} text-2xl text-white`}></i>
                    </div>

                    <div className="mt-12 flex gap-4">
                        <button 
                            onClick={() => setRole('marketing')}
                            className={`px-4 py-2 rounded-lg text-xs font-bold border ${role === 'marketing' ? 'bg-white text-black border-white' : 'text-gray-500 border-gray-800'}`}
                        >
                            MARKETING
                        </button>
                        <button 
                            onClick={() => setRole('real_estate')}
                            className={`px-4 py-2 rounded-lg text-xs font-bold border ${role === 'real_estate' ? 'bg-white text-black border-white' : 'text-gray-500 border-gray-800'}`}
                        >
                            REAL ESTATE
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
