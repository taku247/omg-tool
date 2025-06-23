#!/usr/bin/env python3
"""全取引所のL2Book解析テスト"""

import asyncio
import unittest
import sys
from pathlib import Path
from decimal import Decimal

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange
from src.exchanges.bybit import BybitExchange
from src.exchanges.binance import BinanceExchange


class TestAllExchangesL2Book(unittest.TestCase):
    """全取引所のL2Book解析テスト"""
    
    def test_hyperliquid_l2book_parsing(self):
        """Hyperliquid L2Book解析テスト"""
        
        exchange = HyperliquidExchange()
        
        # Hyperliquid実際のデータ形式
        l2book_data = {
            "coin": "BTC",
            "time": 1750507485538,
            "levels": [
                [{"px": "103891.0", "sz": "1.4292", "n": 9}],
                [{"px": "103892.0", "sz": "2.68933", "n": 10}]
            ]
        }
        
        async def run_test():
            return await exchange._parse_l2book_data(l2book_data)
        
        ticker = asyncio.run(run_test())
        
        self.assertIsNotNone(ticker)
        self.assertEqual(ticker.symbol, "BTC")
        self.assertEqual(ticker.bid, Decimal("103891.0"))
        self.assertEqual(ticker.ask, Decimal("103892.0"))
        print("✅ Hyperliquid L2Book解析成功")
    
    def test_bybit_orderbook_parsing(self):
        """Bybit板情報解析テスト"""
        
        exchange = BybitExchange()
        
        # Bybit実際のデータ形式
        orderbook_data = {
            "b": [["103891.0", "1.4292"]],  # bids
            "a": [["103892.0", "2.68933"]],  # asks
            "ts": 1750507485538
        }
        
        async def run_test():
            return await exchange._parse_orderbook_data("BTC", orderbook_data)
        
        ticker = asyncio.run(run_test())
        
        self.assertIsNotNone(ticker)
        self.assertEqual(ticker.symbol, "BTC")
        self.assertEqual(ticker.bid, Decimal("103891.0"))
        self.assertEqual(ticker.ask, Decimal("103892.0"))
        print("✅ Bybit Orderbook解析成功")
    
    def test_binance_bookticker_parsing(self):
        """Binance BookTicker解析テスト"""
        
        exchange = BinanceExchange()
        
        # Binance実際のデータ形式
        bookticker_data = {
            "b": "103891.0",  # bid price
            "a": "103892.0"   # ask price
        }
        
        async def run_test():
            return await exchange._parse_book_ticker_data("BTC", bookticker_data)
        
        ticker = asyncio.run(run_test())
        
        self.assertIsNotNone(ticker)
        self.assertEqual(ticker.symbol, "BTC")
        self.assertEqual(ticker.bid, Decimal("103891.0"))
        self.assertEqual(ticker.ask, Decimal("103892.0"))
        print("✅ Binance BookTicker解析成功")

    def test_cross_exchange_price_consistency(self):
        """取引所間価格データ一貫性テスト"""
        
        # 同じ市場価格を各取引所形式で表現
        market_bid = Decimal("103891.0")
        market_ask = Decimal("103892.0")
        
        # Hyperliquid
        hl_exchange = HyperliquidExchange()
        hl_data = {
            "coin": "BTC",
            "levels": [
                [{"px": str(market_bid), "sz": "1.0", "n": 1}],
                [{"px": str(market_ask), "sz": "1.0", "n": 1}]
            ]
        }
        
        # Bybit
        bybit_exchange = BybitExchange()
        bybit_data = {
            "b": [[str(market_bid), "1.0"]],
            "a": [[str(market_ask), "1.0"]],
            "ts": 1750507485538
        }
        
        # Binance
        binance_exchange = BinanceExchange()
        binance_data = {
            "b": str(market_bid),
            "a": str(market_ask)
        }
        
        async def run_test():
            hl_ticker = await hl_exchange._parse_l2book_data(hl_data)
            bybit_ticker = await bybit_exchange._parse_orderbook_data("BTC", bybit_data)
            binance_ticker = await binance_exchange._parse_book_ticker_data("BTC", binance_data)
            return hl_ticker, bybit_ticker, binance_ticker
        
        hl_ticker, bybit_ticker, binance_ticker = asyncio.run(run_test())
        
        # 全取引所のbid/askが一致することを確認
        self.assertEqual(hl_ticker.bid, market_bid)
        self.assertEqual(bybit_ticker.bid, market_bid)
        self.assertEqual(binance_ticker.bid, market_bid)
        
        self.assertEqual(hl_ticker.ask, market_ask)
        self.assertEqual(bybit_ticker.ask, market_ask)
        self.assertEqual(binance_ticker.ask, market_ask)
        
        print("✅ 取引所間価格一貫性確認成功")


def run_tests():
    """テスト実行"""
    print("🧪 全取引所L2Book解析テスト開始")
    print("=" * 60)
    
    test_suite = unittest.TestLoader().loadTestsFromTestCase(TestAllExchangesL2Book)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("🎉 全取引所L2Book解析テスト成功!")
        return True
    else:
        print("❌ テスト失敗")
        return False


if __name__ == "__main__":
    try:
        success = run_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"💥 テスト実行エラー: {e}")
        sys.exit(1)