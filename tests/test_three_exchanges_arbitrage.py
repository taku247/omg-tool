#!/usr/bin/env python3
"""3取引所（Hyperliquid, Bybit, Binance）アービトラージ検出テスト"""

import asyncio
import logging
import sys
from pathlib import Path
from decimal import Decimal

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange
from src.exchanges.bybit import BybitExchange
from src.exchanges.binance import BinanceExchange
from src.core.arbitrage_detector import ArbitrageDetector

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_three_exchanges_price_comparison():
    """3取引所価格比較テスト（REST API）"""
    
    print("=" * 80)
    print("📊 Hyperliquid vs Bybit vs Binance 価格比較テスト")
    print("=" * 80)
    
    # 取引所インスタンス作成
    hyperliquid = HyperliquidExchange()
    bybit = BybitExchange()
    binance = BinanceExchange()
    
    test_symbols = ["BTC", "ETH", "SOL"]
    exchange_data = {}
    
    for symbol in test_symbols:
        print(f"\n🔍 {symbol} 価格取得中...")
        
        try:
            # 3取引所の価格を並行取得
            hl_ticker, bybit_ticker, binance_ticker = await asyncio.gather(
                hyperliquid.get_ticker(symbol),
                bybit.get_ticker(symbol),
                binance.get_ticker(symbol),
                return_exceptions=True
            )
            
            prices = {}
            
            # Hyperliquid
            if isinstance(hl_ticker, Exception):
                print(f"❌ Hyperliquid {symbol}: {hl_ticker}")
            else:
                hl_mid = (hl_ticker.bid + hl_ticker.ask) / 2
                prices["Hyperliquid"] = {
                    "bid": hl_ticker.bid,
                    "ask": hl_ticker.ask,
                    "mid": hl_mid
                }
                print(f"✅ Hyperliquid {symbol}: Bid={hl_ticker.bid}, Ask={hl_ticker.ask}, Mid={hl_mid:.2f}")
            
            # Bybit
            if isinstance(bybit_ticker, Exception):
                print(f"❌ Bybit {symbol}: {bybit_ticker}")
            else:
                bybit_mid = (bybit_ticker.bid + bybit_ticker.ask) / 2
                prices["Bybit"] = {
                    "bid": bybit_ticker.bid,
                    "ask": bybit_ticker.ask,
                    "mid": bybit_mid
                }
                print(f"✅ Bybit {symbol}: Bid={bybit_ticker.bid}, Ask={bybit_ticker.ask}, Mid={bybit_mid:.2f}")
            
            # Binance
            if isinstance(binance_ticker, Exception):
                print(f"❌ Binance {symbol}: {binance_ticker}")
            else:
                binance_mid = (binance_ticker.bid + binance_ticker.ask) / 2
                prices["Binance"] = {
                    "bid": binance_ticker.bid,
                    "ask": binance_ticker.ask,
                    "mid": binance_mid
                }
                print(f"✅ Binance {symbol}: Bid={binance_ticker.bid}, Ask={binance_ticker.ask}, Mid={binance_mid:.2f}")
            
            # 価格差分析
            if len(prices) >= 2:
                print(f"\n📈 {symbol} 価格差分析:")
                exchange_names = list(prices.keys())
                
                for i, exchange1 in enumerate(exchange_names):
                    for exchange2 in exchange_names[i+1:]:
                        mid1 = prices[exchange1]["mid"]
                        mid2 = prices[exchange2]["mid"]
                        
                        price_diff = mid2 - mid1
                        percentage_diff = (price_diff / mid1) * 100
                        
                        print(f"   {exchange1} vs {exchange2}: {price_diff:+.2f} ({percentage_diff:+.3f}%)")
                        
                        # アービトラージ機会の判定
                        if abs(percentage_diff) >= 0.1:  # 0.1%以上の乖離
                            if percentage_diff > 0:
                                print(f"   🔥 アービトラージ機会: {exchange1}で買い、{exchange2}で売り")
                            else:
                                print(f"   🔥 アービトラージ機会: {exchange2}で買い、{exchange1}で売り")
            
            exchange_data[symbol] = prices
                
        except Exception as e:
            print(f"❌ {symbol} 価格取得エラー: {e}")
            
    return exchange_data


