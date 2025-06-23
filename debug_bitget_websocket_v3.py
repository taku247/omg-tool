#!/usr/bin/env python3
"""Bitget WebSocket デバッグ v3 - 正しい形式を探す"""

import asyncio
import websockets
import json

async def debug_bitget_websocket_v3():
    """Bitget WebSocket デバッグ v3"""
    
    print("🔍 Bitget WebSocket デバッグ v3")
    print("=" * 60)
    
    ws_url = "wss://ws.bitget.com/mix/v1/stream"
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print("✅ WebSocket接続成功")
            
            # Bitget公式ドキュメントに基づく正しい形式を試す
            test_formats = [
                # Format 1: mc (mix contracts)
                {
                    "op": "subscribe",
                    "args": [{
                        "instType": "mc",
                        "channel": "ticker",
                        "instId": "BTCUSDT"
                    }]
                },
                # Format 2: 完全なシンボル形式
                {
                    "op": "subscribe", 
                    "args": [{
                        "instType": "mc",
                        "channel": "ticker",
                        "instId": "BTCUSDT_UMCBL"
                    }]
                },
                # Format 3: books (orderbook)
                {  
                    "op": "subscribe",
                    "args": [{
                        "instType": "mc",
                        "channel": "books",
                        "instId": "BTCUSDT"
                    }]
                },
                # Format 4: 異なるチャンネル名を試す
                {
                    "op": "subscribe",
                    "args": [{
                        "instType": "mc", 
                        "channel": "candle1m",
                        "instId": "BTCUSDT"
                    }]
                },
                # Format 5: trade
                {
                    "op": "subscribe",
                    "args": [{
                        "instType": "mc",
                        "channel": "trade",
                        "instId": "BTCUSDT" 
                    }]
                }
            ]
            
            for i, subscription in enumerate(test_formats):
                print(f"\n📡 テスト #{i+1}: {subscription['args'][0]['channel']} / {subscription['args'][0]['instId']}")
                await websocket.send(json.dumps(subscription))
                
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(response)
                    
                    if data.get("event") == "subscribe":
                        print("✅ 購読成功!")
                        print(f"   応答: {json.dumps(data, indent=2)}")
                        
                        # データ受信テスト
                        print("📊 データ受信テスト中...")
                        for _ in range(3):
                            try:
                                message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                                msg_data = json.loads(message)
                                if "data" in msg_data:
                                    print(f"📈 データ受信成功: {json.dumps(msg_data, indent=2)[:300]}...")
                                    return True  # 成功したので終了
                            except asyncio.TimeoutError:
                                continue
                                
                    elif data.get("event") == "error":
                        print(f"❌ エラー: {data.get('msg')} (code: {data.get('code')})")
                    else:
                        print(f"📨 その他の応答: {json.dumps(data, indent=2)}")
                        
                except asyncio.TimeoutError:
                    print("⏰ タイムアウト")
                except json.JSONDecodeError:
                    print("❌ JSON解析エラー")
                    
            print("\n❌ すべてのテストが失敗しました")
            return False
            
    except Exception as e:
        print(f"❌ エラー: {e}")
        return False

if __name__ == "__main__":
    try:
        asyncio.run(debug_bitget_websocket_v3())
    except KeyboardInterrupt:
        print("\n👋 デバッグ中断されました")
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")