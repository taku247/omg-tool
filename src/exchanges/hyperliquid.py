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
from ..utils.fee_utils import get_exchange_fees

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
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants
            
            self.info = Info(constants.MAINNET_API_URL if not testnet else constants.TESTNET_API_URL)
            
            # Exchange instanceを初期化（注文実行用）
            if api_key and api_secret:
                self.exchange = Exchange(
                    address=api_key,  # Wallet address
                    secret_key=api_secret,  # Private key
                    base_url=constants.MAINNET_API_URL if not testnet else constants.TESTNET_API_URL
                )
            else:
                self.exchange = None
                
            self.has_hyperliquid_lib = True
            logger.info("Hyperliquid library loaded successfully")
        except ImportError:
            logger.warning("Hyperliquid library not found. Some features may be limited.")
            self.has_hyperliquid_lib = False
            self.info = None
            self.exchange = None
            
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
            
    def _create_orderbook_from_l2data(self, data: Dict) -> Optional[OrderBook]:
        """L2 Book データからOrderBookオブジェクトを生成"""
        try:
            symbol = data.get("coin")
            if not symbol:
                return None
                
            levels = data.get("levels", [])
            if not levels or len(levels) < 2:
                return None
                
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
            
            orderbook = OrderBook(
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            return orderbook
            
        except Exception as e:
            logger.error(f"Error creating OrderBook from L2 data: {e}")
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
        """注文を実行"""
        if not self.has_hyperliquid_lib or not self.exchange:
            raise NotImplementedError("Hyperliquid exchange library not available or not authenticated")
            
        try:
            # Hyperliquid APIの注文パラメータを構築
            is_buy = side == OrderSide.BUY
            
            # 注文タイプの変換
            if order_type == OrderType.MARKET:
                # マーケット注文：現在の最良価格を取得
                ticker = await self.get_ticker(symbol)
                if is_buy:
                    order_price = float(ticker.ask)
                else:
                    order_price = float(ticker.bid)
                    
                # Hyperliquidではマーケット注文も価格を指定する必要がある
                # 適切なslippageを考慮した価格設定
                slippage = 0.01  # 1%のslippage
                if is_buy:
                    order_price *= (1 + slippage)
                else:
                    order_price *= (1 - slippage)
                    
            elif order_type == OrderType.LIMIT:
                if price is None:
                    raise ValueError("Price is required for limit orders")
                order_price = float(price)
            else:
                raise NotImplementedError(f"Order type {order_type} not supported yet")
                
            # 注文実行
            order_result = self.exchange.order(
                coin=symbol,
                is_buy=is_buy,
                sz=float(quantity),
                limit_px=order_price,
                order_type={"limit": {"tif": "Gtc"}},  # Good Till Canceled
                reduce_only=False
            )
            
            if not order_result or order_result.get('status') == 'error':
                error_msg = order_result.get('error', 'Unknown error') if order_result else 'No response'
                raise Exception(f"Order placement failed: {error_msg}")
                
            # 注文情報をOrderオブジェクトに変換
            order_data = order_result.get('response', {}).get('data', {})
            if isinstance(order_data, dict) and 'statuses' in order_data:
                status_info = order_data['statuses'][0] if order_data['statuses'] else {}
                order_id = status_info.get('resting', {}).get('oid')
                
                if not order_id:
                    # 即座に約定した場合のID取得
                    order_id = str(int(datetime.now().timestamp() * 1000))
                    
            else:
                order_id = str(int(datetime.now().timestamp() * 1000))
                
            # Orderオブジェクトを構築
            order = Order(
                id=str(order_id),
                symbol=symbol,
                side=side,
                type=order_type,
                price=Decimal(str(order_price)) if price else None,
                quantity=quantity,
                filled=Decimal('0'),  # 初期状態では未約定
                remaining=quantity,
                status=OrderStatus.NEW,
                timestamp=int(datetime.now().timestamp() * 1000),
                client_order_id=client_order_id
            )
            
            logger.info(f"Hyperliquid order placed successfully: {order_id}")
            return order
            
        except Exception as e:
            logger.error(f"Failed to place Hyperliquid order: {e}")
            raise
        
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセル"""
        if not self.has_hyperliquid_lib or not self.exchange:
            raise NotImplementedError("Hyperliquid exchange library not available or not authenticated")
            
        try:
            # Hyperliquidでの注文キャンセル
            cancel_result = self.exchange.cancel(
                coin=symbol,
                oid=int(order_id)
            )
            
            if cancel_result and cancel_result.get('status') == 'ok':
                logger.info(f"Hyperliquid order {order_id} cancelled successfully")
                return True
            else:
                error_msg = cancel_result.get('error', 'Unknown error') if cancel_result else 'No response'
                logger.error(f"Failed to cancel Hyperliquid order {order_id}: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to cancel Hyperliquid order {order_id}: {e}")
            return False
        
    async def get_order(self, order_id: str, symbol: str) -> Order:
        """注文情報を取得"""
        if not self.has_hyperliquid_lib or not self.info:
            raise NotImplementedError("Hyperliquid library not available")
            
        try:
            # まず未約定注文から検索
            open_orders = await self.get_open_orders(symbol)
            for order in open_orders:
                if order.id == order_id:
                    return order
                    
            # 未約定注文にない場合、約定済み注文から検索
            # Hyperliquidの取引履歴から検索
            user_fills = self.info.user_fills(self.api_key)  # wallet address
            
            for fill in user_fills:
                if str(fill.get('oid')) == order_id and fill.get('coin') == symbol:
                    # 約定済み注文情報を構築
                    return Order(
                        id=order_id,
                        symbol=symbol,
                        side=OrderSide.BUY if fill.get('dir') == 'Open Long' or fill.get('dir') == 'Close Short' else OrderSide.SELL,
                        type=OrderType.LIMIT,  # Hyperliquidは基本的にlimit
                        price=Decimal(str(fill.get('px', 0))),
                        quantity=Decimal(str(fill.get('sz', 0))),
                        filled=Decimal(str(fill.get('sz', 0))),
                        remaining=Decimal('0'),
                        status=OrderStatus.FILLED,
                        timestamp=int(fill.get('time', datetime.now().timestamp() * 1000))
                    )
                    
            raise ValueError(f"Order {order_id} not found")
            
        except Exception as e:
            logger.error(f"Failed to get Hyperliquid order {order_id}: {e}")
            raise
        
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """未約定注文一覧を取得"""
        if not self.has_hyperliquid_lib or not self.info:
            raise NotImplementedError("Hyperliquid library not available")
            
        try:
            # Hyperliquidのuser_open_ordersで未約定注文を取得
            open_orders_data = self.info.user_open_orders(self.api_key)  # wallet address
            orders = []
            
            for order_data in open_orders_data:
                order_symbol = order_data.get('coin')
                
                # シンボルフィルター
                if symbol and order_symbol != symbol:
                    continue
                    
                # OrderSideの判定
                side_str = order_data.get('side', '')
                if side_str.lower() == 'b':
                    side = OrderSide.BUY
                elif side_str.lower() == 'a':
                    side = OrderSide.SELL
                else:
                    continue  # 不明なサイドはスキップ
                    
                order = Order(
                    id=str(order_data.get('oid')),
                    symbol=order_symbol,
                    side=side,
                    type=OrderType.LIMIT,  # Hyperliquidは基本的にlimit
                    price=Decimal(str(order_data.get('limitPx', 0))),
                    quantity=Decimal(str(order_data.get('sz', 0))),
                    filled=Decimal('0'),  # 未約定なので0
                    remaining=Decimal(str(order_data.get('sz', 0))),
                    status=OrderStatus.NEW,
                    timestamp=int(order_data.get('timestamp', datetime.now().timestamp() * 1000))
                )
                orders.append(order)
                
            return orders
            
        except Exception as e:
            logger.error(f"Failed to get Hyperliquid open orders: {e}")
            raise
        
    async def get_balance(self) -> Dict[str, Balance]:
        """残高を取得"""
        if not self.has_hyperliquid_lib or not self.info:
            raise NotImplementedError("Hyperliquid library not available")
            
        try:
            # Hyperliquidのuser_stateで残高情報を取得
            user_state = self.info.user_state(self.api_key)  # wallet address
            balances = {}
            
            # スポット残高
            if 'balances' in user_state:
                for balance_data in user_state['balances']:
                    asset = balance_data.get('coin')
                    total = Decimal(str(balance_data.get('total', '0')))
                    hold = Decimal(str(balance_data.get('hold', '0')))  # ロックされた残高
                    
                    balances[asset] = Balance(
                        asset=asset,
                        free=total - hold,
                        locked=hold,
                        total=total
                    )
            
            # クロスマージン残高
            if 'crossMaintenanceMarginUsed' in user_state:
                margin_summary = user_state.get('marginSummary', {})
                account_value = Decimal(str(margin_summary.get('accountValue', '0')))
                total_margin_used = Decimal(str(user_state.get('crossMaintenanceMarginUsed', '0')))
                
                # USDCでの残高として追加
                if 'USDC' not in balances:
                    balances['USDC'] = Balance(
                        asset='USDC',
                        free=account_value - total_margin_used,
                        locked=total_margin_used,
                        total=account_value
                    )
                else:
                    # 既存のUSDC残高に追加
                    existing = balances['USDC']
                    balances['USDC'] = Balance(
                        asset='USDC',
                        free=existing.free + (account_value - total_margin_used),
                        locked=existing.locked + total_margin_used,
                        total=existing.total + account_value
                    )
            
            return balances
            
        except Exception as e:
            logger.error(f"Failed to get Hyperliquid balance: {e}")
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
        if not self.has_hyperliquid_lib or not self.info:
            raise NotImplementedError("Hyperliquid library not available")
            
        try:
            # Hyperliquidのuser_stateからポジション情報を取得
            user_state = self.info.user_state(self.api_key)  # wallet address
            positions = []
            
            # アクティブポジション
            active_positions = user_state.get('assetPositions', [])
            
            for pos_data in active_positions:
                position_info = pos_data.get('position', {})
                coin = position_info.get('coin')
                size_str = position_info.get('szi', '0')
                
                if not coin or size_str == '0':
                    continue
                    
                size = Decimal(str(size_str))
                
                # サイズから買い/売りを判定
                if size > 0:
                    side = OrderSide.BUY  # Long position
                else:
                    side = OrderSide.SELL  # Short position
                    size = abs(size)
                    
                entry_px = Decimal(str(position_info.get('entryPx', '0')))
                
                # 未実現PnLの計算
                unrealized_pnl = Decimal('0')
                if 'unrealizedPnl' in position_info:
                    unrealized_pnl = Decimal(str(position_info['unrealizedPnl']))
                
                # マーク価格の取得
                mark_price = entry_px
                try:
                    ticker = await self.get_ticker(coin)
                    mark_price = ticker.mark_price
                except:
                    pass  # マーク価格取得失敗時はentry_pxを使用
                
                position = Position(
                    symbol=coin,
                    side=side,
                    size=size,
                    entry_price=entry_px,
                    mark_price=mark_price,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=Decimal('0'),  # Hyperliquidでは別途取得が必要
                    timestamp=int(datetime.now().timestamp() * 1000)
                )
                positions.append(position)
                
            return positions
            
        except Exception as e:
            logger.error(f"Failed to get Hyperliquid positions: {e}")
            raise
        
    async def get_trading_fees(self, symbol: str) -> Dict[str, Decimal]:
        """取引手数料を取得"""
        return get_exchange_fees("hyperliquid")
        
    @property
    def is_connected(self) -> bool:
        """WebSocket接続状態を取得"""
        return self.is_ws_connected and self.websocket is not None