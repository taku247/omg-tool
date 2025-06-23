#!/usr/bin/env python3
"""Bitget WebSocket デバッグ"""

import asyncio
import websockets
import json
import logging

# ログ設定
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def debug_bitget_websocket():
    """Bitget WebSocket 接続デバッグ"""
    
    print("🔍 Bitget WebSocket デバッグ")
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
            
            # ティッカー購読テスト
            ticker_subscription = {
                "op": "subscribe",
                "args": [{
                    "instType": "UMCBL",
                    "channel": "ticker",
                    "instId": "BTCUSDT_UMCBL"
                }]
            }
            
            print(f"📡 ティッカー購読送信: {json.dumps(ticker_subscription, indent=2)}")
            await websocket.send(json.dumps(ticker_subscription))
            
            # 板情報購読テスト
            books_subscription = {
                "op": "subscribe",
                "args": [{
                    "instType": "UMCBL", 
                    "channel": "books",
                    "instId": "BTCUSDT_UMCBL"
                }]
            }
            
            print(f"📡 板情報購読送信: {json.dumps(books_subscription, indent=2)}")
            await websocket.send(json.dumps(books_subscription))
            
            # メッセージ受信
            print("\n📊 メッセージ受信中... (10秒間)")
            print("-" * 60)
            
            message_count = 0
            start_time = asyncio.get_event_loop().time()
            
            while (asyncio.get_event_loop().time() - start_time) < 10:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    message_count += 1
                    
                    try:
                        data = json.loads(message)
                        print(f"📨 メッセージ #{message_count}:")
                        print(f"   Raw: {message}")
                        print(f"   Parsed: {json.dumps(data, indent=2)}")
                        print("-" * 40)
                        
                    except json.JSONDecodeError:
                        print(f"📨 非JSON メッセージ #{message_count}: {message}")
                        
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("❌ WebSocket接続が切断されました")
                    break
                    
            print(f"\n📈 結果: {message_count}件のメッセージを受信")
            
    except Exception as e:
        print(f"❌ エラー: {e}")
        logger.error(f"WebSocket debug failed: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(debug_bitget_websocket())
    except KeyboardInterrupt:
        print("\n👋 デバッグ中断されました")
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")