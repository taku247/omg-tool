"""
取引所手数料関連のユーティリティ関数
"""

from decimal import Decimal
from typing import Dict
import logging

from ..core.config import get_config

logger = logging.getLogger(__name__)


def get_exchange_fees(exchange_name: str) -> Dict[str, Decimal]:
    """
    設定ファイルから取引所の手数料を取得
    
    Args:
        exchange_name: 取引所名（小文字）
        
    Returns:
        手数料辞書 {"maker_fee": Decimal, "taker_fee": Decimal}
    """
    # デフォルト手数料（フォールバック用）
    default_fees = {
        "hyperliquid": {"maker": "0.00013", "taker": "0.000389"},
        "bybit": {"maker": "0.0001", "taker": "0.0006"},
        "binance": {"maker": "0.0002", "taker": "0.0004"},
        "gate": {"maker": "0.0002", "taker": "0.0005"},
        "bitget": {"maker": "0.0002", "taker": "0.0006"},
        "kucoin": {"maker": "0.0002", "taker": "0.0006"}
    }
    
    try:
        config = get_config()
        fees = config.get('exchanges', {}).get(exchange_name.lower(), {}).get('fees', {})
        
        if fees:
            return {
                "maker_fee": Decimal(str(fees.get('maker', default_fees.get(exchange_name.lower(), {}).get('maker', '0.0002')))),
                "taker_fee": Decimal(str(fees.get('taker', default_fees.get(exchange_name.lower(), {}).get('taker', '0.0005'))))
            }
        else:
            # configに手数料設定がない場合はデフォルト値を使用
            defaults = default_fees.get(exchange_name.lower(), {"maker": "0.0002", "taker": "0.0005"})
            logger.warning(f"No fee configuration found for {exchange_name}. Using defaults: {defaults}")
            return {
                "maker_fee": Decimal(defaults["maker"]),
                "taker_fee": Decimal(defaults["taker"])
            }
            
    except Exception as e:
        logger.error(f"Failed to load fees from config for {exchange_name}: {e}")
        # エラー時のフォールバック
        defaults = default_fees.get(exchange_name.lower(), {"maker": "0.0002", "taker": "0.0005"})
        return {
            "maker_fee": Decimal(defaults["maker"]),
            "taker_fee": Decimal(defaults["taker"])
        }


def calculate_arbitrage_fees(buy_exchange: str, sell_exchange: str, 
                           position_size: Decimal) -> Dict[str, Decimal]:
    """
    アービトラージ取引の総手数料を計算
    
    Args:
        buy_exchange: 買い取引所名
        sell_exchange: 売り取引所名  
        position_size: ポジションサイズ
        
    Returns:
        手数料詳細 {"buy_fee": Decimal, "sell_fee": Decimal, "total_fee": Decimal}
    """
    buy_fees = get_exchange_fees(buy_exchange)
    sell_fees = get_exchange_fees(sell_exchange)
    
    # アービトラージでは通常taker手数料が適用される
    buy_fee = position_size * buy_fees["taker_fee"]
    sell_fee = position_size * sell_fees["taker_fee"]
    
    return {
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
        "total_fee": buy_fee + sell_fee,
        "buy_fee_rate": buy_fees["taker_fee"],
        "sell_fee_rate": sell_fees["taker_fee"]
    }


def get_fee_adjusted_threshold(exchanges: list, base_threshold: float = 0.5) -> float:
    """
    手数料を考慮した最小アービトラージ閾値を計算
    
    Args:
        exchanges: 対象取引所リスト
        base_threshold: ベース閾値（%）
        
    Returns:
        手数料調整後の閾値（%）
    """
    if len(exchanges) < 2:
        return base_threshold
        
    # 最も高い手数料ペアを想定
    max_fee_rate = 0.0
    
    for i, exchange1 in enumerate(exchanges):
        for exchange2 in exchanges[i+1:]:
            fees1 = get_exchange_fees(exchange1)
            fees2 = get_exchange_fees(exchange2)
            
            # 往復taker手数料
            total_fee_rate = float(fees1["taker_fee"] + fees2["taker_fee"]) * 100
            max_fee_rate = max(max_fee_rate, total_fee_rate)
    
    # 手数料の2-3倍をマージンとして追加
    safety_margin = max_fee_rate * 2.5
    adjusted_threshold = base_threshold + safety_margin
    
    logger.info(f"Fee-adjusted threshold: {base_threshold}% + {safety_margin:.3f}% = {adjusted_threshold:.3f}%")
    
    return adjusted_threshold