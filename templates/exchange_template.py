"""取引所実装テンプレート"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
from datetime import datetime

from ..interfaces.exchange import (
    ExchangeInterface, Ticker, OrderBook, Order, Balance, Position,
    OrderSide, OrderType, OrderStatus
)

logger = logging.getLogger(__name__)


class TemplateExchange(ExchangeInterface):
    """取引所実装テンプレート - 各取引所でこのテンプレートをコピーして使用"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False, **kwargs):
        super().__init__(api_key, api_secret, testnet)
        self.name = "Template"  # 実際の取引所名に変更
        
        # API設定
        self.base_url = "https://api.example.com" if not testnet else "https://api-testnet.example.com"
        self.ws_url = "wss://stream.example.com" if not testnet else "wss://stream-testnet.example.com"
        
        # WebSocket関連
        self.websocket = None
        self.subscribed_symbols = set()
        self.is_ws_connected = False
        self.price_callbacks = []
        
        # HTTP クライアント設定
        self.session = None
        
        # 取引所固有設定
        self.passphrase = kwargs.get('passphrase')  # KuCoin用
        self.leverage = kwargs.get('leverage', 1)   # レバレッジ設定
        
    # ========================================
    # WebSocket関連メソッド（価格監視）
    # ========================================
    
    async def connect_websocket(self, symbols: List[str]) -> None:
        """WebSocket接続を確立"""
        try:
            logger.info(f"Connecting to {self.name} WebSocket: {self.ws_url}")
            
            # WebSocket接続
            import websockets
            self.websocket = await websockets.connect(self.ws_url)
            self.is_ws_connected = True
            
            # シンボル購読
            for symbol in symbols:
                await self._subscribe_symbol(symbol)
                
            # メッセージハンドラー開始
            asyncio.create_task(self._message_handler())
            
            logger.info(f"{self.name} WebSocket connected successfully")
            
        except Exception as e:
            logger.error(f"Failed to connect {self.name} WebSocket: {e}")
            self.is_ws_connected = False
            raise
            
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        try:
            if self.websocket:
                await self.websocket.close()
                self.is_ws_connected = False
                logger.info(f"{self.name} WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting {self.name} WebSocket: {e}")
            
    async def _subscribe_symbol(self, symbol: str) -> None:
        """シンボル購読"""
        try:
            # 取引所固有の購読メッセージを送信
            subscribe_msg = {
                "method": "SUBSCRIBE",
                "params": [f"{symbol.lower()}@ticker"],
                "id": int(datetime.now().timestamp())
            }
            
            await self.websocket.send(json.dumps(subscribe_msg))
            self.subscribed_symbols.add(symbol)
            logger.info(f"Subscribed to {self.name} {symbol}")
            
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
                    logger.error(f"Failed to decode {self.name} WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing {self.name} WebSocket message: {e}")
                    
        except Exception as e:
            logger.error(f"{self.name} WebSocket message handler error: {e}")
            self.is_ws_connected = False
            
    async def _process_message(self, data: Dict) -> None:
        """受信メッセージを処理してティッカー情報を抽出"""
        try:
            # 取引所固有のメッセージ処理ロジック
            # 例: Binance形式
            if 'stream' in data and 'data' in data:
                stream = data['stream']
                ticker_data = data['data']
                
                if '@ticker' in stream:
                    symbol = self._extract_symbol_from_stream(stream)
                    ticker = self._parse_ticker_data(ticker_data, symbol)
                    
                    if ticker:
                        for callback in self.price_callbacks:
                            await callback(self.name, ticker)
                            
        except Exception as e:
            logger.error(f"Error processing {self.name} message: {e}")
            
    def _extract_symbol_from_stream(self, stream: str) -> str:
        """ストリームからシンボルを抽出"""
        # 例: "btcusdt@ticker" -> "BTC"
        return stream.split('@')[0].upper().replace('USDT', '')
        
    def _parse_ticker_data(self, data: Dict, symbol: str) -> Optional[Ticker]:
        """ティッカーデータをパース"""
        try:
            return Ticker(
                symbol=symbol,
                bid=Decimal(str(data.get('b', 0))),
                ask=Decimal(str(data.get('a', 0))),
                last=Decimal(str(data.get('c', 0))),
                mark_price=Decimal(str(data.get('c', 0))),
                volume_24h=Decimal(str(data.get('v', 0))),
                timestamp=int(data.get('E', datetime.now().timestamp() * 1000))
            )
        except Exception as e:
            logger.error(f"Error parsing {self.name} ticker data: {e}")
            return None
            
    # ========================================
    # REST API関連メソッド
    # ========================================
    
    async def _init_session(self) -> None:
        """HTTPセッション初期化"""
        if not self.session:
            import aiohttp
            self.session = aiohttp.ClientSession()
            
    async def _api_request(self, method: str, endpoint: str, params: Dict = None, 
                          signed: bool = False) -> Dict:
        """API リクエスト実行"""
        await self._init_session()
        
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        if signed:
            # 認証署名を追加
            headers.update(self._create_signature(method, endpoint, params))
            
        try:
            async with self.session.request(method, url, json=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"{self.name} API error {response.status}: {error_text}")
                    
        except Exception as e:
            logger.error(f"{self.name} API request failed: {e}")
            raise
            
    def _create_signature(self, method: str, endpoint: str, params: Dict = None) -> Dict[str, str]:
        """API認証署名を作成"""
        import hmac
        import hashlib
        import time
        
        timestamp = str(int(time.time() * 1000))
        
        # 取引所固有の署名ロジック
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        else:
            query_string = ""
            
        # 署名文字列作成（取引所により異なる）
        message = f"{timestamp}{method}{endpoint}{query_string}"
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return {
            "X-API-KEY": self.api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature
        }
        
    # ========================================
    # 必須実装メソッド（取引所固有で実装）
    # ========================================
    
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得"""
        try:
            response = await self._api_request("GET", f"/api/v1/ticker/{symbol}")
            return self._parse_ticker_response(response, symbol)
        except Exception as e:
            logger.error(f"Failed to get {self.name} ticker for {symbol}: {e}")
            raise
            
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        try:
            params = {"symbol": symbol, "limit": depth}
            response = await self._api_request("GET", "/api/v1/orderbook", params)
            return self._parse_orderbook_response(response, symbol)
        except Exception as e:
            logger.error(f"Failed to get {self.name} orderbook for {symbol}: {e}")
            raise
            
    async def place_order(self, symbol: str, side: OrderSide, quantity: Decimal,
                         order_type: OrderType = OrderType.MARKET,
                         price: Optional[Decimal] = None,
                         client_order_id: Optional[str] = None) -> Order:
        """注文を実行"""
        try:
            params = {
                "symbol": symbol,
                "side": side.value,
                "type": order_type.value,
                "quantity": str(quantity)
            }
            
            if price and order_type == OrderType.LIMIT:
                params["price"] = str(price)
                
            if client_order_id:
                params["clientOrderId"] = client_order_id
                
            response = await self._api_request("POST", "/api/v1/order", params, signed=True)
            return self._parse_order_response(response)
            
        except Exception as e:
            logger.error(f"Failed to place {self.name} order: {e}")
            raise
            
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセル"""
        try:
            params = {"orderId": order_id, "symbol": symbol}
            response = await self._api_request("DELETE", "/api/v1/order", params, signed=True)
            return response.get("status") == "CANCELED"
        except Exception as e:
            logger.error(f"Failed to cancel {self.name} order {order_id}: {e}")
            return False
            
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """注文情報を取得"""
        try:
            params = {"orderId": order_id, "symbol": symbol}
            response = await self._api_request("GET", "/api/v1/order", params, signed=True)
            return self._parse_order_response(response)
        except Exception as e:
            logger.error(f"Failed to get {self.name} order {order_id}: {e}")
            raise
            
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """未約定注文一覧を取得"""
        try:
            params = {"symbol": symbol} if symbol else {}
            response = await self._api_request("GET", "/api/v1/openOrders", params, signed=True)
            return [self._parse_order_response(order) for order in response]
        except Exception as e:
            logger.error(f"Failed to get {self.name} open orders: {e}")
            raise
            
    async def get_balance(self) -> Dict[str, Balance]:
        """残高を取得"""
        try:
            response = await self._api_request("GET", "/api/v1/account", signed=True)
            return self._parse_balance_response(response)
        except Exception as e:
            logger.error(f"Failed to get {self.name} balance: {e}")
            raise
            
    async def get_position(self, symbol: str) -> Optional[Position]:
        """ポジション情報を取得"""
        positions = await self.get_positions()
        for position in positions:
            if position.symbol == symbol:
                return position
        return None
        
    async def get_positions(self) -> List[Position]:
        """ポジション一覧を取得"""
        try:
            response = await self._api_request("GET", "/api/v1/positions", signed=True)
            return [self._parse_position_response(pos) for pos in response]
        except Exception as e:
            logger.error(f"Failed to get {self.name} positions: {e}")
            raise
            
    # ========================================
    # レスポンスパース用ヘルパーメソッド
    # ========================================
    
    def _parse_ticker_response(self, response: Dict, symbol: str) -> Ticker:
        """ティッカーレスポンスをパース"""
        return Ticker(
            symbol=symbol,
            bid=Decimal(str(response.get('bid', 0))),
            ask=Decimal(str(response.get('ask', 0))),
            last=Decimal(str(response.get('last', 0))),
            mark_price=Decimal(str(response.get('mark', 0))),
            volume_24h=Decimal(str(response.get('volume', 0))),
            timestamp=int(response.get('timestamp', datetime.now().timestamp() * 1000))
        )
        
    def _parse_orderbook_response(self, response: Dict, symbol: str) -> OrderBook:
        """板情報レスポンスをパース"""
        bids = [(Decimal(str(bid[0])), Decimal(str(bid[1]))) for bid in response.get('bids', [])]
        asks = [(Decimal(str(ask[0])), Decimal(str(ask[1]))) for ask in response.get('asks', [])]
        
        return OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=int(response.get('timestamp', datetime.now().timestamp() * 1000))
        )
        
    def _parse_order_response(self, response: Dict) -> Order:
        """注文レスポンスをパース"""
        return Order(
            id=str(response.get('orderId')),
            symbol=response.get('symbol'),
            side=OrderSide(response.get('side')),
            type=OrderType(response.get('type')),
            price=Decimal(str(response.get('price', 0))) if response.get('price') else None,
            quantity=Decimal(str(response.get('quantity', 0))),
            filled=Decimal(str(response.get('filled', 0))),
            remaining=Decimal(str(response.get('remaining', 0))),
            status=OrderStatus(response.get('status')),
            timestamp=int(response.get('timestamp', datetime.now().timestamp() * 1000)),
            fee=Decimal(str(response.get('fee', 0))) if response.get('fee') else None
        )
        
    def _parse_balance_response(self, response: Dict) -> Dict[str, Balance]:
        """残高レスポンスをパース"""
        balances = {}
        for balance_data in response.get('balances', []):
            asset = balance_data.get('asset')
            free = Decimal(str(balance_data.get('free', 0)))
            locked = Decimal(str(balance_data.get('locked', 0)))
            
            balances[asset] = Balance(
                asset=asset,
                free=free,
                locked=locked,
                total=free + locked
            )
            
        return balances
        
    def _parse_position_response(self, response: Dict) -> Position:
        """ポジションレスポンスをパース"""
        return Position(
            symbol=response.get('symbol'),
            side=OrderSide(response.get('side')),
            size=Decimal(str(response.get('size', 0))),
            entry_price=Decimal(str(response.get('entryPrice', 0))),
            mark_price=Decimal(str(response.get('markPrice', 0))),
            unrealized_pnl=Decimal(str(response.get('unrealizedPnl', 0))),
            realized_pnl=Decimal(str(response.get('realizedPnl', 0))),
            timestamp=int(response.get('timestamp', datetime.now().timestamp() * 1000))
        )
        
    # ========================================
    # ユーティリティメソッド
    # ========================================
    
    def add_price_callback(self, callback) -> None:
        """価格更新コールバックを追加"""
        self.price_callbacks.append(callback)
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected
        
    async def __aenter__(self):
        """非同期コンテキストマネージャー"""
        await self._init_session()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャー"""
        if self.session:
            await self.session.close()