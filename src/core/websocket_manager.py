"""WebSocket接続管理システム"""

import asyncio
from typing import Dict, Callable, Any, List, Optional
from collections import defaultdict
from datetime import datetime
import logging

from ..interfaces.exchange import ExchangeInterface, Ticker

logger = logging.getLogger(__name__)


class WebSocketManager:
    """複数取引所のWebSocket接続を管理するクラス"""
    
    def __init__(self, reconnect_delay: int = 5, max_reconnect_attempts: int = 10):
        self.connections: Dict[str, ExchangeInterface] = {}
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        
    async def add_exchange(self, exchange_name: str, 
                          exchange_instance: ExchangeInterface,
                          symbols: List[str]) -> None:
        """取引所のWebSocket接続を追加"""
        try:
            await exchange_instance.connect_websocket(symbols)
            self.connections[exchange_name] = exchange_instance
            logger.info(f"Added exchange {exchange_name} with symbols: {symbols}")
            
            # 自動再接続タスクを開始
            if exchange_name not in self.reconnect_tasks:
                task = asyncio.create_task(self._monitor_connection(exchange_name))
                self.reconnect_tasks[exchange_name] = task
                
        except Exception as e:
            logger.error(f"Failed to add exchange {exchange_name}: {e}")
            raise
            
    async def remove_exchange(self, exchange_name: str) -> None:
        """取引所を削除"""
        if exchange_name in self.connections:
            # 再接続タスクをキャンセル
            if exchange_name in self.reconnect_tasks:
                self.reconnect_tasks[exchange_name].cancel()
                del self.reconnect_tasks[exchange_name]
                
            # WebSocket接続を切断
            exchange = self.connections[exchange_name]
            await exchange.disconnect_websocket()
            del self.connections[exchange_name]
            
            logger.info(f"Removed exchange {exchange_name}")
            
    def subscribe(self, event_type: str, callback: Callable) -> None:
        """イベントにコールバックを登録"""
        self.subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to {event_type}")
        
    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """コールバックの登録を解除"""
        if callback in self.subscribers[event_type]:
            self.subscribers[event_type].remove(callback)
            logger.debug(f"Unsubscribed from {event_type}")
            
    async def broadcast(self, event_type: str, data: Any) -> None:
        """登録されたコールバックを実行"""
        for callback in self.subscribers[event_type]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"Error in callback for {event_type}: {e}")
                
    async def _monitor_connection(self, exchange_name: str) -> None:
        """接続状態を監視し、必要に応じて再接続"""
        attempts = 0
        
        while exchange_name in self.connections:
            try:
                exchange = self.connections[exchange_name]
                if not exchange.is_connected:
                    logger.warning(f"Connection lost for {exchange_name}")
                    await self._handle_reconnection(exchange_name, attempts)
                    attempts += 1
                else:
                    attempts = 0  # 接続成功したらリセット
                    
                await asyncio.sleep(self.reconnect_delay)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring {exchange_name}: {e}")
                await asyncio.sleep(self.reconnect_delay)
                
    async def _handle_reconnection(self, exchange_name: str, attempts: int) -> None:
        """再接続処理"""
        if attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts reached for {exchange_name}")
            await self.broadcast("connection_failed", {
                "exchange": exchange_name,
                "timestamp": datetime.now().isoformat()
            })
            return
            
        logger.info(f"Attempting to reconnect {exchange_name} (attempt {attempts + 1})")
        
        try:
            exchange = self.connections[exchange_name]
            # 既存の接続があれば切断
            if exchange.is_connected:
                await exchange.disconnect_websocket()
                
            # 再接続
            await exchange.connect_websocket([])  # シンボルリストは保持されている前提
            
            logger.info(f"Successfully reconnected to {exchange_name}")
            await self.broadcast("connection_restored", {
                "exchange": exchange_name,
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Failed to reconnect {exchange_name}: {e}")
            # 次回の再接続まで待機
            await asyncio.sleep(self.reconnect_delay * (attempts + 1))
            
    async def start(self) -> None:
        """WebSocketマネージャーを開始"""
        self._running = True
        logger.info("WebSocket manager started")
        
    async def stop(self) -> None:
        """WebSocketマネージャーを停止"""
        self._running = False
        
        # 全ての再接続タスクをキャンセル
        for task in self.reconnect_tasks.values():
            task.cancel()
            
        # 全ての接続を切断
        for exchange_name in list(self.connections.keys()):
            await self.remove_exchange(exchange_name)
            
        logger.info("WebSocket manager stopped")
        
    def get_status(self) -> Dict[str, Any]:
        """各取引所の接続状態を取得"""
        status = {}
        for name, exchange in self.connections.items():
            status[name] = {
                "connected": exchange.is_connected,
                "name": exchange.name,
                "testnet": exchange.testnet
            }
        return status


class PriceAggregator:
    """複数取引所の価格データを集約するクラス"""
    
    def __init__(self, websocket_manager: WebSocketManager):
        self.ws_manager = websocket_manager
        self.price_cache: Dict[str, Dict[str, Ticker]] = defaultdict(dict)
        self.update_callbacks: List[Callable] = []
        
        # WebSocketマネージャーに価格更新を購読
        self.ws_manager.subscribe("ticker_update", self._handle_ticker_update)
        
    async def _handle_ticker_update(self, data: Dict[str, Any]) -> None:
        """ティッカー更新を処理"""
        exchange = data["exchange"]
        ticker = data["ticker"]
        
        # キャッシュを更新
        self.price_cache[ticker.symbol][exchange] = ticker
        
        # コールバックを実行
        for callback in self.update_callbacks:
            await callback(exchange, ticker)
            
    def add_update_callback(self, callback: Callable) -> None:
        """価格更新時のコールバックを追加"""
        self.update_callbacks.append(callback)
        
    def get_all_prices(self, symbol: str) -> Dict[str, Ticker]:
        """指定シンボルの全取引所価格を取得"""
        return self.price_cache.get(symbol, {})
        
    def get_best_prices(self, symbol: str) -> Optional[Dict[str, Any]]:
        """最良の買値と売値を取得"""
        prices = self.get_all_prices(symbol)
        if not prices:
            return None
            
        best_bid = None
        best_bid_exchange = None
        best_ask = None
        best_ask_exchange = None
        
        for exchange, ticker in prices.items():
            if best_bid is None or ticker.bid > best_bid:
                best_bid = ticker.bid
                best_bid_exchange = exchange
                
            if best_ask is None or ticker.ask < best_ask:
                best_ask = ticker.ask
                best_ask_exchange = exchange
                
        return {
            "best_bid": best_bid,
            "best_bid_exchange": best_bid_exchange,
            "best_ask": best_ask,
            "best_ask_exchange": best_ask_exchange,
            "spread": best_bid - best_ask if best_bid and best_ask else None
        }