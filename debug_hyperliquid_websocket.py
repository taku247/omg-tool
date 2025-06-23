#!/usr/bin/env python3
"""Hyperliquid WebSocketデータ形式デバッグ"""

import asyncio
import json
import websockets
import logging
from pathlib import Path
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def debug_hyperliquid_websocket():
    """Hyperliquid WebSocketの生データを確認"""
    
    print("🔍 Hyperliquid WebSocket データ形式デバッグ")
    print("=" * 60)
    
    ws_url = "wss://api.hyperliquid.xyz/ws"
    
    try:
        # WebSocket接続
        async with websockets.connect(ws_url) as websocket:
            print(f"✅ 接続成功: {ws_url}")
            
            # BTC L2Bookを購読
            subscription = {
                "method": "subscribe",
                "subscription": {
                    "type": "l2Book",
                    "coin": "BTC"
                }
            }
            
            await websocket.send(json.dumps(subscription))
            print(f"📊 L2Book購読送信: {subscription}")
            
            message_count = 0
            max_messages = 5
            
            print("\n📦 受信メッセージ:")
            print("-" * 60)
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    message_count += 1
                    
                    print(f"\n🔥 メッセージ #{message_count}:")
                    print(f"📄 RAWデータ: {json.dumps(data, indent=2)}")
                    
                    # データ構造を分析
                    if "data" in data:
                        msg_data = data["data"]
                        print(f"🔧 data フィールド: {type(msg_data)} = {msg_data}")
                        
                        if isinstance(msg_data, dict):
                            print("📋 データ構造分析:")
                            for key, value in msg_data.items():
                                print(f"   {key}: {type(value)} = {value}")
                                
                                if key == "levels" and isinstance(value, list):
                                    print(f"   📊 levels詳細 (最初の3要素):")
                                    for i, level in enumerate(value[:3]):
                                        print(f"      [{i}]: {type(level)} = {level}")
                                        
                                        if isinstance(level, list):
                                            print(f"         配列要素: {[f'{j}:{v}' for j, v in enumerate(level)]}")
                                        elif isinstance(level, dict):
                                            print(f"         辞書キー: {list(level.keys())}")
                    
                    # 十分なサンプルを取得したら終了
                    if message_count >= max_messages:
                        break
                        
                except json.JSONDecodeError as e:
                    print(f"❌ JSON解析エラー: {e}")
                except Exception as e:
                    print(f"❌ 処理エラー: {e}")
                    
    except Exception as e:
        print(f"❌ WebSocket接続エラー: {e}")
        
    print(f"\n🏁 デバッグ終了 ({message_count} メッセージ処理)")


if __name__ == "__main__":
    try:
        asyncio.run(debug_hyperliquid_websocket())
    except KeyboardInterrupt:
        print("\n👋 中断されました")
    except Exception as e:
        print(f"💥 エラー: {e}")