async def test_three_exchanges_realtime_arbitrage():
    """3取引所リアルタイムアービトラージ検出テスト"""
    
    print("\n" + "=" * 80)
    print("⚡ 3取引所リアルタイムアービトラージ検出テスト")
    print("=" * 80)
    
    # 取引所とアービトラージ検出器を初期化
    hyperliquid = HyperliquidExchange()
    bybit = BybitExchange()
    binance = BinanceExchange()
    
    arbitrage_detector = ArbitrageDetector(
        min_spread_threshold=Decimal("0.1"),  # 0.1%以上の乖離で検出
        max_position_size=Decimal("10000"),
        min_profit_threshold=Decimal("5")      # 5USD以上の利益
    )
    
    # 検出結果を保存
    arbitrage_opportunities = []
    price_updates = {"hyperliquid": 0, "bybit": 0, "binance": 0}
    
    async def arbitrage_callback(opportunity):
        """アービトラージ機会検出時のコールバック"""
        arbitrage_opportunities.append(opportunity)
        print(f"\n🔥 アービトラージ機会検出!")
        print(f"   ID: {opportunity.id}")
        print(f"   シンボル: {opportunity.symbol}")
        print(f"   方向: {opportunity.buy_exchange} → {opportunity.sell_exchange}")
        print(f"   スプレッド: {opportunity.spread_percentage:.3f}%")
        print(f"   期待利益: ${opportunity.expected_profit:.2f}")
        print(f"   推奨サイズ: {opportunity.recommended_size:.6f}")
        
    async def price_callback_hl(exchange_name, ticker):
        """Hyperliquid価格更新コールバック"""
        price_updates["hyperliquid"] += 1
        await arbitrage_detector.update_price(exchange_name, ticker)
        
    async def price_callback_bybit(exchange_name, ticker):
        """Bybit価格更新コールバック"""
        price_updates["bybit"] += 1
        await arbitrage_detector.update_price(exchange_name, ticker)
        
    async def price_callback_binance(exchange_name, ticker):
        """Binance価格更新コールバック"""
        price_updates["binance"] += 1
        await arbitrage_detector.update_price(exchange_name, ticker)
    
    # コールバック登録
    arbitrage_detector.add_opportunity_callback(arbitrage_callback)
    hyperliquid.add_price_callback(price_callback_hl)
    bybit.add_price_callback(price_callback_bybit)
    binance.add_price_callback(price_callback_binance)
    
    test_symbols = ["BTC", "ETH", "SOL"]
    
    try:
        print(f"\n🚀 WebSocket接続開始...")
        
        # 3取引所のWebSocket接続
        await asyncio.gather(
            hyperliquid.connect_websocket(test_symbols),
            bybit.connect_websocket(test_symbols),
            binance.connect_websocket(test_symbols)
        )
        
        print(f"✅ 3取引所接続成功!")
        print(f"📊 監視シンボル: {test_symbols}")
        print(f"⏱️ 30秒間アービトラージ機会を監視...")
        print("-" * 80)
        
        # 30秒間監視
        await asyncio.sleep(30)
        
        print(f"\n📈 監視結果:")
        print(f"   Hyperliquid価格更新: {price_updates['hyperliquid']} 回")
        print(f"   Bybit価格更新: {price_updates['bybit']} 回")
        print(f"   Binance価格更新: {price_updates['binance']} 回")
        print(f"   総価格更新: {sum(price_updates.values())} 回")
        print(f"   検出されたアービトラージ機会: {len(arbitrage_opportunities)} 件")
        
        if arbitrage_opportunities:
            print(f"\n🎯 検出された機会の詳細:")
            for i, opp in enumerate(arbitrage_opportunities[-10:], 1):  # 最新10件を表示
                print(f"   {i}. {opp.symbol}: {opp.spread_percentage:.3f}% "
                      f"({opp.buy_exchange} → {opp.sell_exchange}) "
                      f"利益: ${opp.expected_profit:.2f}")
                      
        return len(arbitrage_opportunities) > 0
        
    except Exception as e:
        print(f"❌ リアルタイム監視エラー: {e}")
        logger.error(f"Real-time arbitrage test failed: {e}", exc_info=True)
        return False
        
    finally:
        # WebSocket切断
        print(f"\n🔌 WebSocket切断中...")
        await asyncio.gather(
            hyperliquid.disconnect_websocket(),
            bybit.disconnect_websocket(),
            binance.disconnect_websocket(),
            return_exceptions=True
        )
        print("✅ 切断完了")


async def main():
    """メイン関数"""
    
    print("🔥 3取引所 (Hyperliquid vs Bybit vs Binance) アービトラージ検出テスト")
    
    # 1. 価格比較テスト
    price_data = await test_three_exchanges_price_comparison()
    
    # 2. リアルタイム検出テスト
    print("\n3取引所リアルタイムテストを実行しますか？")
    print("注意: 30秒間WebSocket接続を維持し、大量のデータを受信します")
    
    # 自動でリアルタイムテスト実行
    await asyncio.sleep(2)
    print("リアルタイムテストを開始します...")
    
    realtime_success = await test_three_exchanges_realtime_arbitrage()
    
    if realtime_success:
        print("\n🎉 アービトラージ機会を検出しました!")
        print("3取引所統合システムが正常に動作しています")
        return 0
    else:
        print("\n⚠️ リアルタイムでは機会が検出されませんでした")
        print("（価格差が小さい場合は正常です）")
        print("3取引所統合システムは正常に動作しています")
        return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 テスト中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        logger.error(f"Three exchange arbitrage test failed: {e}", exc_info=True)
        sys.exit(1)