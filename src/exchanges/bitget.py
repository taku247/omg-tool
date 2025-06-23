"""Bitget取引所の実装"""

import asyncio
import json
import websockets
import logging
from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime
import aiohttp

from ..interfaces.exchange import (
    ExchangeInterface, Ticker, OrderBook, Order, Balance, Position,
    OrderSide, OrderType, OrderStatus
)

logger = logging.getLogger(__name__)


class BitgetExchange(ExchangeInterface):
    """Bitget取引所実装"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        super().__init__(api_key, api_secret, testnet)
        self.name = "Bitget"
        
        # API設定
        if testnet:
            self.rest_url = "https://api.bitget.com"
            self.ws_url = "wss://ws.bitget.com/mix/v1/stream"
        else:
            self.rest_url = "https://api.bitget.com"
            self.ws_url = "wss://ws.bitget.com/mix/v1/stream"  # USDT Perpetuals
            
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
            logger.info(f"Connecting to Bitget WebSocket: {self.ws_url}")
            
            # 既存接続があれば切断
            if self.websocket:
                await self.disconnect_websocket()
                
            # WebSocket接続
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=10,
                max_size=2**20,
                compression=None
            )
            
            self.is_ws_connected = True
            logger.info("Bitget WebSocket connected successfully")
            
            # シンボルを購読
            for symbol in symbols:
                await self._subscribe_symbol(symbol)
                
            # メッセージ受信ループを開始
            asyncio.create_task(self._message_handler())
            
        except Exception as e:
            logger.error(f"Failed to connect Bitget WebSocket: {e}")
            self.is_ws_connected = False
            raise
            
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        self.is_ws_connected = False
        self.subscribed_symbols.clear()
        logger.info("Bitget WebSocket disconnected")
        
    async def _subscribe_symbol(self, symbol: str) -> None:
        """シンボルのデータを購読"""
        if not self.is_ws_connected or not self.websocket:
            return
            
        # Bitgetのシンボル形式に変換（例: BTC -> BTCUSDT_UMCBL）
        bitget_symbol = self._convert_symbol_to_bitget(symbol)
        
        # 複数のデータフィードを購読
        subscriptions = [
            # ティッカー購読
            {
                "op": "subscribe",
                "args": [{
                    "instType": "mc",
                    "channel": "ticker",
                    "instId": bitget_symbol
                }]
            },
            # 板情報購読
            {
                "op": "subscribe", 
                "args": [{
                    "instType": "mc",
                    "channel": "books",
                    "instId": bitget_symbol
                }]
            },
            # 取引データ購読
            {
                "op": "subscribe",
                "args": [{
                    "instType": "mc",
                    "channel": "trade",
                    "instId": bitget_symbol
                }]
            }
        ]
        
        try:
            for subscription in subscriptions:
                await self.websocket.send(json.dumps(subscription))
                await asyncio.sleep(0.1)
            
            self.subscribed_symbols.add(symbol)
            logger.info(f"Subscribed to Bitget feeds for {symbol} ({bitget_symbol})")
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {symbol}: {e}")
            
    def _convert_symbol_to_bitget(self, symbol: str) -> str:
        """統一シンボルをBitget形式に変換"""
        symbol_map = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT", 
            "SOL": "SOLUSDT",
            "XRP": "XRPUSDT",   # XRPを追加
            "HYPE": "HYPEUSDT",  # Hyperliquidトークン
            "WIF": "WIFUSDT",
            "PEPE": "PEPEUSDT",
            "DOGE": "DOGEUSDT",
            "BNB": "BNBUSDT"
        }
        return symbol_map.get(symbol, f"{symbol}USDT")
        
    def _convert_symbol_from_bitget(self, bitget_symbol: str) -> str:
        """Bitgetシンボルを統一形式に変換"""
        return bitget_symbol.replace("USDT", "").replace("USDC", "")
        
    async def _message_handler(self) -> None:
        """WebSocketメッセージ処理"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode Bitget WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing Bitget WebSocket message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Bitget WebSocket connection closed")
            self.is_ws_connected = False
        except Exception as e:
            logger.error(f"Bitget WebSocket message handler error: {e}")
            self.is_ws_connected = False
            
    async def _process_message(self, data: Dict) -> None:
        """受信メッセージを処理"""
        try:
            # 購読確認メッセージ
            if data.get("event") == "subscribe":
                logger.info(f"Bitget subscription confirmed: {data.get('arg', {}).get('channel')}")
                return
                
            # データメッセージ
            arg = data.get("arg", {})
            channel = arg.get("channel", "")
            inst_id = arg.get("instId", "")
            data_list = data.get("data", [])
            
            if not data_list or not inst_id:
                return
                
            symbol = self._convert_symbol_from_bitget(inst_id)
            
            # ティッカーデータ処理
            if channel == "ticker":
                for ticker_data in data_list:
                    ticker = await self._parse_ticker_data(symbol, ticker_data)
                    if ticker:
                        self.ticker_cache[symbol] = ticker
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                        
            # 板情報処理
            elif channel == "books":
                for book_data in data_list:
                    ticker = await self._parse_orderbook_data(symbol, book_data)
                    if ticker:
                        self.orderbook_cache[symbol] = book_data
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                        
            # 取引データ処理
            elif channel == "trade":
                for trade_data in data_list:
                    ticker = await self._parse_trade_data(symbol, trade_data)
                    if ticker:
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                            
        except Exception as e:
            logger.error(f"Error processing Bitget message: {e}")
            
    async def _parse_ticker_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """ティッカーデータからTicker情報を生成（データレート制限付き）"""
        try:
            # Bitget ティッカーデータ形式
            last = Decimal(str(data.get("lastPr", 0)))
            best_bid = Decimal(str(data.get("bidPr", 0)))
            best_ask = Decimal(str(data.get("askPr", 0)))
            volume_24h = Decimal(str(data.get("baseVolume", 0)))
            
            if last <= 0:
                return None
            
            # bid > ask異常値の検出と破棄
            if best_bid > best_ask and best_ask > 0:
                logger.warning(f"Bitget {symbol}: bid ({best_bid}) > ask ({best_ask}) - データをスキップします")
                return None  # 異常データは使用しない
                
            timestamp = int(data.get("ts", datetime.now().timestamp() * 1000))
            
            # データレート制限: 過度に頻繁な更新をスキップ
            now = timestamp / 1000.0
            last_time_key = f"ticker_{symbol}"
            if hasattr(self, '_last_ticker_times'):
                if last_time_key in self._last_ticker_times:
                    if now - self._last_ticker_times[last_time_key] < 0.5:  # 500ms制限
                        return None
            else:
                self._last_ticker_times = {}
            self._last_ticker_times[last_time_key] = now
                
            ticker = Ticker(
                symbol=symbol,
                bid=best_bid,
                ask=best_ask,
                last=last,
                mark_price=last,  # Bitgetではmark_priceが別途ある場合もある
                volume_24h=volume_24h,
                timestamp=timestamp
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Bitget ticker data: {e}")
            return None
            
    async def _parse_orderbook_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """板データからTicker情報を生成（データレート制限付き）"""
        try:
            # Bitget 板データ形式 [["price", "size"], ...]
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            if not bids or not asks:
                return None
                
            best_bid = Decimal(str(bids[0][0])) if bids[0] else Decimal("0")
            best_ask = Decimal(str(asks[0][0])) if asks[0] else Decimal("0")
            
            # bid > ask異常値の検出と破棄
            if best_bid > best_ask and best_ask > 0:
                logger.warning(f"Bitget {symbol}: orderbook bid ({best_bid}) > ask ({best_ask}) - データをスキップします")
                return None  # 異常データは使用しない
                
            mid_price = (best_bid + best_ask) / 2
            timestamp = int(data.get("ts", datetime.now().timestamp() * 1000))
            
            # データレート制限: 板情報は更新頻度を抑える
            now = timestamp / 1000.0
            last_time_key = f"orderbook_{symbol}"
            if hasattr(self, '_last_orderbook_times'):
                if last_time_key in self._last_orderbook_times:
                    if now - self._last_orderbook_times[last_time_key] < 0.2:  # 200ms制限
                        return None
            else:
                self._last_orderbook_times = {}
            self._last_orderbook_times[last_time_key] = now
            
            ticker = Ticker(
                symbol=symbol,
                bid=best_bid,
                ask=best_ask,
                last=mid_price,
                mark_price=mid_price,
                timestamp=timestamp
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Bitget orderbook data: {e}")
            return None
            
    async def _parse_trade_data(self, symbol: str, trade) -> Optional[Ticker]:
        """取引データからTicker情報を生成（データレート制限付き）"""
        try:
            # Bitget trade データは配列形式: [timestamp, price, size, side] 
            # または辞書形式の場合もある
            if isinstance(trade, list):
                if len(trade) < 4:
                    logger.debug(f"Bitget trade data format unexpected: {trade}")
                    return None
                    
                timestamp = int(trade[0])       # timestamp (ミリ秒)
                price = Decimal(str(trade[1]))  # price
                size = Decimal(str(trade[2]))   # size
                # trade[3] は side ("buy" or "sell")
                
            elif isinstance(trade, dict):
                price = Decimal(str(trade.get("price", 0)))
                size = Decimal(str(trade.get("size", 0)))
                timestamp = int(trade.get("ts", datetime.now().timestamp() * 1000))
            else:
                logger.warning(f"Bitget trade data unexpected type: {type(trade)} - {trade}")
                return None
            
            if price <= 0:
                return None
                
            # データレート制限: 過度に頻繁な更新をスキップ
            now = timestamp / 1000.0
            last_time_key = f"trade_{symbol}"
            if hasattr(self, '_last_trade_times'):
                if last_time_key in self._last_trade_times:
                    if now - self._last_trade_times[last_time_key] < 0.1:  # 100ms制限
                        return None
            else:
                self._last_trade_times = {}
            self._last_trade_times[last_time_key] = now
                
            # 簡易的なbid/ask計算
            spread = price * Decimal("0.0005")  # 0.05%
            
            ticker = Ticker(
                symbol=symbol,
                bid=price - spread/2,
                ask=price + spread/2,
                last=price,
                mark_price=price,
                volume_24h=size,
                timestamp=timestamp
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Bitget trade data: {e}")
            logger.error(f"Trade data: {trade}")
            return None
            
    def add_price_callback(self, callback) -> None:
        """価格更新コールバックを追加"""
        self.price_callbacks.append(callback)
        
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得（REST API）"""
        # REST APIは _UMCBL suffix が必要
        bitget_rest_symbol = f"{self._convert_symbol_to_bitget(symbol)}_UMCBL"
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/mix/v1/market/ticker"
                params = {"symbol": bitget_rest_symbol}
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"Bitget API error: {response.status}")
                        
                    result = await response.json()
                    
                    if result.get("code") != "00000":
                        raise Exception(f"Bitget API error: {result.get('msg')}")
                    
                    data = result.get("data")
                    if not data:
                        raise Exception("No ticker data returned")
                    
                    last = Decimal(str(data["last"]))
                    best_bid = Decimal(str(data["bestBid"]))
                    best_ask = Decimal(str(data["bestAsk"]))
                    
                    ticker = Ticker(
                        symbol=symbol,
                        bid=best_bid,
                        ask=best_ask,
                        last=last,
                        mark_price=last,
                        volume_24h=Decimal(str(data.get("baseVolume", 0))),
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return ticker
                    
        except Exception as e:
            logger.error(f"Failed to get Bitget ticker for {symbol}: {e}")
            raise
            
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        # REST APIは _UMCBL suffix が必要
        bitget_rest_symbol = f"{self._convert_symbol_to_bitget(symbol)}_UMCBL"
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/mix/v1/market/depth"
                params = {
                    "symbol": bitget_rest_symbol,
                    "limit": min(depth, 100)  # Bitgetの最大値
                }
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"Bitget API error: {response.status}")
                        
                    result = await response.json()
                    
                    if result.get("code") != "00000":
                        raise Exception(f"Bitget API error: {result.get('msg')}")
                    
                    data = result.get("data")
                    if not data:
                        raise Exception("No orderbook data returned")
                    
                    # Bitget 板データを変換 [["price", "size"], ...]
                    bids = [(Decimal(str(bid[0])), Decimal(str(bid[1]))) 
                           for bid in data.get("bids", [])]
                    asks = [(Decimal(str(ask[0])), Decimal(str(ask[1]))) 
                           for ask in data.get("asks", [])]
                    
                    orderbook = OrderBook(
                        symbol=symbol,
                        bids=bids,
                        asks=asks,
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return orderbook
                    
        except Exception as e:
            logger.error(f"Failed to get Bitget orderbook for {symbol}: {e}")
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
        # Bitgetの一般的な手数料（実際のAPIから取得すべき）
        return {
            "maker_fee": Decimal("0.0002"),  # 0.02% 
            "taker_fee": Decimal("0.0006")   # 0.06%
        }
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None