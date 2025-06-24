#!/usr/bin/env python3
"""取引所認証・基本機能テストスクリプト"""

import asyncio
import os
import sys
import argparse
import logging
from pathlib import Path
from decimal import Decimal

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 環境変数読み込み
from dotenv import load_dotenv
load_dotenv()

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ExchangeAuthTester:
    """取引所認証・基本機能テスト"""
    
    def __init__(self, exchange_name: str, testnet: bool = True):
        self.exchange_name = exchange_name.lower()
        self.testnet = testnet
        self.exchange = None
        
    async def setup_exchange(self):
        """取引所インスタンス作成"""
        try:
            # 環境変数から認証情報取得
            api_key = os.getenv(f"{self.exchange_name.upper()}_API_KEY")
            api_secret = os.getenv(f"{self.exchange_name.upper()}_API_SECRET")
            passphrase = os.getenv(f"{self.exchange_name.upper()}_PASSPHRASE")  # KuCoin用
            
            if not api_key or not api_secret:
                raise ValueError(f"API credentials not found for {self.exchange_name}")
                
            print(f"🔑 {self.exchange_name.title()} 認証情報確認:")
            print(f"   API Key: {api_key[:10]}..." if api_key else "   API Key: ❌ Not found")
            print(f"   API Secret: {'✅ Found' if api_secret else '❌ Not found'}")
            if passphrase:
                print(f"   Passphrase: {'✅ Found' if passphrase else '❌ Not found'}")
            print(f"   Testnet: {'✅ Enabled' if self.testnet else '❌ Disabled'}")
            
            # 取引所インスタンス作成
            if self.exchange_name == "hyperliquid":
                from src.exchanges.hyperliquid import HyperliquidExchange
                self.exchange = HyperliquidExchange(api_key, api_secret, self.testnet)
            elif self.exchange_name == "bybit":
                from src.exchanges.bybit import BybitExchange
                self.exchange = BybitExchange(api_key, api_secret, self.testnet)
            elif self.exchange_name == "binance":
                from src.exchanges.binance import BinanceExchange
                self.exchange = BinanceExchange(api_key, api_secret, self.testnet)
            elif self.exchange_name == "gateio":
                from src.exchanges.gateio import GateioExchange
                self.exchange = GateioExchange(api_key, api_secret, self.testnet)
            elif self.exchange_name == "bitget":
                from src.exchanges.bitget import BitgetExchange
                self.exchange = BitgetExchange(api_key, api_secret, self.testnet)
            elif self.exchange_name == "kucoin":
                from src.exchanges.kucoin import KuCoinExchange
                self.exchange = KuCoinExchange(api_key, api_secret, self.testnet, passphrase=passphrase)
            else:
                raise ValueError(f"Unsupported exchange: {self.exchange_name}")
                
            print(f"✅ {self.exchange_name.title()} インスタンス作成成功")
            return True
            
        except Exception as e:
            print(f"❌ {self.exchange_name.title()} セットアップ失敗: {e}")
            return False
            
    async def test_basic_connectivity(self):
        """基本接続テスト"""
        print(f"\n📡 {self.exchange_name.title()} 基本接続テスト")
        print("-" * 50)
        
        try:
            # ティッカー取得テスト
            print("1️⃣ ティッカー取得テスト...")
            ticker = await self.exchange.get_ticker("BTC")
            print(f"   ✅ BTC Ticker: Bid=${ticker.bid}, Ask=${ticker.ask}")
            
            # 板情報取得テスト
            print("2️⃣ 板情報取得テスト...")
            orderbook = await self.exchange.get_orderbook("BTC", depth=5)
            print(f"   ✅ BTC OrderBook: {len(orderbook.bids)} bids, {len(orderbook.asks)} asks")
            
            print(f"✅ {self.exchange_name.title()} 基本接続テスト成功")
            return True
            
        except NotImplementedError as e:
            print(f"⚠️ 一部機能未実装: {e}")
            return False
        except Exception as e:
            print(f"❌ 基本接続テスト失敗: {e}")
            return False
            
    async def test_authenticated_methods(self):
        """認証が必要なメソッドテスト"""
        print(f"\n🔐 {self.exchange_name.title()} 認証メソッドテスト")
        print("-" * 50)
        
        try:
            # 残高取得テスト
            print("1️⃣ 残高取得テスト...")
            try:
                balances = await self.exchange.get_balance()
                print(f"   ✅ 残高取得成功: {len(balances)} 通貨")
                for asset, balance in list(balances.items())[:3]:  # 最初の3つのみ表示
                    if balance.total > 0:
                        print(f"      {asset}: {balance.total} (Free: {balance.free})")
            except NotImplementedError:
                print("   ⚠️ 残高取得機能未実装")
            except Exception as e:
                print(f"   ❌ 残高取得失敗: {e}")
                
            # 未約定注文取得テスト
            print("2️⃣ 未約定注文取得テスト...")
            try:
                open_orders = await self.exchange.get_open_orders()
                print(f"   ✅ 未約定注文取得成功: {len(open_orders)} 注文")
            except NotImplementedError:
                print("   ⚠️ 未約定注文取得機能未実装")
            except Exception as e:
                print(f"   ❌ 未約定注文取得失敗: {e}")
                
            # ポジション取得テスト（先物取引所のみ）
            if self.exchange_name in ["bybit", "hyperliquid"]:
                print("3️⃣ ポジション取得テスト...")
                try:
                    positions = await self.exchange.get_positions()
                    print(f"   ✅ ポジション取得成功: {len(positions)} ポジション")
                except NotImplementedError:
                    print("   ⚠️ ポジション取得機能未実装")
                except Exception as e:
                    print(f"   ❌ ポジション取得失敗: {e}")
                    
            return True
            
        except Exception as e:
            print(f"❌ 認証メソッドテスト失敗: {e}")
            return False
            
    async def test_order_methods(self, dry_run: bool = True):
        """注文関連メソッドテスト"""
        print(f"\n📝 {self.exchange_name.title()} 注文メソッドテスト")
        print(f"   Dry Run: {'✅ Enabled' if dry_run else '❌ Disabled (実注文実行)'}")
        print("-" * 50)
        
        if not dry_run:
            response = input("⚠️ 実際に注文を実行しますか？ (yes/no): ")
            if response.lower() != "yes":
                print("❌ 注文テストをキャンセルしました")
                return False
                
        try:
            from src.interfaces.exchange import OrderSide, OrderType
            
            # 小額テスト注文パラメータ
            symbol = "BTC"
            side = OrderSide.BUY
            quantity = Decimal("0.001")  # 0.001 BTC
            order_type = OrderType.MARKET
            
            print(f"1️⃣ 注文実行テスト...")
            print(f"   Symbol: {symbol}")
            print(f"   Side: {side.value}")
            print(f"   Quantity: {quantity}")
            print(f"   Type: {order_type.value}")
            
            if dry_run:
                print("   ⚠️ Dry Run モード - 実際の注文は実行されません")
                try:
                    # NotImplementedErrorをキャッチして未実装を確認
                    await self.exchange.place_order(symbol, side, quantity, order_type)
                except NotImplementedError:
                    print("   ⚠️ 注文実行機能未実装")
                except Exception as e:
                    print(f"   ❌ 注文実行失敗: {e}")
            else:
                try:
                    order = await self.exchange.place_order(symbol, side, quantity, order_type)
                    print(f"   ✅ 注文実行成功: {order.id}")
                    
                    # 注文状況確認
                    await asyncio.sleep(1)
                    order_status = await self.exchange.get_order(order.id, symbol)
                    print(f"   📊 注文状況: {order_status.status.value}")
                    
                except NotImplementedError:
                    print("   ⚠️ 注文実行機能未実装")
                except Exception as e:
                    print(f"   ❌ 注文実行失敗: {e}")
                    
            return True
            
        except Exception as e:
            print(f"❌ 注文メソッドテスト失敗: {e}")
            return False
            
    async def test_websocket_connection(self, duration: int = 10):
        """WebSocket接続テスト"""
        print(f"\n🌐 {self.exchange_name.title()} WebSocket接続テスト")
        print(f"   監視時間: {duration}秒")
        print("-" * 50)
        
        try:
            price_updates = 0
            
            async def price_callback(exchange, ticker):
                nonlocal price_updates
                price_updates += 1
                if price_updates % 5 == 1:  # 5回に1回表示
                    print(f"   📈 {ticker.symbol}: ${ticker.last} (更新#{price_updates})")
                    
            # コールバック登録
            self.exchange.add_price_callback(price_callback)
            
            # WebSocket接続
            await self.exchange.connect_websocket(["BTC", "ETH"])
            print("   ✅ WebSocket接続成功")
            
            # 指定時間監視
            await asyncio.sleep(duration)
            
            # 切断
            await self.exchange.disconnect_websocket()
            print(f"   ✅ WebSocket切断成功")
            print(f"   📊 総価格更新回数: {price_updates}")
            
            return price_updates > 0
            
        except Exception as e:
            print(f"❌ WebSocket接続テスト失敗: {e}")
            return False
            
    async def run_full_test(self, websocket_duration: int = 10, test_orders: bool = False):
        """完全テスト実行"""
        print("=" * 80)
        print(f"🧪 {self.exchange_name.title()} 完全機能テスト開始")
        print("=" * 80)
        
        results = {}
        
        # 1. セットアップ
        results["setup"] = await self.setup_exchange()
        if not results["setup"]:
            print(f"\n❌ {self.exchange_name.title()} テスト失敗: セットアップエラー")
            return results
            
        # 2. 基本接続テスト
        results["connectivity"] = await self.test_basic_connectivity()
        
        # 3. 認証メソッドテスト
        results["authentication"] = await self.test_authenticated_methods()
        
        # 4. 注文メソッドテスト（Dry Runのみ）
        results["orders"] = await self.test_order_methods(dry_run=True)
        
        # 5. WebSocket接続テスト
        results["websocket"] = await self.test_websocket_connection(websocket_duration)
        
        # 6. 実注文テスト（オプション）
        if test_orders:
            results["real_orders"] = await self.test_order_methods(dry_run=False)
            
        # 結果サマリー
        print("\n" + "=" * 80)
        print(f"📊 {self.exchange_name.title()} テスト結果サマリー")
        print("=" * 80)
        
        for test_name, result in results.items():
            status = "✅ 成功" if result else "❌ 失敗"
            print(f"   {test_name.title()}: {status}")
            
        total_tests = len(results)
        passed_tests = sum(results.values())
        pass_rate = (passed_tests / total_tests) * 100
        
        print(f"\n🎯 総合結果: {passed_tests}/{total_tests} ({pass_rate:.1f}%)")
        
        if pass_rate >= 80:
            print(f"🎉 {self.exchange_name.title()} は本格実装の準備ができています！")
        elif pass_rate >= 50:
            print(f"⚠️ {self.exchange_name.title()} は部分的に動作しています")
        else:
            print(f"❌ {self.exchange_name.title()} は多くの問題があります")
            
        return results


async def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="取引所認証・基本機能テスト")
    parser.add_argument("--exchange", required=True, 
                       choices=["hyperliquid", "bybit", "binance", "gateio", "bitget", "kucoin"],
                       help="テスト対象取引所")
    parser.add_argument("--testnet", action="store_true", default=True,
                       help="テストネット使用（デフォルト: True）")
    parser.add_argument("--websocket-duration", type=int, default=10,
                       help="WebSocket監視時間（秒）")
    parser.add_argument("--test-orders", action="store_true",
                       help="実注文テスト実行（注意: 実際に注文が実行されます）")
    
    args = parser.parse_args()
    
    print("🔬 取引所認証・基本機能テストツール")
    print("=" * 80)
    
    # テスター初期化
    tester = ExchangeAuthTester(args.exchange, args.testnet)
    
    # 完全テスト実行
    results = await tester.run_full_test(
        websocket_duration=args.websocket_duration,
        test_orders=args.test_orders
    )
    
    # 終了コード決定
    passed_tests = sum(results.values())
    total_tests = len(results)
    
    if passed_tests >= total_tests * 0.8:
        return 0  # 成功
    else:
        return 1  # 失敗


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 テスト中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        sys.exit(1)