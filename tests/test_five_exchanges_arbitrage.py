#!/usr/bin/env python3
"""5取引所統合アービトラージテスト"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Optional

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange
from src.exchanges.bybit import BybitExchange
from src.exchanges.binance import BinanceExchange
from src.exchanges.gateio import GateioExchange
from src.exchanges.bitget import BitgetExchange
from src.exchanges.kucoin import KuCoinExchange
from src.core.config import get_config

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FiveExchangeArbitrageMonitor:
    """5取引所アービトラージ監視システム"""
    
    def __init__(self):
        # 設定読み込み
        self.config = get_config()
        
        self.exchanges = {
            "Hyperliquid": HyperliquidExchange(),
            "Bybit": BybitExchange(),
            "Binance": BinanceExchange(),
            "Gate.io": GateioExchange(),
            "Bitget": BitgetExchange(),
            "KuCoin": KuCoinExchange()
        }
        
        # 価格データ保存
        self.latest_prices = {}  # {exchange: {symbol: ticker}}
        self.price_updates = defaultdict(int)  # 更新回数カウント
        self.arbitrage_opportunities = []  # アービトラージ機会
        
        # 統計情報
        self.start_time = None
        self.total_updates = 0
        
        # 設定値を取得
        self.arbitrage_threshold = self.config.get_arbitrage_threshold("default")
        self.display_limits = self.config.get_display_limits()
        
        print(f"📋 設定読み込み完了:")
        print(f"   アービトラージ閾値: {self.arbitrage_threshold}%")
        print(f"   価格更新表示制限: {self.display_limits['price_updates']}件")
        print(f"   アービトラージ表示制限: {self.display_limits['arbitrage_opportunities']}件")
        
    async def price_callback(self, exchange_name: str, ticker):
        """価格更新コールバック"""
        self.total_updates += 1
        self.price_updates[exchange_name] += 1
        
        # 最新価格を保存
        if exchange_name not in self.latest_prices:
            self.latest_prices[exchange_name] = {}
        self.latest_prices[exchange_name][ticker.symbol] = ticker
        
        # アービトラージ機会をチェック
        await self._check_arbitrage_opportunity(ticker.symbol)
        
    async def _check_arbitrage_opportunity(self, symbol: str):
        """アービトラージ機会をチェック"""
        prices = {}
        
        # 各取引所の最新価格を取得
        for exchange_name, exchange_prices in self.latest_prices.items():
            if symbol in exchange_prices:
                ticker = exchange_prices[symbol]
                mid_price = (ticker.bid + ticker.ask) / 2
                prices[exchange_name] = mid_price
        
        # 最低3取引所のデータが必要
        if len(prices) < 3:
            return
            
        # 最高価格と最低価格を特定
        max_exchange = max(prices.keys(), key=lambda x: prices[x])
        min_exchange = min(prices.keys(), key=lambda x: prices[x])
        
        max_price = prices[max_exchange]
        min_price = prices[min_exchange]
        
        # 価格差を計算（パーセンテージ）
        if min_price > 0:
            price_diff_pct = ((max_price - min_price) / min_price) * 100
            
            # 設定された閾値以上の価格差があればアービトラージ機会
            if price_diff_pct >= self.arbitrage_threshold:
                opportunity = {
                    "symbol": symbol,
                    "max_exchange": max_exchange,
                    "max_price": max_price,
                    "min_exchange": min_exchange, 
                    "min_price": min_price,
                    "price_diff": max_price - min_price,
                    "price_diff_pct": price_diff_pct,
                    "timestamp": time.time()
                }
                
                self.arbitrage_opportunities.append(opportunity)
                
                # リアルタイム表示（設定された件数のみ）
                if len(self.arbitrage_opportunities) <= self.display_limits['arbitrage_opportunities']:
                    print(f"\n🚨 アービトラージ機会検出！")
                    print(f"   {symbol}: {max_exchange} ${max_price:,.2f} → {min_exchange} ${min_price:,.2f}")
                    print(f"   価格差: ${max_price - min_price:,.2f} ({price_diff_pct:.3f}%)")
                
    async def connect_all_exchanges(self, symbols: List[str]) -> bool:
        """全取引所に接続"""
        print("🚀 5取引所への接続を開始...")
        print("-" * 60)
        
        connected_count = 0
        
        for name, exchange in self.exchanges.items():
            try:
                print(f"📡 {name} 接続中...")
                
                # コールバック登録
                exchange.add_price_callback(self.price_callback)
                
                # WebSocket接続
                await exchange.connect_websocket(symbols)
                
                if exchange.is_connected:
                    print(f"✅ {name} 接続成功")
                    connected_count += 1
                else:
                    print(f"❌ {name} 接続失敗")
                    
            except Exception as e:
                print(f"❌ {name} 接続エラー: {e}")
                
        print("-" * 60)
        print(f"📊 接続結果: {connected_count}/{len(self.exchanges)} 取引所")
        
        return connected_count >= 3  # 最低3取引所が接続されていればOK
        
    async def disconnect_all_exchanges(self):
        """全取引所から切断"""
        print("\n🔌 全取引所から切断中...")
        
        for name, exchange in self.exchanges.items():
            try:
                if exchange.is_connected:
                    await exchange.disconnect_websocket()
                    print(f"✅ {name} 切断完了")
            except Exception as e:
                print(f"⚠️ {name} 切断エラー: {e}")
                
    def display_statistics(self):
        """統計情報を表示"""
        duration = time.time() - self.start_time if self.start_time else 0
        
        print("\n" + "=" * 70)
        print("📈 5取引所統合監視結果")
        print("=" * 70)
        
        # 接続状況
        connected_exchanges = [name for name, ex in self.exchanges.items() if ex.is_connected]
        print(f"🔌 接続中の取引所: {len(connected_exchanges)}/{len(self.exchanges)}")
        for name in connected_exchanges:
            print(f"   ✅ {name}")
            
        print(f"\n⏱️ 監視時間: {duration:.1f}秒")
        print(f"📊 総価格更新数: {self.total_updates:,}回")
        
        # 取引所別更新数
        print(f"\n📋 取引所別更新数:")
        total_percentage = 0
        for exchange_name, count in sorted(self.price_updates.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / self.total_updates * 100) if self.total_updates > 0 else 0
            total_percentage += percentage
            print(f"   {exchange_name}: {count:,}回 ({percentage:.1f}%)")
            
        # 最新価格表示
        print(f"\n💰 最新価格:")
        symbols = set()
        for exchange_prices in self.latest_prices.values():
            symbols.update(exchange_prices.keys())
            
        for symbol in sorted(symbols):
            prices_line = f"   {symbol}: "
            symbol_prices = []
            
            for exchange_name in self.exchanges.keys():
                if (exchange_name in self.latest_prices and 
                    symbol in self.latest_prices[exchange_name]):
                    ticker = self.latest_prices[exchange_name][symbol]
                    mid_price = (ticker.bid + ticker.ask) / 2
                    symbol_prices.append(f"{exchange_name} ${mid_price:,.2f}")
                    
            prices_line += " vs ".join(symbol_prices)
            print(prices_line)
            
        # アービトラージ機会
        print(f"\n🚨 検出されたアービトラージ機会: {len(self.arbitrage_opportunities)}件")
        
        if self.arbitrage_opportunities:
            print("   上位5件:")
            for i, opp in enumerate(sorted(self.arbitrage_opportunities, 
                                         key=lambda x: x['price_diff_pct'], reverse=True)[:5]):
                print(f"   {i+1}. {opp['symbol']}: {opp['max_exchange']} → {opp['min_exchange']} "
                      f"({opp['price_diff_pct']:.3f}%)")
        
        print("=" * 70)


async def test_five_exchanges_integration():
    """5取引所統合テスト実行"""
    
    print("🧪 5取引所統合アービトラージテスト")
    print("=" * 70)
    
    monitor = FiveExchangeArbitrageMonitor()
    # 設定ファイルからシンボルを取得
    test_symbols = monitor.config.get_monitoring_symbols()
    
    try:
        # 1. 接続テスト
        print("📋 テスト項目: 5取引所同時接続")
        connected = await monitor.connect_all_exchanges(test_symbols)
        
        if not connected:
            print("❌ 接続テスト失敗: 最低3取引所の接続が必要")
            return False
            
        print("✅ 接続テスト成功")
        
        # 2. リアルタイム価格監視テスト
        monitoring_duration = monitor.config.get_monitoring_duration()
        print(f"\n📋 テスト項目: リアルタイム価格監視 ({monitoring_duration}秒間)")
        print(f"📊 監視シンボル: {test_symbols}")
        print(f"📈 アービトラージ検出閾値: {monitor.arbitrage_threshold}%")
        print("=" * 70)
        print("📊 価格監視開始... (Ctrl+Cで中断)")
        print("-" * 70)
        
        monitor.start_time = time.time()
        
        # 設定された時間の監視
        last_display_time = time.time()
        
        for remaining in range(monitoring_duration, 0, -1):
            await asyncio.sleep(1)
            
            # 5秒ごとに進捗表示
            current_time = time.time()
            if current_time - last_display_time >= 5:
                active_exchanges = sum(1 for ex in monitor.exchanges.values() if ex.is_connected)
                print(f"📊 {remaining:2d}秒残り | 接続中: {active_exchanges}/6取引所 | "
                      f"総更新: {monitor.total_updates:,}回 | "
                      f"アービトラージ: {len(monitor.arbitrage_opportunities)}件")
                last_display_time = current_time
        
        # 3. 結果分析
        monitor.display_statistics()
        
        # 4. テスト成功判定
        success_criteria = [
            monitor.total_updates >= 50,  # 最低50回の価格更新
            len(monitor.latest_prices) >= 3,  # 最低3取引所からデータ
            len(set().union(*[prices.keys() for prices in monitor.latest_prices.values()])) >= 2  # 最低2シンボル
        ]
        
        if all(success_criteria):
            print("\n🎉 5取引所統合テスト成功!")
            return True
        else:
            print("\n⚠️ 5取引所統合テスト部分成功")
            print("   改善点: データ受信量または取引所接続数を確認してください")
            return False
            
    except KeyboardInterrupt:
        print("\n👋 テスト中断されました")
        return False
        
    except Exception as e:
        print(f"\n❌ テストエラー: {e}")
        logger.error(f"Five exchange test failed: {e}", exc_info=True)
        return False
        
    finally:
        # 切断処理
        await monitor.disconnect_all_exchanges()


async def main():
    """メイン関数"""
    
    try:
        success = await test_five_exchanges_integration()
        return 0 if success else 1
        
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        logger.error(f"Main function failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 プログラム終了")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 致命的エラー: {e}")
        sys.exit(1)