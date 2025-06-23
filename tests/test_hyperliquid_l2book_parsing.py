#!/usr/bin/env python3
"""Hyperliquid L2Book解析ロジックの単体テスト"""

import asyncio
import unittest
import sys
from pathlib import Path
from decimal import Decimal

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange


class TestHyperliquidL2BookParsing(unittest.TestCase):
    """Hyperliquid L2Book解析のテストクラス"""
    
    def setUp(self):
        """テスト用のHyperliquidExchangeインスタンスを作成"""
        self.exchange = HyperliquidExchange()
    
    def test_parse_l2book_data_correct_format(self):
        """正しいL2Bookデータ形式の解析テスト"""
        
        # 実際のHyperliquid WebSocketから取得したデータ形式
        l2book_data = {
            "coin": "BTC",
            "time": 1750507485538,
            "levels": [
                # Bids (levels[0])
                [
                    {"px": "103891.0", "sz": "1.4292", "n": 9},
                    {"px": "103890.0", "sz": "0.52403", "n": 6},
                    {"px": "103889.0", "sz": "1.4993", "n": 5}
                ],
                # Asks (levels[1])
                [
                    {"px": "103892.0", "sz": "2.68933", "n": 10},
                    {"px": "103893.0", "sz": "0.1899", "n": 5},
                    {"px": "103894.0", "sz": "0.00011", "n": 1}
                ]
            ]
        }
        
        # 非同期メソッドをテスト
        async def run_test():
            ticker = await self.exchange._parse_l2book_data(l2book_data)
            return ticker
        
        ticker = asyncio.run(run_test())
        
        # テスト検証
        self.assertIsNotNone(ticker, "Tickerが正常に生成されること")
        self.assertEqual(ticker.symbol, "BTC", "シンボルが正しく設定されること")
        
        # Bid価格（最高価格）
        self.assertEqual(ticker.bid, Decimal("103891.0"), "最良Bid価格が正しく設定されること")
        
        # Ask価格（最低価格）
        self.assertEqual(ticker.ask, Decimal("103892.0"), "最良Ask価格が正しく設定されること")
        
        # Mid価格
        expected_mid = (Decimal("103891.0") + Decimal("103892.0")) / 2
        self.assertEqual(ticker.last, expected_mid, "Mid価格が正しく計算されること")
        self.assertEqual(ticker.mark_price, expected_mid, "Mark価格が正しく設定されること")
        
        print(f"✅ 正常データ解析成功: Bid={ticker.bid}, Ask={ticker.ask}, Mid={ticker.last}")
    
    def test_parse_l2book_data_empty_levels(self):
        """空のlevelsデータの処理テスト"""
        
        l2book_data = {
            "coin": "BTC",
            "time": 1750507485538,
            "levels": []
        }
        
        async def run_test():
            ticker = await self.exchange._parse_l2book_data(l2book_data)
            return ticker
        
        ticker = asyncio.run(run_test())
        self.assertIsNone(ticker, "空のlevelsの場合はNoneが返されること")
        print("✅ 空データ処理成功: None返却")
    
    def test_parse_l2book_data_insufficient_levels(self):
        """不十分なlevelsデータ（1つのみ）の処理テスト"""
        
        l2book_data = {
            "coin": "BTC", 
            "time": 1750507485538,
            "levels": [
                # Bidsのみ、Asksなし
                [
                    {"px": "103891.0", "sz": "1.4292", "n": 9}
                ]
            ]
        }
        
        async def run_test():
            ticker = await self.exchange._parse_l2book_data(l2book_data)
            return ticker
        
        ticker = asyncio.run(run_test())
        self.assertIsNone(ticker, "levels長が2未満の場合はNoneが返されること")
        print("✅ 不十分データ処理成功: None返却")
    
    def test_parse_l2book_data_no_coin(self):
        """coinフィールドなしデータの処理テスト"""
        
        l2book_data = {
            "time": 1750507485538,
            "levels": [
                [{"px": "103891.0", "sz": "1.4292", "n": 9}],
                [{"px": "103892.0", "sz": "2.68933", "n": 10}]
            ]
        }
        
        async def run_test():
            ticker = await self.exchange._parse_l2book_data(l2book_data)
            return ticker
        
        ticker = asyncio.run(run_test())
        self.assertIsNone(ticker, "coinフィールドがない場合はNoneが返されること")
        print("✅ coinなしデータ処理成功: None返却")
    
    def test_parse_l2book_data_empty_bids_or_asks(self):
        """空のbidsまたはasksの処理テスト"""
        
        l2book_data = {
            "coin": "BTC",
            "time": 1750507485538,
            "levels": [
                [],  # 空のbids
                [{"px": "103892.0", "sz": "2.68933", "n": 10}]  # 正常なasks
            ]
        }
        
        async def run_test():
            ticker = await self.exchange._parse_l2book_data(l2book_data)
            return ticker
        
        ticker = asyncio.run(run_test())
        self.assertIsNone(ticker, "bidsまたはasksが空の場合はNoneが返されること")
        print("✅ 空bids/asks処理成功: None返却")
    
    def test_parse_l2book_data_invalid_price_format(self):
        """無効な価格形式の処理テスト"""
        
        l2book_data = {
            "coin": "BTC",
            "time": 1750507485538, 
            "levels": [
                [{"px": "invalid_price", "sz": "1.4292", "n": 9}],
                [{"px": "103892.0", "sz": "2.68933", "n": 10}]
            ]
        }
        
        async def run_test():
            ticker = await self.exchange._parse_l2book_data(l2book_data)
            return ticker
        
        ticker = asyncio.run(run_test())
        self.assertIsNone(ticker, "無効な価格形式の場合はNoneが返されること")
        print("✅ 無効価格形式処理成功: None返却")

    def test_parse_l2book_data_multiple_price_levels(self):
        """複数価格レベルの正しいソート処理テスト"""
        
        # わざと価格順序を混在させたデータ
        l2book_data = {
            "coin": "ETH",
            "time": 1750507485538,
            "levels": [
                # Bids (高い順にソートされるべき)
                [
                    {"px": "2440.0", "sz": "1.0", "n": 1},
                    {"px": "2441.0", "sz": "2.0", "n": 2},  # より高い価格
                    {"px": "2439.0", "sz": "0.5", "n": 1}
                ],
                # Asks (低い順にソートされるべき)
                [
                    {"px": "2443.0", "sz": "1.5", "n": 2},
                    {"px": "2442.0", "sz": "1.0", "n": 1},  # より低い価格
                    {"px": "2444.0", "sz": "2.0", "n": 3}
                ]
            ]
        }
        
        async def run_test():
            ticker = await self.exchange._parse_l2book_data(l2book_data)
            return ticker
        
        ticker = asyncio.run(run_test())
        
        # 最良Bid（最高価格）が正しく選ばれることを確認
        self.assertEqual(ticker.bid, Decimal("2441.0"), "最良Bid（最高価格）が正しく選ばれること")
        
        # 最良Ask（最低価格）が正しく選ばれることを確認
        self.assertEqual(ticker.ask, Decimal("2442.0"), "最良Ask（最低価格）が正しく選ばれること")
        
        print(f"✅ 複数レベルソート成功: Best Bid={ticker.bid}, Best Ask={ticker.ask}")


def run_tests():
    """テスト実行"""
    print("🧪 Hyperliquid L2Book解析テスト開始")
    print("=" * 60)
    
    # テストスイートを作成
    test_suite = unittest.TestLoader().loadTestsFromTestCase(TestHyperliquidL2BookParsing)
    
    # テスト実行
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("🎉 全テスト成功!")
        print(f"実行: {result.testsRun}件, 成功: {result.testsRun}件")
        return True
    else:
        print("❌ テスト失敗")
        print(f"実行: {result.testsRun}件, 失敗: {len(result.failures)}件, エラー: {len(result.errors)}件")
        return False


if __name__ == "__main__":
    try:
        success = run_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"💥 テスト実行エラー: {e}")
        sys.exit(1)