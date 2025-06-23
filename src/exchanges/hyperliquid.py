"""Hyperliquid取引所の実装"""

import asyncio
import json
import websockets
import logging
from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime

from ..interfaces.exchange import (
    ExchangeInterface, Ticker, OrderBook, Order, Balance, Position,
    OrderSide, OrderType, OrderStatus
)

logger = logging.getLogger(__name__)


class HyperliquidExchange(ExchangeInterface):
    """Hyperliquid取引所実装"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        super().__init__(api_key, api_secret, testnet)
        self.name = "Hyperliquid"
        
        # WebSocket設定
        self.ws_url = "wss://api.hyperliquid.xyz/ws"
        self.websocket = None
        self.subscribed_symbols = set()
        self.is_ws_connected = False
        self.price_callbacks = []
        
        # REST API設定（参考コードから）
        try:
            from hyperliquid.info import Info
            from hyperliquid.utils import constants
            
            self.info = Info(constants.MAINNET_API_URL if not testnet else constants.TESTNET_API_URL)
            self.has_hyperliquid_lib = True
            logger.info("Hyperliquid library loaded successfully")
        except ImportError:
            logger.warning("Hyperliquid library not found. Some features may be limited.")
            self.has_hyperliquid_lib = False
            self.info = None
            
    async def connect_websocket(self, symbols: List[str]) -> None:
        """WebSocket接続を確立"""
        try:
            logger.info(f"Connecting to Hyperliquid WebSocket: {self.ws_url}")
            
            # 既存接続があれば切断
            if self.websocket:
                await self.disconnect_websocket()
                
            # WebSocket接続
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=10,
                max_size=2**20,  # 1MB
                compression=None
            )
            
            self.is_ws_connected = True
            logger.info("WebSocket connected successfully")
            
            # シンボルを購読
            for symbol in symbols:
                await self._subscribe_symbol(symbol)
                
            # メッセージ受信ループを開始
            asyncio.create_task(self._message_handler())
            
        except Exception as e:
            logger.error(f"Failed to connect WebSocket: {e}")
            self.is_ws_connected = False
            raise
            
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        self.is_ws_connected = False
        self.subscribed_symbols.clear()
        logger.info("WebSocket disconnected")
        
    async def _subscribe_symbol(self, symbol: str) -> None:
        """シンボルのティッカー情報を購読"""
        if not self.is_ws_connected or not self.websocket:
            return
            
        # 複数のデータフィードを購読
        subscription_types = [
            {
                "method": "subscribe",
                "subscription": {
                    "type": "l2Book",
                    "coin": symbol
                }
            },
            {
                "method": "subscribe", 
                "subscription": {
                    "type": "trades",
                    "coin": symbol
                }
            }
        ]
        
        # allMidsも購読（全銘柄の中間価格）
        if not hasattr(self, '_subscribed_allmids'):
            subscription_types.append({
                "method": "subscribe",
                "subscription": {
                    "type": "allMids"
                }
            })
            self._subscribed_allmids = True
        
        try:
            for sub_msg in subscription_types:
                await self.websocket.send(json.dumps(sub_msg))
                logger.info(f"Subscribed to {sub_msg['subscription']['type']} for {symbol}")
                
            self.subscribed_symbols.add(symbol)
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {symbol}: {e}")
            
    async def _message_handler(self) -> None:
        """WebSocketメッセージ処理"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.is_ws_connected = False
        except Exception as e:
            logger.error(f"WebSocket message handler error: {e}")
            self.is_ws_connected = False
            
    async def _process_message(self, data: Dict) -> None:
        """受信メッセージを処理してティッカー情報を抽出"""
        try:
            # Hyperliquidのメッセージ形式に応じた処理
            channel = data.get("channel")
            msg_data = data.get("data")
            
            if channel == "l2Book" and msg_data:
                # L2 Book データの処理
                symbol = msg_data.get("coin")
                if symbol:
                    ticker = await self._parse_l2book_data(msg_data)
                    if ticker:
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                            
            elif channel == "trades" and msg_data:
                # Trade データの処理
                for trade in msg_data:
                    symbol = trade.get("coin")
                    if symbol:
                        ticker = await self._parse_trade_data(trade)
                        if ticker:
                            for callback in self.price_callbacks:
                                await callback(self.name, ticker)
                                
            elif channel == "allMids" and msg_data:
                # 全銘柄の中間価格データの処理
                await self._process_allmids_data(msg_data)
                            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            
    async def _parse_l2book_data(self, data: Dict) -> Optional[Ticker]:
        """L2 Book データからTicker情報を生成"""
        try:
            symbol = data.get("coin")
            if not symbol:
                return None
                
            levels = data.get("levels", [])
            if not levels or len(levels) < 2:
                return None
                
            # Hyperliquid L2Book形式: levels[0]=bids, levels[1]=asks
            bids = []
            asks = []
            
            # Bids処理（levels[0]）
            for bid_level in levels[0]:
                px = Decimal(str(bid_level["px"]))
                sz = Decimal(str(bid_level["sz"]))
                bids.append((px, sz))
                
            # Asks処理（levels[1]）
            for ask_level in levels[1]:
                px = Decimal(str(ask_level["px"]))
                sz = Decimal(str(ask_level["sz"]))
                asks.append((px, sz))
                    
            if not bids or not asks:
                return None
                
            # 価格順でソート
            bids.sort(reverse=True)  # 高い順
            asks.sort()  # 安い順
            
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            mid_price = (best_bid + best_ask) / 2
            
            ticker = Ticker(
                symbol=symbol,
                bid=best_bid,
                ask=best_ask,
                last=mid_price,
                mark_price=mid_price,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing L2 book data: {e}")
            return None
            
    async def _parse_trade_data(self, trade: Dict) -> Optional[Ticker]:
        """Trade データからTicker情報を生成"""
        try:
            symbol = trade.get("coin")
            price = Decimal(str(trade.get("px", 0)))
            
            if not symbol or price <= 0:
                return None
                
            # トレード価格を最新価格として使用
            # bid/askは簡易的にスプレッドを想定
            spread = price * Decimal("0.001")  # 0.1%
            
            ticker = Ticker(
                symbol=symbol,
                bid=price - spread/2,
                ask=price + spread/2,
                last=price,
                mark_price=price,
                volume_24h=Decimal(str(trade.get("sz", 0))),
                timestamp=int(trade.get("time", datetime.now().timestamp() * 1000))
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing trade data: {e}")
            return None
            
    async def _process_allmids_data(self, data: Dict) -> None:
        """全銘柄中間価格データを処理"""
        try:
            # allMidsデータには全銘柄の中間価格が含まれる
            mids = data.get("mids", {})
            
            for symbol, mid_price in mids.items():
                if symbol in self.subscribed_symbols:
                    price = Decimal(str(mid_price))
                    spread = price * Decimal("0.001")  # 0.1%
                    
                    ticker = Ticker(
                        symbol=symbol,
                        bid=price - spread/2,
                        ask=price + spread/2,
                        last=price,
                        mark_price=price,
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    for callback in self.price_callbacks:
                        await callback(self.name, ticker)
                        
        except Exception as e:
            logger.error(f"Error processing allMids data: {e}")
            
    def add_price_callback(self, callback) -> None:
        """価格更新コールバックを追加"""
        self.price_callbacks.append(callback)
        
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得（REST API）"""
        if not self.has_hyperliquid_lib or not self.info:
            raise NotImplementedError("Hyperliquid library not available")
            
        try:
            # REST APIでティッカー情報を取得
            # 実際のHyperliquid APIメソッドに応じて実装
            market_data = self.info.all_mids()  # 全銘柄の中間価格
            
            if symbol not in market_data:
                raise ValueError(f"Symbol {symbol} not found")
                
            mid_price = Decimal(str(market_data[symbol]))
            
            # 板情報も取得してbid/askを計算
            # これは簡易実装で、実際にはl2_snapshot等を使用
            spread = mid_price * Decimal("0.001")  # 0.1%のスプレッドと仮定
            
            ticker = Ticker(
                symbol=symbol,
                bid=mid_price - spread/2,
                ask=mid_price + spread/2,
                last=mid_price,
                mark_price=mid_price,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Failed to get ticker for {symbol}: {e}")
            raise
            
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        if not self.has_hyperliquid_lib or not self.info:
            raise NotImplementedError("Hyperliquid library not available")
            
        try:
            # Hyperliquid API仕様に基づく正しい実装
            l2_data = self.info.l2_snapshot(symbol)
            
            bids = []
            asks = []
            
            # Hyperliquidの実際のデータ形式: levels is array of arrays
            levels = l2_data.get("levels", [])
            
            if len(levels) >= 2:
                # levels[0] = bids, levels[1] = asks
                bid_levels = levels[0] if len(levels) > 0 else []
                ask_levels = levels[1] if len(levels) > 1 else []
                
                # Bidsを処理（配列の各要素は {px: price, sz: size}）
                for level in bid_levels[:depth]:
                    if isinstance(level, dict) and "px" in level and "sz" in level:
                        price = Decimal(str(level["px"]))
                        size = Decimal(str(level["sz"]))
                        bids.append((price, size))
                        
                # Asksを処理
                for level in ask_levels[:depth]:
                    if isinstance(level, dict) and "px" in level and "sz" in level:
                        price = Decimal(str(level["px"]))
                        size = Decimal(str(level["sz"]))
                        asks.append((price, size))
            
            # 価格順でソート
            bids.sort(reverse=True)  # 高い順
            asks.sort()  # 安い順
            
            orderbook = OrderBook(
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=l2_data.get("time", int(datetime.now().timestamp() * 1000))
            )
            
            return orderbook
            
        except Exception as e:
            logger.error(f"Failed to get orderbook for {symbol}: {e}")
            raise
            
    async def place_order(self, symbol: str, side: OrderSide, quantity: Decimal,
                         order_type: OrderType = OrderType.MARKET,
                         price: Optional[Decimal] = None,
                         client_order_id: Optional[str] = None) -> Order:
        """注文を実行（実装予定）"""
        raise NotImplementedError("Order placement not yet implemented")
        
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセル（実装予定）"""
        raise NotImplementedError("Order cancellation not yet implemented")
        
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """注文情報を取得（実装予定）"""
        raise NotImplementedError("Get order not yet implemented")
        
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """未約定注文一覧を取得（実装予定）"""
        raise NotImplementedError("Get open orders not yet implemented")
        
    async def get_balance(self) -> Dict[str, Balance]:
        """残高を取得（実装予定）"""
        raise NotImplementedError("Get balance not yet implemented")
        
    async def get_position(self, symbol: str) -> Optional[Position]:
        """ポジション情報を取得（実装予定）"""
        raise NotImplementedError("Get position not yet implemented")
        
    async def get_positions(self) -> List[Position]:
        """全ポジション情報を取得（実装予定）"""
        raise NotImplementedError("Get positions not yet implemented")
        
    async def get_trading_fees(self, symbol: str) -> Dict[str, Decimal]:
        """取引手数料を取得"""
        # Hyperliquidの一般的な手数料（実際のAPIから取得すべき）
        return {
            "maker_fee": Decimal("0.0002"),  # 0.02%
            "taker_fee": Decimal("0.0005")   # 0.05%
        }
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None