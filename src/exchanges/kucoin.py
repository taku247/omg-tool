"""KuCoin取引所の実装"""

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


class KuCoinExchange(ExchangeInterface):
    """KuCoin取引所実装"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        super().__init__(api_key, api_secret, testnet)
        self.name = "KuCoin"
        
        # API設定
        if testnet:
            self.rest_url = "https://api-sandbox-futures.kucoin.com"
            self.ws_endpoint_url = "https://api-sandbox-futures.kucoin.com/api/v1/bullet-public"
        else:
            self.rest_url = "https://api-futures.kucoin.com"
            self.ws_endpoint_url = "https://api-futures.kucoin.com/api/v1/bullet-public"
            
        # WebSocket設定（動的に取得）
        self.websocket = None
        self.ws_url = None
        self.ws_token = None
        self.subscribed_symbols = set()
        self.is_ws_connected = False
        self.price_callbacks = []
        
        # データキャッシュ
        self.ticker_cache = {}
        self.orderbook_cache = {}
        
    async def _get_websocket_endpoint(self) -> str:
        """WebSocketエンドポイントとトークンを取得"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.ws_endpoint_url) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to get KuCoin WebSocket endpoint: {response.status}")
                    
                    result = await response.json()
                    data = result.get("data")
                    if not data:
                        raise Exception("No WebSocket endpoint data returned")
                    
                    # WebSocket URLとトークンを取得
                    instances = data.get("instanceServers", [])
                    if not instances:
                        raise Exception("No WebSocket instances available")
                    
                    instance = instances[0]
                    endpoint = instance.get("endpoint")
                    token = data.get("token")
                    
                    if not endpoint or not token:
                        raise Exception("Invalid WebSocket endpoint or token")
                    
                    # URLを構築
                    ws_url = f"{endpoint}?token={token}&[connectId={int(datetime.now().timestamp() * 1000)}]"
                    
                    self.ws_url = ws_url
                    self.ws_token = token
                    
                    return ws_url
                    
        except Exception as e:
            logger.error(f"Failed to get KuCoin WebSocket endpoint: {e}")
            raise
        
    async def connect_websocket(self, symbols: List[str]) -> None:
        """WebSocket接続を確立"""
        try:
            # WebSocketエンドポイントを取得
            ws_url = await self._get_websocket_endpoint()
            logger.info(f"Connecting to KuCoin WebSocket: {ws_url[:100]}...")
            
            # 既存接続があれば切断
            if self.websocket:
                await self.disconnect_websocket()
                
            # WebSocket接続
            self.websocket = await websockets.connect(
                ws_url,
                ping_interval=18,  # KuCoinは20秒でping
                ping_timeout=10,
                max_size=2**20,
                compression=None
            )
            
            self.is_ws_connected = True
            logger.info("KuCoin WebSocket connected successfully")
            
            # シンボルを購読
            for symbol in symbols:
                await self._subscribe_symbol(symbol)
                
            # メッセージ受信ループを開始
            asyncio.create_task(self._message_handler())
            
        except Exception as e:
            logger.error(f"Failed to connect KuCoin WebSocket: {e}")
            self.is_ws_connected = False
            raise
            
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        self.is_ws_connected = False
        self.subscribed_symbols.clear()
        logger.info("KuCoin WebSocket disconnected")
        
    async def _subscribe_symbol(self, symbol: str) -> None:
        """シンボルのデータを購読"""
        if not self.is_ws_connected or not self.websocket:
            return
            
        # KuCoinのシンボル形式に変換（例: BTC -> XBTUSDTM）
        kucoin_symbol = self._convert_symbol_to_kucoin(symbol)
        
        # 複数のデータフィードを購読
        request_id = int(datetime.now().timestamp() * 1000)
        
        subscriptions = [
            # ティッカー購読
            {
                "id": str(request_id),
                "type": "subscribe", 
                "topic": f"/contractMarket/ticker:{kucoin_symbol}",
                "privateChannel": False,
                "response": True
            },
            # 板情報購読
            {
                "id": str(request_id + 1),
                "type": "subscribe",
                "topic": f"/contractMarket/level2:{kucoin_symbol}",
                "privateChannel": False,
                "response": True
            },
            # 取引データ購読
            {
                "id": str(request_id + 2),
                "type": "subscribe",
                "topic": f"/contractMarket/execution:{kucoin_symbol}",
                "privateChannel": False,
                "response": True
            }
        ]
        
        try:
            for subscription in subscriptions:
                await self.websocket.send(json.dumps(subscription))
                await asyncio.sleep(0.1)
            
            self.subscribed_symbols.add(symbol)
            logger.info(f"Subscribed to KuCoin feeds for {symbol} ({kucoin_symbol})")
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {symbol}: {e}")
            
    def _convert_symbol_to_kucoin(self, symbol: str) -> str:
        """統一シンボルをKuCoin形式に変換"""
        symbol_map = {
            "BTC": "XBTUSDTM",
            "ETH": "ETHUSDTM", 
            "SOL": "SOLUSDTM",
            "HYPE": "HYPEUSDTM",  # Hyperliquidトークン
            "WIF": "WIFUSDTM",
            "PEPE": "PEPEUSDTM",
            "DOGE": "DOGEUSDTM",
            "BNB": "BNBUSDTM"
        }
        return symbol_map.get(symbol, f"{symbol}USDTM")
        
    def _convert_symbol_from_kucoin(self, kucoin_symbol: str) -> str:
        """KuCoinシンボルを統一形式に変換"""
        # XBT -> BTC の特別な変換
        if kucoin_symbol.startswith("XBT"):
            return "BTC"
        return kucoin_symbol.replace("USDTM", "").replace("USDCM", "")
        
    async def _message_handler(self) -> None:
        """WebSocketメッセージ処理"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode KuCoin WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing KuCoin WebSocket message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("KuCoin WebSocket connection closed")
            self.is_ws_connected = False
        except Exception as e:
            logger.error(f"KuCoin WebSocket message handler error: {e}")
            self.is_ws_connected = False
            
    async def _process_message(self, data: Dict) -> None:
        """受信メッセージを処理"""
        try:
            # 購読確認メッセージ
            if data.get("type") == "ack":
                logger.info(f"KuCoin subscription confirmed: {data.get('id')}")
                return
                
            # Welcomeメッセージ
            if data.get("type") == "welcome":
                logger.info("KuCoin WebSocket welcome received")
                return
                
            # データメッセージ
            if data.get("type") == "message":
                topic = data.get("topic", "")
                subject = data.get("subject", "")
                msg_data = data.get("data", {})
                
                if not msg_data:
                    return
                    
                # トピックからシンボルを抽出
                symbol = self._extract_symbol_from_topic(topic)
                if not symbol:
                    return
                
                # ティッカーデータ処理
                if "ticker" in topic:
                    ticker = await self._parse_ticker_data(symbol, msg_data)
                    if ticker:
                        self.ticker_cache[symbol] = ticker
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                        
                # 板情報処理
                elif "level2" in topic:
                    ticker = await self._parse_orderbook_data(symbol, msg_data)
                    if ticker:
                        self.orderbook_cache[symbol] = msg_data
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                        
                # 取引データ処理
                elif "execution" in topic:
                    ticker = await self._parse_trade_data(symbol, msg_data)
                    if ticker:
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                            
        except Exception as e:
            logger.error(f"Error processing KuCoin message: {e}")
            
    def _extract_symbol_from_topic(self, topic: str) -> str:
        """トピックから統一シンボルを抽出"""
        # トピック例: /contractMarket/ticker:XBTUSDTM
        parts = topic.split(":")
        if len(parts) > 1:
            kucoin_symbol = parts[1]
            return self._convert_symbol_from_kucoin(kucoin_symbol)
        return ""
        
    async def _parse_ticker_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """ティッカーデータからTicker情報を生成"""
        try:
            # KuCoin ティッカーデータ形式
            last = Decimal(str(data.get("price", 0)))
            best_bid = Decimal(str(data.get("bestBidPrice", 0)))
            best_ask = Decimal(str(data.get("bestAskPrice", 0)))
            volume_24h = Decimal(str(data.get("turnover24h", 0)))
            
            if last <= 0:
                return None
                
            ticker = Ticker(
                symbol=symbol,
                bid=best_bid,
                ask=best_ask,
                last=last,
                mark_price=last,  # KuCoinでは別途取得可能
                volume_24h=volume_24h,
                timestamp=int(data.get("ts", datetime.now().timestamp() * 1000000) // 1000)  # nsをmsに変換
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing KuCoin ticker data: {e}")
            return None
            
    async def _parse_orderbook_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """板データからTicker情報を生成"""
        try:
            # KuCoin 板データ形式
            changes = data.get("changes", {})
            bids = changes.get("bids", [])
            asks = changes.get("asks", [])
            
            if not bids or not asks:
                return None
                
            # Format: [["price", "size"], ...]
            best_bid = Decimal(str(bids[0][0])) if bids[0] else Decimal("0")
            best_ask = Decimal(str(asks[0][0])) if asks[0] else Decimal("0")
            mid_price = (best_bid + best_ask) / 2
            
            ticker = Ticker(
                symbol=symbol,
                bid=best_bid,
                ask=best_ask,
                last=mid_price,
                mark_price=mid_price,
                timestamp=int(data.get("ts", datetime.now().timestamp() * 1000000) // 1000)
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing KuCoin orderbook data: {e}")
            return None
            
    async def _parse_trade_data(self, symbol: str, trade: Dict) -> Optional[Ticker]:
        """取引データからTicker情報を生成"""
        try:
            price = Decimal(str(trade.get("price", 0)))
            size = Decimal(str(trade.get("size", 0)))
            
            if price <= 0:
                return None
                
            # 簡易的なbid/ask計算
            spread = price * Decimal("0.0005")  # 0.05%
            
            ticker = Ticker(
                symbol=symbol,
                bid=price - spread/2,
                ask=price + spread/2,
                last=price,
                mark_price=price,
                volume_24h=size,
                timestamp=int(trade.get("ts", datetime.now().timestamp() * 1000000) // 1000)
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing KuCoin trade data: {e}")
            return None
            
    def add_price_callback(self, callback) -> None:
        """価格更新コールバックを追加"""
        self.price_callbacks.append(callback)
        
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得（REST API）"""
        kucoin_symbol = self._convert_symbol_to_kucoin(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v1/ticker"
                params = {"symbol": kucoin_symbol}
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"KuCoin API error: {response.status}")
                        
                    result = await response.json()
                    
                    if result.get("code") != "200000":
                        raise Exception(f"KuCoin API error: {result.get('msg')}")
                    
                    data = result.get("data")
                    if not data:
                        raise Exception("No ticker data returned")
                    
                    last = Decimal(str(data["price"]))
                    best_bid = Decimal(str(data["bestBidPrice"]))
                    best_ask = Decimal(str(data["bestAskPrice"]))
                    
                    ticker = Ticker(
                        symbol=symbol,
                        bid=best_bid,
                        ask=best_ask,
                        last=last,
                        mark_price=last,
                        volume_24h=Decimal(str(data.get("turnover24h", 0))),
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return ticker
                    
        except Exception as e:
            logger.error(f"Failed to get KuCoin ticker for {symbol}: {e}")
            raise
            
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        kucoin_symbol = self._convert_symbol_to_kucoin(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                # 深度に応じてエンドポイントを選択
                if depth <= 20:
                    endpoint = "/api/v1/level2/depth20"
                elif depth <= 100:
                    endpoint = "/api/v1/level2/depth100"
                else:
                    endpoint = "/api/v1/level2/snapshot"
                    
                url = f"{self.rest_url}{endpoint}"
                params = {"symbol": kucoin_symbol}
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"KuCoin API error: {response.status}")
                        
                    result = await response.json()
                    
                    if result.get("code") != "200000":
                        raise Exception(f"KuCoin API error: {result.get('msg')}")
                    
                    data = result.get("data")
                    if not data:
                        raise Exception("No orderbook data returned")
                    
                    # KuCoin 板データを変換 [price, size]
                    bids = [(Decimal(str(bid[0])), Decimal(str(bid[1]))) 
                           for bid in data.get("bids", [])[:depth]]
                    asks = [(Decimal(str(ask[0])), Decimal(str(ask[1]))) 
                           for ask in data.get("asks", [])[:depth]]
                    
                    orderbook = OrderBook(
                        symbol=symbol,
                        bids=bids,
                        asks=asks,
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return orderbook
                    
        except Exception as e:
            logger.error(f"Failed to get KuCoin orderbook for {symbol}: {e}")
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
        # KuCoinの一般的な手数料（実際のAPIから取得すべき）
        return {
            "maker_fee": Decimal("0.0002"),  # 0.02% 
            "taker_fee": Decimal("0.0006")   # 0.06%
        }
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None