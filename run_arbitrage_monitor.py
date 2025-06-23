#!/usr/bin/env python3
"""アービトラージ監視システム - 詳細ログ版"""

import asyncio
import logging
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange
from src.exchanges.bybit import BybitExchange
from src.exchanges.binance import BinanceExchange
from src.core.arbitrage_detector import ArbitrageDetector
from src.core.config import get_config

# 詳細ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('arbitrage_monitor.log')
    ]
)
logger = logging.getLogger(__name__)


class ArbitrageMonitor:
    """アービトラージ監視システム"""
    
    def __init__(self):
        # 設定読み込み
        self.config = get_config()
        
        self.exchanges = {
            "Hyperliquid": HyperliquidExchange(),
            "Bybit": BybitExchange(),
            "Binance": BinanceExchange()
        }
        
        # 設定から閾値を取得
        threshold = self.config.get_arbitrage_threshold("default")
        max_position = self.config.get("arbitrage.max_position_size", 10000)
        min_profit = self.config.get("arbitrage.min_profit_threshold", 5)
        
        self.arbitrage_detector = ArbitrageDetector(
            min_spread_threshold=Decimal(str(threshold)),
            max_position_size=Decimal(str(max_position)),
            min_profit_threshold=Decimal(str(min_profit))
        )
        
        print(f"📋 設定読み込み: 閾値={threshold}%, 最大ポジション=${max_position}, 最小利益=${min_profit}")
        
        self.price_updates = {name: 0 for name in self.exchanges.keys()}
        self.arbitrage_opportunities = []
        self.latest_prices = {}
        
    async def setup_callbacks(self):
        """コールバック設定"""
        
        async def arbitrage_callback(opportunity):
            """アービトラージ機会検出"""
            self.arbitrage_opportunities.append(opportunity)
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"\n🔥 [{timestamp}] アービトラージ機会検出!")
            print(f"   シンボル: {opportunity.symbol}")
            print(f"   方向: {opportunity.buy_exchange} → {opportunity.sell_exchange}")
            print(f"   スプレッド: {opportunity.spread_percentage:.3f}%")
            print(f"   期待利益: ${opportunity.expected_profit:.2f}")
            print("-" * 60)
        
        async def price_callback(exchange_name, ticker):
            """価格更新コールバック"""
            self.price_updates[exchange_name] += 1
            self.latest_prices[f"{exchange_name}_{ticker.symbol}"] = ticker
            
            # 10回に1回価格表示
            if self.price_updates[exchange_name] % 10 == 0:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] {exchange_name:11} {ticker.symbol}: "
                      f"Bid={ticker.bid:>10} Ask={ticker.ask:>10} "
                      f"(更新#{self.price_updates[exchange_name]})")
            
            # アービトラージ検出器に価格を送信
            await self.arbitrage_detector.update_price(exchange_name, ticker)
        
        # コールバック登録
        self.arbitrage_detector.add_opportunity_callback(arbitrage_callback)
        
        for name, exchange in self.exchanges.items():
            exchange.add_price_callback(lambda ex_name, ticker, name=name: price_callback(name, ticker))
    
    async def start_monitoring(self, symbols, duration_seconds=60):
        """監視開始"""
        print("🚀 アービトラージ監視システム起動中...")
        print(f"📊 監視シンボル: {symbols}")
        print(f"⏱️ 監視時間: {duration_seconds}秒")
        print(f"📈 アービトラージ検出閾値: 0.1%")
        print("=" * 80)
        
        # コールバック設定
        await self.setup_callbacks()
        
        try:
            # 全取引所WebSocket接続
            connection_tasks = [
                exchange.connect_websocket(symbols)
                for exchange in self.exchanges.values()
            ]
            await asyncio.gather(*connection_tasks)
            
            print("✅ 全取引所接続完了")
            print("📊 価格監視開始... (Ctrl+Cで停止)")
            print("-" * 60)
            
            # 指定時間監視
            await asyncio.sleep(duration_seconds)
            
        except KeyboardInterrupt:
            print("\n\n⚠️ ユーザーによる中断")
        except Exception as e:
            print(f"\n❌ エラー発生: {e}")
            logger.error(f"Monitoring error: {e}", exc_info=True)
        finally:
            await self.disconnect_all()
    
    async def disconnect_all(self):
        """全接続切断"""
        print("\n🔌 全取引所切断中...")
        disconnect_tasks = [
            exchange.disconnect_websocket()
            for exchange in self.exchanges.values()
        ]
        await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        print("✅ 切断完了")
    
    def print_summary(self):
        """監視結果サマリー"""
        print("\n" + "=" * 80)
        print("📈 監視結果サマリー")
        print("=" * 80)
        
        total_updates = sum(self.price_updates.values())
        print(f"🔢 価格更新統計:")
        for name, count in self.price_updates.items():
            percentage = (count / total_updates * 100) if total_updates > 0 else 0
            print(f"   {name:11}: {count:6}回 ({percentage:5.1f}%)")
        print(f"   総更新数: {total_updates}回")
        
        print(f"\n🎯 アービトラージ機会: {len(self.arbitrage_opportunities)}件")
        if self.arbitrage_opportunities:
            print("📋 検出された機会:")
            for i, opp in enumerate(self.arbitrage_opportunities[-5:], 1):
                print(f"   {i}. {opp.symbol}: {opp.spread_percentage:.3f}% "
                      f"({opp.buy_exchange}→{opp.sell_exchange}) "
                      f"利益${opp.expected_profit:.2f}")
        
        print(f"\n💰 最新価格:")
        symbols = set()
        for key in self.latest_prices.keys():
            symbols.add(key.split('_')[1])
        
        for symbol in sorted(symbols):
            print(f"   {symbol}:")
            for exchange_name in self.exchanges.keys():
                key = f"{exchange_name}_{symbol}"
                if key in self.latest_prices:
                    ticker = self.latest_prices[key]
                    mid = (ticker.bid + ticker.ask) / 2
                    print(f"     {exchange_name:11}: {mid:>10.2f}")


async def main():
    """メイン関数"""
    
    monitor = ArbitrageMonitor()
    
    print("🔥 アービトラージ監視システム")
    print("=" * 80)
    
    # 監視設定
    symbols = ["BTC", "ETH", "SOL"]
    duration = 30  # 30秒監視
    
    try:
        # 監視開始
        await monitor.start_monitoring(symbols, duration)
        
    finally:
        # 結果表示
        monitor.print_summary()
        print("\n👋 監視終了")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 プログラム終了")
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        logger.error(f"Program failed: {e}", exc_info=True)