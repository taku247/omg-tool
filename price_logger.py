#!/usr/bin/env python3
"""
price_logger.py
===============
リアルタイム価格ロガースクリプト。

複数取引所（Hyperliquid / Bybit / Binance / Gate.io / KuCoin）と
複数銘柄（例: BTC, ETH, SOL など）のBid/Ask価格を1秒間隔でCSVに記録します。

* 取引所固有のWebSocket実装は src/exchanges/ 以下にある各クラスを再利用
* 取得間隔は LOG_INTERVAL で制御
* ファイルは日付ごと、取引所ごとに自動ローテート
* 圧縮オプション対応（--compress）

使い方
------
```bash
python price_logger.py --symbols BTC ETH SOL
python price_logger.py --symbols BTC ETH SOL --compress --interval 0.5
```
"""

import asyncio
import csv
import gzip
import logging
from logging.handlers import RotatingFileHandler
import psutil
import signal
import sys
import time
import traceback
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.exchanges.hyperliquid import HyperliquidExchange
from src.exchanges.bybit import BybitExchange
from src.exchanges.binance import BinanceExchange
from src.exchanges.gateio import GateioExchange
from src.exchanges.bitget import BitgetExchange
from src.exchanges.kucoin import KuCoinExchange
from src.core.config import get_config
from src.interfaces.exchange import Ticker

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# エラー専用ログハンドラーを追加
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

error_handler = RotatingFileHandler(
    logs_dir / "price_logger_errors.log",
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] %(message)s'
))

# エラー専用ロガー
error_logger = logging.getLogger('price_logger.errors')
error_logger.addHandler(error_handler)
error_logger.setLevel(logging.ERROR)


