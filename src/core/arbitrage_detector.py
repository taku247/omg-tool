"""アービトラージ機会検出モジュール"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Callable
from datetime import datetime
import logging

from ..interfaces.exchange import Ticker, OrderBook, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class ArbitrageOpportunity:
    """アービトラージ機会"""
    id: str
    buy_exchange: str
    sell_exchange: str
    symbol: str
    spread_percentage: Decimal
    expected_profit: Decimal
    buy_price: Decimal
    sell_price: Decimal
    recommended_size: Decimal
    slippage_buy: Optional[Decimal] = None
    slippage_sell: Optional[Decimal] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
            
    @property
    def net_spread(self) -> Decimal:
        """スリッページを考慮した実質スプレッド"""
        slippage_total = (self.slippage_buy or Decimal("0")) + (self.slippage_sell or Decimal("0"))
        return self.spread_percentage - slippage_total


class ArbitrageDetector:
    """アービトラージ機会を検出するクラス"""
    
    def __init__(self, 
                 min_spread_threshold: Decimal = Decimal("0.5"),
                 max_position_size: Decimal = Decimal("10000"),
                 min_profit_threshold: Decimal = Decimal("10"),
                 slippage_calculator: Optional[Callable] = None):
        self.min_spread_threshold = min_spread_threshold
        self.max_position_size = max_position_size
        self.min_profit_threshold = min_profit_threshold
        self.slippage_calculator = slippage_calculator
        self.price_cache: Dict[str, Dict[str, Ticker]] = {}
        self.opportunity_callbacks: List[Callable] = []
        self.opportunity_counter = 0
        
    def add_opportunity_callback(self, callback: Callable) -> None:
        """機会検出時のコールバックを追加"""
        self.opportunity_callbacks.append(callback)
        
    async def update_price(self, exchange: str, ticker: Ticker) -> None:
        """価格キャッシュを更新し、アービトラージ機会をチェック"""
        # キャッシュを更新
        if ticker.symbol not in self.price_cache:
            self.price_cache[ticker.symbol] = {}
        self.price_cache[ticker.symbol][exchange] = ticker
        
        # アービトラージ機会をチェック
        opportunities = await self.check_arbitrage(ticker.symbol)
        
        # コールバックを実行
        for opportunity in opportunities:
            for callback in self.opportunity_callbacks:
                await callback(opportunity)
                
    async def check_arbitrage(self, symbol: str) -> List[ArbitrageOpportunity]:
        """指定シンボルのアービトラージ機会を検出"""
        prices = self.price_cache.get(symbol, {})
        if len(prices) < 2:
            return []
            
        opportunities = []
        
        # 全ての取引所ペアをチェック
        exchanges = list(prices.keys())
        for i, ex1 in enumerate(exchanges):
            for ex2 in exchanges[i+1:]:
                ticker1 = prices[ex1]
                ticker2 = prices[ex2]
                
                # 両方向のアービトラージをチェック
                # ex1で買い、ex2で売り
                opp1 = self._check_opportunity(ex1, ticker1, ex2, ticker2, symbol)
                if opp1:
                    opportunities.append(opp1)
                    
                # ex2で買い、ex1で売り
                opp2 = self._check_opportunity(ex2, ticker2, ex1, ticker1, symbol)
                if opp2:
                    opportunities.append(opp2)
                    
        return opportunities
        
    def _check_opportunity(self, buy_exchange: str, buy_ticker: Ticker,
                          sell_exchange: str, sell_ticker: Ticker,
                          symbol: str) -> Optional[ArbitrageOpportunity]:
        """単一方向のアービトラージ機会をチェック"""
        # スプレッド計算（売値 - 買値）
        spread = sell_ticker.bid - buy_ticker.ask
        spread_percentage = (spread / buy_ticker.ask) * 100
        
        # 閾値チェック
        if spread_percentage < self.min_spread_threshold:
            return None
            
        # 推奨サイズの計算
        recommended_size = self._calculate_optimal_size(buy_ticker, sell_ticker)
        if recommended_size <= 0:
            return None
            
        # 期待利益の計算
        expected_profit = spread * recommended_size
        
        # 最小利益チェック
        if expected_profit < self.min_profit_threshold:
            return None
            
        # アービトラージ機会を作成
        self.opportunity_counter += 1
        opportunity = ArbitrageOpportunity(
            id=f"ARB_{self.opportunity_counter:06d}",
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            symbol=symbol,
            spread_percentage=spread_percentage,
            expected_profit=expected_profit,
            buy_price=buy_ticker.ask,
            sell_price=sell_ticker.bid,
            recommended_size=recommended_size
        )
        
        logger.info(f"Arbitrage opportunity detected: {opportunity.id} - "
                   f"{buy_exchange} -> {sell_exchange}, "
                   f"spread: {spread_percentage:.2f}%, "
                   f"profit: ${expected_profit:.2f}")
        
        return opportunity
        
    def _calculate_optimal_size(self, buy_ticker: Ticker, sell_ticker: Ticker) -> Decimal:
        """最適な取引サイズを計算"""
        # 簡易版：最大ポジションサイズと取引量の10%の小さい方
        volume_limit = min(
            buy_ticker.volume_24h * Decimal("0.1") if buy_ticker.volume_24h else self.max_position_size,
            sell_ticker.volume_24h * Decimal("0.1") if sell_ticker.volume_24h else self.max_position_size
        )
        
        # USD換算
        size_in_usd = min(self.max_position_size, volume_limit * buy_ticker.ask)
        size_in_asset = size_in_usd / buy_ticker.ask
        
        return size_in_asset
        
    async def calculate_slippage_for_opportunity(self, 
                                               opportunity: ArbitrageOpportunity,
                                               buy_orderbook: OrderBook,
                                               sell_orderbook: OrderBook) -> ArbitrageOpportunity:
        """アービトラージ機会のスリッページを計算"""
        if self.slippage_calculator:
            # カスタムスリッページ計算
            buy_slippage = await self.slippage_calculator(
                buy_orderbook, OrderSide.BUY, opportunity.recommended_size
            )
            sell_slippage = await self.slippage_calculator(
                sell_orderbook, OrderSide.SELL, opportunity.recommended_size
            )
        else:
            # デフォルトスリッページ計算
            buy_slippage = self._calculate_default_slippage(
                buy_orderbook, OrderSide.BUY, opportunity.recommended_size
            )
            sell_slippage = self._calculate_default_slippage(
                sell_orderbook, OrderSide.SELL, opportunity.recommended_size
            )
            
        opportunity.slippage_buy = buy_slippage
        opportunity.slippage_sell = sell_slippage
        
        return opportunity
        
    def _calculate_default_slippage(self, orderbook: OrderBook, 
                                  side: OrderSide, size: Decimal) -> Decimal:
        """デフォルトのスリッページ計算"""
        book = orderbook.asks if side == OrderSide.BUY else orderbook.bids
        if not book:
            return Decimal("999")  # 板がない場合は大きなスリッページ
            
        remaining = size
        total_cost = Decimal("0")
        
        for price, volume in book:
            if remaining <= 0:
                break
            fill_size = min(remaining, volume)
            total_cost += price * fill_size
            remaining -= fill_size
            
        if remaining > 0:
            return Decimal("999")  # 板が薄い
            
        avg_price = total_cost / size
        best_price = book[0][0]
        slippage = abs(avg_price - best_price) / best_price * 100
        
        return slippage
        
    def get_statistics(self) -> Dict[str, any]:
        """統計情報を取得"""
        total_symbols = len(self.price_cache)
        total_exchanges = len(set(
            exchange for prices in self.price_cache.values() 
            for exchange in prices.keys()
        ))
        
        return {
            "total_opportunities": self.opportunity_counter,
            "monitored_symbols": total_symbols,
            "connected_exchanges": total_exchanges,
            "min_spread_threshold": float(self.min_spread_threshold),
            "max_position_size": float(self.max_position_size)
        }