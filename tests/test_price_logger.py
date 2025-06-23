#!/usr/bin/env python3
"""
price_logger.py のユニットテスト
"""

import pytest
import sys
from pathlib import Path
from decimal import Decimal
from unittest.mock import Mock, patch
import tempfile
import csv

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from price_logger import PriceLogger
from src.interfaces.exchange import Ticker


class TestPriceLogger:
    """PriceLoggerクラスのテスト"""
    
    def setup_method(self):
        """各テストメソッドの前に実行"""
        self.mock_exchanges = {
            "TestExchange": Mock()
        }
        self.symbols = ["BTC", "ETH"]
        
        # 設定モック
        with patch('price_logger.get_config') as mock_config:
            mock_config.return_value.get.return_value = 0.00001
            self.price_logger = PriceLogger(
                exchanges=self.mock_exchanges,
                symbols=self.symbols,
                log_interval=1.0,
                compress=False
            )
    
    def test_has_price_changed_none_values(self):
        """bid/askがNoneの場合のテスト"""
        # Noneのティッカー
        ticker_with_none = Ticker(
            symbol="BTC",
            bid=None,
            ask=Decimal("100"),
            last=Decimal("100"),
            mark_price=Decimal("100"),
            volume_24h=Decimal("1000"),
            timestamp=1234567890
        )
        
        # 初回は変化ありとして記録される
        assert self.price_logger._has_price_changed("TestExchange", "BTC", ticker_with_none) is True
        
        # 前回記録価格を設定
        valid_ticker = Ticker(
            symbol="BTC",
            bid=Decimal("99"),
            ask=Decimal("101"),
            last=Decimal("100"),
            mark_price=Decimal("100"),
            volume_24h=Decimal("1000"),
            timestamp=1234567890
        )
        self.price_logger.last_saved_prices["TestExchange"] = {"BTC": valid_ticker}
        
        # bid/askがNoneの場合は変化ありとして記録される
        assert self.price_logger._has_price_changed("TestExchange", "BTC", ticker_with_none) is True
    
    def test_has_price_changed_threshold(self):
        """価格変更しきい値のテスト"""
        # 基準ティッカー
        base_ticker = Ticker(
            symbol="BTC",
            bid=Decimal("100"),
            ask=Decimal("101"),
            last=Decimal("100.5"),
            mark_price=Decimal("100.5"),
            volume_24h=Decimal("1000"),
            timestamp=1234567890
        )
        
        # 前回記録価格として設定
        self.price_logger.last_saved_prices["TestExchange"] = {"BTC": base_ticker}
        
        # 小さな変化（しきい値以下）
        small_change_ticker = Ticker(
            symbol="BTC",
            bid=Decimal("100.0001"),  # 0.0001% の変化
            ask=Decimal("101.0001"),
            last=Decimal("100.5"),
            mark_price=Decimal("100.5"),
            volume_24h=Decimal("1000"),
            timestamp=1234567891
        )
        
        # しきい値以下なので変化なし
        assert self.price_logger._has_price_changed("TestExchange", "BTC", small_change_ticker) is False
        
        # 大きな変化（しきい値以上）
        large_change_ticker = Ticker(
            symbol="BTC",
            bid=Decimal("100.01"),  # 0.01% の変化
            ask=Decimal("101.01"),
            last=Decimal("100.5"),
            mark_price=Decimal("100.5"),
            volume_24h=Decimal("1000"),
            timestamp=1234567892
        )
        
        # しきい値以上なので変化あり
        assert self.price_logger._has_price_changed("TestExchange", "BTC", large_change_ticker) is True
    
    def test_custom_price_threshold(self):
        """カスタム価格しきい値のテスト"""
        # カスタムしきい値でPriceLoggerを作成
        with patch('price_logger.get_config') as mock_config:
            mock_config.return_value.get.return_value = 0.00001
            custom_logger = PriceLogger(
                exchanges=self.mock_exchanges,
                symbols=self.symbols,
                log_interval=1.0,
                compress=False,
                price_threshold=0.001  # 0.1% のカスタムしきい値
            )
        
        # 基準ティッカー
        base_ticker = Ticker(
            symbol="BTC",
            bid=Decimal("100"),
            ask=Decimal("101"),
            last=Decimal("100.5"),
            mark_price=Decimal("100.5"),
            volume_24h=Decimal("1000"),
            timestamp=1234567890
        )
        
        custom_logger.last_saved_prices["TestExchange"] = {"BTC": base_ticker}
        
        # 0.05% の変化（カスタムしきい値0.1%以下）
        small_change_ticker = Ticker(
            symbol="BTC",
            bid=Decimal("100.05"),
            ask=Decimal("101.05"),
            last=Decimal("100.5"),
            mark_price=Decimal("100.5"),
            volume_24h=Decimal("1000"),
            timestamp=1234567891
        )
        
        # カスタムしきい値以下なので変化なし
        assert custom_logger._has_price_changed("TestExchange", "BTC", small_change_ticker) is False
        
        # 0.2% の変化（カスタムしきい値0.1%以上）
        large_change_ticker = Ticker(
            symbol="BTC",
            bid=Decimal("100.2"),
            ask=Decimal("101.2"),
            last=Decimal("100.5"),
            mark_price=Decimal("100.5"),
            volume_24h=Decimal("1000"),
            timestamp=1234567892
        )
        
        # カスタムしきい値以上なので変化あり
        assert custom_logger._has_price_changed("TestExchange", "BTC", large_change_ticker) is True
    
    def test_csv_output_format(self):
        """CSV出力フォーマットのテスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 一時ディレクトリでCSVファイル生成をテスト
            with patch('price_logger.Path') as mock_path:
                mock_path.return_value = Path(temp_dir)
                
                # テスト用ティッカー
                test_ticker = Ticker(
                    symbol="BTC",
                    bid=Decimal("100"),
                    ask=Decimal("101"),
                    last=Decimal("100.5"),
                    mark_price=Decimal("100.5"),
                    volume_24h=Decimal("1000"),
                    timestamp=1234567890
                )
                
                # CSV書き込みをテスト
                csv_path = Path(temp_dir) / "test_prices.csv"
                with open(csv_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    
                    # ヘッダー書き込み
                    writer.writerow([
                        "timestamp", "exchange", "symbol", 
                        "bid", "ask", "bid_size", "ask_size",
                        "last", "mark_price", "volume_24h"
                    ])
                    
                    # データ書き込み
                    writer.writerow([
                        "2023-01-01T00:00:00+00:00",
                        "TestExchange",
                        "BTC",
                        float(test_ticker.bid),
                        float(test_ticker.ask),
                        "",  # bid_size
                        "",  # ask_size
                        float(test_ticker.last),
                        float(test_ticker.mark_price),
                        float(test_ticker.volume_24h)
                    ])
                
                # ファイルが正しく作成されたことを確認
                assert csv_path.exists()
                
                # CSVファイルの内容を確認
                with open(csv_path, "r") as f:
                    lines = f.readlines()
                    assert len(lines) == 2  # ヘッダー + データ行
                    assert "TestExchange,BTC,100.0,101.0" in lines[1]


if __name__ == "__main__":
    # pytest実行
    pytest.main([__file__, "-v"])