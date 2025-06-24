"""Gate.io取引所の実装"""

import asyncio
import json
import websockets
import logging
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


class GateioExchange(ExchangeInterface):
    """Gate.io取引所実装"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        super().__init__(api_key, api_secret, testnet)
        self.name = "Gate.io"
        
        # API設定
        if testnet:
            self.rest_url = "https://fx-api-testnet.gateio.ws"
            self.ws_url = "wss://fx-ws-testnet.gateio.ws/v4/ws/usdt"
        else:
            self.rest_url = "https://api.gateio.ws"
            self.ws_url = "wss://fx-ws.gateio.ws/v4/ws/usdt"  # USDT Perpetuals
            
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
                self.ccxt_exchange = ccxt.gateio({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'sandbox': testnet,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'swap',  # perpetual swap contracts
                    }
                })
                logger.info("Gate.io CCXT exchange initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Gate.io CCXT exchange: {e}")
                self.ccxt_exchange = None
        
    async def connect_websocket(self, symbols: List[str]) -> None:
        """WebSocket接続を確立"""
        try:
            logger.info(f"Connecting to Gate.io WebSocket: {self.ws_url}")
            
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
            logger.info("Gate.io WebSocket connected successfully")
            
            # シンボルを購読
            for symbol in symbols:
                await self._subscribe_symbol(symbol)
                
            # メッセージ受信ループを開始
            asyncio.create_task(self._message_handler())
            
        except Exception as e:
            logger.error(f"Failed to connect Gate.io WebSocket: {e}")
            self.is_ws_connected = False
            raise
            
    async def disconnect_websocket(self) -> None:
        """WebSocket接続を切断"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        self.is_ws_connected = False
        self.subscribed_symbols.clear()
        logger.info("Gate.io WebSocket disconnected")
        
    async def _subscribe_symbol(self, symbol: str) -> None:
        """シンボルのデータを購読"""
        if not self.is_ws_connected or not self.websocket:
            return
            
        # Gate.ioのシンボル形式に変換（例: BTC -> BTC_USDT）
        gateio_symbol = self._convert_symbol_to_gateio(symbol)
        
        # 複数のデータフィードを購読
        current_time = int(datetime.now().timestamp())
        
        # ティッカー購読
        ticker_subscription = {
            "time": current_time,
            "channel": "futures.tickers",
            "event": "subscribe", 
            "payload": [gateio_symbol]
        }
        
        # 板情報購読
        orderbook_subscription = {
            "time": current_time + 1,
            "channel": "futures.order_book",
            "event": "subscribe",
            "payload": [gateio_symbol, "20", "0"]  # symbol, limit, interval
        }
        
        # 取引データ購読
        trades_subscription = {
            "time": current_time + 2,
            "channel": "futures.trades",
            "event": "subscribe",
            "payload": [gateio_symbol]
        }
        
        try:
            await self.websocket.send(json.dumps(ticker_subscription))
            await asyncio.sleep(0.1)
            await self.websocket.send(json.dumps(orderbook_subscription))
            await asyncio.sleep(0.1)
            await self.websocket.send(json.dumps(trades_subscription))
            
            self.subscribed_symbols.add(symbol)
            logger.info(f"Subscribed to Gate.io feeds for {symbol} ({gateio_symbol})")
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {symbol}: {e}")
            
    def _convert_symbol_to_gateio(self, symbol: str) -> str:
        """統一シンボルをGate.io形式に変換"""
        symbol_map = {
            "BTC": "BTC_USDT",
            "ETH": "ETH_USDT", 
            "SOL": "SOL_USDT",
            "HYPE": "HYPE_USDT",  # Hyperliquidトークン
            "WIF": "WIF_USDT",
            "PEPE": "PEPE_USDT",
            "DOGE": "DOGE_USDT",
            "BNB": "BNB_USDT"
        }
        return symbol_map.get(symbol, f"{symbol}_USDT")
        
    def _convert_symbol_from_gateio(self, gateio_symbol: str) -> str:
        """Gate.ioシンボルを統一形式に変換"""
        return gateio_symbol.replace("_USDT", "").replace("_USDC", "")
        
    async def _message_handler(self) -> None:
        """WebSocketメッセージ処理"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode Gate.io WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error processing Gate.io WebSocket message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Gate.io WebSocket connection closed")
            self.is_ws_connected = False
        except Exception as e:
            logger.error(f"Gate.io WebSocket message handler error: {e}")
            self.is_ws_connected = False
            
    async def _process_message(self, data: Dict) -> None:
        """受信メッセージを処理"""
        try:
            # 購読確認メッセージ
            if data.get("event") == "subscribe" and "error" not in data:
                logger.info(f"Gate.io subscription confirmed: {data.get('channel')}")
                return
                
            # データメッセージ
            channel = data.get("channel", "")
            event = data.get("event", "")
            result = data.get("result")
            
            if not result:
                return
                
            # ティッカーデータ処理
            if channel == "futures.tickers" and event == "update":
                for ticker_data in result:
                    symbol = self._extract_symbol_from_data(ticker_data.get("contract", ""))
                    if symbol:
                        ticker = await self._parse_ticker_data(symbol, ticker_data)
                        if ticker:
                            self.ticker_cache[symbol] = ticker
                            for callback in self.price_callbacks:
                                await callback(self.name, ticker)
                        
            # 板情報処理
            elif channel == "futures.order_book" and event == "update":
                for book_data in result:
                    symbol = self._extract_symbol_from_data(book_data.get("contract", ""))
                    if symbol:
                        ticker = await self._parse_orderbook_data(symbol, book_data)
                        if ticker:
                            self.orderbook_cache[symbol] = book_data
                            for callback in self.price_callbacks:
                                await callback(self.name, ticker)
                        
            # 取引データ処理
            elif channel == "futures.trades" and event == "update":
                for trade_data in result:
                    symbol = self._extract_symbol_from_data(trade_data.get("contract", ""))
                    if symbol:
                        ticker = await self._parse_trade_data(symbol, trade_data)
                        if ticker:
                            for callback in self.price_callbacks:
                                await callback(self.name, ticker)
                            
        except Exception as e:
            logger.error(f"Error processing Gate.io message: {e}")
            
    def _extract_symbol_from_data(self, contract: str) -> str:
        """契約名から統一シンボルを抽出"""
        if contract:
            return self._convert_symbol_from_gateio(contract)
        return ""
        
    async def _parse_ticker_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """ティッカーデータからTicker情報を生成"""
        try:
            # Gate.io ティッカーデータ形式
            last = Decimal(str(data.get("last", 0)))
            mark_price = Decimal(str(data.get("mark_price", last)))
            volume_24h = Decimal(str(data.get("volume_24h", 0)))
            
            if last <= 0:
                return None
                
            # bid/askは別チャンネル（order_book）から取得するため、lastから推定
            spread = last * Decimal("0.001")  # 0.1%
            
            ticker = Ticker(
                symbol=symbol,
                bid=last - spread/2,
                ask=last + spread/2,
                last=last,
                mark_price=mark_price,
                volume_24h=volume_24h,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Gate.io ticker data: {e}")
            return None
            
    async def _parse_orderbook_data(self, symbol: str, data: Dict) -> Optional[Ticker]:
        """板データからTicker情報を生成"""
        try:
            # Gate.io 板データ形式 ({"p": "price", "s": size})
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            if not bids or not asks:
                return None
                
            best_bid = Decimal(str(bids[0]["p"]))
            best_ask = Decimal(str(asks[0]["p"]))
            mid_price = (best_bid + best_ask) / 2
            
            ticker = Ticker(
                symbol=symbol,
                bid=best_bid,
                ask=best_ask,
                last=mid_price,
                mark_price=mid_price,
                timestamp=int(data.get("t", datetime.now().timestamp() * 1000))
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Gate.io orderbook data: {e}")
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
                # volume_24hは ticker データからのみ設定すべき
                # 個別の取引サイズ(size)は使用しない
                timestamp=int(trade.get("time", datetime.now().timestamp() * 1000))
            )
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error parsing Gate.io trade data: {e}")
            return None
            
    def add_price_callback(self, callback) -> None:
        """価格更新コールバックを追加"""
        self.price_callbacks.append(callback)
        
    async def get_ticker(self, symbol: str) -> Ticker:
        """現在のティッカー情報を取得（REST API）"""
        gateio_symbol = self._convert_symbol_to_gateio(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v4/futures/usdt/tickers"
                params = {"contract": gateio_symbol} if gateio_symbol else {}
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"Gate.io API error: {response.status}")
                        
                    data = await response.json()
                    
                    if not data:
                        raise Exception("No ticker data returned")
                    
                    # Gate.io APIは配列を返す場合があるので、該当コントラクトを見つける
                    ticker_data = None
                    if isinstance(data, list):
                        for item in data:
                            if item.get("contract") == gateio_symbol:
                                ticker_data = item
                                break
                        if not ticker_data and data:
                            ticker_data = data[0]  # フォールバック
                    else:
                        ticker_data = data
                    
                    if not ticker_data:
                        raise Exception(f"No ticker data found for {gateio_symbol}")
                    
                    last = Decimal(str(ticker_data["last"]))
                    mark_price = Decimal(str(ticker_data.get("mark_price", last)))
                    
                    # 板情報も取得してbid/askを正確に  
                    book_url = f"{self.rest_url}/api/v4/futures/usdt/order_book"
                    book_params = {"contract": gateio_symbol, "limit": 1}
                    
                    async with session.get(book_url, params=book_params) as book_response:
                        if book_response.status == 200:
                            book_data = await book_response.json()
                            bids = book_data.get("bids", [])
                            asks = book_data.get("asks", [])
                            
                            if bids and asks:
                                bid = Decimal(str(bids[0]["p"]))
                                ask = Decimal(str(asks[0]["p"]))
                            else:
                                spread = last * Decimal("0.001")
                                bid = last - spread/2
                                ask = last + spread/2
                        else:
                            spread = last * Decimal("0.001")
                            bid = last - spread/2
                            ask = last + spread/2
                    
                    ticker = Ticker(
                        symbol=symbol,
                        bid=bid,
                        ask=ask,
                        last=last,
                        mark_price=mark_price,
                        volume_24h=Decimal(str(ticker_data.get("volume_24h", 0))),
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return ticker
                    
        except Exception as e:
            logger.error(f"Failed to get Gate.io ticker for {symbol}: {e}")
            raise
            
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """板情報を取得"""
        gateio_symbol = self._convert_symbol_to_gateio(symbol)
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v4/futures/usdt/order_book"
                params = {
                    "contract": gateio_symbol,
                    "limit": min(depth, 100)  # Gate.ioの最大値
                }
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"Gate.io API error: {response.status}")
                        
                    data = await response.json()
                    
                    # Gate.io 板データを変換 ({"p": "price", "s": size} 形式)
                    bids = [(Decimal(str(bid["p"])), Decimal(str(bid["s"]))) 
                           for bid in data.get("bids", [])]
                    asks = [(Decimal(str(ask["p"])), Decimal(str(ask["s"]))) 
                           for ask in data.get("asks", [])]
                    
                    orderbook = OrderBook(
                        symbol=symbol,
                        bids=bids,
                        asks=asks,
                        timestamp=int(datetime.now().timestamp() * 1000)
                    )
                    
                    return orderbook
                    
        except Exception as e:
            logger.error(f"Failed to get Gate.io orderbook for {symbol}: {e}")
            raise
            
    async def place_order(self, symbol: str, side: OrderSide, quantity: Decimal,
                         order_type: OrderType = OrderType.MARKET,
                         price: Optional[Decimal] = None,
                         client_order_id: Optional[str] = None) -> Order:
        """注文を実行"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Gate.ioシンボル形式に変換
            gateio_symbol = self._convert_symbol_to_gateio(symbol)
            
            # 注文パラメータ構築
            order_params = {
                'symbol': gateio_symbol,
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
                order_params['params'] = {'text': client_order_id}
                
            # 注文実行
            logger.info(f"Placing Gate.io order: {order_params}")
            result = await self.ccxt_exchange.create_order(**order_params)
            
            # CCXTの結果をOrderオブジェクトに変換
            order = self._convert_ccxt_order_to_order(result, symbol, side, order_type)
            
            logger.info(f"Gate.io order placed successfully: {order.id}")
            return order
            
        except Exception as e:
            logger.error(f"Failed to place Gate.io order: {e}")
            raise
        
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセル"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Gate.ioシンボル形式に変換
            gateio_symbol = self._convert_symbol_to_gateio(symbol)
            
            # 注文キャンセル実行
            result = await self.ccxt_exchange.cancel_order(order_id, gateio_symbol)
            
            # キャンセル成功の判定
            is_cancelled = result.get('status') in ['canceled', 'cancelled']
            
            if is_cancelled:
                logger.info(f"Gate.io order {order_id} cancelled successfully")
            else:
                logger.warning(f"Gate.io order {order_id} cancellation status: {result.get('status')}")
                
            return is_cancelled
            
        except Exception as e:
            logger.error(f"Failed to cancel Gate.io order {order_id}: {e}")
            return False
        
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """注文情報を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # Gate.ioシンボル形式に変換
            gateio_symbol = self._convert_symbol_to_gateio(symbol)
            
            # 注文情報取得
            result = await self.ccxt_exchange.fetch_order(order_id, gateio_symbol)
            
            # CCXTの結果をOrderオブジェクトに変換
            order = self._convert_ccxt_order_to_order(result, symbol)
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to get Gate.io order {order_id}: {e}")
            raise
        
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """未約定注文一覧を取得"""
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            raise NotImplementedError("CCXT library not available or exchange not authenticated")
            
        try:
            # 未約定注文取得
            if symbol:
                gateio_symbol = self._convert_symbol_to_gateio(symbol)
                results = await self.ccxt_exchange.fetch_open_orders(gateio_symbol)
            else:
                results = await self.ccxt_exchange.fetch_open_orders()
                
            # CCXTの結果をOrderオブジェクトのリストに変換
            orders = []
            for result in results:
                order_symbol = self._convert_symbol_from_gateio(result['symbol'])
                order = self._convert_ccxt_order_to_order(result, order_symbol)
                orders.append(order)
                
            return orders
            
        except Exception as e:
            logger.error(f"Failed to get Gate.io open orders: {e}")
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
            logger.error(f"Failed to get Gate.io balance: {e}")
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
                    
                symbol = self._convert_symbol_from_gateio(pos_data['symbol'])
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
            logger.error(f"Failed to get Gate.io positions: {e}")
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
        # Gate.ioの一般的な手数料（実際のAPIから取得すべき）
        return {
            "maker_fee": Decimal("0.0002"),  # 0.02% 
            "taker_fee": Decimal("0.0005")   # 0.05%
        }
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None