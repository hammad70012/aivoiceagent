import os
import json
import asyncio
import sys
import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 1. CONFIGURATION
load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 

# 2. APP SETUP
app = FastAPI(title="Founder AI (Multi-Lang)", version="14.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 3. MEMORY (Sliding Window)
local_memory = {}

async def get_chat_history(session_id: str):
    if session_id in local_memory:
        return local_memory[session_id]
    return []

async def update_chat_history(session_id: str, new_messages: list):
    history = await get_chat_history(session_id)
    history.extend(new_messages)
    # Keep System + Last 10 messages
    if len(history) > 11: 
        system_msg = history[0]
        recent_history = history[-10:] 
        history = [system_msg] + recent_history
    local_memory[session_id] = history

# 4. STREAMING LOGIC (MULTI-LANG SUPPORT)
async def stream_conversation(session_id: str, user_text: str, websocket: WebSocket):
    
    # --- MULTI-LANGUAGE PROMPT ---
    system_prompt = (
        "You are an elite Sales Closer. "
        "Goal: Book a meeting. "
        "Rules: "
        "1. DETECT the language of the user. "
        "2. REPLY IN THE EXACT SAME LANGUAGE. "
        "3. START your response with a language code in brackets. Examples: [EN] for English, [ES] for Spanish, [FR] for French, [HI] for Hindi, [DE] for German, [ZH] for Chinese. "
        "4. Keep answer under 20 words. End with a question."
    )
    
    history = await get_chat_history(session_id)
    if not history:
        history = [{"role": "system", "content": system_prompt}]
    
    current_exchange = [{"role": "user", "content": user_text}]
    messages_to_send = history + current_exchange

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
                            
                            # Send chunk to UI
                            await websocket.send_json({"type": "chunk", "content": word})
                            
                        if chunk.get("done", False):
                            break
                    except:
                        pass
        
        # Save Memory
        await update_chat_history(session_id, [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": full_response}
        ])

        # End of stream -> Speak
        await websocket.send_json({"type": "end", "full_text": full_response})

    except Exception as e:
        print(f"Error: {e}")
        error_msg = "[EN] Connection unstable."
        await websocket.send_json({"type": "chunk", "content": error_msg})
        await websocket.send_json({"type": "end", "full_text": error_msg})

# 5. WEBSOCKET HANDLER
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            
            await websocket.send_json({"type": "status", "content": "Thinking..."})
            await stream_conversation(session_id, data, websocket)
            await websocket.send_json({"type": "status", "content": "Listening..."})
            
    except WebSocketDisconnect:
        if session_id in local_memory:
            del local_memory[session_id]

# 6. FRONTEND (SMART VOICE SWITCHER)
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Founder AI (Multi-Lang)</title>
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
            
            const ws = React.useRef(null);
            const recognition = React.useRef(null);
            const isConversationActive = React.useRef(false);

            React.useEffect(() => {
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(protocol + window.location.host + "/ws");
                
                ws.current.onopen = () => setStatus("Connected");
                ws.current.onclose = () => setStatus("Disconnected");
                
                ws.current.onmessage = (e) => {
                    const data = JSON.parse(e.data);
                    
                    if (data.type === "status") {
                        setAiState("thinking");
                        setResponse(""); 
                    }
                    else if (data.type === "chunk") {
                        setResponse(prev => prev + data.content);
                    }
                    else if (data.type === "end") {
                        speakResponse(data.full_text);
                    }
                };

                // Init Speech (AUTO LANGUAGE DETECTION FROM BROWSER)
                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = false; 
                    // REMOVED 'en-US' hardcode. Now it uses your Browser/OS default language.
                    // recognition.current.lang = 'en-US'; 

                    recognition.current.onstart = () => {
                        if (isConversationActive.current) setAiState("listening");
                    };
                    recognition.current.onend = () => {
                        if (isConversationActive.current && aiState === "listening") {
                             try { recognition.current.start(); } catch(e) {}
                        }
                    };
                    recognition.current.onresult = (event) => {
                        const text = event.results[0][0].transcript;
                        setTranscript(text);
                        setAiState("thinking");
                        ws.current.send(text);
                    };
                }
            }, [aiState]);

            // --- SMART MULTI-LANGUAGE SPEAKER ---
            const speakResponse = (fullText) => {
                setAiState("speaking");
                window.speechSynthesis.cancel();
                
                // 1. Detect Language from Tag [EN], [ES], etc.
                let langCode = 'en'; // Default
                let textToSpeak = fullText;

                // Parse Tag
                const tagMatch = fullText.match(/^\[([A-Z]{2})\]/);
                if (tagMatch) {
                    langCode = tagMatch[1].toLowerCase(); // es, fr, hi, de
                    textToSpeak = fullText.replace(tagMatch[0], '').trim(); // Remove tag for speech
                }

                // 2. Select Best Voice for that Language
                const utterance = new SpeechSynthesisUtterance(textToSpeak);
                window.currentUtterance = utterance; 

                const voices = window.speechSynthesis.getVoices();
                
                // PRIORITY: Google Native -> Any Native -> Default
                let selectedVoice = voices.find(v => v.lang.startsWith(langCode) && v.name.includes("Google"));
                
                if (!selectedVoice) {
                    selectedVoice = voices.find(v => v.lang.startsWith(langCode));
                }

                if (selectedVoice) {
                    utterance.voice = selectedVoice;
                    // Adjust rate for languages
                    utterance.rate = langCode === 'es' || langCode === 'hi' ? 0.9 : 1.0; 
                }

                console.log(`Speaking [${langCode}] using voice:`, selectedVoice ? selectedVoice.name : "System Default");

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

            // Clean display text (Remove [EN] tags for UI)
            const cleanResponse = response.replace(/^\[[A-Z]{2}\]/, '');

            return (
                <div className="flex flex-col items-center w-full px-4">
                    <div className="mb-10 text-center">
                        <h1 className="text-3xl font-bold tracking-[0.2em] text-sky-400 drop-shadow-lg">GLOBAL AGENT</h1>
                        <p className="text-gray-600 text-[10px] mt-2 uppercase">{status}</p>
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
