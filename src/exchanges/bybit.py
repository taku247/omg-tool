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

# CCXT for order execution
try:
    import ccxt.async_support as ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    logger.warning("CCXT library not available. Order execution will be limited.")

from ..interfaces.exchange import (
    ExchangeInterface, Ticker, OrderBook, Order, Balance, Position,
    OrderSide, OrderType, OrderStatus
)
from ..utils.fee_utils import get_exchange_fees

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
        
        # CCXT取引所インスタンス（注文実行用）
        self.ccxt_exchange = None
        if CCXT_AVAILABLE and api_key and api_secret:
            try:
                self.ccxt_exchange = ccxt.bybit({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'sandbox': testnet,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'linear',  # perpetual futures
                    }
                })
                logger.info("Bybit CCXT exchange initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Bybit CCXT exchange: {e}")
                self.ccxt_exchange = None
        
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
        """注文を実行"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Bybitシンボル形式に変換
            bybit_symbol = self._convert_symbol_to_bybit(symbol)
            
            # 注文パラメータ構築
            order_params = {
                'symbol': bybit_symbol,
                'type': order_type.value.lower(),
                'side': side.value.lower(),
                'amount': float(quantity)
            }
            
            # 価格設定
            if order_type == OrderType.LIMIT:
                if price is None:
                    raise ValueError("Price is required for limit orders")
                order_params['price'] = float(price)
            elif order_type == OrderType.MARKET:
                # マーケット注文では価格は不要
                pass
            else:
                raise NotImplementedError(f"Order type {order_type} not supported yet")
                
            # クライアント注文ID
            if client_order_id:
                order_params['params'] = {'clientOrderId': client_order_id}
                
            # 注文実行
            logger.info(f"Placing Bybit order: {order_params}")
            result = await self.ccxt_exchange.create_order(**order_params)
            
            # CCXTの結果をOrderオブジェクトに変換
            order = self._convert_ccxt_order_to_order(result, symbol, side, order_type)
            
            logger.info(f"Bybit order placed successfully: {order.id}")
            return order
            
        except Exception as e:
            logger.error(f"Failed to place Bybit order: {e}")
            raise
        
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセル"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Bybitシンボル形式に変換
            bybit_symbol = self._convert_symbol_to_bybit(symbol)
            
            # 注文キャンセル実行
            result = await self.ccxt_exchange.cancel_order(order_id, bybit_symbol)
            
            # キャンセル成功の判定
            is_cancelled = result.get('status') in ['canceled', 'cancelled']
            
            if is_cancelled:
                logger.info(f"Bybit order {order_id} cancelled successfully")
            else:
                logger.warning(f"Bybit order {order_id} cancellation status: {result.get('status')}")
                
            return is_cancelled
            
        except Exception as e:
            logger.error(f"Failed to cancel Bybit order {order_id}: {e}")
            return False
        
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """注文情報を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Bybitシンボル形式に変換
            bybit_symbol = self._convert_symbol_to_bybit(symbol)
            
            # 注文情報取得
            result = await self.ccxt_exchange.fetch_order(order_id, bybit_symbol)
            
            # CCXTの結果をOrderオブジェクトに変換
            order = self._convert_ccxt_order_to_order(result, symbol)
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to get Bybit order {order_id}: {e}")
            raise
        
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """未約定注文一覧を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # 未約定注文取得
            if symbol:
                bybit_symbol = self._convert_symbol_to_bybit(symbol)
                results = await self.ccxt_exchange.fetch_open_orders(bybit_symbol)
            else:
                results = await self.ccxt_exchange.fetch_open_orders()
                
            # CCXTの結果をOrderオブジェクトのリストに変換
            orders = []
            for result in results:
                order_symbol = self._convert_symbol_from_bybit(result['symbol'])
                order = self._convert_ccxt_order_to_order(result, order_symbol)
                orders.append(order)
                
            return orders
            
        except Exception as e:
            logger.error(f"Failed to get Bybit open orders: {e}")
            raise
        
    async def get_balance(self) -> Dict[str, Balance]:
        """残高を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # 残高取得
            balance_data = await self.ccxt_exchange.fetch_balance()
            balances = {}
            
            for asset, balance_info in balance_data.items():
                if asset in ['info', 'free', 'used', 'total']:
                    continue  # CCXTの特殊キーをスキップ
                    
                if isinstance(balance_info, dict):
                    free = Decimal(str(balance_info.get('free', 0)))
                    used = Decimal(str(balance_info.get('used', 0)))
                    total = Decimal(str(balance_info.get('total', 0)))
                    
                    if total > 0:  # 残高がある資産のみ
                        balances[asset] = Balance(
                            asset=asset,
                            free=free,
                            locked=used,
                            total=total
                        )
                        
            return balances
            
        except Exception as e:
            logger.error(f"Failed to get Bybit balance: {e}")
            raise
        
    async def get_position(self, symbol: str) -> Optional[Position]:
        """ポジション情報を取得"""
        positions = await self.get_positions()
        for position in positions:
            if position.symbol == symbol:
                return position
        return None
        
    async def get_positions(self) -> List[Position]:
        """全ポジション情報を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # ポジション取得
            positions_data = await self.ccxt_exchange.fetch_positions()
            positions = []
            
            for pos_data in positions_data:
                # アクティブなポジションのみ
                if pos_data.get('size', 0) == 0:
                    continue
                    
                symbol = self._convert_symbol_from_bybit(pos_data['symbol'])
                side = OrderSide.BUY if pos_data['side'] == 'long' else OrderSide.SELL
                size = Decimal(str(abs(pos_data['size'])))
                entry_price = Decimal(str(pos_data.get('entryPrice', 0)))
                mark_price = Decimal(str(pos_data.get('markPrice', entry_price)))
                unrealized_pnl = Decimal(str(pos_data.get('unrealizedPnl', 0)))
                
                position = Position(
                    symbol=symbol,
                    side=side,
                    size=size,
                    entry_price=entry_price,
                    mark_price=mark_price,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=Decimal('0'),  # CCXTでは別途取得が必要
                    timestamp=int(datetime.now().timestamp() * 1000)
                )
                positions.append(position)
                
            return positions
            
        except Exception as e:
            logger.error(f"Failed to get Bybit positions: {e}")
            raise
        
    def _convert_ccxt_order_to_order(self, ccxt_order: Dict, symbol: str, 
                                    side: Optional[OrderSide] = None, 
                                    order_type: Optional[OrderType] = None) -> Order:
        """CCXTの注文データをOrderオブジェクトに変換"""
        try:
            # CCXTから必要な情報を抽出
            order_id = str(ccxt_order['id'])
            
            # サイドの変換
            if side is None:
                side_str = ccxt_order.get('side', '').upper()
                side = OrderSide.BUY if side_str == 'BUY' else OrderSide.SELL
                
            # 注文タイプの変換
            if order_type is None:
                type_str = ccxt_order.get('type', '').upper()
                if type_str == 'MARKET':
                    order_type = OrderType.MARKET
                elif type_str == 'LIMIT':
                    order_type = OrderType.LIMIT
                else:
                    order_type = OrderType.LIMIT  # デフォルト
                    
            # ステータスの変換
            status_str = ccxt_order.get('status', '').lower()
            status_map = {
                'open': OrderStatus.NEW,
                'pending': OrderStatus.NEW,
                'closed': OrderStatus.FILLED,
                'filled': OrderStatus.FILLED,
                'canceled': OrderStatus.CANCELLED,
                'cancelled': OrderStatus.CANCELLED,
                'expired': OrderStatus.EXPIRED
            }
            status = status_map.get(status_str, OrderStatus.NEW)
            
            # 数量・価格の変換
            quantity = Decimal(str(ccxt_order.get('amount', 0)))
            filled = Decimal(str(ccxt_order.get('filled', 0)))
            remaining = quantity - filled
            
            price = None
            if ccxt_order.get('price'):
                price = Decimal(str(ccxt_order['price']))
                
            # 手数料
            fee = None
            if ccxt_order.get('fee') and ccxt_order['fee'].get('cost'):
                fee = Decimal(str(ccxt_order['fee']['cost']))
                
            order = Order(
                id=order_id,
                symbol=symbol,
                side=side,
                type=order_type,
                price=price,
                quantity=quantity,
                filled=filled,
                remaining=remaining,
                status=status,
                timestamp=int(ccxt_order.get('timestamp', datetime.now().timestamp() * 1000)),
                client_order_id=ccxt_order.get('clientOrderId'),
                fee=fee
            )
            
            return order
            
        except Exception as e:
            logger.error(f"Error converting CCXT order to Order: {e}")
            # フォールバック用の基本注文オブジェクトを返す
            return Order(
                id=str(ccxt_order.get('id', 'unknown')),
                symbol=symbol,
                side=side or OrderSide.BUY,
                type=order_type or OrderType.MARKET,
                quantity=Decimal(str(ccxt_order.get('amount', 0))),
                filled=Decimal('0'),
                remaining=Decimal(str(ccxt_order.get('amount', 0))),
                status=OrderStatus.NEW,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
    
    async def get_trading_fees(self, symbol: str) -> Dict[str, Decimal]:
        """取引手数料を取得"""
        return get_exchange_fees("bybit")
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None