#!/usr/bin/env python3
"""Gate.io取引所実装テスト"""

import asyncio
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.exchanges.gateio import GateioExchange

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_gateio_rest_api():
    """Gate.io REST API テスト"""
    
    print("=" * 60)
    print("🟡 Gate.io REST API テスト")
    print("=" * 60)
    
    exchange = GateioExchange(testnet=False)
    
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
                      f"Last: {ticker.last}, Volume: {ticker.volume_24h}")
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
            
        # シンボル変換テスト
        print(f"\n🔄 シンボル変換テスト...")
        total_tests += 1
        
        test_conversions = [
            ("BTC", "BTC_USDT"),
            ("ETH", "ETH_USDT"),
            ("SOL", "SOL_USDT"),
            ("BNB", "BNB_USDT")
        ]
        
        conversion_success = 0
        for unified, expected in test_conversions:
            gateio_symbol = exchange._convert_symbol_to_gateio(unified)
            back_to_unified = exchange._convert_symbol_from_gateio(gateio_symbol)
            
            if gateio_symbol == expected and back_to_unified == unified:
                print(f"✅ {unified} <-> {gateio_symbol}")
                conversion_success += 1
            else:
                print(f"❌ {unified} -> {gateio_symbol} (expected {expected})")
                
        if conversion_success == len(test_conversions):
            success_count += 1
            
        # 接続状態テスト
        print(f"\n🔌 接続状態テスト...")
        total_tests += 1
        
        print(f"WebSocket接続状態: {exchange.is_connected}")
        print(f"取引所名: {exchange.name}")
        print(f"WebSocket URL: {exchange.ws_url}")
        print(f"REST URL: {exchange.rest_url}")
        success_count += 1
            
    except Exception as e:
        print(f"❌ Gate.io REST APIテストエラー: {e}")
        logger.error(f"Gate.io REST API test failed: {e}", exc_info=True)
        
    print("\n" + "=" * 60)
    print(f"🏁 テスト結果: {success_count}/{total_tests} 成功")
    print("=" * 60)
    
    return success_count == total_tests


async def test_gateio_websocket():
    """Gate.io WebSocket テスト（短時間）"""
    
    print("\n" + "=" * 60)
    print("🔌 Gate.io WebSocket テスト")
    print("=" * 60)
    
    exchange = GateioExchange(testnet=False)
    
    # 価格更新カウンター
    price_updates = {"count": 0, "symbols": set()}
    
    async def price_callback(exchange_name: str, ticker):
        """価格更新コールバック"""
        price_updates["count"] += 1
        price_updates["symbols"].add(ticker.symbol)
        
        if price_updates["count"] <= 10:  # 最初の10件のみ表示
            print(f"📊 [{exchange_name}] {ticker.symbol}: "
                  f"Bid: {ticker.bid}, Ask: {ticker.ask}, Last: {ticker.last}")
    
    # コールバック登録
    exchange.add_price_callback(price_callback)
    
    test_symbols = ["BTC", "ETH", "SOL"]
    
    try:
        # WebSocket接続
        print(f"\n🚀 WebSocket接続中...")
        await exchange.connect_websocket(test_symbols)
        
        print(f"✅ 接続成功! 購読シンボル: {test_symbols}")
        print("📊 価格データを受信中... (15秒間)")
        print("-" * 60)
        
        # 15秒間データを受信
        await asyncio.sleep(15)
        
        print(f"\n📈 受信統計:")
        print(f"   総更新数: {price_updates['count']}")
        print(f"   受信シンボル: {list(price_updates['symbols'])}")
        
        if price_updates["count"] > 0:
            print("✅ WebSocketデータ受信成功")
            return True
        else:
            print("⚠️ WebSocketデータ受信なし")
            return False
            
    except Exception as e:
        print(f"\n❌ WebSocketテストエラー: {e}")
        logger.error(f"Gate.io WebSocket test failed: {e}", exc_info=True)
        return False
        
    finally:
        # 接続を切断
        print("\n🔌 WebSocket切断中...")
        await exchange.disconnect_websocket()
        print("✅ 切断完了")


async def main():
    """メイン関数"""
    
    print("🧪 Gate.io取引所実装テスト")
    print("=" * 60)
    
    # REST APIテストを実行
    rest_success = await test_gateio_rest_api()
    
    if rest_success:
        print("\n🎉 REST APIテスト成功!")
        
        # WebSocketテストを実行
        print("\nWebSocketテストを実行します...")
        await asyncio.sleep(2)  # 少し待機
        
        ws_success = await test_gateio_websocket()
        
        if ws_success:
            print("\n🚀 全テスト成功!")
            return 0
        else:
            print("\n⚠️ WebSocketテストが失敗しました")
            return 1
    else:
        print("\n❌ REST APIテストが失敗しました")
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