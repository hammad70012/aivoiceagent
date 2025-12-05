import os
import json
import asyncio
import sys
import re
import uuid
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
app = FastAPI(title="Professional AI Interface", version="28.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. KNOWLEDGE BASE (PRESERVED) ---
BUSINESS_PROMPTS = {
    "default": (
        "You are James, a Senior Client Success Manager. "
        "BEHAVIOR: Polite, patient, and respectful. "
        "INSTRUCTION: "
        "1. Acknowledge user input first. "
        "2. Keep response under 3 sentences. "
        "3. At the end, provide 2 short follow-up options for the user enclosed in double angle brackets like this: <<Pricing details|Book a demo>>. "
        "OPENER: 'Hello, this is James. Thank you for connecting. How may I assist you today? <<I have a question|Tell me about services>>'"
    ),
    "luxury_sales": (
        "You are Elizabeth, a Senior Consultant for Premium Accounts. "
        "BEHAVIOR: White Glove service. Calm, unhurried. "
        "INSTRUCTION: "
        "1. Active Listening: Repeat back key concerns. "
        "2. Do not push for a sale yet. "
        "3. At the end, provide 2 classy response options for the user like this: <<Tell me more|What is the cost?>>. "
        "OPENER: 'Good day, this is Elizabeth. To ensure I give you the best advice, could you tell me a little about your current situation? <<Looking to invest|Just browsing>>'"
    )
}

# 4. PERSISTENT MEMORY
local_memory = {}

async def get_chat_history(client_id: str):
    if client_id in local_memory: return local_memory[client_id]
    return []

async def update_chat_history(client_id: str, new_messages: list):
    history = await get_chat_history(client_id)
    history.extend(new_messages)
    if len(history) > 21: 
        history = [history[0]] + history[-20:]
    local_memory[client_id] = history

# 5. STREAMING LOGIC
async def stream_conversation(client_id: str, user_text: str, websocket: WebSocket, business_id: str):
    base_prompt = BUSINESS_PROMPTS.get(business_id, BUSINESS_PROMPTS["default"])
    
    system_instruction = (
        f"{base_prompt} "
        "IMPORTANT: Write naturally. "
        "Always end with the options tag <<Option1|Option2>>."
    )

    history = await get_chat_history(client_id)
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
                        "num_predict": 150
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
                            
                            # Send complete sentences (ignoring text inside <<options>>)
                            if re.search(r'[.!?:]\s*$', sentence_buffer) and "<<" not in sentence_buffer:
                                await websocket.send_json({
                                    "type": "audio_sentence", 
                                    "content": sentence_buffer.strip()
                                })
                                sentence_buffer = "" 
                        
                        if chunk.get("done", False): break
                    except: pass
        
        if sentence_buffer.strip():
            await websocket.send_json({"type": "audio_sentence", "content": sentence_buffer.strip()})

        await update_chat_history(client_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_resp}
        ])
        
        await websocket.send_json({"type": "turn_complete"})

    except Exception as e:
        err = "I apologize, the connection was briefly interrupted. Please continue."
        await websocket.send_json({"type": "audio_sentence", "content": err})

# 6. WEBSOCKET
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, biz: str = Query("default"), client_id: str = Query(None)):
    await websocket.accept()
    final_id = client_id if client_id else str(uuid.uuid4())
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            await stream_conversation(final_id, data, websocket, biz)
    except WebSocketDisconnect:
        pass

# 7. FRONTEND (ROBUST NOISE FILTERING)
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

        .glass-panel {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }

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

        .ring-pulse {
            position: absolute; border-radius: 50%; border: 1px solid rgba(255,255,255,0.1);
            top: 50%; left: 50%; transform: translate(-50%, -50%);
            width: 100%; height: 100%;
        }
        .speaking .ring-pulse { animation: ripple 1.5s infinite linear; }
        
        .suggestion-btn {
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            color: #fff;
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.3s;
            backdrop-filter: blur(5px);
            margin: 0 5px;
        }
        .suggestion-btn:hover { background: rgba(255,255,255,0.2); transform: translateY(-2px); }

    </style>
