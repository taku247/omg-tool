"""Bybit取引所の実装"""

import asyncio
import json
import websockets
import logging
import time
from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime
import aiohttp

from ..interfaces.exchange import (
    ExchangeInterface, Ticker, OrderBook, Order, Balance, Position,
    OrderSide, OrderType, OrderStatus
)

logger = logging.getLogger(__name__)


class BybitExchange(ExchangeInterface):
    """Bybit取引所実装"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        super().__init__(api_key, api_secret, testnet)
        self.name = "Bybit"
        
        # API設定
        if testnet:
            self.rest_url = "https://api-testnet.bybit.com"
            self.ws_url = "wss://stream-testnet.bybit.com/v5/public/linear"
        else:
            self.rest_url = "https://api.bybit.com"
            self.ws_url = "wss://stream.bybit.com/v5/public/linear"
            
        # WebSocket設定
        self.websocket = None
        self.subscribed_symbols = set()
        self.is_ws_connected = False
        self.price_callbacks = []
        
        # データキャッシュ
        self.ticker_cache = {}
        self.orderbook_cache = {}
        
    async def connect_websocket(self, symbols: List[str]) -> None:
        """WebSocket接続を確立"""
        try:
            logger.info(f"Connecting to Bybit WebSocket: {self.ws_url}")
            
            # 既存接続があれば切断
            if self.websocket:
                await self.disconnect_websocket()
                
            # WebSocket接続
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=20,    # Bybitの推奨値
                ping_timeout=10,
                max_size=2**20,
                compression=None
            )
            
            self.is_ws_connected = True
            logger.info("Bybit WebSocket connected successfully")
            
            # シンボルを購読
            for symbol in symbols:
                await self._subscribe_symbol(symbol)
                
            # メッセージ受信ループを開始
            asyncio.create_task(self._message_handler())
            
        except Exception as e:
            logger.error(f"Failed to connect Bybit WebSocket: {e}")
            self.is_ws_connected = False
            raise
            
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        self.is_ws_connected = False
        self.subscribed_symbols.clear()
        logger.info("Bybit WebSocket disconnected")
        
    async def _subscribe_symbol(self, symbol: str) -> None:
        """シンボルのデータを購読"""
        if not self.is_ws_connected or not self.websocket:
            return
            
        # Bybitのシンボル形式に変換（例: BTC -> BTCUSDT）
        bybit_symbol = self._convert_symbol_to_bybit(symbol)
        
        # 複数のデータフィードを購読
        subscriptions = {
            "req_id": f"sub_{symbol}_{int(datetime.now().timestamp())}",
            "op": "subscribe",
            "args": [
                f"orderbook.1.{bybit_symbol}",      # レベル1板情報
                f"publicTrade.{bybit_symbol}",      # 公開取引データ
                f"tickers.{bybit_symbol}"           # ティッカー情報
            ]
        }
        
        try:
            await self.websocket.send(json.dumps(subscriptions))
            self.subscribed_symbols.add(symbol)
            logger.info(f"Subscribed to Bybit feeds for {symbol} ({bybit_symbol})")
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {symbol}: {e}")
            
    def _convert_symbol_to_bybit(self, symbol: str) -> str:
        """統一シンボルをBybit形式に変換"""
        symbol_map = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT", 
            "SOL": "SOLUSDT",
            "HYPE": "HYPEUSDT",  # Hyperliquidトークン
            "WIF": "WIFUSDT",
            "PEPE": "PEPEUSDT"
        }
        return symbol_map.get(symbol, f"{symbol}USDT")
        
    def _convert_symbol_from_bybit(self, bybit_symbol: str) -> str:
        """Bybitシンボルを統一形式に変換"""
        return bybit_symbol.replace("USDT", "").replace("USDC", "")
        
    async def _message_handler(self) -> None:
        """WebSocketメッセージ処理"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode Bybit WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing Bybit WebSocket message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Bybit WebSocket connection closed")
            self.is_ws_connected = False
        except Exception as e:
            logger.error(f"Bybit WebSocket message handler error: {e}")
            self.is_ws_connected = False
            
    async def _process_message(self, data: Dict) -> None:
        """受信メッセージを処理"""
        try:
            # 購読確認メッセージ
            if data.get("op") == "subscribe" and data.get("success"):
                logger.info(f"Bybit subscription confirmed: {data.get('req_id')}")
                return
                
            # データメッセージ
            topic = data.get("topic", "")
            msg_data = data.get("data")
            
            if not topic or not msg_data:
                return
                
            # ティッカーデータ処理
            if topic.startswith("tickers."):
                symbol = self._extract_symbol_from_topic(topic)
                ticker = await self._parse_ticker_data(symbol, msg_data)
                if ticker:
                    self.ticker_cache[symbol] = ticker
                    for callback in self.price_callbacks:
                        await callback(self.name, ticker)
                        
            # 板情報処理
            elif topic.startswith("orderbook."):
                symbol = self._extract_symbol_from_topic(topic)
                ticker = await self._parse_orderbook_data(symbol, msg_data)
                if ticker:
                    # 板情報をキャッシュ
                    self.orderbook_cache[symbol] = msg_data
                    # ティッカー形式でも配信
                    for callback in self.price_callbacks:
                        await callback(self.name, ticker)
                        
            # 取引データ処理
            elif topic.startswith("publicTrade."):
                symbol = self._extract_symbol_from_topic(topic)
                if isinstance(msg_data, list) and msg_data:
                    # 最新の取引データを使用
                    trade = msg_data[0]
                    ticker = await self._parse_trade_data(symbol, trade)
                    if ticker:
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                            
        except Exception as e:
            logger.error(f"Error processing Bybit message: {e}")
            
    def _extract_symbol_from_topic(self, topic: str) -> str:
        """トピックから統一シンボルを抽出"""
        # topic例: "tickers.BTCUSDT" -> "BTC", "orderbook.1.BTCUSDT" -> "BTC"
        parts = topic.split(".")
        if len(parts) >= 2:
            if topic.startswith("orderbook."):
                # orderbook.1.BTCUSDT -> BTCUSDT is at index 2
                if len(parts) >= 3:
                    bybit_symbol = parts[2]
                else:
                    return ""
            else:
                # tickers.BTCUSDT or publicTrade.BTCUSDT -> BTCUSDT is at index 1
                bybit_symbol = parts[1]
            return self._convert_symbol_from_bybit(bybit_symbol)
        return ""
        
    async def _parse_ticker_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """ティッカーデータからTicker情報を生成"""
        try:
            # Bybit ティッカーデータ形式
            bid = Decimal(str(data.get("bid1Price", 0)))
            ask = Decimal(str(data.get("ask1Price", 0)))
            last = Decimal(str(data.get("lastPrice", 0)))
            volume_24h = Decimal(str(data.get("volume24h", 0)))
            
            if bid <= 0 or ask <= 0 or last <= 0:
                return None
                
            ticker = Ticker(
                symbol=symbol,
                bid=bid,
                ask=ask,
                last=last,
                mark_price=Decimal(str(data.get("markPrice", last))),
                volume_24h=volume_24h,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Bybit ticker data: {e}")
            return None
            
    async def _parse_orderbook_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """板データからTicker情報を生成"""
        try:
            # Bybit 板データ形式
            bids = data.get("b", [])  # [[price, size], ...]
            asks = data.get("a", [])  # [[price, size], ...]
            
            if not bids or not asks:
                return None
                
            best_bid = Decimal(str(bids[0][0]))
            best_ask = Decimal(str(asks[0][0]))
            mid_price = (best_bid + best_ask) / 2
            
            ticker = Ticker(
                symbol=symbol,
                bid=best_bid,
                ask=best_ask,
                last=mid_price,
                mark_price=mid_price,
                timestamp=int(data.get("ts", datetime.now().timestamp() * 1000))
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Bybit orderbook data: {e}")
            return None
            
    async def _parse_trade_data(self, symbol: str, trade: Dict) -> Optional[Ticker]:
        """取引データからTicker情報を生成"""
        try:
            price = Decimal(str(trade.get("p", 0)))
            size = Decimal(str(trade.get("v", 0)))
            
            if price <= 0:
                return None
                
            # 簡易的なbid/ask計算
            spread = price * Decimal("0.001")  # 0.1%
            
            ticker = Ticker(
                symbol=symbol,
                bid=price - spread/2,
                ask=price + spread/2,
                last=price,
                mark_price=price,
                volume_24h=size,
                timestamp=int(trade.get("T", datetime.now().timestamp() * 1000))
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Bybit trade data: {e}")
            return None
            
    def add_price_callback(self, callback) -> None:
        """価格更新コールバックを追加"""
        self.price_callbacks.append(callback)
        
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得（REST API）"""
        bybit_symbol = self._convert_symbol_to_bybit(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/v5/market/tickers"
                params = {
                    "category": "linear",  # perpetual futures
                    "symbol": bybit_symbol
                }
                
                async with session.get(url, params=params) as response:
                    data = await response.json()
                    
                    if data.get("retCode") != 0:
                        raise Exception(f"Bybit API error: {data.get('retMsg')}")
                        
                    ticker_data = data["result"]["list"][0]
                    
                    bid = Decimal(str(ticker_data["bid1Price"]))
                    ask = Decimal(str(ticker_data["ask1Price"]))
                    last = Decimal(str(ticker_data["lastPrice"]))
                    
                    ticker = Ticker(
                        symbol=symbol,
                        bid=bid,
                        ask=ask,
                        last=last,
                        mark_price=Decimal(str(ticker_data.get("markPrice", last))),
                        volume_24h=Decimal(str(ticker_data.get("volume24h", 0))),
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return ticker
                    
        except Exception as e:
            logger.error(f"Failed to get Bybit ticker for {symbol}: {e}")
            raise
            
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        bybit_symbol = self._convert_symbol_to_bybit(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/v5/market/orderbook"
                params = {
                    "category": "linear",
                    "symbol": bybit_symbol,
                    "limit": min(depth, 200)  # Bybitの最大値
                }
                
                async with session.get(url, params=params) as response:
                    data = await response.json()
                    
                    if data.get("retCode") != 0:
                        raise Exception(f"Bybit API error: {data.get('retMsg')}")
                        
                    result = data["result"]
                    
                    # 板データを変換
                    bids = [(Decimal(str(bid[0])), Decimal(str(bid[1]))) 
                           for bid in result.get("b", [])]
                    asks = [(Decimal(str(ask[0])), Decimal(str(ask[1]))) 
                           for ask in result.get("a", [])]
                    
                    orderbook = OrderBook(
                        symbol=symbol,
                        bids=bids,
                        asks=asks,
                        timestamp=int(result.get("ts", datetime.now().timestamp() * 1000))
                    )
                    
                    return orderbook
                    
        except Exception as e:
            logger.error(f"Failed to get Bybit orderbook for {symbol}: {e}")
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
        # Bybitの一般的な手数料（実際のAPIから取得すべき）
        return {
            "maker_fee": Decimal("0.0001"),  # 0.01% 
            "taker_fee": Decimal("0.0006")   # 0.06%
        }
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None