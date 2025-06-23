#!/usr/bin/env python3
"""Hyperliquid vs Bybit アービトラージ検出テスト"""

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
from src.core.arbitrage_detector import ArbitrageDetector

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_price_comparison():
    """価格比較テスト（REST API）"""
    
    print("=" * 80)
    print("📊 Hyperliquid vs Bybit 価格比較テスト")
    print("=" * 80)
    
    # 取引所インスタンス作成
    hyperliquid = HyperliquidExchange()
    bybit = BybitExchange()
    
    test_symbols = ["BTC", "ETH", "SOL"]
    
    price_data = {}
    
    for symbol in test_symbols:
        print(f"\n🔍 {symbol} 価格取得中...")
        
        try:
            # Hyperliquid価格取得
            hl_ticker = await hyperliquid.get_ticker(symbol)
            
            # Bybit価格取得
            bybit_ticker = await bybit.get_ticker(symbol)
            
            # 価格差計算
            hl_mid = (hl_ticker.bid + hl_ticker.ask) / 2
            bybit_mid = (bybit_ticker.bid + bybit_ticker.ask) / 2
            
            price_diff = bybit_mid - hl_mid
            percentage_diff = (price_diff / hl_mid) * 100
            
            price_data[symbol] = {
                "hyperliquid": {
                    "bid": hl_ticker.bid,
                    "ask": hl_ticker.ask,
                    "mid": hl_mid
                },
                "bybit": {
                    "bid": bybit_ticker.bid,
                    "ask": bybit_ticker.ask,
                    "mid": bybit_mid
                },
                "difference": price_diff,
                "percentage": percentage_diff
            }
            
            print(f"✅ {symbol} 価格取得成功:")
            print(f"   Hyperliquid: Bid={hl_ticker.bid}, Ask={hl_ticker.ask}, Mid={hl_mid:.2f}")
            print(f"   Bybit:       Bid={bybit_ticker.bid}, Ask={bybit_ticker.ask}, Mid={bybit_mid:.2f}")
            print(f"   価格差:      {price_diff:+.2f} ({percentage_diff:+.3f}%)")
            
            # アービトラージ機会の判定
            if abs(percentage_diff) >= 0.1:  # 0.1%以上の乖離
                if percentage_diff > 0:
                    print(f"   🔥 アービトラージ機会: Hyperliquidで買い、Bybitで売り")
                else:
                    print(f"   🔥 アービトラージ機会: Bybitで買い、Hyperliquidで売り")
            else:
                print(f"   ⚪ 小さな価格差")
                
        except Exception as e:
            print(f"❌ {symbol} 価格取得エラー: {e}")
            
    return price_data


async def test_realtime_arbitrage_detection():
    """リアルタイムアービトラージ検出テスト"""
    
    print("\n" + "=" * 80)
    print("⚡ リアルタイムアービトラージ検出テスト")
    print("=" * 80)
    
    # 取引所とアービトラージ検出器を初期化
    hyperliquid = HyperliquidExchange()
    bybit = BybitExchange()
    
    arbitrage_detector = ArbitrageDetector(
        min_spread_threshold=Decimal("0.1"),  # 0.1%以上の乖離で検出
        max_position_size=Decimal("10000"),
        min_profit_threshold=Decimal("5")      # 5USD以上の利益
    )
    
    # 検出結果を保存
    arbitrage_opportunities = []
    price_updates = {"hyperliquid": 0, "bybit": 0}
    
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
    
    # コールバック登録
    arbitrage_detector.add_opportunity_callback(arbitrage_callback)
    hyperliquid.add_price_callback(price_callback_hl)
    bybit.add_price_callback(price_callback_bybit)
    
    test_symbols = ["BTC", "ETH", "SOL"]
    
    try:
        print(f"\n🚀 WebSocket接続開始...")
        
        # 両取引所のWebSocket接続
        await asyncio.gather(
            hyperliquid.connect_websocket(test_symbols),
            bybit.connect_websocket(test_symbols)
        )
        
        print(f"✅ 両取引所接続成功!")
        print(f"📊 監視シンボル: {test_symbols}")
        print(f"⏱️ 30秒間アービトラージ機会を監視...")
        print("-" * 80)
        
        # 30秒間監視
        await asyncio.sleep(30)
        
        print(f"\n📈 監視結果:")
        print(f"   Hyperliquid価格更新: {price_updates['hyperliquid']} 回")
        print(f"   Bybit価格更新: {price_updates['bybit']} 回")
        print(f"   検出されたアービトラージ機会: {len(arbitrage_opportunities)} 件")
        
        if arbitrage_opportunities:
            print(f"\n🎯 検出された機会の詳細:")
            for i, opp in enumerate(arbitrage_opportunities[-5:], 1):  # 最新5件を表示
                print(f"   {i}. {opp.symbol}: {opp.spread_percentage:.3f}% "
                      f"({opp.buy_exchange} → {opp.sell_exchange})")
                      
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
            return_exceptions=True
        )
        print("✅ 切断完了")


