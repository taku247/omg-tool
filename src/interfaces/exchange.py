"""取引所統一インターフェース定義"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional
from decimal import Decimal
from enum import Enum


class OrderSide(Enum):
    """注文サイド"""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """注文タイプ"""
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    """注文ステータス"""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Ticker:
    """ティッカー情報"""
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    mark_price: Decimal
    volume_24h: Optional[Decimal] = None
    timestamp: int = 0


@dataclass
class OrderBook:
    """板情報"""
    symbol: str
    bids: List[tuple[Decimal, Decimal]]  # [(price, size), ...]
    asks: List[tuple[Decimal, Decimal]]  # [(price, size), ...]
    timestamp: int


@dataclass
class Order:
    """注文情報"""
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    price: Optional[Decimal]
    quantity: Decimal
    filled: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.PENDING
    timestamp: int = 0
    fee: Optional[Decimal] = None


@dataclass
class Balance:
    """残高情報"""
    asset: str
    free: Decimal
    locked: Decimal
    total: Decimal


@dataclass
class Position:
    """ポジション情報"""
    symbol: str
    side: OrderSide
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = Decimal("0")
    timestamp: int = 0


class ExchangeInterface(ABC):
    """取引所統一インターフェース"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.name = self.__class__.__name__
    
    @abstractmethod
    async def connect_websocket(self, symbols: List[str]) -> None:
        """WebSocket接続を確立"""
        pass
    
    @abstractmethod
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        pass
    
    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得"""
        pass
    
    @abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        pass
    
    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None
    ) -> Order:
        """注文を実行"""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセル"""
        pass
    
    @abstractmethod
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """注文情報を取得"""
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """未約定注文一覧を取得"""
        pass
    
    @abstractmethod
    async def get_balance(self) -> Dict[str, Balance]:
        """残高を取得"""
        pass
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        """ポジション情報を取得"""
        pass
    
    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """全ポジション情報を取得"""
        pass
    
    @abstractmethod
    async def get_trading_fees(self, symbol: str) -> Dict[str, Decimal]:
        """取引手数料を取得 (maker_fee, taker_fee)"""
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        pass
    
    def calculate_slippage(self, orderbook: OrderBook, side: OrderSide, 
                          quantity: Decimal) -> tuple[Decimal, Decimal]:
        """
        スリッページを計算
        Returns: (平均約定価格, スリッページ率)
        """
        book = orderbook.asks if side == OrderSide.BUY else orderbook.bids
        remaining = quantity
        total_cost = Decimal("0")
        
        for price, size in book:
            if remaining <= 0:
                break
            fill_size = min(remaining, size)
            total_cost += price * fill_size
            remaining -= fill_size
        
        if remaining > 0:
            # 板が薄くて全量約定できない
            raise ValueError(f"Insufficient liquidity. Remaining: {remaining}")
        
        avg_price = total_cost / quantity
        best_price = book[0][0]
        slippage = abs(avg_price - best_price) / best_price * 100
        
        return avg_price, slippage