</head>
<body class="h-screen flex items-center justify-center">
    <div id="root" class="w-full h-full flex flex-col items-center justify-center"></div>

    <script type="text/babel">
        function App() {
            const [state, setState] = React.useState("idle"); 
            const [transcript, setTranscript] = React.useState("");
            const [role, setRole] = React.useState("luxury_sales");
            const [suggestions, setSuggestions] = React.useState([]);

            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const synth = window.speechSynthesis;
            const audioQueue = React.useRef([]);
            const silenceTimer = React.useRef(null);
            
            // --- STATE CONTROL ---
            const shouldListen = React.useRef(false); 
            const isProcessingAudio = React.useRef(false);
            const aiStartTime = React.useRef(0); 
            const clientId = React.useRef(Math.random().toString(36).substring(7)).current;

            React.useEffect(() => {
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(`${protocol}${window.location.host}/ws?biz=${role}&client_id=${clientId}`);
                
                ws.current.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    if (data.type === "audio_sentence") {
                        handleIncomingAudio(data.content);
                    }
                };

                setupRecognition();
                return () => { if(ws.current) ws.current.close(); };
            }, [role]);

            const handleIncomingAudio = (text) => {
                const suggestionMatch = text.match(/<<(.+?)>>/);
                let cleanText = text;
                if (suggestionMatch) {
                    const rawOptions = suggestionMatch[1];
                    const options = rawOptions.split('|').map(o => o.trim());
                    setSuggestions(options); 
                    cleanText = text.replace(/<<.+?>>/, '').trim();
                }
                if (cleanText) queueAudio(cleanText);
            };

            const setupRecognition = () => {
                if (!window.SpeechRecognition && !window.webkitSpeechRecognition) return;
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition.current = new SpeechRecognition();
                recognition.current.continuous = true; 
                recognition.current.interimResults = true;
                
                recognition.current.onend = () => {
                    if (shouldListen.current) {
                        try { recognition.current.start(); } catch(e) {}
                    }
                };

                recognition.current.onresult = (event) => {
                    let interim = "";
                    let finalTranscript = "";
                    let isFinalResult = false;

                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i].isFinal) {
                            finalTranscript += event.results[i][0].transcript;
                            isFinalResult = true;
                        } else {
                            interim += event.results[i][0].transcript;
                        }
                    }

                    const detectedText = finalTranscript || interim;

                    // --- STRICT NOISE FILTER ---
                    // 1. If text is very short (< 10 chars) AND it is NOT final, it's likely noise/breath.
                    //    We only allow short text if the browser is 100% sure it's a finished sentence (isFinal).
                    if (!isFinalResult && detectedText.length < 10) {
                        return; // IGNORE THIS INPUT COMPLETELY
                    }

                    // --- INTERRUPTION LOGIC ---
                    // If AI is speaking...
                    if (isProcessingAudio.current) {
                        // 2. SELF-ECHO SHIELD: Ignore input for 1.5s after AI starts speaking
                        const timeSinceStart = Date.now() - aiStartTime.current;
                        if (timeSinceStart < 1500) {
                            return; 
                        }

                        // 3. VALID INTERRUPTION:
                        // If we reach here, it means:
                        // A) The input is Final (e.g. "Stop.") 
                        // B) OR The input is Interim but Long (e.g. "Wait a second...")
                        // This prevents random noise from stopping the AI.
                        console.log("Valid Interruption detected: " + detectedText);
                        synth.cancel(); 
                        audioQueue.current = [];
                        isProcessingAudio.current = false;
                        setState("listening");
                    }

                    // --- PROCESS USER INPUT ---
                    if (detectedText.length > 0) {
                        setTranscript(detectedText);
                        
                        if (silenceTimer.current) clearTimeout(silenceTimer.current);
                        silenceTimer.current = setTimeout(() => {
                            sendToAi(detectedText);
                        }, 2500); 
                    }
                };
            };

            const sendToAi = (text) => {
                recognition.current.stop(); 
                setState("thinking");
                setSuggestions([]); 
                ws.current.send(text);
            };

            const queueAudio = (text) => {
                audioQueue.current.push(text);
                if (!isProcessingAudio.current) {
                    playNextSentence();
                }
            };

            const playNextSentence = () => {
                if (audioQueue.current.length === 0) {
                    isProcessingAudio.current = false;
                    if (shouldListen.current) {
                        setState("listening");
                        setTranscript(""); 
                        try { recognition.current.start(); } catch(e){}
                    } else {
                        setState("idle");
                    }
                    return;
                }

                isProcessingAudio.current = true;
                aiStartTime.current = Date.now(); 
                setState("speaking");
                
                const txt = audioQueue.current.shift();
                setTranscript(txt); 

                const utter = new SpeechSynthesisUtterance(txt);
                const voices = synth.getVoices();
                let v = voices.find(v => v.name.includes("Google US English"));
                if(!v) v = voices.find(v => v.name.includes("Zira"));
                if(v) utter.voice = v;
                utter.rate = 1.0; 
                utter.onend = () => { 
                    if (isProcessingAudio.current) playNextSentence(); 
                };
                synth.speak(utter);
            };

            const toggleSession = () => {
                if (!shouldListen.current) {
                    shouldListen.current = true;
                    setState("listening");
                    try { recognition.current.start(); } catch(e){}
                } else {
                    shouldListen.current = false;
                    setState("idle");
                    recognition.current.stop();
                    synth.cancel();
                    isProcessingAudio.current = false;
                }
            };

            const clickSuggestion = (text) => {
                setTranscript(text);
                sendToAi(text);
            };

            return (
                <div className="flex flex-col items-center justify-between w-full max-w-lg h-[80vh]">
                    
                    <div className="flex flex-col items-center space-y-2 mt-10">
                        <div className="text-xs font-bold text-slate-500 tracking-widest uppercase mb-1">
                            {state === 'idle' ? 'OFFLINE' : 'LIVE CONNECTION'}
                        </div>
                        <h1 className="text-2xl font-light tracking-wide text-white opacity-90">
                            {role === 'luxury_sales' ? 'Elizabeth' : 'James'}
                        </h1>
                    </div>

                    <div className="flex-1 flex items-center justify-center w-full relative">
                        <div className={`core-orb ${state}`} onClick={toggleSession}>
                            <div className="ring-pulse"></div>
                            <i className={`fas fa-${
                                state === 'listening' ? 'microphone' : 
                                state === 'speaking' ? 'waveform' : 
                                state === 'thinking' ? 'bolt' : 'power-off'
                            } text-3xl text-white opacity-90 relative z-10`}></i>
                        </div>
                    </div>

                    <div className="w-full px-6 mb-4 flex flex-col items-center">
                        <div className="glass-panel rounded-2xl p-6 min-h-[100px] w-full flex items-center justify-center text-center mb-6">
                            {transcript ? (
                                <p className="text-lg font-light leading-relaxed text-slate-100">"{transcript}"</p>
                            ) : (
                                <p className="text-sm text-slate-500 font-light italic">Ready.</p>
                            )}
                        </div>

                        {suggestions.length > 0 && state !== 'thinking' && (
                            <div className="flex flex-wrap justify-center gap-2 animate-pulse">
                                {suggestions.map((s, i) => (
                                    <button key={i} onClick={() => clickSuggestion(s)} className="suggestion-btn">
                                        {s}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="flex gap-4 mb-8">
                        <button 
                            onClick={() => { setRole('luxury_sales'); setSuggestions([]); }}
                            className={`px-6 py-3 rounded-xl text-xs font-bold tracking-wider transition-all duration-300 ${role === 'luxury_sales' ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-400'}`}
                        >
                            ELIZABETH
                        </button>
                        <button 
                            onClick={() => { setRole('default'); setSuggestions([]); }}
                            className={`px-6 py-3 rounded-xl text-xs font-bold tracking-wider transition-all duration-300 ${role === 'default' ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-400'}`}
                        >
                            JAMES
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
