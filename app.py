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
# Ideally use a model with good reasoning like mistral, llama3, or qwen2.5
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 

# 2. APP SETUP
app = FastAPI(title="Founder AI (Human Marketer)", version="19.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. FOUNDER LEVEL KNOWLEDGE BASE ---
# PSYCHOLOGY: High Status, Low Attachment, Radical Candor.
BUSINESS_PROMPTS = {
    "real_estate": (
        "You are Sarah, a Luxury Property Specialist. "
        "PSYCHOLOGY: You are busy and high-status. You don't 'need' the sale, which makes them want you more. "
        "FRAMEWORK: "
        "1. Discovery: Find out 'Why now?' (Pain). "
        "2. Agitate: 'What happens if you don't find a place by next month?' "
        "3. Solution: Only show properties that fit perfectly. "
        "RULES: "
        "- Keep responses SHORT (Max 2 sentences). "
        "- Always end with a specific question to guide them. "
        "- If they ask price, say: 'It varies. What's the range where you feel comfortable stopping?' "
        "OPENER: 'Hi, this is Sarah. I saw your inquiry. Are you looking to move asap, or just getting a feel for the market?'"
    ),

    "dentist": (
        "You are Jessica, the Treatment Coordinator at Elite Dental. "
        "PSYCHOLOGY: Warm authority. You are the expert's gatekeeper. "
        "FRAMEWORK: "
        "1. Empathy First: Validate their fear or pain immediately. "
        "2. Authority: 'Dr. Smith is the specialist for exactly that.' "
        "3. Scarcity: 'We actually have a cancellation for tomorrow, otherwise it's a 3-week wait.' "
        "RULES: "
        "- Speak like a caring friend. "
        "- DETECT LANGUAGE & REPLY IN IT. "
        "- Never just say 'yes'. Say 'Yes, and here is how it works...'"
        "OPENER: 'Thanks for calling Elite Dental. Are you calling about a specific tooth bothering you, or just a cleaning?'"
    ),

    "marketing": (
        "You are Alex, a Fractional CMO (Founder Mode). "
        "PSYCHOLOGY: Brutally honest. You only work with winners. "
        "FRAMEWORK (Gap Selling): "
        "1. Current State: 'What's your revenue right now?' "
        "2. Desired State: 'Where do you want to be in 90 days?' "
        "3. The Gap: 'Why haven't you hit that yet? What's breaking?' "
        "RULES: "
        "- Do NOT pitch services until you know the bottleneck. "
        "- Use 'Got it', 'Interesting', 'Let's be real'. "
        "- If they are vague, challenge them: 'I can't help if you don't know your numbers.' "
        "OPENER: 'This is Alex. To respect your time, are you currently running ads, or are you relying purely on referrals?'"
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
    # Context window: Keep System + Last 12 for better flow retention
    if len(history) > 13: 
        history = [history[0]] + history[-12:]
    local_memory[session_id] = history

# 5. STREAMING LOGIC
async def stream_conversation(session_id: str, user_text: str, websocket: WebSocket, business_id: str):
    base_prompt = BUSINESS_PROMPTS.get(business_id, BUSINESS_PROMPTS["real_estate"])
    
    # SYSTEM INSTRUCTION FOR HUMAN REALISM
    system_instruction = (
        f"{base_prompt} "
        "CRITICAL INSTRUCTIONS FOR AUDIO CONVERSATION: "
        "1. ACT NATURAL: Use fillers like 'Hmm', 'I see', 'Exactly'. "
        "2. NO LISTS: Do not use bullet points. Speak in flow. "
        "3. SHORTNESS: Spoken conversation is short. Max 30 words per turn. "
        "4. DETECT LANGUAGE: If user speaks Spanish, reply Spanish [ES]. "
        "5. THE LOOP: Answer their thought, then IMMEDIATELY ask a relevant question to keep the lead."
    )

    history = await get_chat_history(session_id)
    
    if not history: 
        history = [{"role": "system", "content": system_instruction}]

    # Append user message
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
                        "temperature": 0.8, # Higher temp for more 'human' variance
                        "top_p": 0.9,
                        "num_predict": 100   # Keep generation short
                    }
                },
                timeout=60.0
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
        
        # Save history
        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_resp}
        ])
        
        # Signal end of turn
        await websocket.send_json({"type": "end", "full_text": full_resp})

    except Exception as e:
        print(f"Error: {e}")
        err = "I'm losing signal for a second, say that again?"
        await websocket.send_json({"type": "chunk", "content": err})
        await websocket.send_json({"type": "end", "full_text": err})

# 6. WEBSOCKET
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, biz: str = Query("real_estate")):
    await websocket.accept()
    session_id = str(id(websocket))
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            
            # The UI handles the "Thinking" state, backend just processes
            await stream_conversation(session_id, data, websocket, biz)
            
    except WebSocketDisconnect:
        if session_id in local_memory: del local_memory[session_id]

