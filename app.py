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
app = FastAPI(title="Founder AI (Streaming)", version="11.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 3. STREAMING LOGIC
# This sends text word-by-word so the connection never times out.
async def stream_conversation(user_text: str, websocket: WebSocket):
    system_prompt = (
        "You are a professional Sales Closer. "
        "Goal: Book a meeting. "
        "Keep answers under 20 words. End with a question."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]

    full_response = ""
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", 
                f"{OLLAMA_URL}/api/chat", 
                json={
                    "model": AI_MODEL, 
                    "messages": messages, 
                    "stream": True,  # ENABLE STREAMING
                    "options": {"temperature": 0.6, "num_predict": 50}
                },
                timeout=60.0 # Longer timeout allowed for streaming
            ) as response:
                
                async for line in response.aiter_lines():
                    if not line: continue
                    
                    try:
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            word = chunk["message"]["content"]
                            full_response += word
                            
                            # Send chunk to UI immediately
                            await websocket.send_json({
                                "type": "chunk", 
                                "content": word
                            })
                            
                        if chunk.get("done", False):
                            break
                    except:
                        pass
        
        # Stream finished, tell UI to speak
        await websocket.send_json({
            "type": "end", 
            "full_text": full_response
        })

    except Exception as e:
        print(f"Stream Error: {e}")
        error_msg = "I lost the connection."
        await websocket.send_json({"type": "chunk", "content": error_msg})
        await websocket.send_json({"type": "end", "full_text": error_msg})

# 4. WEBSOCKET HANDLER
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🔗 Client Connected")
    
    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue
            
            # 1. Acknowledge Receipt
            await websocket.send_json({"type": "status", "content": "Thinking..."})
            
            # 2. Start Streaming
            await stream_conversation(data, websocket)
            
            # 3. Reset Status
            await websocket.send_json({"type": "status", "content": "Listening..."})
            
    except WebSocketDisconnect:
        print("📴 Client Disconnected")

# 5. FRONTEND (STREAMING READY)
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Founder AI (Streaming)</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0f172a; color: #fff; font-family: 'Segoe UI', sans-serif; }
        .orb-container {
            width: 140px; height: 140px;
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
            const [aiState, setAiState] = React.useState("idle"); // idle, listening, thinking, speaking
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
                        // "Thinking..."
                        setAiState("thinking");
                        setResponse(""); // Clear old response
                    }
                    else if (data.type === "chunk") {
                        // Append text as it arrives
                        setResponse(prev => prev + data.content);
                    }
                    else if (data.type === "end") {
                        // Full sentence done, speak it
                        speakResponse(data.full_text);
                    }
                };

                // Init Speech
                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = false; // Important: Stop after 1 sentence
                    recognition.current.lang = 'en-US';

                    recognition.current.onstart = () => {
                        if (isConversationActive.current) setAiState("listening");
                    };
                    recognition.current.onend = () => {
                        if (isConversationActive.current && aiState === "listening") {
                            // If it stopped but we didn't get a result, restart
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

            const speakResponse = (text) => {
                setAiState("speaking");
                window.speechSynthesis.cancel();
                
                const utterance = new SpeechSynthesisUtterance(text);
                window.currentUtterance = utterance; // Keep alive

                let voices = window.speechSynthesis.getVoices();
                const setVoice = () => {
                    utterance.voice = voices.find(v => v.name === "Google US English") || voices[0];
                };
                if(voices.length) setVoice();
                else window.speechSynthesis.onvoiceschanged = () => { voices = window.speechSynthesis.getVoices(); setVoice(); };

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
                    window.speechSynthesis.resume(); // Unlock audio
                    setAiState("listening");
                    try { recognition.current.start(); } catch(e) {}
                }
            };

            // Test Audio Button
            const testAudio = () => {
                const u = new SpeechSynthesisUtterance("Audio check.");
                window.speechSynthesis.speak(u);
            };

            return (
                <div className="flex flex-col items-center w-full px-4">
                    <div className="mb-8 text-center">
                        <h1 className="text-3xl font-bold tracking-widest text-sky-400">FOUNDER AI</h1>
                        <p className="text-gray-500 text-xs mt-2">{status}</p>
                        <button onClick={testAudio} className="mt-2 text-[10px] border border-gray-700 px-2 py-1 rounded text-gray-400 hover:text-white">Test Audio</button>
                    </div>

                    <div className={`orb-container ${aiState}`} onClick={toggle}>
                        <i className={`fas fa-${
                            aiState === 'listening' ? 'microphone' : 
                            aiState === 'speaking' ? 'volume-up' : 
                            aiState === 'thinking' ? 'sync fa-spin' : 'power-off'
                        } text-4xl text-white`}></i>
                    </div>

                    <div className="mt-6 text-center h-6">
                        <span className="text-sm font-mono text-gray-400 uppercase tracking-widest">{aiState}</span>
                    </div>

                    <div className="w-full max-w-md mt-6 min-h-[120px] flex flex-col justify-end space-y-4">
                        {transcript && (
                            <div className="self-end bg-slate-800 text-sky-100 px-4 py-2 rounded-2xl rounded-tr-none text-sm max-w-[90%]">
                                {transcript}
                            </div>
                        )}
                        {response && (
                            <div className="self-start text-white text-lg font-medium leading-snug">
                                {response}
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
