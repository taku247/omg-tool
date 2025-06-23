from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import yaml
import json
import asyncio
from pathlib import Path
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# TODO: Import when modules are available
# from src.core.backtest import BacktestEngine
# from src.core.opportunity_detector import OpportunityDetector
# from src.interfaces.exchange import Exchange

app = FastAPI(title="Arbitrage Bot Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

class ConfigUpdate(BaseModel):
    config_type: str  # 'bot' or 'production'
    config_data: Dict[str, Any]

class BacktestRequest(BaseModel):
    start_date: str
    end_date: str
    initial_balance: float = 10000.0
    config_type: str = 'bot'

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

@app.get("/api/config/{config_type}")
async def get_config(config_type: str):
    config_path = Path(f"../config/{config_type}_config.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Config not found")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    return {"config": config, "type": config_type}

@app.post("/api/config/update")
async def update_config(config_update: ConfigUpdate):
    config_path = Path(f"../config/{config_update.config_type}_config.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Config not found")
    
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config_update.config_data, f, default_flow_style=False, allow_unicode=True)
    
    await manager.broadcast(json.dumps({
        "type": "config_updated",
        "config_type": config_update.config_type
    }))
    
    return {"message": "Config updated successfully"}

@app.post("/api/backtest")
async def run_backtest(request: BacktestRequest):
    try:
        config_path = Path(f"../config/{request.config_type}_config.yaml")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        backtest_id = f"backtest_{int(asyncio.get_event_loop().time())}"
        
        await manager.broadcast(json.dumps({
            "type": "backtest_started",
            "id": backtest_id,
            "params": request.dict()
        }))
        
        # TODO: Implement actual backtest logic
        await asyncio.sleep(2)  # Simulate backtest running
        
        results = {
            "id": backtest_id,
            "total_return": 15.5,
            "sharpe_ratio": 1.8,
            "max_drawdown": -5.2,
            "total_trades": 156,
            "winning_trades": 98,
            "losing_trades": 58,
            "profit_factor": 2.1
        }
        
        await manager.broadcast(json.dumps({
            "type": "backtest_completed",
            "results": results
        }))
        
        return {"status": "completed", "results": results}
        
    except Exception as e:
        await manager.broadcast(json.dumps({
            "type": "backtest_error",
            "error": str(e)
        }))
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal_message(f"Echo: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/exchanges")
async def get_exchanges():
    config_path = Path("../config/bot_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    exchanges = list(config.get('exchanges', {}).keys())
    return {"exchanges": exchanges}

@app.get("/api/trading-pairs")
async def get_trading_pairs():
    config_path = Path("../config/bot_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    pairs = config.get('trading_pairs', [])
    return {"pairs": pairs}

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)