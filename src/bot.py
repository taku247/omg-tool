"""アービトラージBot メインクラス"""

import asyncio
import logging
from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime, timedelta

from .interfaces.exchange import ExchangeInterface
from .core.websocket_manager import WebSocketManager, PriceAggregator
from .core.arbitrage_detector import ArbitrageDetector, ArbitrageOpportunity
from .core.position_manager import PositionManager
from .core.order_manager import OrderManager
from .core.risk_manager import RiskManager, RiskParameters

logger = logging.getLogger(__name__)


class ArbitrageBot:
    """アービトラージBot メインクラス"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        
        # コンポーネント初期化
        self.order_manager = OrderManager()
        self.position_manager = PositionManager(self.order_manager)
        self.ws_manager = WebSocketManager()
        self.price_aggregator = PriceAggregator(self.ws_manager)
        
        # 設定からリスクパラメータを作成
        risk_config = config.get('risk', {})
        self.risk_params = RiskParameters(
            max_position_size=Decimal(str(risk_config.get('max_position_size', 10000))),
            max_total_exposure=Decimal(str(risk_config.get('max_total_exposure', 50000))),
            max_positions_per_symbol=risk_config.get('max_positions_per_symbol', 3),
            max_slippage_percentage=Decimal(str(risk_config.get('max_slippage_percentage', 0.5))),
            min_net_spread=Decimal(str(risk_config.get('min_net_spread', 0.2))),
            max_daily_loss=Decimal(str(risk_config.get('max_daily_loss', 1000)))
        )
        self.risk_manager = RiskManager(self.risk_params)
        
        # アービトラージ検出器
        detector_config = config.get('arbitrage', {})
        self.arbitrage_detector = ArbitrageDetector(
            min_spread_threshold=Decimal(str(detector_config.get('min_spread_threshold', 0.5))),
            max_position_size=Decimal(str(detector_config.get('max_position_size', 10000))),
            min_profit_threshold=Decimal(str(detector_config.get('min_profit_threshold', 10)))
        )
        
        # 監視対象シンボル
        self.symbols = config.get('symbols', ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'])
        
        # 統計情報
        self.start_time = None
        self.total_opportunities = 0
        self.total_trades = 0
        
        # コールバック設定
        self._setup_callbacks()
        
    def _setup_callbacks(self):
        """各コンポーネントのコールバックを設定"""
        
        # 価格更新時のアービトラージ検出
        self.price_aggregator.add_update_callback(self._on_price_update)
        
        # アービトラージ機会検出時の処理
        self.arbitrage_detector.add_opportunity_callback(self._on_arbitrage_opportunity)
        
        # ポジション関連のコールバック
        self.position_manager.add_callback("position_opened", self._on_position_opened)
        self.position_manager.add_callback("position_closed", self._on_position_closed)
        self.position_manager.add_callback("position_failed", self._on_position_failed)
        
        # 接続関連のコールバック
        self.ws_manager.subscribe("connection_failed", self._on_connection_failed)
        self.ws_manager.subscribe("connection_restored", self._on_connection_restored)
        
    async def add_exchange(self, name: str, exchange: ExchangeInterface) -> None:
        """取引所を追加"""
        # 各コンポーネントに取引所を追加
        self.order_manager.add_exchange(name, exchange)
        await self.ws_manager.add_exchange(name, exchange, self.symbols)
        
        logger.info(f"Added exchange: {name}")
        
    async def start(self) -> None:
        """Botを開始"""
        if self.running:
            logger.warning("Bot is already running")
            return
            
        self.running = True
        self.start_time = datetime.now()
        
        
        logger.info("Starting Arbitrage Bot...")
        
        # WebSocketマネージャーを開始
        await self.ws_manager.start()
        
        # メインループを開始
        asyncio.create_task(self._main_loop())
        asyncio.create_task(self._periodic_tasks())
        
        logger.info("Arbitrage Bot started successfully")
        
    async def stop(self) -> None:
        """Botを停止"""
        if not self.running:
            logger.warning("Bot is not running")
            return
            
        self.running = False
        
        logger.info("Stopping Arbitrage Bot...")
        
        # WebSocketマネージャーを停止
        await self.ws_manager.stop()
        
        # アクティブなポジションを全てクローズ
        await self._close_all_positions()
        
        logger.info("Arbitrage Bot stopped")
        
    async def _main_loop(self) -> None:
        """メインループ"""
        while self.running:
            try:
                # アクティブなポジションの監視
                await self._monitor_positions()
                
                # 短い間隔で実行
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)
                
    async def _periodic_tasks(self) -> None:
        """定期実行タスク"""
        while self.running:
            try:
                # 5分ごとに実行
                await asyncio.sleep(300)
                
                # 統計情報の出力
                await self._log_statistics()
                
                # 日次リセット（必要に応じて）
                await self._check_daily_reset()
                
            except Exception as e:
                logger.error(f"Error in periodic tasks: {e}")
                
    async def _on_price_update(self, exchange: str, ticker) -> None:
        """価格更新時の処理"""
        try:
            await self.arbitrage_detector.update_price(exchange, ticker)
        except Exception as e:
            logger.error(f"Error processing price update: {e}")
            
    async def _on_arbitrage_opportunity(self, opportunity: ArbitrageOpportunity) -> None:
        """アービトラージ機会検出時の処理"""
        try:
            self.total_opportunities += 1
            
            logger.info(f"Arbitrage opportunity: {opportunity.id} - "
                       f"{opportunity.symbol} {opportunity.spread_percentage:.2f}% "
                       f"({opportunity.buy_exchange} -> {opportunity.sell_exchange})")
            
            # リスクチェック
            balances = await self.order_manager.get_all_balances()
            is_valid, reason = await self.risk_manager.validate_opportunity(
                opportunity, self.position_manager, balances
            )
            
            if not is_valid:
                logger.info(f"Opportunity {opportunity.id} rejected: {reason}")
                return
                
            # 板情報を取得してスリッページを計算
            await self._calculate_slippage(opportunity)
            
            # 再度リスクチェック（スリッページ考慮）
            is_valid, reason = await self.risk_manager.validate_opportunity(
                opportunity, self.position_manager, balances
            )
            
            if not is_valid:
                logger.info(f"Opportunity {opportunity.id} rejected after slippage check: {reason}")
                return
                
            # ポジションをオープン
            await self._execute_opportunity(opportunity)
            
        except Exception as e:
            logger.error(f"Error handling arbitrage opportunity: {e}")
            
    async def _calculate_slippage(self, opportunity: ArbitrageOpportunity) -> None:
        """スリッページを計算"""
        try:
            # 買い取引所の板情報を取得
            buy_exchange = self.order_manager.exchanges[opportunity.buy_exchange]
            buy_orderbook = await buy_exchange.get_orderbook(opportunity.symbol)
            
            # 売り取引所の板情報を取得
            sell_exchange = self.order_manager.exchanges[opportunity.sell_exchange]
            sell_orderbook = await sell_exchange.get_orderbook(opportunity.symbol)
            
            # スリッページを計算
            opportunity = await self.arbitrage_detector.calculate_slippage_for_opportunity(
                opportunity, buy_orderbook, sell_orderbook
            )
            
        except Exception as e:
            logger.error(f"Error calculating slippage: {e}")
            # スリッページ計算に失敗した場合は大きな値を設定
            opportunity.slippage_buy = Decimal("999")
            opportunity.slippage_sell = Decimal("999")
            
    async def _execute_opportunity(self, opportunity: ArbitrageOpportunity) -> None:
        """アービトラージ機会を実行"""
        try:
            logger.info(f"Executing opportunity: {opportunity.id}")
            
            # ポジションをオープン
            position = await self.position_manager.open_position(opportunity)
            
            if position.status.value == "open":
                self.total_trades += 1
                logger.info(f"Position opened successfully: {position.id}")
            else:
                logger.error(f"Failed to open position: {position.id}")
                
        except Exception as e:
            logger.error(f"Error executing opportunity: {e}")
            
    async def _monitor_positions(self) -> None:
        """アクティブポジションを監視"""
        for position in self.position_manager.get_active_positions():
            try:
                # 現在の価格を取得
                current_prices = self.price_aggregator.get_all_prices(position.symbol)
                
                if len(current_prices) < 2:
                    continue
                    
                # 現在のスプレッドを計算
                long_price = current_prices.get(position.long_exchange)
                short_price = current_prices.get(position.short_exchange)
                
                if not long_price or not short_price:
                    continue
                    
                current_spread = (short_price.bid - long_price.ask) / long_price.ask * 100
                
                # 未実現損益を更新
                if position.long_order and position.short_order:
                    long_pnl = (long_price.mark_price - position.long_order.price) * position.size
                    short_pnl = (position.short_order.price - short_price.mark_price) * position.size
                    position.unrealized_pnl = long_pnl + short_pnl
                
                # ストップロスチェック
                if await self.risk_manager.check_stop_loss(position, current_spread):
                    logger.warning(f"Stop loss triggered for position {position.id}")
                    await self.position_manager.close_position(position.id, "stop_loss")
                    continue
                    
                # 通常のクローズ条件チェック
                if await self.position_manager.should_close_position(position, current_spread):
                    logger.info(f"Closing position {position.id} due to spread convergence")
                    await self.position_manager.close_position(position.id, "spread_convergence")
                    
            except Exception as e:
                logger.error(f"Error monitoring position {position.id}: {e}")
                
    async def _on_position_opened(self, position) -> None:
        """ポジションオープン時の処理"""
        await self.risk_manager.update_position_opened(position)
        logger.info(f"Position opened: {position.id}")
        
    async def _on_position_closed(self, position) -> None:
        """ポジションクローズ時の処理"""
        await self.risk_manager.update_position_closed(position)
        logger.info(f"Position closed: {position.id}, PnL: {position.net_pnl}")
        
    async def _on_position_failed(self, position) -> None:
        """ポジション失敗時の処理"""
        logger.error(f"Position failed: {position.id} - {position.error_message}")
        
    async def _on_connection_failed(self, data) -> None:
        """接続失敗時の処理"""
        exchange = data['exchange']
        logger.error(f"Connection failed for {exchange}")
        
        # 該当取引所を一時的にブロック
        self.risk_manager.block_exchange(exchange, 30)
        
    async def _on_connection_restored(self, data) -> None:
        """接続復旧時の処理"""
        exchange = data['exchange']
        logger.info(f"Connection restored for {exchange}")
        
    async def _close_all_positions(self) -> None:
        """全てのポジションをクローズ"""
        active_positions = self.position_manager.get_active_positions()
        if not active_positions:
            return
            
        logger.info(f"Closing {len(active_positions)} active positions...")
        
        tasks = []
        for position in active_positions:
            task = self.position_manager.close_position(position.id, "bot_shutdown")
            tasks.append(task)
            
        await asyncio.gather(*tasks, return_exceptions=True)
        
    async def _log_statistics(self) -> None:
        """統計情報をログ出力"""
        uptime = datetime.now() - self.start_time if self.start_time else timedelta(0)
        
        stats = {
            "uptime": str(uptime),
            "total_opportunities": self.total_opportunities,
            "total_trades": self.total_trades,
            "active_positions": len(self.position_manager.get_active_positions()),
            "risk_status": self.risk_manager.get_risk_status(),
            "position_stats": self.position_manager.get_statistics(),
            "order_stats": self.order_manager.get_statistics()
        }
        
        logger.info(f"Bot Statistics: {stats}")
        
    async def _check_daily_reset(self) -> None:
        """日次リセットチェック"""
        now = datetime.now()
        if now.hour == 0 and now.minute < 5:  # 午前0時台
            self.risk_manager.reset_daily_stats()
            
    def get_status(self) -> Dict:
        """Bot状態を取得"""
        return {
            "running": self.running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "total_opportunities": self.total_opportunities,
            "total_trades": self.total_trades,
            "active_positions": len(self.position_manager.get_active_positions()),
            "exchanges": self.ws_manager.get_status(),
            "risk_status": self.risk_manager.get_risk_status()
        }