"""リスク管理モジュール"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging

from .arbitrage_detector import ArbitrageOpportunity
from .position_manager import ArbitragePosition, PositionManager

logger = logging.getLogger(__name__)


@dataclass
class RiskParameters:
    """リスク管理パラメータ"""
    # ポジションサイズ制限
    max_position_size: Decimal = Decimal("10000")  # USD
    max_total_exposure: Decimal = Decimal("50000")  # USD
    max_positions_per_symbol: int = 3
    max_total_positions: int = 10
    
    # スリッページ・スプレッド制限
    max_slippage_percentage: Decimal = Decimal("0.5")  # 0.5%
    min_net_spread: Decimal = Decimal("0.2")  # 0.2% 最小純スプレッド
    
    # 時間制限
    max_position_duration: int = 24 * 3600  # 24時間
    cooldown_period: int = 300  # 5分間のクールダウン
    
    # 損失制限
    max_daily_loss: Decimal = Decimal("1000")  # 日次最大損失
    max_drawdown: Decimal = Decimal("5000")  # 最大ドローダウン
    stop_loss_percentage: Decimal = Decimal("2.0")  # 2% ストップロス
    
    # 取引所リスク
    max_exchange_exposure: Decimal = Decimal("20000")  # 取引所あたり最大エクスポージャー
    min_exchange_balance: Decimal = Decimal("1000")  # 最小残高要件


class RiskManager:
    """リスク管理クラス"""
    
    def __init__(self, params: RiskParameters):
        self.params = params
        self.current_exposure: Dict[str, Decimal] = {}  # シンボル別エクスポージャー
        self.exchange_exposure: Dict[str, Decimal] = {}  # 取引所別エクスポージャー
        self.daily_pnl: Decimal = Decimal("0")
        self.max_drawdown_today: Decimal = Decimal("0")
        self.last_trade_time: Dict[str, datetime] = {}  # シンボル別最終取引時間
        self.blocked_symbols: List[str] = []
        self.blocked_exchanges: List[str] = []
        
    async def validate_opportunity(self, 
                                 opportunity: ArbitrageOpportunity,
                                 position_manager: PositionManager,
                                 balances: Dict[str, Dict[str, Any]]) -> tuple[bool, str]:
        """取引機会がリスク基準を満たすか検証"""
        
        # 1. ポジションサイズチェック
        if opportunity.recommended_size * opportunity.buy_price > self.params.max_position_size:
            return False, f"Position size too large: {opportunity.recommended_size * opportunity.buy_price}"
            
        # 2. シンボル別ポジション数チェック
        symbol_positions = sum(1 for p in position_manager.get_active_positions()
                             if p.symbol == opportunity.symbol)
        if symbol_positions >= self.params.max_positions_per_symbol:
            return False, f"Too many positions for {opportunity.symbol}: {symbol_positions}"
            
        # 3. 総ポジション数チェック
        total_positions = len(position_manager.get_active_positions())
        if total_positions >= self.params.max_total_positions:
            return False, f"Too many total positions: {total_positions}"
            
        # 4. 総エクスポージャーチェック
        position_value = opportunity.recommended_size * opportunity.buy_price
        current_total_exposure = sum(self.current_exposure.values())
        if current_total_exposure + position_value > self.params.max_total_exposure:
            return False, f"Total exposure limit exceeded: {current_total_exposure + position_value}"
            
        # 5. 取引所別エクスポージャーチェック
        buy_exchange_exposure = self.exchange_exposure.get(opportunity.buy_exchange, Decimal("0"))
        sell_exchange_exposure = self.exchange_exposure.get(opportunity.sell_exchange, Decimal("0"))
        
        if (buy_exchange_exposure + position_value > self.params.max_exchange_exposure or
            sell_exchange_exposure + position_value > self.params.max_exchange_exposure):
            return False, "Exchange exposure limit exceeded"
            
        # 6. スリッページチェック
        if (opportunity.slippage_buy and opportunity.slippage_buy > self.params.max_slippage_percentage):
            return False, f"Buy slippage too high: {opportunity.slippage_buy}%"
            
        if (opportunity.slippage_sell and opportunity.slippage_sell > self.params.max_slippage_percentage):
            return False, f"Sell slippage too high: {opportunity.slippage_sell}%"
            
        # 7. 純スプレッドチェック
        if opportunity.net_spread < self.params.min_net_spread:
            return False, f"Net spread too low: {opportunity.net_spread}%"
            
        # 8. クールダウンチェック
        last_trade = self.last_trade_time.get(opportunity.symbol)
        if last_trade and datetime.now() - last_trade < timedelta(seconds=self.params.cooldown_period):
            return False, f"Cooldown period active for {opportunity.symbol}"
            
        # 9. 日次損失チェック
        if self.daily_pnl <= -self.params.max_daily_loss:
            return False, f"Daily loss limit reached: {self.daily_pnl}"
            
        # 10. ドローダウンチェック
        if self.max_drawdown_today >= self.params.max_drawdown:
            return False, f"Max drawdown reached: {self.max_drawdown_today}"
            
        # 11. ブロック状態チェック
        if (opportunity.symbol in self.blocked_symbols or
            opportunity.buy_exchange in self.blocked_exchanges or
            opportunity.sell_exchange in self.blocked_exchanges):
            return False, "Symbol or exchange is blocked"
            
        # 12. 残高チェック
        buy_balance = balances.get(opportunity.buy_exchange, {})
        sell_balance = balances.get(opportunity.sell_exchange, {})
        
        if not self._check_sufficient_balance(opportunity, buy_balance, sell_balance):
            return False, "Insufficient balance"
            
        return True, "Risk check passed"
        
    def _check_sufficient_balance(self, 
                                opportunity: ArbitrageOpportunity,
                                buy_balance: Dict[str, Any],
                                sell_balance: Dict[str, Any]) -> bool:
        """残高が十分かチェック"""
        # 簡易チェック（実装時に詳細化）
        symbol_parts = opportunity.symbol.replace('/', '').replace('-', '')
        base_asset = symbol_parts.replace('USDT', '').replace('USD', '')
        quote_asset = 'USDT' if 'USDT' in symbol_parts else 'USD'
        
        # 買い取引所にクオート通貨の残高があるか
        quote_balance = buy_balance.get(quote_asset, {}).get('free', 0)
        required_quote = float(opportunity.recommended_size * opportunity.buy_price)
        
        if quote_balance < required_quote + float(self.params.min_exchange_balance):
            return False
            
        # 売り取引所に基軸通貨の残高があるか
        base_balance = sell_balance.get(base_asset, {}).get('free', 0)
        required_base = float(opportunity.recommended_size)
        
        if base_balance < required_base:
            return False
            
        return True
        
    async def update_position_opened(self, position: ArbitragePosition) -> None:
        """ポジションオープン時の更新"""
        position_value = position.size * (position.long_order.price if position.long_order else Decimal("0"))
        
        # エクスポージャー更新
        self.current_exposure[position.symbol] = self.current_exposure.get(position.symbol, Decimal("0")) + position_value
        self.exchange_exposure[position.long_exchange] = self.exchange_exposure.get(position.long_exchange, Decimal("0")) + position_value
        self.exchange_exposure[position.short_exchange] = self.exchange_exposure.get(position.short_exchange, Decimal("0")) + position_value
        
        # 最終取引時間更新
        self.last_trade_time[position.symbol] = datetime.now()
        
        logger.info(f"Risk updated for opened position {position.id}")
        
    async def update_position_closed(self, position: ArbitragePosition) -> None:
        """ポジションクローズ時の更新"""
        position_value = position.size * (position.long_order.price if position.long_order else Decimal("0"))
        
        # エクスポージャー更新
        self.current_exposure[position.symbol] = max(Decimal("0"), 
                                                   self.current_exposure.get(position.symbol, Decimal("0")) - position_value)
        self.exchange_exposure[position.long_exchange] = max(Decimal("0"),
                                                           self.exchange_exposure.get(position.long_exchange, Decimal("0")) - position_value)
        self.exchange_exposure[position.short_exchange] = max(Decimal("0"),
                                                            self.exchange_exposure.get(position.short_exchange, Decimal("0")) - position_value)
        
        # 日次PnL更新
        self.daily_pnl += position.net_pnl
        
        # ドローダウン更新
        if position.net_pnl < 0:
            self.max_drawdown_today = max(self.max_drawdown_today, abs(position.net_pnl))
            
        logger.info(f"Risk updated for closed position {position.id}, PnL: {position.net_pnl}")
        
    async def check_stop_loss(self, position: ArbitragePosition, current_spread: Decimal) -> bool:
        """ストップロス条件をチェック"""
        if not position.is_open:
            return False
            
        # 未実現損失が閾値を超えた場合
        if position.unrealized_pnl < 0:
            loss_percentage = abs(position.unrealized_pnl) / (position.size * position.long_order.price) * 100
            if loss_percentage >= self.params.stop_loss_percentage:
                logger.warning(f"Stop loss triggered for position {position.id}: {loss_percentage}%")
                return True
                
        # ポジション保有時間が長すぎる場合
        if position.duration and position.duration > self.params.max_position_duration:
            logger.warning(f"Position {position.id} held too long: {position.duration}s")
            return True
            
        return False
        
    def block_symbol(self, symbol: str, duration_minutes: int = 60) -> None:
        """シンボルを一時的にブロック"""
        if symbol not in self.blocked_symbols:
            self.blocked_symbols.append(symbol)
            logger.warning(f"Blocked symbol {symbol} for {duration_minutes} minutes")
            
            # 自動解除タスクを作成（実装時に追加）
            
    def block_exchange(self, exchange: str, duration_minutes: int = 60) -> None:
        """取引所を一時的にブロック"""
        if exchange not in self.blocked_exchanges:
            self.blocked_exchanges.append(exchange)
            logger.warning(f"Blocked exchange {exchange} for {duration_minutes} minutes")
            
    def reset_daily_stats(self) -> None:
        """日次統計をリセット"""
        self.daily_pnl = Decimal("0")
        self.max_drawdown_today = Decimal("0")
        logger.info("Daily risk stats reset")
        
    def get_risk_status(self) -> Dict[str, Any]:
        """リスク状態を取得"""
        return {
            "current_exposure": {k: float(v) for k, v in self.current_exposure.items()},
            "exchange_exposure": {k: float(v) for k, v in self.exchange_exposure.items()},
            "daily_pnl": float(self.daily_pnl),
            "max_drawdown_today": float(self.max_drawdown_today),
            "blocked_symbols": self.blocked_symbols,
            "blocked_exchanges": self.blocked_exchanges,
            "risk_limits": {
                "max_position_size": float(self.params.max_position_size),
                "max_total_exposure": float(self.params.max_total_exposure),
                "max_daily_loss": float(self.params.max_daily_loss),
                "max_drawdown": float(self.params.max_drawdown)
            }
        }