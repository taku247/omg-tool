#!/usr/bin/env python3
"""Hyperliquid REST API のみのテスト（ノンインタラクティブ）"""

import asyncio
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_rest_api():
    """REST API機能テスト"""
    
    print("=" * 60)
    print("🌐 Hyperliquid REST API テスト")
    print("=" * 60)
    
    exchange = HyperliquidExchange(testnet=False)
    
    if not exchange.has_hyperliquid_lib:
        print("❌ hyperliquidライブラリが見つかりません")
        print("pip install hyperliquid-python-sdk でインストールしてください")
        return False
        
    success_count = 0
    total_tests = 0
    
    try:
        # ティッカー情報取得テスト
        print("\n📊 ティッカー情報取得テスト...")
        total_tests += 1
        
        test_symbols = ["BTC", "ETH", "SOL"]
        ticker_success = 0
        
        for symbol in test_symbols:
            try:
                ticker = await exchange.get_ticker(symbol)
                print(f"✅ {symbol}: "
                      f"Bid: {ticker.bid}, Ask: {ticker.ask}, "
                      f"Last: {ticker.last}")
                ticker_success += 1
                      
            except Exception as e:
                print(f"❌ {symbol}: {e}")
                
        if ticker_success == len(test_symbols):
            print(f"✅ ティッカーテスト成功: {ticker_success}/{len(test_symbols)}")
            success_count += 1
        else:
            print(f"⚠️ ティッカーテスト部分成功: {ticker_success}/{len(test_symbols)}")
                
        # 板情報取得テスト
        print(f"\n📋 板情報取得テスト...")
        total_tests += 1
        
        try:
            orderbook = await exchange.get_orderbook("BTC", depth=5)
            print(f"✅ BTC板情報取得成功:")
            print(f"   Bids Top 3: {orderbook.bids[:3]}")
            print(f"   Asks Top 3: {orderbook.asks[:3]}")
            print(f"   Timestamp: {orderbook.timestamp}")
            success_count += 1
            
        except Exception as e:
            print(f"❌ 板情報取得エラー: {e}")
            logger.error(f"Orderbook test failed: {e}", exc_info=True)
            
        # 手数料情報取得テスト
        print(f"\n💰 手数料情報取得テスト...")
        total_tests += 1
        
        try:
            fees = await exchange.get_trading_fees("BTC")
            print(f"✅ BTC手数料: Maker: {fees['maker_fee']}%, Taker: {fees['taker_fee']}%")
            success_count += 1
            
        except Exception as e:
            print(f"❌ 手数料取得エラー: {e}")
            
        # 接続状態テスト
        print(f"\n🔌 接続状態テスト...")
        total_tests += 1
        
        print(f"WebSocket接続状態: {exchange.is_connected}")
        print(f"ライブラリ使用可能: {exchange.has_hyperliquid_lib}")
        print(f"取引所名: {exchange.name}")
        success_count += 1
            
    except Exception as e:
        print(f"❌ REST APIテストエラー: {e}")
        logger.error(f"REST API test failed: {e}", exc_info=True)
        
    print("\n" + "=" * 60)
    print(f"🏁 テスト結果: {success_count}/{total_tests} 成功")
    print("=" * 60)
    
    return success_count == total_tests


async def main():
    """メイン関数"""
    
    print("🧪 Hyperliquid REST API テスト")
    
    success = await test_rest_api()
    
    if success:
        print("\n🎉 全テスト成功!")
        return 0
    else:
        print("\n⚠️ 一部テストが失敗しました")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 テスト中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        logger.error(f"Test script failed: {e}", exc_info=True)
        sys.exit(1)