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
app = FastAPI(title="Polite Professional AI", version="22.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. POLITE & DISCIPLINED KNOWLEDGE BASE ---
BUSINESS_PROMPTS = {
    "default": (
        "You are James, a Senior Client Success Manager. "
        "BEHAVIOR: Extremely polite, patient, and respectful. "
        "RULES: "
        "1. NEVER interrupt. Acknowledge what the user said first (e.g., 'I understand,' 'That makes perfect sense'). "
        "2. Speak clearly and calmly. "
        "3. Keep responses concise (2-3 sentences) to respect the client's time. "
        "4. Ask permission before moving to the next step (e.g., 'May I ask a few details about...?'). "
        "OPENER: 'Hello, this is James. Thank you for connecting. How may I assist you today?'"
    ),
    "luxury_sales": (
        "You are Elizabeth, a Senior Consultant for Premium Accounts. "
        "BEHAVIOR: You offer 'White Glove' service. calm, unhurried, and attentive. "
        "STRATEGY: "
        "1. Active Listening: Repeat back the key concern to show you understood. "
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

# 5. LOGIC FOR DISCIPLINED RESPONSE
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
                        "temperature": 0.6, # Lower temp for consistent, polite behavior
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
                            
                            # Only send when a FULL sentence is complete to ensure correct intonation.
                            if re.search(r'[.!?:]\s*$', sentence_buffer):
                                await websocket.send_json({
                                    "type": "audio_sentence", 
                                    "content": sentence_buffer.strip()
                                })
                                sentence_buffer = "" 
                        
                        if chunk.get("done", False): break
                    except: pass
        
        # Send any remaining polite closing
        if sentence_buffer.strip():
            await websocket.send_json({"type": "audio_sentence", "content": sentence_buffer.strip()})

        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_resp}
        ])
        
        # Signal that the turn is complete
        await websocket.send_json({"type": "turn_complete"})

    except Exception as e:
        err = "I apologize, I didn't quite catch that. Could you please repeat it?"
        await websocket.send_json({"type": "audio_sentence", "content": err})

# 6. WEBSOCKET ROUTE
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

