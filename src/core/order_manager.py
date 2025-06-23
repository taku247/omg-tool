"""注文管理モジュール"""

from typing import Dict, List, Optional, Callable
from decimal import Decimal
from datetime import datetime
import asyncio
import logging
import uuid

from ..interfaces.exchange import ExchangeInterface, Order, OrderSide, OrderType, OrderStatus

logger = logging.getLogger(__name__)


class OrderManager:
    """取引所への注文管理を統一するクラス"""
    
    def __init__(self):
        self.exchanges: Dict[str, ExchangeInterface] = {}
        self.active_orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        self.order_callbacks: Dict[str, List[Callable]] = {
            "order_placed": [],
            "order_filled": [],
            "order_cancelled": [],
            "order_failed": []
        }
        
    def add_exchange(self, name: str, exchange: ExchangeInterface) -> None:
        """取引所を追加"""
        self.exchanges[name] = exchange
        logger.info(f"Added exchange: {name}")
        
    def add_callback(self, event: str, callback: Callable) -> None:
        """イベントコールバックを追加"""
        if event in self.order_callbacks:
            self.order_callbacks[event].append(callback)
            
    async def place_order(self, 
                         exchange: str,
                         symbol: str,
                         side: OrderSide,
                         size: Decimal,
                         order_type: OrderType = OrderType.MARKET,
                         price: Optional[Decimal] = None,
                         client_order_id: Optional[str] = None) -> Order:
        """注文を実行"""
        
        if exchange not in self.exchanges:
            raise ValueError(f"Exchange {exchange} not found")
            
        if client_order_id is None:
            client_order_id = str(uuid.uuid4())
            
        exchange_instance = self.exchanges[exchange]
        
        try:
            logger.info(f"Placing order: {exchange} {symbol} {side.value} {size} {order_type.value}")
            
            # 残高チェック
            await self._check_balance(exchange_instance, symbol, side, size, price)
            
            # 注文実行
            order = await exchange_instance.place_order(
                symbol=symbol,
                side=side,
                quantity=size,
                order_type=order_type,
                price=price,
                client_order_id=client_order_id
            )
            
            # 注文を管理対象に追加
            self.active_orders[order.id] = order
            
            logger.info(f"Order placed successfully: {order.id}")
            
            # コールバック実行
            for callback in self.order_callbacks["order_placed"]:
                await callback(order)
                
            # 注文状態を監視
            asyncio.create_task(self._monitor_order(exchange, order))
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            
            # 失敗時のダミー注文オブジェクト
            failed_order = Order(
                id=client_order_id,
                symbol=symbol,
                side=side,
                type=order_type,
                price=price,
                quantity=size,
                status=OrderStatus.REJECTED
            )
            
            # エラーコールバック実行
            for callback in self.order_callbacks["order_failed"]:
                await callback(failed_order)
                
            raise
            
    async def cancel_order(self, order_id: str, exchange: str, symbol: str) -> bool:
        """注文をキャンセル"""
        if exchange not in self.exchanges:
            logger.error(f"Exchange {exchange} not found")
            return False
            
        try:
            exchange_instance = self.exchanges[exchange]
            success = await exchange_instance.cancel_order(order_id, symbol)
            
            if success and order_id in self.active_orders:
                order = self.active_orders[order_id]
                order.status = OrderStatus.CANCELLED
                
                # コールバック実行
                for callback in self.order_callbacks["order_cancelled"]:
                    await callback(order)
                    
                # 履歴に移動
                self._move_to_history(order_id)
                
            logger.info(f"Order {order_id} cancelled: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
            
    async def get_order_status(self, order_id: str, exchange: str, symbol: str) -> Optional[Order]:
        """注文状態を取得"""
        if exchange not in self.exchanges:
            return None
            
        try:
            exchange_instance = self.exchanges[exchange]
            order = await exchange_instance.get_order(order_id, symbol)
            
            # ローカルキャッシュも更新
            if order_id in self.active_orders:
                self.active_orders[order_id] = order
                
            return order
            
        except Exception as e:
            logger.error(f"Failed to get order status {order_id}: {e}")
            return None
            
    async def _check_balance(self, exchange: ExchangeInterface, symbol: str, 
                           side: OrderSide, size: Decimal, price: Optional[Decimal]) -> None:
        """残高チェック"""
        try:
            balances = await exchange.get_balance()
            
            # 通貨ペアから基軸通貨とクオート通貨を取得
            base_asset = symbol.split('/')[0] if '/' in symbol else symbol.replace('USDT', '').replace('USD', '')
            quote_asset = 'USDT' if 'USDT' in symbol else 'USD'
            
            if side == OrderSide.BUY:
                # 買い注文：クオート通貨が必要
                required_amount = size * (price or Decimal("999999"))  # 成行の場合は高めに見積もり
                available = balances.get(quote_asset)
                
                if not available or available.free < required_amount:
                    raise ValueError(f"Insufficient {quote_asset} balance. Required: {required_amount}, Available: {available.free if available else 0}")
                    
            else:
                # 売り注文：基軸通貨が必要
                available = balances.get(base_asset)
                
                if not available or available.free < size:
                    raise ValueError(f"Insufficient {base_asset} balance. Required: {size}, Available: {available.free if available else 0}")
                    
        except Exception as e:
            logger.warning(f"Balance check failed: {e}")
            # 残高チェックに失敗しても注文は続行（取引所側でエラーになる）
            
    async def _monitor_order(self, exchange: str, order: Order) -> None:
        """注文状態を監視"""
        max_attempts = 60  # 最大60回（約5分間）
        attempt = 0
        
        while attempt < max_attempts:
            try:
                await asyncio.sleep(5)  # 5秒間隔でチェック
                
                current_order = await self.get_order_status(order.id, exchange, order.symbol)
                if not current_order:
                    continue
                    
                # 約定またはキャンセルされた場合
                if current_order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
                    
                    if current_order.status == OrderStatus.FILLED:
                        logger.info(f"Order {order.id} filled")
                        for callback in self.order_callbacks["order_filled"]:
                            await callback(current_order)
                    
                    # 履歴に移動
                    self._move_to_history(order.id)
                    break
                    
                attempt += 1
                
            except Exception as e:
                logger.error(f"Error monitoring order {order.id}: {e}")
                attempt += 1
                
        # タイムアウト
        if attempt >= max_attempts:
            logger.warning(f"Order monitoring timeout for {order.id}")
            
    def _move_to_history(self, order_id: str) -> None:
        """注文を履歴に移動"""
        if order_id in self.active_orders:
            order = self.active_orders[order_id]
            self.order_history.append(order)
            del self.active_orders[order_id]
            
    async def get_all_balances(self) -> Dict[str, Dict[str, any]]:
        """全取引所の残高を取得"""
        all_balances = {}
        
        for exchange_name, exchange in self.exchanges.items():
            try:
                balances = await exchange.get_balance()
                all_balances[exchange_name] = {
                    asset: {
                        "free": float(balance.free),
                        "locked": float(balance.locked),
                        "total": float(balance.total)
                    }
                    for asset, balance in balances.items() if balance.total > 0
                }
            except Exception as e:
                logger.error(f"Failed to get balance from {exchange_name}: {e}")
                all_balances[exchange_name] = {}
                
        return all_balances
        
    def get_active_orders(self) -> List[Order]:
        """アクティブな注文一覧を取得"""
        return list(self.active_orders.values())
        
    def get_order_history(self, limit: int = 100) -> List[Order]:
        """注文履歴を取得"""
        return self.order_history[-limit:]
        
    def get_statistics(self) -> Dict[str, any]:
        """統計情報を取得"""
        filled_orders = [o for o in self.order_history if o.status == OrderStatus.FILLED]
        
        total_volume = sum(float(o.filled * o.price) if o.price else 0 for o in filled_orders)
        total_fees = sum(float(o.fee) if o.fee else 0 for o in filled_orders)
        
        return {
            "total_orders": len(self.order_history),
            "active_orders": len(self.active_orders),
            "filled_orders": len(filled_orders),
            "total_volume": total_volume,
            "total_fees": total_fees,
            "connected_exchanges": len(self.exchanges)
        }