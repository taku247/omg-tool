#!/usr/bin/env python3
"""Hyperliquid WebSocket統合テスト - 実際のWebSocketデータ形式確認"""

import asyncio
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_websocket_l2book_real_data():
    """実際のWebSocketからL2Bookデータを受信してテスト"""
    
    print("🔍 Hyperliquid WebSocket L2Book 統合テスト")
    print("=" * 60)
    
    exchange = HyperliquidExchange()
    
    # 受信したティッカーデータを保存
    received_tickers = []
    l2book_parse_errors = []
    
    async def price_callback(exchange_name, ticker):
        """価格更新コールバック"""
        received_tickers.append(ticker)
        if len(received_tickers) <= 5:  # 最初の5個だけ表示
            print(f"📊 受信成功: {ticker.symbol} - "
                  f"Bid={ticker.bid}, Ask={ticker.ask}, Mid={ticker.last}")
    
    # エラーキャッチ用にログハンドラーを追加
    class ErrorCatcher(logging.Handler):
        def emit(self, record):
            if "Error parsing L2 book data" in record.getMessage():
                l2book_parse_errors.append(record.getMessage())
    
    error_catcher = ErrorCatcher()
    logging.getLogger("src.exchanges.hyperliquid").addHandler(error_catcher)
    
    # コールバック登録
    exchange.add_price_callback(price_callback)
    
    try:
        print("🚀 WebSocket接続開始...")
        
        # WebSocket接続（BTCのみテスト）
        await exchange.connect_websocket(["BTC"])
        
        print("✅ 接続成功! L2Bookデータ受信中...")
        print("⏱️ 10秒間監視...")
        
        # 10秒間データ受信
        await asyncio.sleep(10)
        
        # 結果検証
        print(f"\n📈 テスト結果:")
        print(f"   受信ティッカー数: {len(received_tickers)}")
        print(f"   L2Book解析エラー数: {len(l2book_parse_errors)}")
        
        if l2book_parse_errors:
            print(f"\n❌ L2Book解析エラーが発生:")
            for error in l2book_parse_errors[:3]:  # 最初の3個のエラーを表示
                print(f"   {error}")
            return False
        
        if len(received_tickers) == 0:
            print("❌ ティッカーデータが受信されませんでした")
            return False
        
        # ティッカーデータの妥当性確認
        valid_tickers = 0
        for ticker in received_tickers[:10]:  # 最初の10個を確認
            if (ticker.symbol == "BTC" and 
                ticker.bid > 0 and 
                ticker.ask > 0 and 
                ticker.ask > ticker.bid):
                valid_tickers += 1
        
        print(f"   有効ティッカー数: {valid_tickers}/{min(len(received_tickers), 10)}")
        
        if valid_tickers >= 5:  # 少なくとも5個有効なデータが必要
            print("✅ WebSocket L2Book統合テスト成功!")
            return True
        else:
            print("❌ 有効なティッカーデータが不足")
            return False
        
    except Exception as e:
        print(f"❌ WebSocket統合テストエラー: {e}")
        logger.error(f"WebSocket integration test failed: {e}", exc_info=True)
        return False
        
    finally:
        # 接続を切断
        print("\n🔌 WebSocket切断中...")
        await exchange.disconnect_websocket()
        print("✅ 切断完了")


async def test_message_processing_flow():
    """メッセージ処理フローのテスト"""
    
    print("\n" + "=" * 60)
    print("🔧 メッセージ処理フロー単体テスト")
    print("=" * 60)
    
    exchange = HyperliquidExchange()
    
    # 実際のWebSocketメッセージデータを模擬
    mock_l2book_message = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1750507485538,
            "levels": [
                [
                    {"px": "103891.0", "sz": "1.4292", "n": 9},
                    {"px": "103890.0", "sz": "0.52403", "n": 6}
                ],
                [
                    {"px": "103892.0", "sz": "2.68933", "n": 10},
                    {"px": "103893.0", "sz": "0.1899", "n": 5}
                ]
            ]
        }
    }
    
    processed_tickers = []
    
    async def test_callback(exchange_name, ticker):
        processed_tickers.append(ticker)
        print(f"📊 処理成功: {ticker.symbol} - Bid={ticker.bid}, Ask={ticker.ask}")
    
    exchange.add_price_callback(test_callback)
    
    try:
        # メッセージ処理をテスト
        await exchange._process_message(mock_l2book_message)
        
        if len(processed_tickers) == 1:
            ticker = processed_tickers[0]
            if (ticker.symbol == "BTC" and
                ticker.bid == 103891.0 and 
                ticker.ask == 103892.0):
                print("✅ メッセージ処理フローテスト成功!")
                return True
            else:
                print(f"❌ ティッカーデータが期待値と異なります: {ticker}")
                return False
        else:
            print(f"❌ 処理されたティッカー数が異常: {len(processed_tickers)}")
            return False
            
    except Exception as e:
        print(f"❌ メッセージ処理フローエラー: {e}")
        return False


async def main():
    """メイン関数"""
    
    print("🧪 Hyperliquid WebSocket L2Book 統合テスト実行")
    
    # 1. メッセージ処理フローテスト
    flow_success = await test_message_processing_flow()
    
    # 2. 実際のWebSocketテスト
    websocket_success = await test_websocket_l2book_real_data()
    
    print("\n" + "=" * 60)
    print("🏁 統合テスト結果")
    print("=" * 60)
    print(f"メッセージ処理フロー: {'✅ 成功' if flow_success else '❌ 失敗'}")
    print(f"WebSocket統合: {'✅ 成功' if websocket_success else '❌ 失敗'}")
    
    if flow_success and websocket_success:
        print("\n🎉 全統合テスト成功!")
        print("Hyperliquid L2Book解析修正が正常に動作しています")
        return 0
    else:
        print("\n❌ 統合テスト失敗")
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
        logger.error(f"Integration test failed: {e}", exc_info=True)
        sys.exit(1)