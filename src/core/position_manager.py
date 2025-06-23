"""ポジション管理モジュール"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Callable
from datetime import datetime
from enum import Enum
import uuid
import logging

from ..interfaces.exchange import Order, OrderSide, OrderStatus
from .arbitrage_detector import ArbitrageOpportunity

logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    """ポジションステータス"""
    PENDING = "pending"
    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass
class ArbitragePosition:
    """アービトラージポジション"""
    id: str
    opportunity_id: str
    symbol: str
    long_exchange: str
    short_exchange: str
    size: Decimal
    entry_spread: Decimal
    exit_spread_target: Decimal = Decimal("0.1")
    
    # 注文情報
    long_order: Optional[Order] = None
    short_order: Optional[Order] = None
    close_long_order: Optional[Order] = None
    close_short_order: Optional[Order] = None
    
    # 時間情報
    created_at: datetime = field(default_factory=datetime.now)
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # 損益情報
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    
    # ステータス
    status: PositionStatus = PositionStatus.PENDING
    error_message: Optional[str] = None
    
    @property
    def is_open(self) -> bool:
        """ポジションがオープンしているか"""
        return self.status == PositionStatus.OPEN
        
    @property
    def net_pnl(self) -> Decimal:
        """手数料を差し引いた純損益"""
        return self.realized_pnl - self.fees_paid
        
    @property
    def duration(self) -> Optional[int]:
        """ポジション保有時間（秒）"""
        if self.opened_at is None:
            return None
        end_time = self.closed_at or datetime.now()
        return int((end_time - self.opened_at).total_seconds())


class PositionManager:
    """アービトラージポジション管理クラス"""
    
    def __init__(self, order_manager: 'OrderManager'):
        self.order_manager = order_manager
        self.active_positions: Dict[str, ArbitragePosition] = {}
        self.position_history: List[ArbitragePosition] = []
        self.position_callbacks: Dict[str, List[Callable]] = {
            "position_opened": [],
            "position_closed": [],
            "position_failed": []
        }
        
    def add_callback(self, event: str, callback: Callable) -> None:
        """イベントコールバックを追加"""
        if event in self.position_callbacks:
            self.position_callbacks[event].append(callback)
            
    async def open_position(self, opportunity: ArbitrageOpportunity) -> ArbitragePosition:
        """ポジションをオープン"""
        position_id = str(uuid.uuid4())
        
        position = ArbitragePosition(
            id=position_id,
            opportunity_id=opportunity.id,
            symbol=opportunity.symbol,
            long_exchange=opportunity.buy_exchange,
            short_exchange=opportunity.sell_exchange,
            size=opportunity.recommended_size,
            entry_spread=opportunity.spread_percentage,
            status=PositionStatus.OPENING
        )
        
        self.active_positions[position_id] = position
        
        try:
            # 両建て注文を同時実行
            logger.info(f"Opening position {position_id} for {opportunity.symbol}")
            
            # ロング注文（買い）
            long_order = await self.order_manager.place_order(
                exchange=opportunity.buy_exchange,
                symbol=opportunity.symbol,
                side=OrderSide.BUY,
                size=opportunity.recommended_size,
                client_order_id=f"{position_id}_long"
            )
            position.long_order = long_order
            
            # ショート注文（売り）
            short_order = await self.order_manager.place_order(
                exchange=opportunity.sell_exchange,
                symbol=opportunity.symbol,
                side=OrderSide.SELL,
                size=opportunity.recommended_size,
                client_order_id=f"{position_id}_short"
            )
            position.short_order = short_order
            
            # 両方の注文が成功したかチェック
            if (long_order.status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED] and
                short_order.status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]):
                
                position.status = PositionStatus.OPEN
                position.opened_at = datetime.now()
                
                # 手数料を計算
                position.fees_paid = (long_order.fee or Decimal("0")) + (short_order.fee or Decimal("0"))
                
                logger.info(f"Position {position_id} opened successfully")
                
                # コールバック実行
                for callback in self.position_callbacks["position_opened"]:
                    await callback(position)
                    
            else:
                position.status = PositionStatus.FAILED
                position.error_message = "Orders not filled"
                logger.error(f"Position {position_id} failed: orders not filled")
                
                # 失敗したポジションを履歴に移動
                self._move_to_history(position_id)
                
        except Exception as e:
            position.status = PositionStatus.FAILED
            position.error_message = str(e)
            logger.error(f"Failed to open position {position_id}: {e}")
            
            # エラーコールバック実行
            for callback in self.position_callbacks["position_failed"]:
                await callback(position)
                
            # 失敗したポジションを履歴に移動
            self._move_to_history(position_id)
            
        return position
        
    async def close_position(self, position_id: str, reason: str = "manual") -> bool:
        """ポジションをクローズ"""
        if position_id not in self.active_positions:
            logger.warning(f"Position {position_id} not found")
            return False
            
        position = self.active_positions[position_id]
        
        if position.status != PositionStatus.OPEN:
            logger.warning(f"Position {position_id} is not open")
            return False
            
        position.status = PositionStatus.CLOSING
        
        try:
            logger.info(f"Closing position {position_id}, reason: {reason}")
            
            # 決済注文を実行
            # ロングポジションを売却
            close_long_order = await self.order_manager.place_order(
                exchange=position.long_exchange,
                symbol=position.symbol,
                side=OrderSide.SELL,
                size=position.size,
                client_order_id=f"{position_id}_close_long"
            )
            position.close_long_order = close_long_order
            
            # ショートポジションを買戻し
            close_short_order = await self.order_manager.place_order(
                exchange=position.short_exchange,
                symbol=position.symbol,
                side=OrderSide.BUY,
                size=position.size,
                client_order_id=f"{position_id}_close_short"
            )
            position.close_short_order = close_short_order
            
            # 損益計算
            position.realized_pnl = self._calculate_pnl(position)
            position.fees_paid += (close_long_order.fee or Decimal("0")) + (close_short_order.fee or Decimal("0"))
            
            # ポジション完了
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.now()
            
            logger.info(f"Position {position_id} closed successfully, PnL: {position.net_pnl}")
            
            # コールバック実行
            for callback in self.position_callbacks["position_closed"]:
                await callback(position)
                
            # 履歴に移動
            self._move_to_history(position_id)
            
            return True
            
        except Exception as e:
            position.status = PositionStatus.FAILED
            position.error_message = f"Close failed: {str(e)}"
            logger.error(f"Failed to close position {position_id}: {e}")
            
            # エラーコールバック実行
            for callback in self.position_callbacks["position_failed"]:
                await callback(position)
                
            return False
            
    async def should_close_position(self, position: ArbitragePosition,
                                  current_spread: Decimal) -> bool:
        """ポジションをクローズすべきか判定"""
        if not position.is_open:
            return False
            
        # スプレッドが目標値以下になった場合
        if abs(current_spread) <= position.exit_spread_target:
            return True
            
        # 保有時間が長すぎる場合（24時間以上）
        if position.duration and position.duration > 24 * 3600:
            logger.info(f"Position {position.id} held too long, closing")
            return True
            
        # 損失が大きくなりすぎた場合
        if position.unrealized_pnl < -position.size * Decimal("0.1"):  # 10%の損失
            logger.warning(f"Position {position.id} has large loss, closing")
            return True
            
        return False
        
    def _calculate_pnl(self, position: ArbitragePosition) -> Decimal:
        """損益を計算"""
        if not position.long_order or not position.short_order:
            return Decimal("0")
            
        if not position.close_long_order or not position.close_short_order:
            return Decimal("0")
            
        # ロングポジションの損益
        long_pnl = (position.close_long_order.price - position.long_order.price) * position.size
        
        # ショートポジションの損益
        short_pnl = (position.short_order.price - position.close_short_order.price) * position.size
        
        return long_pnl + short_pnl
        
    def _move_to_history(self, position_id: str) -> None:
        """ポジションを履歴に移動"""
        if position_id in self.active_positions:
            position = self.active_positions[position_id]
            self.position_history.append(position)
            del self.active_positions[position_id]
            
    def get_active_positions(self) -> List[ArbitragePosition]:
        """アクティブなポジション一覧を取得"""
        return list(self.active_positions.values())
        
    def get_position_history(self, limit: int = 100) -> List[ArbitragePosition]:
        """ポジション履歴を取得"""
        return self.position_history[-limit:]
        
    def get_statistics(self) -> Dict[str, any]:
        """統計情報を取得"""
        closed_positions = [p for p in self.position_history if p.status == PositionStatus.CLOSED]
        
        if not closed_positions:
            return {
                "total_positions": len(self.position_history),
                "active_positions": len(self.active_positions),
                "closed_positions": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "avg_duration": 0
            }
            
        total_pnl = sum(p.net_pnl for p in closed_positions)
        winning_positions = [p for p in closed_positions if p.net_pnl > 0]
        win_rate = len(winning_positions) / len(closed_positions) * 100
        avg_pnl = total_pnl / len(closed_positions)
        avg_duration = sum(p.duration or 0 for p in closed_positions) / len(closed_positions)
        
        return {
            "total_positions": len(self.position_history),
            "active_positions": len(self.active_positions),
            "closed_positions": len(closed_positions),
            "win_rate": float(win_rate),
            "total_pnl": float(total_pnl),
            "avg_pnl": float(avg_pnl),
            "avg_duration": int(avg_duration)
        }