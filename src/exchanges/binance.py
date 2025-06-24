"""Binance取引所の実装"""

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

logger = logging.getLogger(__name__)


class BinanceExchange(ExchangeInterface):
    """Binance取引所実装"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        super().__init__(api_key, api_secret, testnet)
        self.name = "Binance"
        
        # API設定
        if testnet:
            self.rest_url = "https://testnet.binancefuture.com"
            self.ws_url = "wss://stream.binancefuture.com/ws"
        else:
            self.rest_url = "https://fapi.binance.com"
            self.ws_url = "wss://fstream.binance.com/ws"
            
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
                self.ccxt_exchange = ccxt.binance({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'sandbox': testnet,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'future',  # futures trading
                    }
                })
                logger.info("Binance CCXT exchange initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Binance CCXT exchange: {e}")
                self.ccxt_exchange = None
        
    async def connect_websocket(self, symbols: List[str]) -> None:
        """WebSocket接続を確立"""
        try:
            logger.info(f"Connecting to Binance WebSocket: {self.ws_url}")
            
            # 既存接続があれば切断
            if self.websocket:
                await self.disconnect_websocket()
                
            # ストリーム名を生成
            streams = []
            for symbol in symbols:
                binance_symbol = self._convert_symbol_to_binance(symbol)
                streams.extend([
                    f"{binance_symbol.lower()}@bookTicker",    # Best bid/ask
                    f"{binance_symbol.lower()}@ticker",        # 24hr ticker statistics
                    f"{binance_symbol.lower()}@trade"          # Trade stream
                ])
                
            # Binance複合ストリーム用のURL構築
            ws_url = f"wss://fstream.binance.com/stream?streams={'/'.join(streams)}"
            
            # WebSocket接続
            self.websocket = await websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=10,
                max_size=2**20,
                compression=None
            )
            
            self.is_ws_connected = True
            self.subscribed_symbols.update(symbols)
            logger.info(f"Binance WebSocket connected successfully, subscribed to {len(symbols)} symbols")
            
            # メッセージ受信ループを開始
            asyncio.create_task(self._message_handler())
            
        except Exception as e:
            logger.error(f"Failed to connect Binance WebSocket: {e}")
            self.is_ws_connected = False
            raise
            
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        self.is_ws_connected = False
        self.subscribed_symbols.clear()
        logger.info("Binance WebSocket disconnected")
        
    def _convert_symbol_to_binance(self, symbol: str) -> str:
        """統一シンボルをBinance形式に変換"""
        symbol_map = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT", 
            "SOL": "SOLUSDT",
            "HYPE": "HYPEUSDT",  # Hyperliquidトークン
            "WIF": "WIFUSDT",
            "PEPE": "PEPEUSDT",
            "DOGE": "DOGEUSDT",
            "BNB": "BNBUSDT"
        }
        return symbol_map.get(symbol, f"{symbol}USDT")
        
    def _convert_symbol_from_binance(self, binance_symbol: str) -> str:
        """Binanceシンボルを統一形式に変換"""
        return binance_symbol.replace("USDT", "").replace("USDC", "")
        
    async def _message_handler(self) -> None:
        """WebSocketメッセージ処理"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode Binance WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing Binance WebSocket message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Binance WebSocket connection closed")
            self.is_ws_connected = False
            # 自動再接続を試みる
            if self.subscribed_symbols:
                logger.info("Attempting to reconnect Binance WebSocket...")
                await asyncio.sleep(5)  # 5秒待機
                try:
                    await self.connect_websocket(list(self.subscribed_symbols))
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect Binance: {reconnect_error}")
        except Exception as e:
            logger.error(f"Binance WebSocket message handler error: {e}")
            self.is_ws_connected = False
            
    async def _process_message(self, data: Dict) -> None:
        """受信メッセージを処理"""
        try:
            stream = data.get("stream", "")
            event_data = data.get("data", data)
            
            if not stream:
                return
                
            # シンボルを抽出
            symbol = self._extract_symbol_from_stream(stream)
            if not symbol:
                return
                
            # ストリームタイプ別処理
            if "@bookTicker" in stream:
                ticker = await self._parse_book_ticker_data(symbol, event_data)
                if ticker:
                    self.ticker_cache[symbol] = ticker
                    for callback in self.price_callbacks:
                        await callback(self.name, ticker)
                        
            elif "@ticker" in stream:
                ticker = await self._parse_ticker_data(symbol, event_data)
                if ticker:
                    # 既存のbid/askと統合
                    cached_ticker = self.ticker_cache.get(symbol)
                    if cached_ticker:
                        ticker.bid = cached_ticker.bid
                        ticker.ask = cached_ticker.ask
                    self.ticker_cache[symbol] = ticker
                    for callback in self.price_callbacks:
                        await callback(self.name, ticker)
                        
            elif "@trade" in stream:
                ticker = await self._parse_trade_data(symbol, event_data)
                if ticker:
                    for callback in self.price_callbacks:
                        await callback(self.name, ticker)
                        
        except Exception as e:
            logger.error(f"Error processing Binance message: {e}")
            
    def _extract_symbol_from_stream(self, stream: str) -> str:
        """ストリーム名から統一シンボルを抽出"""
        # stream例: "btcusdt@bookTicker" -> "BTC"
        parts = stream.split("@")
        if len(parts) >= 1:
            binance_symbol = parts[0].upper()
            return self._convert_symbol_from_binance(binance_symbol)
        return ""
        
    async def _parse_book_ticker_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """BookTickerデータからTicker情報を生成"""
        try:
            # Binance BookTicker形式
            bid = Decimal(str(data.get("b", 0)))  # best bid price
            ask = Decimal(str(data.get("a", 0)))  # best ask price
            
            if bid <= 0 or ask <= 0:
                return None
                
            mid_price = (bid + ask) / 2
            
            ticker = Ticker(
                symbol=symbol,
                bid=bid,
                ask=ask,
                last=mid_price,
                mark_price=mid_price,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Binance book ticker data: {e}")
            return None
            
    async def _parse_ticker_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """24hrTickerデータからTicker情報を生成"""
        try:
            # Binance 24hr Ticker形式
            last = Decimal(str(data.get("c", 0)))       # close price
            volume_24h = Decimal(str(data.get("v", 0))) # volume
            high_24h = Decimal(str(data.get("h", 0)))   # high price
            low_24h = Decimal(str(data.get("l", 0)))    # low price
            
            if last <= 0:
                return None
                
            # BookTickerからのbid/askが無い場合は推定
            spread = last * Decimal("0.001")  # 0.1%
            
            ticker = Ticker(
                symbol=symbol,
                bid=last - spread/2,
                ask=last + spread/2,
                last=last,
                mark_price=last,
                volume_24h=volume_24h,
                timestamp=int(data.get("E", datetime.now().timestamp() * 1000))
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Binance ticker data: {e}")
            return None
            
    async def _parse_trade_data(self, symbol: str, trade: Dict) -> Optional[Ticker]:
        """トレードデータからTicker情報を生成"""
        try:
            price = Decimal(str(trade.get("p", 0)))
            quantity = Decimal(str(trade.get("q", 0)))
            
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
                volume_24h=quantity,
                timestamp=int(trade.get("T", datetime.now().timestamp() * 1000))
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Binance trade data: {e}")
            return None
            
    def add_price_callback(self, callback) -> None:
        """価格更新コールバックを追加"""
        self.price_callbacks.append(callback)
        
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得（REST API）"""
        binance_symbol = self._convert_symbol_to_binance(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                # 24hr ticker statsを取得
                url = f"{self.rest_url}/fapi/v1/ticker/24hr"
                params = {"symbol": binance_symbol}
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"Binance API error: {response.status}")
                        
                    ticker_data = await response.json()
                    
                    # Book tickerも取得してbid/askを正確に
                    book_url = f"{self.rest_url}/fapi/v1/ticker/bookTicker"
                    async with session.get(book_url, params=params) as book_response:
                        if book_response.status == 200:
                            book_data = await book_response.json()
                            bid = Decimal(str(book_data["bidPrice"]))
                            ask = Decimal(str(book_data["askPrice"]))
                        else:
                            # BookTickerが取得できない場合は推定
                            last = Decimal(str(ticker_data["lastPrice"]))
                            spread = last * Decimal("0.001")
                            bid = last - spread/2
                            ask = last + spread/2
                    
                    last = Decimal(str(ticker_data["lastPrice"]))
                    
                    ticker = Ticker(
                        symbol=symbol,
                        bid=bid,
                        ask=ask,
                        last=last,
                        mark_price=last,  # Futures用のmark priceは別エンドポイント
                        volume_24h=Decimal(str(ticker_data["volume"])),
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return ticker
                    
        except Exception as e:
            logger.error(f"Failed to get Binance ticker for {symbol}: {e}")
            raise
            
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        binance_symbol = self._convert_symbol_to_binance(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/fapi/v1/depth"
                params = {
                    "symbol": binance_symbol,
                    "limit": min(depth, 1000)  # Binanceの最大値
                }
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"Binance API error: {response.status}")
                        
                    data = await response.json()
                    
                    # 板データを変換
                    bids = [(Decimal(str(bid[0])), Decimal(str(bid[1]))) 
                           for bid in data.get("bids", [])]
                    asks = [(Decimal(str(ask[0])), Decimal(str(ask[1]))) 
                           for ask in data.get("asks", [])]
                    
                    orderbook = OrderBook(
                        symbol=symbol,
                        bids=bids,
                        asks=asks,
                        timestamp=int(data.get("E", datetime.now().timestamp() * 1000))
                    )
                    
                    return orderbook
                    
        except Exception as e:
            logger.error(f"Failed to get Binance orderbook for {symbol}: {e}")
            raise
            
    async def place_order(self, symbol: str, side: OrderSide, quantity: Decimal,
                         order_type: OrderType = OrderType.MARKET,
                         price: Optional[Decimal] = None,
                         client_order_id: Optional[str] = None) -> Order:
        """注文を実行"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Binanceシンボル形式に変換
            binance_symbol = self._convert_symbol_to_binance(symbol)
            
            # 注文パラメータ構築
            order_params = {
                'symbol': binance_symbol,
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
                order_params['params'] = {'newClientOrderId': client_order_id}
                
            # 注文実行
            logger.info(f"Placing Binance order: {order_params}")
            result = await self.ccxt_exchange.create_order(**order_params)
            
            # CCXTの結果をOrderオブジェクトに変換
            order = self._convert_ccxt_order_to_order(result, symbol, side, order_type)
            
            logger.info(f"Binance order placed successfully: {order.id}")
            return order
            
        except Exception as e:
            logger.error(f"Failed to place Binance order: {e}")
            raise
        
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセル"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Binanceシンボル形式に変換
            binance_symbol = self._convert_symbol_to_binance(symbol)
            
            # 注文キャンセル実行
            result = await self.ccxt_exchange.cancel_order(order_id, binance_symbol)
            
            # キャンセル成功の判定
            is_cancelled = result.get('status') in ['canceled', 'cancelled']
            
            if is_cancelled:
                logger.info(f"Binance order {order_id} cancelled successfully")
            else:
                logger.warning(f"Binance order {order_id} cancellation status: {result.get('status')}")
                
            return is_cancelled
            
        except Exception as e:
            logger.error(f"Failed to cancel Binance order {order_id}: {e}")
            return False
        
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """注文情報を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Binanceシンボル形式に変換
            binance_symbol = self._convert_symbol_to_binance(symbol)
            
            # 注文情報取得
            result = await self.ccxt_exchange.fetch_order(order_id, binance_symbol)
            
            # CCXTの結果をOrderオブジェクトに変換
            order = self._convert_ccxt_order_to_order(result, symbol)
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to get Binance order {order_id}: {e}")
            raise
        
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """未約定注文一覧を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # 未約定注文取得
            if symbol:
                binance_symbol = self._convert_symbol_to_binance(symbol)
                results = await self.ccxt_exchange.fetch_open_orders(binance_symbol)
            else:
                results = await self.ccxt_exchange.fetch_open_orders()
                
            # CCXTの結果をOrderオブジェクトのリストに変換
            orders = []
            for result in results:
                order_symbol = self._convert_symbol_from_binance(result['symbol'])
                order = self._convert_ccxt_order_to_order(result, order_symbol)
                orders.append(order)
                
            return orders
            
        except Exception as e:
            logger.error(f"Failed to get Binance open orders: {e}")
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
            logger.error(f"Failed to get Binance balance: {e}")
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
                    
                symbol = self._convert_symbol_from_binance(pos_data['symbol'])
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
            logger.error(f"Failed to get Binance positions: {e}")
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
        # Binanceの一般的な手数料（実際のAPIから取得すべき）
        return {
            "maker_fee": Decimal("0.0002"),  # 0.02% 
            "taker_fee": Decimal("0.0004")   # 0.04%
        }
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None