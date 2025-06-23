#!/usr/bin/env python3
"""Bitget取引所単体での接続テスト"""

import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.exchanges.bitget import BitgetExchange

async def test_bitget():
    exchange = BitgetExchange()
    print("🧪 Bitget単体接続テスト開始...")
    
    try:
        await exchange.connect_websocket(['BTC'])
        print("📡 接続中...")
        await asyncio.sleep(5)
        print("✅ Bitget接続成功")
        await exchange.disconnect_websocket()
        print("🔌 切断完了")
    except Exception as e:
        print(f"❌ Bitget接続エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_bitget())