async def test_arbitrage_detector_only():
    """アービトラージ検出器のみのテスト"""
    
    print("\n" + "=" * 80)
    print("🧮 アービトラージ検出器単体テスト")
    print("=" * 80)
    
    from src.interfaces.exchange import Ticker
    
    # テストデータ作成
    hyperliquid_ticker = Ticker(
        symbol="BTC",
        bid=Decimal("103750"),
        ask=Decimal("103760"),
        last=Decimal("103755"),
        mark_price=Decimal("103755"),
        timestamp=1234567890
    )
    
    bybit_ticker = Ticker(
        symbol="BTC",
        bid=Decimal("104100"),  # より高い価格
        ask=Decimal("104110"),
        last=Decimal("104105"),
        mark_price=Decimal("104105"),
        timestamp=1234567890
    )
    
    # アービトラージ検出器を初期化
    detector = ArbitrageDetector(
        min_spread_threshold=Decimal("0.1"),
        min_profit_threshold=Decimal("1")
    )
    
    opportunities = []
    
    async def test_callback(opportunity):
        opportunities.append(opportunity)
        print(f"🔥 機会検出: {opportunity.symbol} - "
              f"{opportunity.spread_percentage:.3f}% - "
              f"${opportunity.expected_profit:.2f}")
    
    detector.add_opportunity_callback(test_callback)
    
    print("📊 テストデータ:")
    print(f"   Hyperliquid BTC: {hyperliquid_ticker.bid} / {hyperliquid_ticker.ask}")
    print(f"   Bybit BTC:       {bybit_ticker.bid} / {bybit_ticker.ask}")
    
    # 価格更新
    await detector.update_price("Hyperliquid", hyperliquid_ticker)
    await detector.update_price("Bybit", bybit_ticker)
    
    if opportunities:
        opp = opportunities[0]
        print(f"\n✅ アービトラージ検出成功!")
        print(f"   方向: {opp.buy_exchange} → {opp.sell_exchange}")
        print(f"   スプレッド: {opp.spread_percentage:.3f}%")
        print(f"   期待利益: ${opp.expected_profit:.2f}")
        return True
    else:
        print(f"\n❌ アービトラージ機会が検出されませんでした")
        return False


async def main():
    """メイン関数"""
    
    print("🔥 Hyperliquid vs Bybit アービトラージ検出テスト")
    
    # 1. 価格比較テスト
    price_data = await test_price_comparison()
    
    # 2. 検出器単体テスト
    detector_success = await test_arbitrage_detector_only()
    
    # 3. リアルタイム検出テスト
    if detector_success:
        print("\n検出器テスト成功! リアルタイムテストを実行しますか？")
        print("注意: 30秒間WebSocket接続を維持します")
        
        # 自動でリアルタイムテスト実行
        await asyncio.sleep(2)
        print("リアルタイムテストを開始します...")
        
        realtime_success = await test_realtime_arbitrage_detection()
        
        if realtime_success:
            print("\n🎉 全テスト成功! アービトラージ機会を検出しました!")
            return 0
        else:
            print("\n⚠️ リアルタイムでは機会が検出されませんでした")
            print("（価格差が小さい場合は正常です）")
            return 0
    else:
        print("\n❌ 検出器テストが失敗しました")
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
        logger.error(f"Arbitrage test failed: {e}", exc_info=True)
        sys.exit(1)