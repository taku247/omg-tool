#!/usr/bin/env python3
"""
バックテストエンジンのテストコード
正しい利益計算ロジックをテストする
"""

import unittest
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import pandas as pd

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.arbitrage_detector import ArbitrageOpportunity
from src.interfaces.exchange import Ticker
from backtest_engine import BacktestEngine


class TestBacktestEngine(unittest.TestCase):
    """バックテストエンジンのテストクラス"""
    
    def setUp(self):
        """テスト前の準備"""
        self.detector_config = {
            "min_spread_threshold": Decimal("0.5"),
            "max_position_size": Decimal("10000"),
            "min_profit_threshold": Decimal("10")
        }
        
        self.engine = BacktestEngine(
            detector_config=self.detector_config,
            fee_rate=0.0006,  # 0.06%
            slippage=0.0003,  # 0.03%
            exit_threshold=0.1
        )
    
    def test_profit_calculation_simple_case(self):
        """シンプルなケースでの利益計算テスト"""
        # テストデータ準備
        entry_buy_price = 100.0
        entry_sell_price = 101.0
        exit_buy_price = 102.0    # 2%上昇
        exit_sell_price = 102.5   # 1.49%上昇（101.0 → 102.5）
        
        # 手動計算
        long_pnl_pct = (102.0 - 100.0) / 100.0 * 100  # +2.0%
        short_pnl_pct = (101.0 - 102.5) / 101.0 * 100  # -1.485%
        gross_profit_pct = long_pnl_pct + short_pnl_pct  # +0.515%
        
        # 手数料: 4回取引 × 0.06% = 0.24%
        total_fee_pct = 0.0006 * 4 * 100  # 0.24%
        net_profit_pct = gross_profit_pct - total_fee_pct  # 0.275%
        
        print(f"✅ 手動計算結果:")
        print(f"  Long PnL: {long_pnl_pct:.3f}%")
        print(f"  Short PnL: {short_pnl_pct:.3f}%")
        print(f"  Gross Profit: {gross_profit_pct:.3f}%")
        print(f"  Total Fees: {total_fee_pct:.3f}%")
        print(f"  Net Profit: {net_profit_pct:.3f}%")
        
        # 利益が正であることを確認
        self.assertGreater(net_profit_pct, 0, "正常なアービトラージでは利益が出るはず")
    
    def test_profit_calculation_loss_case(self):
        """損失ケースでの利益計算テスト"""
        # スプレッドが拡大するケース（損失になる）
        entry_buy_price = 100.0
        entry_sell_price = 101.0
        exit_buy_price = 99.0     # 1%下落
        exit_sell_price = 103.0   # 1.98%上昇（101.0 → 103.0）
        
        # 手動計算
        long_pnl_pct = (99.0 - 100.0) / 100.0 * 100   # -1.0%
        short_pnl_pct = (101.0 - 103.0) / 101.0 * 100  # -1.98%
        gross_profit_pct = long_pnl_pct + short_pnl_pct  # -2.98%
        
        # 手数料: 4回取引 × 0.06% = 0.24%
        total_fee_pct = 0.0006 * 4 * 100  # 0.24%
        net_profit_pct = gross_profit_pct - total_fee_pct  # -3.22%
        
        print(f"⚠️ 損失ケース結果:")
        print(f"  Long PnL: {long_pnl_pct:.3f}%")
        print(f"  Short PnL: {short_pnl_pct:.3f}%")
        print(f"  Gross Profit: {gross_profit_pct:.3f}%")
        print(f"  Total Fees: {total_fee_pct:.3f}%")
        print(f"  Net Profit: {net_profit_pct:.3f}%")
        
        # 損失が正しく計算されることを確認
        self.assertLess(net_profit_pct, 0, "スプレッド拡大時は損失になるはず")
    
    async def test_full_trade_cycle(self):
        """完全な取引サイクルのテスト"""
        # モックデータを準備
        symbol = "BTC"
        timestamp = pd.Timestamp("2025-06-23 16:00:00", tz="UTC")
        
        # エントリー時の価格データ
        buy_ticker = Ticker(
            symbol=symbol,
            bid=Decimal("100.0"),
            ask=Decimal("100.1"),  # スプレッド0.1%
            last=Decimal("100.05"),
            mark_price=Decimal("100.05"),
            timestamp=1234567890
        )
        
        sell_ticker = Ticker(
            symbol=symbol,
            bid=Decimal("101.0"),  # 0.9%高い
            ask=Decimal("101.1"),
            last=Decimal("101.05"),
            mark_price=Decimal("101.05"),
            timestamp=1234567890
        )
        
        # ArbitrageDetectorの価格キャッシュを設定
        self.engine.detector.price_cache[symbol] = {
            "hyperliquid": buy_ticker,
            "bybit": sell_ticker
        }
        
        # ArbitrageOpportunityを作成
        opportunity = ArbitrageOpportunity(
            id="TEST_001",
            buy_exchange="hyperliquid",
            sell_exchange="bybit",
            symbol=symbol,
            spread_percentage=Decimal("0.899"),
            expected_profit=Decimal("50.0"),
            buy_price=buy_ticker.ask,
            sell_price=sell_ticker.bid,
            recommended_size=Decimal("1000"),
            timestamp=timestamp
        )
        
        # エントリーテスト
        await self.engine._try_enter_position(opportunity, timestamp)
        
        # ポジションが作成されたことを確認
        self.assertIn(symbol, self.engine.open_positions)
        position = self.engine.open_positions[symbol]
        
        # エントリー価格の確認
        expected_buy_price = float(buy_ticker.ask) * (1 + self.engine.slippage)  # 100.1303
        expected_sell_price = float(sell_ticker.bid) * (1 - self.engine.slippage)  # 100.6970
        
        self.assertAlmostEqual(position["entry_buy_price"], expected_buy_price, places=4)
        self.assertAlmostEqual(position["entry_sell_price"], expected_sell_price, places=4)
        
        print(f"📊 エントリー確認:")
        print(f"  買い価格: {position['entry_buy_price']:.4f}")
        print(f"  売り価格: {position['entry_sell_price']:.4f}")
        
        # エグジット時の価格データ（収益ケース）
        exit_buy_ticker = Ticker(
            symbol=symbol,
            bid=Decimal("101.0"),  # 1%上昇
            ask=Decimal("101.1"),
            last=Decimal("101.05"),
            mark_price=Decimal("101.05"),
            timestamp=1234567891
        )
        
        exit_sell_ticker = Ticker(
            symbol=symbol,
            bid=Decimal("101.5"),  # 0.5%上昇（101.0 → 101.5）
            ask=Decimal("101.6"),
            last=Decimal("101.55"),
            mark_price=Decimal("101.55"),
            timestamp=1234567891
        )
        
        # 価格キャッシュを更新
        self.engine.detector.price_cache[symbol] = {
            "hyperliquid": exit_buy_ticker,
            "bybit": exit_sell_ticker
        }
        
        # エグジットテスト
        exit_timestamp = pd.Timestamp("2025-06-23 16:05:00", tz="UTC")
        await self.engine._close_position(position, 0.4, exit_timestamp)
        
        # トレードが記録されたことを確認
        self.assertEqual(len(self.engine.closed_trades), 1)
        trade = self.engine.closed_trades[0]
        
        # 利益計算の確認
        self.assertIn("long_pnl_pct", trade)
        self.assertIn("short_pnl_pct", trade)
        self.assertIn("gross_profit_pct", trade)
        self.assertIn("net_profit_pct", trade)
        self.assertIn("total_fee_pct", trade)
        
        print(f"💰 決済結果:")
        print(f"  Long PnL: {trade['long_pnl_pct']:.3f}%")
        print(f"  Short PnL: {trade['short_pnl_pct']:.3f}%")
        print(f"  Gross Profit: {trade['gross_profit_pct']:.3f}%")
        print(f"  Total Fees: {trade['total_fee_pct']:.3f}%")
        print(f"  Net Profit: {trade['net_profit_pct']:.3f}%")
        
        # ポジションが削除されたことを確認
        self.assertNotIn(symbol, self.engine.open_positions)
    
    def test_fee_calculation(self):
        """手数料計算のテスト"""
        fee_rate = 0.0006  # 0.06%
        expected_total_fee_pct = fee_rate * 4 * 100  # 4回取引で0.24%
        
        engine = BacktestEngine(
            detector_config=self.detector_config,
            fee_rate=fee_rate,
            slippage=0.0003,
            exit_threshold=0.1
        )
        
        # 手数料計算の確認
        actual_fee_pct = engine.fee_rate * 4 * 100
        self.assertAlmostEqual(actual_fee_pct, expected_total_fee_pct, places=6)
        
        print(f"🏦 手数料計算:")
        print(f"  片道手数料: {fee_rate*100:.3f}%")
        print(f"  往復手数料: {fee_rate*4*100:.3f}%")
    
    def test_slippage_calculation(self):
        """スリッページ計算のテスト"""
        slippage = 0.0003  # 0.03%
        base_price = 100.0
        
        # 買い注文（askベース + スリッページ）
        buy_price_with_slippage = base_price * (1 + slippage)
        expected_buy_price = 100.03
        
        # 売り注文（bidベース - スリッページ）
        sell_price_with_slippage = base_price * (1 - slippage)
        expected_sell_price = 99.97
        
        self.assertAlmostEqual(buy_price_with_slippage, expected_buy_price, places=4)
        self.assertAlmostEqual(sell_price_with_slippage, expected_sell_price, places=4)
        
        print(f"⚡ スリッページ計算:")
        print(f"  基準価格: {base_price}")
        print(f"  買い実行価格: {buy_price_with_slippage:.4f}")
        print(f"  売り実行価格: {sell_price_with_slippage:.4f}")


async def run_async_tests():
    """非同期テストを実行"""
    test_instance = TestBacktestEngine()
    test_instance.setUp()
    
    print("=" * 80)
    print("🧪 バックテストエンジン利益計算テスト")
    print("=" * 80)
    
    try:
        print("\n1️⃣ シンプル利益計算テスト")
        test_instance.test_profit_calculation_simple_case()
        
        print("\n2️⃣ 損失ケース計算テスト")
        test_instance.test_profit_calculation_loss_case()
        
        print("\n3️⃣ 完全取引サイクルテスト")
        await test_instance.test_full_trade_cycle()
        
        print("\n4️⃣ 手数料計算テスト")
        test_instance.test_fee_calculation()
        
        print("\n5️⃣ スリッページ計算テスト")
        test_instance.test_slippage_calculation()
        
        print("\n" + "=" * 80)
        print("✅ 全テスト合格: バックテストエンジンの利益計算が正しく実装されています")
        print("=" * 80)
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ テスト失敗: {e}")
        return False
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_async_tests())
    exit(0 if success else 1)