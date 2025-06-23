#!/usr/bin/env python3
"""Bitget WebSocket デバッグ v2"""

import asyncio
import websockets
import json
import logging

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def debug_bitget_websocket_v2():
    """Bitget WebSocket 接続デバッグ v2"""
    
    print("🔍 Bitget WebSocket デバッグ v2")
    print("=" * 60)
    
    ws_url = "wss://ws.bitget.com/mix/v1/stream"
    
    try:
        # WebSocket接続
        print(f"📡 接続中: {ws_url}")
        
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=10
        ) as websocket:
            
            print("✅ WebSocket接続成功")
            
            # 修正されたティッカー購読テスト
            # 可能な形式を試す
            test_formats = [
                # Format 1: 基本形式
                {
                    "op": "subscribe",
                    "args": [{
                        "instType": "mc",
                        "channel": "ticker",
                        "instId": "BTCUSDT_UMCBL"
                    }]
                },
                # Format 2: ProductType指定
                {
                    "op": "subscribe",
                    "args": [{
                        "instType": "UMCBL",
                        "channel": "ticker",
                        "instId": "BTCUSDT"
                    }]
                },
                # Format 3: 別のinstType
                {
                    "op": "subscribe",
                    "args": [{
                        "instType": "umcbl",
                        "channel": "ticker", 
                        "instId": "BTCUSDT_UMCBL"
                    }]
                }
            ]
            
            for i, subscription in enumerate(test_formats):
                print(f"\n📡 テスト #{i+1}: {json.dumps(subscription, indent=2)}")
                await websocket.send(json.dumps(subscription))
                
                # 応答を待つ
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(response)
                    print(f"📨 応答: {json.dumps(data, indent=2)}")
                    
                    if data.get("event") == "subscribe":
                        print("✅ 購読成功!")
                        
                        # 実データを少し待つ
                        print("📊 データ受信中... (5秒間)")
                        for _ in range(5):
                            try:
                                message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                                data = json.loads(message)
                                if "data" in data:
                                    print(f"📈 データ受信: {json.dumps(data, indent=2)[:200]}...")
                                    break
                            except asyncio.TimeoutError:
                                continue
                        break
                        
                except asyncio.TimeoutError:
                    print("⏰ タイムアウト")
                except json.JSONDecodeError as e:
                    print(f"❌ JSON解析エラー: {e}")
                    
    except Exception as e:
        print(f"❌ エラー: {e}")
        logger.error(f"WebSocket debug failed: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(debug_bitget_websocket_v2())
    except KeyboardInterrupt:
        print("\n👋 デバッグ中断されました")
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")