class PriceLogger:
    """各取引所の価格をCSVに記録するクラス"""

    def __init__(self, exchanges: Dict[str, Any], symbols: List[str], 
                 log_interval: float = 1.0, compress: bool = False, 
                 price_threshold: float = None):
        """
        Args:
            exchanges: 取引所名とインスタンスの辞書
            symbols: 監視対象シンボルリスト
            log_interval: ログ記録間隔（秒）
            compress: gzip圧縮を使用するか
            price_threshold: 価格変更検出しきい値（CLIオプション）
        """
        self.exchanges = exchanges
        self.symbols = symbols
        self.log_interval = log_interval
        self.compress = compress
        self.custom_price_threshold = price_threshold
        
        # 設定読み込み
        self.config = get_config()
        
        # 価格更新キュー（高頻度更新対応）
        self.price_queue = asyncio.Queue(maxsize=200000)  # 2倍に拡大
        
        # CSV書き込み専用キュー（CSV処理を分離）
        self.csv_queue = asyncio.Queue(maxsize=20000)  # 2倍に拡大
        
        # 最新価格を保存 {exchange: {symbol: Ticker}}
        self.latest_prices: Dict[str, Dict[str, Ticker]] = {
            name: {} for name in exchanges.keys()
        }
        
        # 前回記録価格（差分記録用）
        self.last_saved_prices: Dict[str, Dict[str, Ticker]] = {
            name: {} for name in exchanges.keys()
        }
        
        # 統計情報
        self.stats = {
            "total_updates": 0,
            "updates_per_exchange": defaultdict(int),
            "start_time": None,
            "last_save_time": None,
            "queue_size": 0,
            "memory_mb": 0,
            "cpu_percent": 0.0
        }
        
        # CSVライター管理 {exchange: {"file": file_handle, "writer": csv.writer}}
        self.csv_handlers: Dict[str, Dict[str, Any]] = {}
        self.current_date = None
        self.last_flush_time = datetime.now()
        
        # psutil CPU監視用
        self.process = psutil.Process()
        # 初回CPU計測（後続の計測を安定させる）
        self.process.cpu_percent(interval=None)
        
        # 制御フラグ
        self.shutdown_event = asyncio.Event()
        self.tasks = []
        
        # キュー満杯警告の制限（レート制限）
        self.last_queue_full_warning = 0
        self.queue_full_warning_interval = 5  # 5秒に1回まで
        
        # エラーログ用メソッド
        self.error_logger = error_logger
        
        # シグナルハンドラー登録
        self._setup_signal_handlers()
    
    def log_error(self, error_type: str, exchange: str = "", symbol: str = "", 
                  message: str = "", exception: Exception = None):
        """エラーログを記録する"""
        try:
            error_msg = f"[{error_type}]"
            if exchange:
                error_msg += f" Exchange: {exchange}"
            if symbol:
                error_msg += f" Symbol: {symbol}"
            if message:
                error_msg += f" Message: {message}"
            
            # システム状態情報を追加
            error_msg += f" | Queue: {self.price_queue.qsize()}"
            error_msg += f" | Memory: {self.stats.get('memory_mb', 0):.1f}MB"
            error_msg += f" | CPU: {self.stats.get('cpu_percent', 0):.1f}%"
            error_msg += f" | Updates: {self.stats.get('total_updates', 0)}"
            
            if exception:
                error_msg += f" | Exception: {str(exception)}"
                self.error_logger.error(error_msg, exc_info=True)
            else:
                self.error_logger.error(error_msg)
                
        except Exception as e:
            # エラーログ自体がエラーした場合の最低限の処理
            print(f"Error logging failed: {e}")
            logger.error(f"Error logging failed: {e}")
        
    def _get_output_path(self, exchange: str, date_str: str) -> Path:
        """出力ファイルパスを生成"""
        output_dir = Path("data") / "price_logs" / date_str
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{exchange.lower()}_prices_{date_str}.csv"
        if self.compress:
            filename += ".gz"
            
        return output_dir / filename
        
    def _init_csv_writers(self) -> None:
        """CSVライターを初期化"""
        current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        # 日付が変わった場合は既存のファイルを閉じる
        if self.current_date and self.current_date != current_date:
            self._close_csv_writers()
            # 24時間ローテート時に last_saved_prices をクリア（メモリ節約）
            self.last_saved_prices.clear()
            for exchange in self.exchanges.keys():
                self.last_saved_prices[exchange] = {}
            logger.info("🔄 日付変更により前回記録価格をクリアしました")
            
        self.current_date = current_date
        
        for exchange in self.exchanges.keys():
            if exchange in self.csv_handlers:
                continue
                
            csv_path = self._get_output_path(exchange, current_date)
            
            # ファイルを開く
            if self.compress:
                file_handle = gzip.open(csv_path, "at", encoding="utf-8", newline="")
            else:
                file_handle = open(csv_path, "a", encoding="utf-8", newline="", buffering=1)
                
            writer = csv.writer(file_handle)
            
            # 新規ファイルの場合はヘッダーを書く
            if csv_path.stat().st_size == 0:
                writer.writerow([
                    "timestamp", "exchange", "symbol", 
                    "bid", "ask", "bid_size", "ask_size",
                    "last", "mark_price", "volume_24h"
                ])
                
            self.csv_handlers[exchange] = {
                "file": file_handle,
                "writer": writer
            }
            
    def _close_csv_writers(self) -> None:
        """CSVライターを閉じる"""
        for handler in self.csv_handlers.values():
            try:
                handler["file"].close()
            except Exception as e:
                logger.error(f"Failed to close file: {e}")
                
        self.csv_handlers.clear()
        
    async def price_callback(self, exchange_name: str, ticker: Ticker) -> None:
        """価格更新コールバック（キューに投入）"""
        try:
            # キューに価格更新を投入（非同期でブロックしない）
            self.price_queue.put_nowait((exchange_name, ticker))
            
            # 統計更新
            self.stats["total_updates"] += 1
            self.stats["updates_per_exchange"][exchange_name] += 1
            self.stats["queue_size"] = self.price_queue.qsize()
            
        except asyncio.QueueFull:
            # キューが満杯の場合は警告してスキップ（レート制限付き）
            current_time = time.time()
            if current_time - self.last_queue_full_warning > self.queue_full_warning_interval:
                logger.warning(f"⚠️ 価格更新キューが満杯です - 一部データをスキップ中... (キューサイズ: {self.price_queue.qsize()})")
                self.log_error("QUEUE_FULL", exchange_name, ticker.symbol, 
                             f"キューが満杯でデータをスキップ")
                self.last_queue_full_warning = current_time
            
    async def _price_consumer(self) -> None:
        """価格更新キューの消費者（適応的バッチ処理）"""
        base_batch_size = 500   # 大幅に拡大
        max_batch_size = 2000   # さらに大きく
        min_timeout = 0.0005    # より短いタイムアウト（0.5ms）
        max_timeout = 0.1       # 100ms
        
        # 適応的パラメータ
        current_batch_size = base_batch_size
        current_timeout = min_timeout
        
        while not self.shutdown_event.is_set():
            try:
                batch = []
                
                # バッチを収集（適応的タイムアウト）
                end_time = asyncio.get_event_loop().time() + current_timeout
                
                while len(batch) < current_batch_size and asyncio.get_event_loop().time() < end_time:
                    try:
                        remaining_time = max(0, end_time - asyncio.get_event_loop().time())
                        exchange_name, ticker = await asyncio.wait_for(
                            self.price_queue.get(), timeout=remaining_time
                        )
                        batch.append((exchange_name, ticker))
                        
                    except asyncio.TimeoutError:
                        break
                        
                # バッチ処理
                if batch:
                    for exchange_name, ticker in batch:
                        # 最新価格を更新
                        if exchange_name not in self.latest_prices:
                            self.latest_prices[exchange_name] = {}
                        self.latest_prices[exchange_name][ticker.symbol] = ticker
                        
                        # キュータスクを完了
                        self.price_queue.task_done()
                    
                    # 適応的パラメータ調整
                    queue_size = self.price_queue.qsize()
                    if queue_size > 1000:  # 高負荷時（閾値を上げる）
                        current_batch_size = min(max_batch_size, current_batch_size + 20)
                        current_timeout = min(max_timeout, current_timeout * 1.1)
                    elif queue_size < 100:  # 低負荷時
                        current_batch_size = max(base_batch_size, current_batch_size - 10)
                        current_timeout = max(min_timeout, current_timeout * 0.95)
                
                # CPUを他タスクに譲る（idle時は無駄なsleepを避ける）
                await asyncio.sleep(0)
                
            except Exception as e:
                logger.error(f"価格消費者エラー: {e}")
                self.log_error("PRICE_CONSUMER_ERROR", "", "", 
                             f"価格消費者でエラー", e)
                await asyncio.sleep(1)
        
    def _has_price_changed(self, exchange: str, symbol: str, ticker: Ticker) -> bool:
        """価格が前回記録から変化したかチェック（差分記録）"""
        if exchange not in self.last_saved_prices:
            return True
        if symbol not in self.last_saved_prices[exchange]:
            return True
            
        last_ticker = self.last_saved_prices[exchange][symbol]
        
        # bid/askがNoneの場合は変化ありとして記録
        if ticker.bid is None or ticker.ask is None:
            return True
        if last_ticker.bid is None or last_ticker.ask is None:
            return True
        
        # 価格変更しきい値を取得（CLI > config > デフォルト の優先順位）
        threshold = (self.custom_price_threshold or 
                    self.config.get('price_logger.price_change_threshold', 0.00001))  # デフォルト0.001%
        
        # bid/askの変化をチェック
        if (abs(float(ticker.bid) - float(last_ticker.bid)) / float(last_ticker.bid)) > threshold:
            return True
        if (abs(float(ticker.ask) - float(last_ticker.ask)) / float(last_ticker.ask)) > threshold:
            return True
            
        return False

    async def _save_prices_periodically(self) -> None:
        """定期的に価格をCSVキューに送信（差分記録対応）"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(self.log_interval)
                
                # 現在時刻
                timestamp = datetime.now(timezone.utc).isoformat()
                
                # 各取引所の価格をチェックしてCSVキューに送信（差分のみ）
                csv_items = []
                for exchange_name, prices in self.latest_prices.items():
                    for symbol, ticker in prices.items():
                        # 価格変化をチェック
                        if self._has_price_changed(exchange_name, symbol, ticker):
                            # CSVキュー用のデータを作成
                            csv_data = {
                                "timestamp": timestamp,
                                "exchange": exchange_name,
                                "symbol": symbol,
                                "ticker": ticker
                            }
                            csv_items.append(csv_data)
                            
                            # 記録済み価格を更新
                            if exchange_name not in self.last_saved_prices:
                                self.last_saved_prices[exchange_name] = {}
                            self.last_saved_prices[exchange_name][symbol] = ticker
                
                # CSVキューに送信（ノンブロッキング）
                for csv_data in csv_items:
                    try:
                        self.csv_queue.put_nowait(csv_data)
                    except asyncio.QueueFull:
                        logger.warning(f"⚠️ CSVキューが満杯です - 一部データをスキップ中... (キューサイズ: {self.csv_queue.qsize()})")
                        self.log_error("CSV_QUEUE_FULL", csv_data["exchange"], csv_data["symbol"], 
                                     f"CSVキューが満杯でデータをスキップ")
                        break
                
                # 統計更新
                self.stats["last_save_time"] = timestamp
                
                # メモリクリーンアップ（5分ごと）
                if int(datetime.now().timestamp()) % 300 == 0:
                    # latest_pricesをクリア（メモリ節約）
                    for exchange_prices in self.latest_prices.values():
                        exchange_prices.clear()
                
                # ログ出力（5秒ごと）
                if int(datetime.now().timestamp()) % 5 == 0:
                    elapsed = datetime.now() - self.stats["start_time"]
                    
                    # リソース使用量を更新
                    self.stats["memory_mb"] = self.process.memory_info().rss / 1024 / 1024
                    self.stats["cpu_percent"] = self.process.cpu_percent()
                    
                    logger.info(
                        f"📊 記録中: {len(csv_items)}件送信 | "
                        f"総更新: {self.stats['total_updates']:,}回 | "
                        f"キュー: {self.stats['queue_size']} | "
                        f"CSVキュー: {self.csv_queue.qsize()} | "
                        f"メモリ: {self.stats['memory_mb']:.1f}MB | "
                        f"CPU: {self.stats['cpu_percent']:.1f}% | "
                        f"経過: {elapsed.seconds}秒"
                    )
                    
            except Exception as e:
                logger.error(f"価格保存スケジューラーエラー: {e}")
                self.log_error("PRICE_SCHEDULER_ERROR", "", "", 
                             f"価格保存スケジューラーでエラー", e)
                await asyncio.sleep(1)
    
    async def _csv_writer_worker(self) -> None:
        """CSV書き込み専用ワーカー（別キューで処理）"""
        batch_size = 500  # CSVバッチサイズを大幅拡大
        timeout = 0.2     # CSVバッチタイムアウトを短縮
        
        while not self.shutdown_event.is_set():
            try:
                batch = []
                
                # バッチを収集
                end_time = asyncio.get_event_loop().time() + timeout
                
                while len(batch) < batch_size and asyncio.get_event_loop().time() < end_time:
                    try:
                        remaining_time = max(0, end_time - asyncio.get_event_loop().time())
                        csv_data = await asyncio.wait_for(
                            self.csv_queue.get(), timeout=remaining_time
                        )
                        batch.append(csv_data)
                        
                    except asyncio.TimeoutError:
                        break
                
                # バッチをCSVに書き込み
                if batch:
                    # CSVライターを初期化（日付ローテート対応）
                    self._init_csv_writers()
                    
                    # バッチ書き込み
                    for csv_data in batch:
                        exchange_name = csv_data["exchange"]
                        
                        if exchange_name not in self.csv_handlers:
                            continue
                            
                        writer = self.csv_handlers[exchange_name]["writer"]
                        ticker = csv_data["ticker"]
                        
                        # データ行を作成
                        row = [
                            csv_data["timestamp"],
                            exchange_name,
                            csv_data["symbol"],
                            float(ticker.bid) if ticker.bid else "",
                            float(ticker.ask) if ticker.ask else "",
                            "",  # bid_size (将来の拡張用)
                            "",  # ask_size (将来の拡張用)
                            float(ticker.last) if ticker.last else "",
                            float(ticker.mark_price) if ticker.mark_price else "",
                            float(ticker.volume_24h) if ticker.volume_24h else ""
                        ]
                        
                        writer.writerow(row)
                        self.csv_queue.task_done()
                    
                    # 定期的にフラッシュ（圧縮時は60秒、非圧縮時は30秒）
                    now = datetime.now()
                    flush_interval = (self.config.get('price_logger.gzip_flush_interval', 60) 
                                    if self.compress else 30)
                    
                    if (now - self.last_flush_time).seconds >= flush_interval:
                        for handler in self.csv_handlers.values():
                            handler["file"].flush()
                        self.last_flush_time = now
                
                # CPUを他タスクに譲る
                await asyncio.sleep(0)
                
            except Exception as e:
                logger.error(f"CSVライターエラー: {e}")
                self.log_error("CSV_WRITER_ERROR", "", "", 
                             f"CSVライターでエラー", e)
                await asyncio.sleep(1)
                
    async def connect_all_exchanges(self) -> bool:
        """全取引所に並列接続"""
        logger.info("🚀 取引所への並列接続を開始...")
        
        # 価格消費者タスクを開始
        self.consumer_task = asyncio.create_task(self._price_consumer())
        
        # CSVライタータスクを開始
        self.csv_writer_task = asyncio.create_task(self._csv_writer_worker())
        
        # 価格コールバックを事前登録（メモリ効率化）
        for name, exchange in self.exchanges.items():
            # 弱参照を使ってメモリリークを防ぐ
            def create_callback(exchange_name: str):
                async def callback(_: str, ticker: Ticker):
                    await self.price_callback(exchange_name, ticker)
                return callback
            
            exchange.add_price_callback(create_callback(name))
        
        # 並列接続（高速化）
        connection_tasks = [
            self._connect_single_exchange(name, exchange) 
            for name, exchange in self.exchanges.items()
        ]
        
        connection_results = await asyncio.gather(*connection_tasks, return_exceptions=True)
        
        # 結果を集計
        connected = []
        for name, result in zip(self.exchanges.keys(), connection_results):
            if isinstance(result, Exception):
                logger.error(f"❌ {name} 接続エラー: {result}")
            elif result:
                connected.append(name)
                logger.info(f"✅ {name} 接続成功")
            else:
                logger.warning(f"❌ {name} 接続失敗")
                
        success_rate = len(connected) / len(self.exchanges) * 100
        logger.info(f"📊 接続結果: {len(connected)}/{len(self.exchanges)}取引所 ({success_rate:.0f}%)")
        
        return len(connected) >= 3  # 最低3取引所は接続必要
        
    async def _connect_single_exchange(self, name: str, exchange: Any) -> bool:
        """単一取引所への接続（指数バックオフ付き再試行）"""
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries + 1):
            try:
                await exchange.connect_websocket(self.symbols)
                if exchange.is_connected:
                    return True
                    
            except Exception as e:
                if attempt == max_retries:
                    logger.error(f"❌ {name} 最大再試行回数に達しました: {e}")
                    self.log_error("CONNECTION_FAILED", name, "", 
                                 f"最大再試行回数に達しました", e)
                    return False
                    
                # 指数バックオフ
                delay = base_delay * (2 ** attempt)
                logger.warning(f"⚠️ {name} 接続失敗 (試行 {attempt + 1}/{max_retries + 1}) - {delay}秒後に再試行: {e}")
                if attempt == 0:  # 初回エラーのみログに記録
                    self.log_error("CONNECTION_RETRY", name, "", 
                                 f"接続失敗、再試行中", e)
                await asyncio.sleep(delay)
                
        return False
        
    async def disconnect_all_exchanges(self) -> None:
        """全取引所から切断"""
        logger.info("🔌 全取引所から切断中...")
        
        for name, exchange in self.exchanges.items():
            try:
                if exchange.is_connected:
                    await exchange.disconnect_websocket()
                    logger.info(f"✅ {name} 切断完了")
            except Exception as e:
                logger.error(f"⚠️ {name} 切断エラー: {e}")
                
    async def run(self) -> None:
        """メイン実行ループ"""
        self.stats["start_time"] = datetime.now()
        
        # 全取引所に接続
        if not await self.connect_all_exchanges():
            raise Exception("取引所への接続に失敗しました")
            
        # 価格保存タスクを開始
        self.save_task = asyncio.create_task(self._save_prices_periodically())
        
        logger.info(f"📊 価格記録開始: {len(self.symbols)}シンボル × {len(self.exchanges)}取引所")
        logger.info(f"💾 保存間隔: {self.log_interval}秒 | 圧縮: {'ON' if self.compress else 'OFF'}")
        logger.info("📈 記録を停止するには Ctrl+C を押してください")
        
        try:
            # シャットダウンイベントを待機
            await self.shutdown_event.wait()
            
        except asyncio.CancelledError:
            pass
            
        finally:
            await self._cleanup()
            
            # 最終統計を表示
            elapsed = datetime.now() - self.stats["start_time"]
            logger.info("=" * 60)
            logger.info("📊 価格記録統計:")
            logger.info(f"⏱️ 記録時間: {elapsed}")
            logger.info(f"📈 総更新数: {self.stats['total_updates']:,}回")
            
            for exchange, count in self.stats["updates_per_exchange"].items():
                percentage = count / self.stats["total_updates"] * 100 if self.stats["total_updates"] > 0 else 0
                logger.info(f"   {exchange}: {count:,}回 ({percentage:.1f}%)")
                
            logger.info("=" * 60)
            
    def _setup_signal_handlers(self) -> None:
        """シグナルハンドラーを設定"""
        import signal
        
        def signal_handler(signum, _):
            logger.info(f"🛑 シグナル {signum} を受信 - 正常終了処理を開始...")
            asyncio.create_task(self._shutdown())
            
        # SIGINTとSIGTERMをハンドリング
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
    async def _shutdown(self) -> None:
        """正常終了処理"""
        logger.info("🔄 シャットダウン処理を開始...")
        self.shutdown_event.set()
        
    async def _cleanup(self) -> None:
        """リソースクリーンアップ"""
        logger.info("🧹 クリーンアップ処理を開始...")
        
        # 価格消費者タスクを停止
        if hasattr(self, 'consumer_task') and self.consumer_task:
            self.consumer_task.cancel()
            try:
                await self.consumer_task
            except asyncio.CancelledError:
                pass
        
        # CSVライタータスクを停止
        if hasattr(self, 'csv_writer_task') and self.csv_writer_task:
            self.csv_writer_task.cancel()
            try:
                await self.csv_writer_task
            except asyncio.CancelledError:
                pass
        
        # 価格保存タスクを停止
        if hasattr(self, 'save_task') and self.save_task:
            self.save_task.cancel()
            try:
                await self.save_task
            except asyncio.CancelledError:
                pass
                
        # 取引所から切断
        await self.disconnect_all_exchanges()
        
        # CSVファイルを閉じる
        self._close_csv_writers()
        
        logger.info("✅ クリーンアップ完了")


def parse_args():
    """コマンドライン引数をパース"""
    parser = ArgumentParser(description="リアルタイム価格ロガー（複数取引所対応）")
    parser.add_argument(
        "--symbols", 
        nargs="+", 
        default=["BTC", "ETH", "SOL"],
        help="監視するシンボル (例: BTC ETH SOL)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="記録間隔（秒）デフォルト: 1.0"
    )
    parser.add_argument(
        "--compress",
        action="store_true",
        help="gzip圧縮を使用"
    )
    parser.add_argument(
        "--exchanges",
        nargs="+",
        default=["Hyperliquid", "Bybit", "Gateio", "KuCoin"],
        help="使用する取引所"
    )
    parser.add_argument(
        "--price-threshold",
        type=float,
        help="価格変更検出しきい値 (例: 0.0001 = 0.01%%)"
    )
    
    return parser.parse_args()


async def main():
    """メイン関数"""
    args = parse_args()
    
    # 利用可能な取引所
    available_exchanges = {
        "Hyperliquid": HyperliquidExchange,
        "Bybit": BybitExchange,
        "Binance": BinanceExchange,
        "Gateio": GateioExchange,
        "Bitget": BitgetExchange,
        "KuCoin": KuCoinExchange
    }
    
    # 指定された取引所のみ使用
    exchanges = {}
    for name in args.exchanges:
        if name in available_exchanges:
            exchanges[name] = available_exchanges[name]()
        else:
            logger.warning(f"⚠️ 不明な取引所: {name}")
            
    if not exchanges:
        logger.error("❌ 有効な取引所が指定されていません")
        return
        
    # 価格ロガーを作成
    price_logger = PriceLogger(
        exchanges=exchanges,
        symbols=args.symbols,
        log_interval=args.interval,
        compress=args.compress,
        price_threshold=args.price_threshold
    )
    
    try:
        await price_logger.run()
        
    except KeyboardInterrupt:
        logger.info("👋 ユーザーによる中断...")
        
    except Exception as e:
        logger.error(f"💥 エラー: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass