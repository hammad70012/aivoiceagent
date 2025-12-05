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
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 

# 2. APP SETUP
app = FastAPI(title="Founder AI (Multi-Business)", version="16.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- 3. BUSINESS KNOWLEDGE BASE (EDIT THIS AREA) ---
# This is where you define the "Brain" for each of your businesses.
BUSINESS_PROMPTS = {
    "default": (
        "You are Alex, a generic Sales Assistant. "
        "Goal: Ask the user what business they run. "
        "Keep answers short."
    ),
    
    "real_estate": (
        "You are Sarah, a Luxury Real Estate Agent for 'Skyline Properties'. "
        "GOAL: Qualify the buyer and book a property viewing. "
        "CONTEXT: We sell condos in Downtown ($500k+) and Villas ($2M+). "
        "BEHAVIOR: "
        "1. Ask if they are looking for investment or a home to live in. "
        "2. Ask for their budget range. "
        "3. If they seem serious, ask 'When are you available for a viewing?' "
        "4. DETECT LANGUAGE and reply in that language (add [EN], [ES], etc). "
        "5. Keep answers under 20 words. Always end with a question."
    ),

    "dentist": (
        "You are the Front Desk Coordinator for 'Bright Smile Dental'. "
        "GOAL: Book a patient for a checkup or cleaning. "
        "CONTEXT: Cleaning is $99. Whitening is $199. We are open Mon-Sat. "
        "BEHAVIOR: "
        "1. Ask if they are in pain or just need a checkup. "
        "2. Be empathetic and gentle. "
        "3. If they ask about price, tell them, then ask 'Does 10 AM tomorrow work?' "
        "4. DETECT LANGUAGE and reply in that language. "
        "5. Keep answers under 20 words."
    ),

    "marketing": (
        "You are Mike, the Growth Director at 'ScaleUp Agency'. "
        "GOAL: Book a Strategy Call with a business owner. "
        "CONTEXT: We help e-commerce brands scale using Facebook Ads. Min budget $2k/mo. "
        "BEHAVIOR: "
        "1. Ask what their current monthly revenue is. "
        "2. Ask if they are currently running ads. "
        "3. If qualified, say 'I have an idea for you. Can we chat for 10 mins?' "
        "4. DETECT LANGUAGE and reply in that language. "
        "5. Keep answers under 20 words."
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
    if len(history) > 11: 
        system_msg = history[0]
        recent_history = history[-10:] 
        history = [system_msg] + recent_history
    local_memory[session_id] = history

# 5. STREAMING LOGIC
async def stream_conversation(session_id: str, user_text: str, websocket: WebSocket, business_id: str):
    
    # LOAD THE CORRECT BUSINESS PROMPT
    # If business_id doesn't exist, use 'default'
    system_prompt_text = BUSINESS_PROMPTS.get(business_id, BUSINESS_PROMPTS["default"])
    
    history = await get_chat_history(session_id)
    
    # Inject the specific prompt if history is empty
    if not history: 
        history = [{"role": "system", "content": system_prompt_text}]
    else:
        # If switching businesses mid-stream, update the system prompt (Optional advanced feature)
        # For now, we assume one session = one business
        pass

    messages_to_send = history + [{"role": "user", "content": user_text}]
    full_response = ""
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", 
                f"{OLLAMA_URL}/api/chat", 
                json={
                    "model": AI_MODEL, 
                    "messages": messages_to_send, 
                    "stream": True,
                    "options": {"temperature": 0.6, "num_predict": 100}
                },
                timeout=60.0
            ) as response:
                async for line in response.aiter_lines():
                    if not line: continue
                    try:
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            word = chunk["message"]["content"]
                            full_response += word
                            await websocket.send_json({"type": "chunk", "content": word})
                        if chunk.get("done", False): break
                    except: pass
        
        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_response}
        ])
        await websocket.send_json({"type": "end", "full_text": full_response})

    except Exception:
        err = "[EN] Connection error."
        await websocket.send_json({"type": "chunk", "content": err})
        await websocket.send_json({"type": "end", "full_text": err})

# 6. WEBSOCKET HANDLER (Accepts ?biz=dentist)
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, biz: str = Query("default")):
    await websocket.accept()
    session_id = str(id(websocket))
    print(f"🔗 Client Connected to Business: {biz}")
    
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            
            await websocket.send_json({"type": "status", "content": "Thinking..."})
            # Pass the 'biz' ID to the streaming function
            await stream_conversation(session_id, data, websocket, biz)
            await websocket.send_json({"type": "status", "content": "Listening..."})
            
    except WebSocketDisconnect:
        if session_id in local_memory: del local_memory[session_id]

# 7. FRONTEND (BUSINESS SELECTOR)
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Multi-Business AI</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0f172a; color: #fff; font-family: 'Segoe UI', sans-serif; }
        .orb-container {
            width: 150px; height: 150px;
            border-radius: 50%;
            background: radial-gradient(circle, #0f2e4a 0%, #020617 100%);
            border: 2px solid #1e3a8a;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            transition: all 0.4s ease;
            box-shadow: 0 0 30px rgba(56, 189, 248, 0.1);
            margin: 0 auto;
        }
        .orb-container:hover { transform: scale(1.05); border-color: #38bdf8; }
        .orb-container.listening { border-color: #ef4444; box-shadow: 0 0 50px rgba(239, 68, 68, 0.4); animation: pulse-red 1.5s infinite; }
        .orb-container.speaking { border-color: #22c55e; box-shadow: 0 0 50px rgba(34, 197, 94, 0.4); animation: pulse-green 1.5s infinite; }
        .orb-container.thinking { border-color: #f59e0b; animation: spin 1s linear infinite; }
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
            const [aiState, setAiState] = React.useState("idle"); 
            const [transcript, setTranscript] = React.useState("");
            const [response, setResponse] = React.useState("");
            
            // BUSINESS SELECTION STATE
            const [selectedBiz, setSelectedBiz] = React.useState("real_estate");

            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const isConversationActive = React.useRef(false);

            // Connect to WebSocket with Business Param
            const connectWebSocket = (bizId) => {
                if(ws.current) ws.current.close();
                
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                // PASSING THE BUSINESS ID HERE
                ws.current = new WebSocket(protocol + window.location.host + "/ws?biz=" + bizId);
                
                ws.current.onopen = () => setStatus("Connected: " + bizId.toUpperCase());
                ws.current.onclose = () => setStatus("Disconnected");
                
                ws.current.onmessage = (e) => {
                    const data = JSON.parse(e.data);
                    if (data.type === "status") {
                        if(aiState !== "speaking") setAiState("thinking");
                        if(data.content === "Thinking...") setResponse("");
                    }
                    else if (data.type === "chunk") {
                        setResponse(prev => prev + data.content);
                    }
                    else if (data.type === "end") {
                        speakResponse(data.full_text);
                    }
                };
            };

            // Re-connect when dropdown changes
            React.useEffect(() => {
                connectWebSocket(selectedBiz);
                return () => { if(ws.current) ws.current.close(); };
            }, [selectedBiz]);

            // Init Speech
            React.useEffect(() => {
                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = false; 
                    
                    recognition.current.onstart = () => { if (isConversationActive.current) setAiState("listening"); };
                    
                    // INFINITE LOOP LOGIC
                    recognition.current.onend = () => {
                        if (!isConversationActive.current) { setAiState("idle"); return; }
                        if (aiState === "speaking") return;
                        try { recognition.current.start(); } catch(e) {}
                    };

                    recognition.current.onresult = (event) => {
                        const text = event.results[0][0].transcript;
                        setTranscript(text);
                        setAiState("thinking");
                        ws.current.send(text);
                    };
                }
            }, [aiState]);

            const speakResponse = (fullText) => {
                setAiState("speaking");
                window.speechSynthesis.cancel();
                
                let langCode = 'en';
                let textToSpeak = fullText;
                const tagMatch = fullText.match(/^\[([A-Z]{2})\]/);
                if (tagMatch) {
                    langCode = tagMatch[1].toLowerCase();
                    textToSpeak = fullText.replace(tagMatch[0], '').trim();
                }

                const utterance = new SpeechSynthesisUtterance(textToSpeak);
                window.currentUtterance = utterance; 
                const voices = window.speechSynthesis.getVoices();
                let selectedVoice = voices.find(v => v.lang.startsWith(langCode) && v.name.includes("Google"));
                if (!selectedVoice) selectedVoice = voices.find(v => v.lang.startsWith(langCode));
                if (selectedVoice) utterance.voice = selectedVoice;

                utterance.onend = () => {
                    if (isConversationActive.current) {
                        setAiState("listening");
                        try { recognition.current.start(); } catch(e) {}
                    } else {
                        setAiState("idle");
                    }
                };
                window.speechSynthesis.speak(utterance);
            };

            const toggle = () => {
                if (isConversationActive.current) {
                    isConversationActive.current = false;
                    recognition.current.stop();
                    window.speechSynthesis.cancel();
                    setAiState("idle");
                } else {
                    isConversationActive.current = true;
                    window.speechSynthesis.resume(); 
                    setAiState("listening");
                    try { recognition.current.start(); } catch(e) {}
                }
            };

            const cleanResponse = response.replace(/^\[[A-Z]{2}\]/, '');

            return (
                <div className="flex flex-col items-center w-full px-4">
                    <div className="mb-6 text-center w-full">
                        <h1 className="text-3xl font-bold tracking-[0.2em] text-sky-400 drop-shadow-lg">BUSINESS AI</h1>
                        <p className="text-gray-600 text-[10px] mt-2 uppercase">{status}</p>

                        {/* BUSINESS SELECTOR DROPDOWN */}
                        <div className="mt-4">
                            <label className="text-xs text-gray-400 mr-2">SELECT BUSINESS:</label>
                            <select 
                                value={selectedBiz} 
                                onChange={(e) => {
                                    setResponse("");
                                    setTranscript("");
                                    setSelectedBiz(e.target.value);
                                }}
                                className="bg-slate-800 text-white text-xs p-2 rounded border border-slate-600 outline-none"
                            >
                                <option value="real_estate">Real Estate Agent</option>
                                <option value="dentist">Dental Clinic</option>
                                <option value="marketing">Marketing Agency</option>
                            </select>
                        </div>
                    </div>

                    <div className={`orb-container ${aiState}`} onClick={toggle}>
                        <i className={`fas fa-${
                            aiState === 'listening' ? 'microphone' : 
                            aiState === 'speaking' ? 'volume-up' : 
                            aiState === 'thinking' ? 'sync fa-spin' : 'power-off'
                        } text-5xl text-white`}></i>
                    </div>

                    <div className="mt-8 text-center h-6">
                        <span className="text-xs font-mono text-sky-200 uppercase tracking-widest animate-pulse">
                            {aiState === 'idle' ? 'TAP TO START' : aiState}
                        </span>
                    </div>

                    <div className="w-full max-w-lg mt-8 space-y-4">
                        {transcript && (
                            <div className="flex justify-end">
                                <div className="bg-slate-800 text-sky-100 px-5 py-3 rounded-2xl rounded-tr-none text-sm shadow-lg max-w-[85%]">
                                    {transcript}
                                </div>
                            </div>
                        )}
                        {cleanResponse && (
                            <div className="flex justify-start">
                                <div className="text-white text-lg font-medium leading-relaxed drop-shadow-md">
                                    {cleanResponse}
                                </div>
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
