#!/usr/bin/env python3
"""Hyperliquid WebSocket接続テスト"""

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


async def price_callback(exchange_name: str, ticker):
    """価格更新コールバック"""
    print(f"[{exchange_name}] {ticker.symbol}: "
          f"Bid: {ticker.bid}, Ask: {ticker.ask}, "
          f"Last: {ticker.last}, Mark: {ticker.mark_price}")


async def test_hyperliquid_websocket():
    """Hyperliquid WebSocket接続テスト"""
    
    print("=" * 60)
    print("🔌 Hyperliquid WebSocket接続テスト開始")
    print("=" * 60)
    
    # Hyperliquid取引所インスタンス作成
    exchange = HyperliquidExchange(testnet=False)
    
    # 価格更新コールバックを追加
    exchange.add_price_callback(price_callback)
    
    # テスト対象シンボル
    test_symbols = ["BTC", "ETH", "SOL"]
    
    try:
        # WebSocket接続
        print(f"\n🚀 WebSocket接続中...")
        await exchange.connect_websocket(test_symbols)
        
        print(f"✅ 接続成功! 購読シンボル: {test_symbols}")
        print("📊 価格データを受信中... (30秒間)")
        print("-" * 60)
        
        # 30秒間データを受信
        await asyncio.sleep(30)
        
    except KeyboardInterrupt:
        print("\n⏹️ ユーザーによる中断")
        
    except Exception as e:
        print(f"\n❌ エラー発生: {e}")
        logger.error(f"WebSocket test failed: {e}", exc_info=True)
        
    finally:
        # 接続を切断
        print("\n🔌 WebSocket切断中...")
        await exchange.disconnect_websocket()
        print("✅ 切断完了")
        
    print("\n" + "=" * 60)
    print("🏁 テスト完了")
    print("=" * 60)


async def test_rest_api():
    """REST API機能テスト"""
    
    print("\n" + "=" * 60)
    print("🌐 Hyperliquid REST API テスト開始")
    print("=" * 60)
    
    exchange = HyperliquidExchange(testnet=False)
    
    if not exchange.has_hyperliquid_lib:
        print("❌ hyperliquidライブラリが見つかりません")
        print("pip install hyperliquid でインストールしてください")
        return
        
    try:
        # ティッカー情報取得テスト
        print("📊 ティッカー情報取得テスト...")
        
        for symbol in ["BTC", "ETH", "SOL"]:
            try:
                ticker = await exchange.get_ticker(symbol)
                print(f"✅ {symbol}: "
                      f"Bid: {ticker.bid}, Ask: {ticker.ask}, "
                      f"Last: {ticker.last}")
                      
            except Exception as e:
                print(f"❌ {symbol}: {e}")
                
        # 板情報取得テスト
        print(f"\n📋 板情報取得テスト (BTC)...")
        try:
            orderbook = await exchange.get_orderbook("BTC", depth=5)
            print(f"✅ BTC板情報:")
            print(f"   Bids: {orderbook.bids[:3]}")
            print(f"   Asks: {orderbook.asks[:3]}")
            
        except Exception as e:
            print(f"❌ 板情報取得エラー: {e}")
            
        # 手数料情報取得テスト
        print(f"\n💰 手数料情報取得テスト...")
        try:
            fees = await exchange.get_trading_fees("BTC")
            print(f"✅ BTC手数料: Maker: {fees['maker_fee']}%, Taker: {fees['taker_fee']}%")
            
        except Exception as e:
            print(f"❌ 手数料取得エラー: {e}")
            
    except Exception as e:
        print(f"❌ REST APIテストエラー: {e}")
        logger.error(f"REST API test failed: {e}", exc_info=True)
        
    print("\n" + "=" * 60)
    print("🏁 REST APIテスト完了")
    print("=" * 60)


async def main():
    """メイン関数"""
    
    print("🧪 Hyperliquid取引所実装テスト")
    print("=" * 60)
    
    # REST APIテストを先に実行
    await test_rest_api()
    
    # WebSocketテストを実行
    response = input("\nWebSocketテストを実行しますか? (y/N): ")
    if response.lower() == 'y':
        await test_hyperliquid_websocket()
    else:
        print("WebSocketテストをスキップしました")
        
    print("\n🎉 全テスト完了!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 テスト中断されました")
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        logger.error(f"Test script failed: {e}", exc_info=True)