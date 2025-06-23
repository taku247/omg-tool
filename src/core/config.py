"""設定ファイル管理モジュール"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class Config:
    """設定ファイル管理クラス"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        設定ファイルを読み込み
        
        Args:
            config_path: 設定ファイルパス（省略時はデフォルトパス）
        """
        if config_path is None:
            # プロジェクトルートから相対パスで設定ファイルを探す
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "bot_config.yaml"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            if not self.config_path.exists():
                logger.warning(f"設定ファイルが見つかりません: {self.config_path}")
                return self._get_default_config()
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            # 環境変数の置換
            config = self._substitute_env_vars(config)
            
            logger.info(f"設定ファイル読み込み完了: {self.config_path}")
            return config
            
        except Exception as e:
            logger.error(f"設定ファイル読み込みエラー: {e}")
            return self._get_default_config()
            
    def _substitute_env_vars(self, config: Any) -> Any:
        """環境変数を置換"""
        if isinstance(config, dict):
            return {k: self._substitute_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._substitute_env_vars(item) for item in config]
        elif isinstance(config, str) and config.startswith('${') and config.endswith('}'):
            env_var = config[2:-1]
            return os.getenv(env_var, config)
        else:
            return config
            
    def _get_default_config(self) -> Dict[str, Any]:
        """デフォルト設定を返す"""
        return {
            "arbitrage": {
                "min_spread_threshold": 0.1,
                "conservative_threshold": 0.05,
                "aggressive_threshold": 0.2,
                "test_threshold": 0.5,
                "monitoring_duration": 30,
                "price_update_display_limit": 10,
                "arbitrage_display_limit": 5,
                "max_position_size": 10000,
                "min_profit_threshold": 10
            },
            "symbols": ["BTC", "ETH", "SOL"],
            "development_mode": True,
            "websocket": {
                "reconnect_delay": 5,
                "max_reconnect_attempts": 10,
                "ping_interval": 30
            },
            "logging": {
                "level": "INFO",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        設定値を取得（ドット記法対応）
        
        Args:
            key: 設定キー（例: "arbitrage.min_spread_threshold"）
            default: デフォルト値
            
        Returns:
            設定値
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_arbitrage_threshold(self, mode: str = "default") -> float:
        """
        アービトラージ閾値を取得
        
        Args:
            mode: 閾値モード ("default", "conservative", "aggressive", "test")
            
        Returns:
            閾値（パーセンテージ）
        """
        threshold_map = {
            "default": "arbitrage.min_spread_threshold",
            "conservative": "arbitrage.conservative_threshold", 
            "aggressive": "arbitrage.aggressive_threshold",
            "test": "arbitrage.test_threshold"
        }
        
        key = threshold_map.get(mode, "arbitrage.min_spread_threshold")
        return self.get(key, 0.1)
    
    def get_monitoring_symbols(self) -> list:
        """監視対象シンボルを取得"""
        symbols = self.get("symbols", ["BTC", "ETH", "SOL"])
        # "BTC/USDT" → "BTC" に変換
        return [symbol.split('/')[0] if '/' in symbol else symbol for symbol in symbols]
    
    def get_monitoring_duration(self) -> int:
        """監視時間を取得"""
        return self.get("arbitrage.monitoring_duration", 30)
    
    def get_display_limits(self) -> Dict[str, int]:
        """表示制限設定を取得"""
        return {
            "price_updates": self.get("arbitrage.price_update_display_limit", 10),
            "arbitrage_opportunities": self.get("arbitrage.arbitrage_display_limit", 5)
        }
    
    def is_development_mode(self) -> bool:
        """開発モードかどうか"""
        return self.get("development_mode", True)
    
    def reload(self):
        """設定ファイルを再読み込み"""
        self.config = self._load_config()
        logger.info("設定ファイルを再読み込みしました")


# グローバル設定インスタンス
_config_instance = None


def get_config() -> Config:
    """グローバル設定インスタンスを取得"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reload_config():
    """グローバル設定を再読み込み"""
    global _config_instance
    if _config_instance:
        _config_instance.reload()
    else:
        _config_instance = Config()


# 便利関数
def get_arbitrage_threshold(mode: str = "default") -> float:
    """アービトラージ閾値を取得"""
    return get_config().get_arbitrage_threshold(mode)


def get_monitoring_symbols() -> list:
    """監視対象シンボルを取得"""
    return get_config().get_monitoring_symbols()


def get_monitoring_duration() -> int:
    """監視時間を取得"""
    return get_config().get_monitoring_duration()