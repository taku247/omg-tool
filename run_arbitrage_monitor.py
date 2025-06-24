#!/usr/bin/env python3
"""アービトラージ監視システム - 詳細ログ版"""

import asyncio
import logging
import sys
import argparse
import csv
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

def setup_logging(log_level="INFO"):
    """詳細ログ設定"""
    # ログレベル設定
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')
    
    # ログフォーマット
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # ファイルハンドラ（ローテーション対応）
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        'arbitrage_monitor.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # ファイルには全レベル記録
    
    # コンソールハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    
    # ルートロガー設定
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)


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
            min_profit_threshold=Decimal(str(min_profit)),
            enable_detailed_analysis=True
        )
        
        print(f"📋 設定読み込み: 閾値={threshold}%, 最大ポジション=${max_position}, 最小利益=${min_profit}")
        
        self.price_updates = {name: 0 for name in self.exchanges.keys()}
        self.arbitrage_opportunities = []
        self.latest_prices = {}
        
        # CSV出力ファイルの設定
        self.csv_output_file = f"arbitrage_opportunities_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self._setup_csv_output()
        
        # アービトラージ専用ログファイルの設定
        self.arbitrage_log_file = f"arbitrage_opportunities_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._setup_arbitrage_logger()
    
    def _setup_csv_output(self):
        """CSV出力ファイルのセットアップ"""
        try:
            # CSVヘッダーの定義
            headers = [
                'timestamp', 'opportunity_id', 'symbol', 'buy_exchange', 'sell_exchange',
                'spread_percentage', 'expected_profit', 'buy_price', 'sell_price', 'recommended_size',
                # 詳細解析結果
                'slippage_buy', 'slippage_sell', 'total_slippage', 'liquidity_score', 
                'optimal_size', 'real_expected_profit', 'profit_difference',
                'risk_score', 'buy_levels', 'sell_levels', 'buy_price_impact', 'sell_price_impact'
            ]
            
            # CSVファイルを作成してヘッダーを書き込み
            with open(self.csv_output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            
            print(f"📄 CSV出力ファイル: {self.csv_output_file}")
            
        except Exception as e:
            logger.error(f"CSV出力ファイルのセットアップエラー: {e}")
            self.csv_output_file = None
    
    def _setup_arbitrage_logger(self):
        """アービトラージ専用ログファイルのセットアップ"""
        try:
            # アービトラージ専用ロガーを作成
            self.arbitrage_logger = logging.getLogger('arbitrage_opportunities')
            self.arbitrage_logger.setLevel(logging.INFO)
            
            # 既存のハンドラーをクリア（重複を避けるため）
            self.arbitrage_logger.handlers.clear()
            
            # アービトラージ専用ファイルハンドラー
            from logging.handlers import RotatingFileHandler
            arb_handler = RotatingFileHandler(
                self.arbitrage_log_file,
                maxBytes=50*1024*1024,  # 50MB
                backupCount=10
            )
            
            # 詳細なフォーマット
            arb_formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            arb_handler.setFormatter(arb_formatter)
            self.arbitrage_logger.addHandler(arb_handler)
            
            # 他のロガーに伝播しない（専用ログファイルのみに出力）
            self.arbitrage_logger.propagate = False
            
            print(f"📄 アービトラージログファイル: {self.arbitrage_log_file}")
            
        except Exception as e:
            logger.error(f"アービトラージログファイルのセットアップエラー: {e}")
            self.arbitrage_logger = None
    
    def _write_opportunity_to_csv(self, opportunity):
        """アービトラージ機会をCSVファイルに出力"""
        if not self.csv_output_file:
            return
            
        try:
            # 詳細解析結果から値を取得
            slippage_buy = float(opportunity.slippage_buy) if opportunity.slippage_buy is not None else None
            slippage_sell = float(opportunity.slippage_sell) if opportunity.slippage_sell is not None else None
            total_slippage = (slippage_buy + slippage_sell) if (slippage_buy is not None and slippage_sell is not None) else None
            
            liquidity_score = float(opportunity.liquidity_score) if opportunity.liquidity_score is not None else None
            optimal_size = float(opportunity.optimal_size) if opportunity.optimal_size is not None else None
            real_expected_profit = float(opportunity.real_expected_profit) if opportunity.real_expected_profit is not None else None
            profit_difference = (real_expected_profit - float(opportunity.expected_profit)) if real_expected_profit is not None else None
            
            # リスク指標の取得
            risk_metrics = opportunity.detailed_analysis.get('risk_metrics', {}) if opportunity.detailed_analysis else {}
            risk_score = risk_metrics.get('total_risk_score')
            buy_levels = risk_metrics.get('buy_levels')
            sell_levels = risk_metrics.get('sell_levels')
            buy_price_impact = risk_metrics.get('buy_price_impact')
            sell_price_impact = risk_metrics.get('sell_price_impact')
            
            # CSVレコードの作成
            record = [
                opportunity.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f'),
                opportunity.id,
                opportunity.symbol,
                opportunity.buy_exchange,
                opportunity.sell_exchange,
                float(opportunity.spread_percentage),
                float(opportunity.expected_profit),
                float(opportunity.buy_price),
                float(opportunity.sell_price),
                float(opportunity.recommended_size),
                # 詳細解析結果
                slippage_buy,
                slippage_sell,
                total_slippage,
                liquidity_score,
                optimal_size,
                real_expected_profit,
                profit_difference,
                risk_score,
                buy_levels,
                sell_levels,
                buy_price_impact,
                sell_price_impact
            ]
            
            # CSVファイルに追記
            with open(self.csv_output_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(record)
                
        except Exception as e:
            logger.error(f"CSV出力エラー: {e}")
    
    def _log_arbitrage_opportunity(self, opportunity):
        """アービトラージ機会を専用ログファイルに記録"""
        if not self.arbitrage_logger:
            return
            
        try:
            # 基本情報の構築
            log_data = {
                "id": opportunity.id,
                "timestamp": opportunity.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f'),
                "symbol": opportunity.symbol,
                "buy_exchange": opportunity.buy_exchange,
                "sell_exchange": opportunity.sell_exchange,
                "spread_percentage": float(opportunity.spread_percentage),
                "expected_profit": float(opportunity.expected_profit),
                "buy_price": float(opportunity.buy_price),
                "sell_price": float(opportunity.sell_price),
                "recommended_size": float(opportunity.recommended_size)
            }
            
            # 詳細解析結果の追加
            if opportunity.detailed_analysis:
                if opportunity.slippage_buy is not None:
                    log_data["slippage_buy"] = float(opportunity.slippage_buy)
                if opportunity.slippage_sell is not None:
                    log_data["slippage_sell"] = float(opportunity.slippage_sell)
                if opportunity.liquidity_score is not None:
                    log_data["liquidity_score"] = float(opportunity.liquidity_score)
                if opportunity.optimal_size is not None:
                    log_data["optimal_size"] = float(opportunity.optimal_size)
                if opportunity.real_expected_profit is not None:
                    log_data["real_expected_profit"] = float(opportunity.real_expected_profit)
                    log_data["profit_difference"] = float(opportunity.real_expected_profit) - float(opportunity.expected_profit)
                
                # リスク指標
                if 'risk_metrics' in opportunity.detailed_analysis:
                    risk = opportunity.detailed_analysis['risk_metrics']
                    if 'total_risk_score' in risk:
                        log_data["risk_score"] = risk['total_risk_score']
            
            # 構造化ログメッセージの作成
            import json
            log_message = f"ARBITRAGE_OPPORTUNITY | {json.dumps(log_data, separators=(',', ':'))}"
            
            # ログ出力
            self.arbitrage_logger.info(log_message)
            
        except Exception as e:
            logger.error(f"アービトラージログ出力エラー: {e}")
        
    async def setup_callbacks(self):
        """コールバック設定"""
        
        async def arbitrage_callback(opportunity):
            """アービトラージ機会検出"""
            self.arbitrage_opportunities.append(opportunity)
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # コンソール表示（基本情報）
            print(f"\n🔥 [{timestamp}] アービトラージ機会検出!")
            print(f"   シンボル: {opportunity.symbol}")
            print(f"   方向: {opportunity.buy_exchange} → {opportunity.sell_exchange}")
            print(f"   スプレッド: {opportunity.spread_percentage:.3f}%")
            print(f"   期待利益: ${opportunity.expected_profit:.2f}")
            
            # 詳細解析結果の表示
            if opportunity.detailed_analysis:
                print(f"   📊 詳細解析結果:")
                if opportunity.slippage_buy is not None and opportunity.slippage_sell is not None:
                    total_slippage = opportunity.slippage_buy + opportunity.slippage_sell
                    print(f"     スリッページ: 買い{opportunity.slippage_buy:.3f}% + 売り{opportunity.slippage_sell:.3f}% = {total_slippage:.3f}%")
                
                if opportunity.liquidity_score is not None:
                    print(f"     流動性スコア: {opportunity.liquidity_score:.2f}")
                
                if opportunity.optimal_size is not None:
                    print(f"     推奨サイズ: {opportunity.recommended_size:.4f} → 最適サイズ: {opportunity.optimal_size:.4f}")
                
                if opportunity.real_expected_profit is not None:
                    profit_diff = opportunity.real_expected_profit - opportunity.expected_profit
                    print(f"     実際の利益: ${opportunity.real_expected_profit:.2f} (差分: ${profit_diff:+.2f})")
                
                if 'risk_metrics' in opportunity.detailed_analysis:
                    risk = opportunity.detailed_analysis['risk_metrics']
                    if 'total_risk_score' in risk:
                        print(f"     リスクスコア: {risk['total_risk_score']:.2f}")
            
            print("-" * 60)
            
            # ログファイルに記録（詳細情報含む）
            log_msg = (f"アービトラージ機会検出: {opportunity.symbol} "
                      f"{opportunity.buy_exchange}→{opportunity.sell_exchange} "
                      f"スプレッド:{opportunity.spread_percentage:.3f}% "
                      f"期待利益:${opportunity.expected_profit:.2f}")
            
            if opportunity.real_expected_profit is not None:
                log_msg += f" 実利益:${opportunity.real_expected_profit:.2f}"
            if opportunity.liquidity_score is not None:
                log_msg += f" 流動性:{opportunity.liquidity_score:.2f}"
            
            logger.info(log_msg)
            
            # CSV出力
            self._write_opportunity_to_csv(opportunity)
            
            # アービトラージ専用ログ出力
            self._log_arbitrage_opportunity(opportunity)
        
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
    
    async def start_monitoring(self, symbols, duration_seconds=None):
        """監視開始"""
        print("🚀 アービトラージ監視システム起動中...")
        print(f"📊 監視シンボル: {symbols}")
        
        if duration_seconds is None:
            print("⏱️ 監視時間: 無制限 (Ctrl+Cで停止)")
        else:
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
            
            # 監視継続
            if duration_seconds is None:
                # 無制限監視（Ctrl+Cまで継続）
                while True:
                    await asyncio.sleep(1)
            else:
                # 指定時間監視
                await asyncio.sleep(duration_seconds)
            
        except KeyboardInterrupt:
            print("\n\n⚠️ ユーザーによる中断")
        except Exception as e:
            print(f"\n❌ エラー発生: {e}")
            logger.error(f"監視中にエラーが発生しました: {e}", exc_info=True)
            logger.error(f"エラー詳細: {type(e).__name__}: {str(e)}")
            # エラー発生時も切断処理は実行
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
                basic_info = (f"   {i}. {opp.symbol}: {opp.spread_percentage:.3f}% "
                             f"({opp.buy_exchange}→{opp.sell_exchange}) "
                             f"利益${opp.expected_profit:.2f}")
                
                # 詳細解析結果があれば追加表示
                if opp.real_expected_profit is not None:
                    basic_info += f" → 実利益${opp.real_expected_profit:.2f}"
                if opp.liquidity_score is not None:
                    basic_info += f" (流動性:{opp.liquidity_score:.1f})"
                
                print(basic_info)
            
            # 詳細解析統計
            detailed_count = sum(1 for opp in self.arbitrage_opportunities if opp.detailed_analysis)
            if detailed_count > 0:
                print(f"\n📊 詳細解析済み: {detailed_count}/{len(self.arbitrage_opportunities)}件")
                
                # 平均値計算
                real_profits = [opp.real_expected_profit for opp in self.arbitrage_opportunities 
                               if opp.real_expected_profit is not None]
                liquidity_scores = [opp.liquidity_score for opp in self.arbitrage_opportunities 
                                   if opp.liquidity_score is not None]
                
                if real_profits:
                    avg_real_profit = sum(real_profits) / len(real_profits)
                    print(f"   平均実利益: ${avg_real_profit:.2f}")
                
                if liquidity_scores:
                    avg_liquidity = sum(liquidity_scores) / len(liquidity_scores)
                    print(f"   平均流動性: {avg_liquidity:.2f}")
        
        # 出力ファイル情報
        if len(self.arbitrage_opportunities) > 0:
            if self.csv_output_file:
                print(f"\n📄 詳細結果CSV: {self.csv_output_file} ({len(self.arbitrage_opportunities)}件記録)")
            if self.arbitrage_log_file:
                print(f"📋 アービトラージログ: {self.arbitrage_log_file} ({len(self.arbitrage_opportunities)}件記録)")
        
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


def parse_args():
    """コマンドライン引数の解析"""
    parser = argparse.ArgumentParser(description="アービトラージ監視システム")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"],
                       help="監視対象シンボル (デフォルト: BTC ETH SOL)")
    parser.add_argument("--duration", type=int, default=None,
                       help="監視時間（秒）。指定しない場合は無制限（Ctrl+Cで停止）")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       default="INFO", help="ログレベル (デフォルト: INFO)")
    return parser.parse_args()


async def main():
    """メイン関数"""
    # コマンドライン引数解析
    args = parse_args()
    
    # ログ設定
    logger = setup_logging(args.log_level)
    
    print("🔥 アービトラージ監視システム")
    print("=" * 80)
    
    logger.info(f"アービトラージ監視システム開始")
    logger.info(f"監視シンボル: {args.symbols}")
    logger.info(f"監視時間: {'無制限' if args.duration is None else f'{args.duration}秒'}")
    logger.info(f"ログレベル: {args.log_level}")
    
    try:
        monitor = ArbitrageMonitor()
        
        # 監視開始
        await monitor.start_monitoring(args.symbols, args.duration)
        
    except Exception as e:
        logger.error(f"メイン処理でエラーが発生: {e}", exc_info=True)
        print(f"\n💥 システムエラー: {e}")
        raise
    finally:
        # 結果表示
        try:
            monitor.print_summary()
            logger.info("監視システム正常終了")
        except:
            logger.error("サマリー表示中にエラー発生", exc_info=True)
        print("\n👋 監視終了")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 プログラム終了")
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        # ログ設定前のエラーの場合はコンソールのみ出力
        try:
            import logging
            logging.getLogger(__name__).error(f"Program failed: {e}", exc_info=True)
        except:
            pass