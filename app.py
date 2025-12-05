import os
import json
import asyncio
import sys
import httpx
import uvicorn
import traceback # IMPORT TRACEBACK TO CATCH CRASHES
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 1. CONFIGURATION
load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:1.5b") 

# 2. APP SETUP
app = FastAPI(title="Founder AI (Crash Reporter)", version="8.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 3. SALES LOGIC (WRAPPED IN SAFETY NET)
async def process_conversation(session_id: str, user_text: str, websocket: WebSocket):
    try:
        messages = []
        system_prompt = "You are the Founder. Short answer. End with question."
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": user_text})
        
        await websocket.send_text(f"LOG: 🚀 Sending to Ollama ({AI_MODEL})...")

        ai_response = ""

        # CALL OLLAMA WITH 45s TIMEOUT (VPS IS SLOW)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": AI_MODEL, 
                    "messages": messages, 
                    "stream": False,
                    "options": {"temperature": 0.6, "num_predict": 50}
                },
                timeout=45.0 
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'message' in data:
                    ai_response = data['message']['content']
                await websocket.send_text("LOG: ✅ Ollama Success!")
            else:
                await websocket.send_text(f"LOG: ❌ Ollama Status {response.status_code}")
                ai_response = "Error connecting to brain."

        return ai_response

    except httpx.TimeoutException:
        await websocket.send_text("LOG: ❌ CRITICAL: Ollama Timed Out (VPS too slow)")
        return "I am thinking too slowly. Please wait."
    except Exception as e:
        # SEND THE CRASH REASON TO THE FRONTEND
        error_msg = str(e)
        print(f"CRASH: {error_msg}")
        await websocket.send_text(f"LOG: 🔥 CRASH: {error_msg}")
        return "System crashed."

# 4. WEBSOCKET (KEEPS CONNECTION ALIVE)
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("LOG: 🔗 Connected (Safe Mode)")
    
    try:
        while True:
            data = await websocket.receive_text()
            
            if data == "__PING__":
                await websocket.send_text("__PONG__")
                continue
                
            if not data.strip(): continue
            
            await websocket.send_text(f"LOG: 🎤 Processing: {data}")
            
            # RUN LOGIC
            response = await process_conversation("session", data, websocket)
            
            # SEND RESPONSE
            await websocket.send_text(response)
            
    except WebSocketDisconnect:
        print("Client disconnected normally")
    except Exception as e:
        # CATCH GLOBAL CRASHES
        error_trace = traceback.format_exc()
        print(error_trace)
        try:
            await websocket.send_text(f"LOG: ☠️ FATAL ERROR: {str(e)}")
        except:
            pass

# 5. FRONTEND
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Founder AI (Crash Reporter)</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #000; color: #fff; font-family: monospace; }
        .orb { width: 100px; height: 100px; border-radius: 50%; background: #333; margin: 20px auto; display:flex; align-items:center; justify-content:center; cursor:pointer;}
        .orb.listening { background: red; }
        .orb.speaking { background: green; }
        .orb.processing { background: orange; }
        .log-box { width: 95%; height: 300px; border: 1px solid #444; overflow-y: scroll; padding: 10px; color: #0f0; background: #111; margin: 0 auto; }
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        function App() {
            const [logs, setLogs] = React.useState(["Waiting for connection..."]);
            const [mode, setMode] = React.useState("idle");
            const ws = React.useRef(null);
            const recognition = React.useRef(null);

            const addLog = (msg) => setLogs(p => [msg, ...p]);

            React.useEffect(() => {
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                ws.current = new WebSocket(protocol + window.location.host + "/ws");
                
                ws.current.onopen = () => {
                    addLog("✅ WebSocket Connected");
                    setInterval(() => { if(ws.current.readyState===1) ws.current.send("__PING__"); }, 5000);
                };
                
                ws.current.onclose = () => addLog("⚠️ CONNECTION CLOSED (Server Crashed/Stopped)");

                ws.current.onmessage = (e) => {
                    const text = e.data;
                    if(text === "__PONG__") return;
                    if(text.startsWith("LOG:")) {
                        addLog(text);
                    } else {
                        addLog("🗣️ AI: " + text);
                        speak(text);
                    }
                };

                // SPEECH RECOGNITION
                if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                    recognition.current = new SpeechRecognition();
                    recognition.current.continuous = false; // STOP AFTER 1 SENTENCE TO PREVENT LOOPS
                    recognition.current.lang = 'en-US';

                    recognition.current.onstart = () => setMode("listening");
                    recognition.current.onend = () => { if(mode !== "speaking") setMode("idle"); };
                    recognition.current.onresult = (e) => {
                        const txt = e.results[0][0].transcript;
                        addLog("🎤 You: " + txt);
                        setMode("processing");
                        ws.current.send(txt);
                    };
                }
            }, []);

            const speak = (txt) => {
                setMode("speaking");
                window.speechSynthesis.cancel();
                const u = new SpeechSynthesisUtterance(txt);
                u.onend = () => setMode("idle");
                window.speechSynthesis.speak(u);
            };

            const toggle = () => {
                if(mode === 'idle') {
                    recognition.current.start();
                } else {
                    recognition.current.stop();
                }
            }

            return (
                <div className="p-4 text-center">
                    <h1 className="text-2xl mb-4">CRASH REPORTER</h1>
                    <div className={`orb ${mode}`} onClick={toggle}>
                        {mode === 'idle' ? 'TAP TO SPEAK' : mode}
                    </div>
                    <div className="log-box">
                        {logs.map((l, i) => <div key={i}>{l}</div>)}
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