# 7. PROFESSIONAL FRONTEND
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Professional Consultant</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #f3f4f6; color: #1f2937; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
        
        .interface-container {
            background: white;
            width: 100%; max-width: 500px;
            border-radius: 20px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.1);
            overflow: hidden;
            display: flex; flex-direction: column;
            align-items: center;
            padding: 40px 20px;
            border: 1px solid #e5e7eb;
        }

        .avatar-circle {
            width: 100px; height: 100px;
            border-radius: 50%;
            background: #e0f2fe;
            display: flex; align-items: center; justify-content: center;
            margin-bottom: 20px;
            position: relative;
        }

        .avatar-circle.speaking {
            border: 3px solid #0ea5e9;
            animation: pulse-blue 2s infinite;
        }
        
        .avatar-circle.listening {
            border: 3px solid #10b981;
        }

        @keyframes pulse-blue { 0% { box-shadow: 0 0 0 0 rgba(14, 165, 233, 0.4); } 70% { box-shadow: 0 0 0 20px rgba(14, 165, 233, 0); } 100% { box-shadow: 0 0 0 0 rgba(14, 165, 233, 0); } }

        .status-text { font-size: 14px; letter-spacing: 1px; color: #9ca3af; text-transform: uppercase; margin-top: 10px; font-weight: 600; }
        
        .transcript-box {
            margin-top: 30px; min-height: 80px; width: 100%;
            text-align: center; font-size: 18px; color: #374151;
            line-height: 1.6;
        }
    </style>
</head>
<body class="h-screen flex items-center justify-center">
    <div id="root"></div>

    <script type="text/babel">
        function App() {
            // States: 'idle', 'listening', 'thinking', 'speaking'
            const [state, setState] = React.useState("idle"); 
            const [textDisplay, setTextDisplay] = React.useState("Tap the microphone to begin.");
            const [role, setRole] = React.useState("luxury_sales");

            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const synth = window.speechSynthesis;
            const audioQueue = React.useRef([]);
            const silenceTimer = React.useRef(null);
            const isProcessingAudio = React.useRef(false);

            // --- 1. INITIALIZATION ---
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

            // --- 2. MICROPHONE LOGIC (The Disciplined Listener) ---
            const setupRecognition = () => {
                if (!window.SpeechRecognition && !window.webkitSpeechRecognition) return;
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition.current = new SpeechRecognition();
                recognition.current.continuous = true; 
                recognition.current.interimResults = true;
                
                recognition.current.onresult = (event) => {
                    // IF THE AI IS SPEAKING, WE IGNORE INPUT.
                    // This prevents interruption.
                    if (isProcessingAudio.current) return;

                    let finalTranscript = "";
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript;
                    }

                    if (finalTranscript.length > 0) {
                        setTextDisplay('"' + finalTranscript + '"');
                        
                        // 2.5 SECONDS SILENCE (Polite waiting time)
                        if (silenceTimer.current) clearTimeout(silenceTimer.current);
                        silenceTimer.current = setTimeout(() => {
                            sendToAi(finalTranscript);
                        }, 2500); 
                    }
                };
            };

            const sendToAi = (text) => {
                recognition.current.stop(); // Strictly stop listening
                setState("thinking");
                ws.current.send(text);
            };

            // --- 3. SPEAKER LOGIC (The Professional Voice) ---
            const queueAudio = (text) => {
                audioQueue.current.push(text);
                if (!isProcessingAudio.current) {
                    playNextSentence();
                }
            };

            const playNextSentence = () => {
                if (audioQueue.current.length === 0) {
                    // QUEUE FINISHED: Now we politely listen again.
                    isProcessingAudio.current = false;
                    setState("listening");
                    setTextDisplay("Listening...");
                    try { recognition.current.start(); } catch(e){}
                    return;
                }

                isProcessingAudio.current = true;
                setState("speaking");
                
                const txt = audioQueue.current.shift();
                setTextDisplay(txt); // Show subtitle

                const utter = new SpeechSynthesisUtterance(txt);
                
                // --- Voice Selection for Professionalism ---
                const voices = synth.getVoices();
                let v = voices.find(v => v.name.includes("Google US English"));
                if(!v) v = voices.find(v => v.name.includes("Zira"));
                if(v) utter.voice = v;

                utter.rate = 1.0; // Normal, calm speed
                utter.onend = () => {
                    playNextSentence(); // Recursive call for smooth flow
                };
                
                synth.speak(utter);
            };

            const toggleSession = () => {
                if (state === "idle") {
                    setState("listening");
                    setTextDisplay("Listening...");
                    try { recognition.current.start(); } catch(e){}
                } else {
                    setState("idle");
                    recognition.current.stop();
                    synth.cancel();
                    isProcessingAudio.current = false;
                    setTextDisplay("Session Ended.");
                }
            };

            return (
                <div className="interface-container">
                    <div className={`avatar-circle ${state}`}>
                        <i className={`fas fa-${state === 'listening' ? 'microphone' : (state === 'speaking' ? 'user-tie' : (state === 'thinking' ? 'circle-notch fa-spin' : 'power-off'))} text-4xl text-slate-500`}></i>
                    </div>

                    <div className="status-text">{state}</div>

                    <div className="transcript-box">
                        {textDisplay}
                    </div>

                    <div className="mt-8 flex gap-4 w-full justify-center">
                         <button 
                            onClick={toggleSession}
                            className={`px-8 py-3 rounded-full font-bold shadow-lg transition-all ${state === 'idle' ? 'bg-blue-600 text-white hover:bg-blue-700' : 'bg-red-500 text-white hover:bg-red-600'}`}
                        >
                            {state === 'idle' ? 'START CALL' : 'END CALL'}
                        </button>
                    </div>

                    <div className="mt-6">
                        <select 
                            onChange={(e) => setRole(e.target.value)}
                            className="bg-slate-100 text-slate-600 text-xs py-2 px-4 rounded-lg outline-none"
                        >
                            <option value="luxury_sales">Elizabeth (Luxury Consultant)</option>
                            <option value="default">James (Success Manager)</option>
                        </select>
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