# 7. FRONTEND (HUMAN-LIKE UI)
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Founder AI Closer</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0b0f19; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        /* The Soul Orb */
        .orb-wrapper {
            position: relative;
            width: 180px; height: 180px;
            display: flex; justify-content: center; align-items: center;
            margin: 0 auto;
        }
        .orb {
            width: 100%; height: 100%;
            border-radius: 50%;
            background: radial-gradient(circle at 30% 30%, #4f46e5, #0f172a);
            box-shadow: 0 0 60px rgba(79, 70, 229, 0.3);
            transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            z-index: 10;
            display: flex; justify-content: center; align-items: center;
        }
        
        /* States */
        .orb.idle { border: 2px solid #334155; transform: scale(1); }
        
        .orb.listening { 
            background: radial-gradient(circle at 50% 50%, #ef4444, #7f1d1d);
            box-shadow: 0 0 80px rgba(239, 68, 68, 0.5);
            animation: breathe 2s infinite ease-in-out;
            border: none;
        }
        
        .orb.thinking { 
            background: radial-gradient(circle at 50% 50%, #f59e0b, #78350f);
            box-shadow: 0 0 60px rgba(245, 158, 11, 0.4);
            animation: pulse-fast 1s infinite;
        }
        
        .orb.speaking { 
            background: radial-gradient(circle at 50% 50%, #10b981, #064e3b);
            box-shadow: 0 0 90px rgba(16, 185, 129, 0.6);
            animation: speak-pulse 0.3s infinite alternate;
        }

        @keyframes breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.05); } }
        @keyframes pulse-fast { 0% { opacity: 0.8; transform: scale(0.98); } 50% { opacity: 1; transform: scale(1.02); } 100% { opacity: 0.8; transform: scale(0.98); } }
        @keyframes speak-pulse { 0% { transform: scale(1); } 100% { transform: scale(1.08); } }
        
        .glow-ring {
            position: absolute; width: 100%; height: 100%; border-radius: 50%;
            border: 1px solid rgba(255,255,255,0.1);
            animation: spin 10s linear infinite;
        }
        @keyframes spin { 100% { transform: rotate(360deg); } }
    </style>
</head>
<body class="h-screen flex flex-col items-center justify-center overflow-hidden">
    <div id="root" class="w-full max-w-2xl"></div>

    <script type="text/babel">
        function App() {
            const [status, setStatus] = React.useState("Disconnected");
            const [aiState, setAiState] = React.useState("idle"); // idle, listening, thinking, speaking
            const [transcript, setTranscript] = React.useState("");
            const [aiText, setAiText] = React.useState("");
            const [selectedBiz, setSelectedBiz] = React.useState("marketing");

            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const isConversationActive = React.useRef(false);
            const silenceTimer = React.useRef(null);
            
            // To handle natural interruptions, we need to stop audio if user speaks
            const synth = window.speechSynthesis;

            const connectWebSocket = (bizId) => {
                if(ws.current) ws.current.close();
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(`${protocol}${window.location.host}/ws?biz=${bizId}`);
                
                ws.current.onopen = () => setStatus("Connected to " + bizId.replace("_", " ").toUpperCase());
                ws.current.onclose = () => setStatus("Offline");
                
                ws.current.onmessage = (e) => {
                    const data = JSON.parse(e.data);
                    
                    if (data.type === "chunk") {
                        if (aiState !== "speaking") setAiState("speaking"); 
                        setAiText(prev => prev + data.content);
                    }
                    else if (data.type === "end") {
                        speakResponse(data.full_text);
                    }
                };
            };

            React.useEffect(() => {
                connectWebSocket(selectedBiz);
                return () => { if(ws.current) ws.current.close(); };
            }, [selectedBiz]);

            // --- SPEECH RECOGNITION SETUP ---
            React.useEffect(() => {
                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = true; 
                    recognition.current.interimResults = true;
                    recognition.current.lang = 'en-US'; // Default, AI auto-detects content

                    recognition.current.onstart = () => {
                        if (isConversationActive.current) setAiState("listening");
                    };

                    recognition.current.onend = () => {
                        // Auto-restart if active, unless we are currently generating/speaking
                        if (isConversationActive.current && aiState === "listening") {
                             try { recognition.current.start(); } catch(e) {}
                        }
                    };

                    recognition.current.onresult = (event) => {
                        // Stop AI speech if user interrupts
                        if (synth.speaking) {
                            synth.cancel();
                            setAiState("listening");
                        }

                        let finalPhrase = "";
                        for (let i = event.resultIndex; i < event.results.length; ++i) {
                            if (event.results[i].isFinal) {
                                finalPhrase += event.results[i][0].transcript;
                            }
                        }
                        
                        if (finalPhrase) {
                            setTranscript(finalPhrase);
                            handleUserSilence(finalPhrase);
                        }
                    };
                }
            }, [aiState]);

            // --- NATURAL PAUSE LOGIC ---
            // A "Perfect Marketer" waits 1.5s to see if you are done, then strikes.
            const handleUserSilence = (text) => {
                if (silenceTimer.current) clearTimeout(silenceTimer.current);
                
                silenceTimer.current = setTimeout(() => {
                    if (text.trim().length > 1) {
                        setAiState("thinking");
                        setAiText(""); 
                        recognition.current.stop(); // Stop listening while thinking
                        ws.current.send(text);
                    }
                }, 1200); // 1.2s silence trigger = Natural conversation pace
            };

            // --- TEXT TO SPEECH ENGINE ---
            const speakResponse = (fullText) => {
                // Strip language tags for audio
                let textToSpeak = fullText.replace(/\[.*?\]/g, '').trim();
                
                // If it's empty or just thinking chars, ignore
                if (!textToSpeak) return;

                const utterance = new SpeechSynthesisUtterance(textToSpeak);
                
                // --- FIND THE BEST VOICE ---
                const voices = synth.getVoices();
                // Priority: Google US English -> Microsoft Zira -> Default
                let selectedVoice = voices.find(v => v.name.includes("Google US English"));
                if (!selectedVoice) selectedVoice = voices.find(v => v.name.includes("Zira")); 
                if (!selectedVoice) selectedVoice = voices.find(v => v.lang === "en-US");

                if (selectedVoice) {
                    utterance.voice = selectedVoice;
                    // Slightly faster = more confident/business-like
                    utterance.rate = 1.1; 
                    utterance.pitch = 1.0; 
                }

                utterance.onend = () => {
                    setAiState("listening");
                    setTranscript(""); // Clear user text for next turn
                    if (isConversationActive.current) {
                        try { recognition.current.start(); } catch(e) {}
                    }
                };

                synth.speak(utterance);
            };

            const toggleConversation = () => {
                if (isConversationActive.current) {
                    isConversationActive.current = false;
                    recognition.current.stop();
                    synth.cancel();
                    setAiState("idle");
                } else {
                    isConversationActive.current = true;
                    // Ensure voices are loaded
                    synth.getVoices(); 
                    setAiState("listening");
                    try { recognition.current.start(); } catch(e) {}
                }
            };

            return (
                <div className="flex flex-col items-center w-full px-4">
                    
                    <div className="mb-10 text-center">
                        <div className="text-[10px] font-bold text-slate-500 tracking-[0.3em] uppercase mb-2">
                            Automated Sales Agent
                        </div>
                        <h1 className="text-4xl font-bold text-white drop-shadow-2xl">
                            {selectedBiz === 'real_estate' ? 'SARAH' : 
                             selectedBiz === 'dentist' ? 'JESSICA' : 'ALEX'}
                        </h1>
                        <p className="text-slate-400 text-sm mt-1 italic">
                            {selectedBiz === 'real_estate' ? 'Luxury Property Specialist' : 
                             selectedBiz === 'dentist' ? 'Patient Care Coordinator' : 'Fractional CMO'}
                        </p>
                    </div>

                    <div className="orb-wrapper" onClick={toggleConversation}>
                        <div className="glow-ring"></div>
                        <div className={`orb ${aiState}`}>
                            <i className={`fas fa-${
                                aiState === 'listening' ? 'microphone' : 
                                aiState === 'speaking' ? 'wave-square' : 
                                aiState === 'thinking' ? 'brain' : 'power-off'
                            } text-4xl text-white opacity-90`}></i>
                        </div>
                    </div>

                    <div className="mt-8 min-h-[60px] text-center w-full max-w-md">
                        {aiState === 'listening' && (
                            <p className="text-slate-500 text-sm animate-pulse">Listening...</p>
                        )}
                        {aiState === 'thinking' && (
                            <p className="text-amber-500 text-sm font-mono">Analyzing sentiment...</p>
                        )}
                        {transcript && aiState === 'listening' && (
                            <p className="text-slate-300 mt-2 text-lg">"{transcript}"</p>
                        )}
                    </div>

                    <div className="mt-8 w-full max-w-lg">
                        {aiText && (
                            <div className="text-center">
                                <span className="text-2xl font-light text-white leading-relaxed">
                                    {aiText}
                                </span>
                            </div>
                        )}
                    </div>

                    {/* SETTINGS BAR */}
                    <div className="fixed bottom-8 flex gap-4 bg-slate-900/50 backdrop-blur-md p-2 rounded-full border border-slate-800">
                        <button 
                            onClick={() => setSelectedBiz('marketing')}
                            className={`px-4 py-2 rounded-full text-xs font-bold transition-all ${selectedBiz === 'marketing' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
                        >
                            MARKETER
                        </button>
                        <button 
                            onClick={() => setSelectedBiz('real_estate')}
                            className={`px-4 py-2 rounded-full text-xs font-bold transition-all ${selectedBiz === 'real_estate' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
                        >
                            REALTOR
                        </button>
                        <button 
                            onClick={() => setSelectedBiz('dentist')}
                            className={`px-4 py-2 rounded-full text-xs font-bold transition-all ${selectedBiz === 'dentist' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
                        >
                            DENTIST
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
