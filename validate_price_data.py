#!/usr/bin/env python3
"""
validate_price_data.py
======================
価格データCSVファイルの品質確認と検証スクリプト

収集された価格データの以下を検証:
- データ形式の整合性
- タイムスタンプの連続性と同期
- 価格データの妥当性（bid <= ask等）
- 欠損データの特定
- アービトラージ機会の予備分析

使い方:
    python validate_price_data.py --date 20250623
    python validate_price_data.py --date 20250623 --detailed
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import logging
from typing import Dict, List, Tuple, Optional
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PriceDataValidator:
    """価格データの検証クラス"""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.exchanges = ["bybit", "hyperliquid", "gateio", "kucoin"]
        self.symbols = ["BTC", "ETH", "SOL", "XRP"]
        self.data_frames = {}
        
    def load_csv_files(self, date: str) -> Dict[str, pd.DataFrame]:
        """指定日のCSVファイルを読み込み"""
        logger.info(f"📂 {date}のCSVファイルを読み込み中...")
        
        date_dir = self.data_dir / date
        if not date_dir.exists():
            raise FileNotFoundError(f"データディレクトリが見つかりません: {date_dir}")
            
        for exchange in self.exchanges:
            csv_file = date_dir / f"{exchange}_prices_{date}.csv"
            
            if csv_file.exists():
                try:
                    df = pd.read_csv(csv_file)
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    self.data_frames[exchange] = df
                    logger.info(f"✅ {exchange}: {len(df)}行 読み込み完了")
                except Exception as e:
                    logger.error(f"❌ {exchange}: CSVファイル読み込みエラー - {e}")
            else:
                logger.warning(f"⚠️  {exchange}: CSVファイルが見つかりません")
                
        return self.data_frames
        
    def validate_data_format(self) -> Dict[str, Dict]:
        """データフォーマットの検証"""
        logger.info("🔍 データフォーマットを検証中...")
        
        required_columns = ['timestamp', 'exchange', 'symbol', 'bid', 'ask', 'last', 'mark_price']
        results = {}
        
        for exchange, df in self.data_frames.items():
            result = {
                'total_rows': len(df),
                'missing_columns': [],
                'data_types': {},
                'null_counts': {},
                'duplicate_rows': 0
            }
            
            # 必須カラムチェック
            for col in required_columns:
                if col not in df.columns:
                    result['missing_columns'].append(col)
                else:
                    result['data_types'][col] = str(df[col].dtype)
                    result['null_counts'][col] = df[col].isnull().sum()
            
            # 重複行チェック
            result['duplicate_rows'] = df.duplicated().sum()
            
            results[exchange] = result
            
        return results
        
    def validate_price_consistency(self) -> Dict[str, Dict]:
        """価格データの整合性検証"""
        logger.info("💰 価格データの整合性を検証中...")
        
        results = {}
        
        for exchange, df in self.data_frames.items():
            result = {
                'bid_ask_violations': 0,
                'zero_prices': 0,
                'negative_prices': 0,
                'extreme_spreads': 0,
                'price_ranges': {}
            }
            
            if 'bid' in df.columns and 'ask' in df.columns:
                # bid > ask の異常をチェック
                bid_ask_violations = (df['bid'] > df['ask']) & (df['ask'] > 0)
                result['bid_ask_violations'] = bid_ask_violations.sum()
                
                # ゼロ価格をチェック
                result['zero_prices'] = ((df['bid'] <= 0) | (df['ask'] <= 0)).sum()
                
                # 負の価格をチェック
                result['negative_prices'] = ((df['bid'] < 0) | (df['ask'] < 0)).sum()
                
                # 極端なスプレッドをチェック（5%以上）
                spread_pct = ((df['ask'] - df['bid']) / df['bid'] * 100)
                result['extreme_spreads'] = (spread_pct > 5.0).sum()
                
                # シンボル別価格レンジ
                for symbol in self.symbols:
                    symbol_data = df[df['symbol'] == symbol]
                    if len(symbol_data) > 0:
                        result['price_ranges'][symbol] = {
                            'bid_min': float(symbol_data['bid'].min()) if 'bid' in symbol_data.columns else None,
                            'bid_max': float(symbol_data['bid'].max()) if 'bid' in symbol_data.columns else None,
                            'ask_min': float(symbol_data['ask'].min()) if 'ask' in symbol_data.columns else None,
                            'ask_max': float(symbol_data['ask'].max()) if 'ask' in symbol_data.columns else None,
                            'count': len(symbol_data)
                        }
            
            results[exchange] = result
            
        return results
        
    def validate_timestamp_synchronization(self) -> Dict:
        """タイムスタンプの同期性検証"""
        logger.info("⏰ タイムスタンプの同期性を検証中...")
        
        if len(self.data_frames) < 2:
            return {"error": "同期検証には2つ以上の取引所データが必要"}
            
        # 全データの時間範囲を計算
        all_timestamps = []
        for df in self.data_frames.values():
            all_timestamps.extend(df['timestamp'].tolist())
            
        if not all_timestamps:
            return {"error": "タイムスタンプデータが見つかりません"}
            
        min_time = min(all_timestamps)
        max_time = max(all_timestamps)
        total_duration = (max_time - min_time).total_seconds()
        
        # 時間窓での同期チェック（1分窓）
        sync_windows = self._check_synchronization_windows()
        
        result = {
            'time_range': {
                'start': min_time.isoformat(),
                'end': max_time.isoformat(),
                'duration_seconds': total_duration,
                'duration_hours': total_duration / 3600
            },
            'exchange_coverage': {},
            'synchronization_windows': sync_windows
        }
        
        # 各取引所の時間カバレッジ
        for exchange, df in self.data_frames.items():
            if len(df) > 0:
                exchange_min = df['timestamp'].min()
                exchange_max = df['timestamp'].max()
                result['exchange_coverage'][exchange] = {
                    'start': exchange_min.isoformat(),
                    'end': exchange_max.isoformat(),
                    'data_points': len(df),
                    'coverage_ratio': (exchange_max - exchange_min).total_seconds() / total_duration if total_duration > 0 else 0
                }
        
        return result
        
    def _check_synchronization_windows(self, window_minutes: int = 1) -> Dict:
        """指定時間窓での同期チェック"""
        if len(self.data_frames) < 2:
            return {}
            
        # 最初の取引所をベースにする
        base_exchange = list(self.data_frames.keys())[0]
        base_df = self.data_frames[base_exchange]
        
        if len(base_df) == 0:
            return {}
            
        # 時間窓を作成
        start_time = base_df['timestamp'].min()
        end_time = base_df['timestamp'].max()
        windows = pd.date_range(start_time, end_time, freq=f'{window_minutes}T')
        
        sync_results = []
        
        for i in range(len(windows) - 1):
            window_start = windows[i]
            window_end = windows[i + 1]
            
            window_data = {}
            for exchange, df in self.data_frames.items():
                window_mask = (df['timestamp'] >= window_start) & (df['timestamp'] < window_end)
                window_data[exchange] = len(df[window_mask])
                
            sync_results.append({
                'window_start': window_start.isoformat(),
                'data_counts': window_data,
                'total_exchanges_with_data': sum(1 for count in window_data.values() if count > 0)
            })
            
        return {
            'window_minutes': window_minutes,
            'total_windows': len(sync_results),
            'windows': sync_results[:10]  # 最初の10個の窓のみ表示
        }
        
    def find_arbitrage_opportunities(self, min_spread_pct: float = 0.1) -> Dict:
        """アービトラージ機会の予備分析"""
        logger.info(f"📊 アービトラージ機会を分析中（最小スプレッド: {min_spread_pct}%）...")
        
        opportunities = []
        
        # 同一タイムスタンプでの価格比較
        for symbol in self.symbols:
            symbol_opportunities = self._find_symbol_arbitrage(symbol, min_spread_pct)
            opportunities.extend(symbol_opportunities)
            
        result = {
            'total_opportunities': len(opportunities),
            'opportunities_by_symbol': {},
            'best_opportunities': sorted(opportunities, key=lambda x: x['spread_pct'], reverse=True)[:10]
        }
        
        # シンボル別集計
        for symbol in self.symbols:
            symbol_opps = [opp for opp in opportunities if opp['symbol'] == symbol]
            result['opportunities_by_symbol'][symbol] = {
                'count': len(symbol_opps),
                'avg_spread': np.mean([opp['spread_pct'] for opp in symbol_opps]) if symbol_opps else 0,
                'max_spread': max([opp['spread_pct'] for opp in symbol_opps]) if symbol_opps else 0
            }
            
        return result
        
    def _find_symbol_arbitrage(self, symbol: str, min_spread_pct: float) -> List[Dict]:
        """特定シンボルのアービトラージ機会を検索"""
        opportunities = []
        
        # 各時点での価格を取得
        all_prices = []
        
        for exchange, df in self.data_frames.items():
            symbol_data = df[df['symbol'] == symbol].copy()
            if len(symbol_data) > 0:
                symbol_data['exchange'] = exchange
                all_prices.append(symbol_data[['timestamp', 'exchange', 'bid', 'ask']])
                
        if len(all_prices) < 2:
            return opportunities
            
        # 時間範囲を30秒の窓で区切って分析
        all_data = pd.concat(all_prices, ignore_index=True)
        all_data = all_data.sort_values('timestamp')
        
        # 30秒窓でグループ化
        all_data['time_window'] = all_data['timestamp'].dt.floor('30S')
        
        for window, window_data in all_data.groupby('time_window'):
            if len(window_data) < 2:
                continue
                
            # 最高bid と最低ask を見つける
            max_bid_row = window_data.loc[window_data['bid'].idxmax()]
            min_ask_row = window_data.loc[window_data['ask'].idxmin()]
            
            if max_bid_row['exchange'] != min_ask_row['exchange']:
                spread = max_bid_row['bid'] - min_ask_row['ask']
                spread_pct = (spread / min_ask_row['ask']) * 100
                
                if spread_pct >= min_spread_pct:
                    opportunities.append({
                        'timestamp': window.isoformat(),
                        'symbol': symbol,
                        'buy_exchange': min_ask_row['exchange'],
                        'sell_exchange': max_bid_row['exchange'],
                        'buy_price': float(min_ask_row['ask']),
                        'sell_price': float(max_bid_row['bid']),
                        'spread': float(spread),
                        'spread_pct': float(spread_pct)
                    })
                    
        return opportunities
        
    def generate_report(self, detailed: bool = False) -> str:
        """検証結果のレポート生成"""
        logger.info("📋 検証レポートを生成中...")
        
        # 各検証を実行
        format_results = self.validate_data_format()
        price_results = self.validate_price_consistency() 
        timestamp_results = self.validate_timestamp_synchronization()
        arbitrage_results = self.find_arbitrage_opportunities()
        
        report_lines = [
            "=" * 80,
            "📊 PRICE DATA VALIDATION REPORT",
            "=" * 80,
            f"生成時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"対象取引所: {', '.join(self.data_frames.keys())}",
            ""
        ]
        
        # データフォーマット結果
        report_lines.extend([
            "📋 1. データフォーマット検証",
            "-" * 40
        ])
        
        for exchange, result in format_results.items():
            status = "✅" if not result['missing_columns'] and result['duplicate_rows'] == 0 else "⚠️"
            report_lines.extend([
                f"{status} {exchange.upper()}:",
                f"  総行数: {result['total_rows']:,}",
                f"  重複行: {result['duplicate_rows']}",
                f"  欠損カラム: {result['missing_columns'] if result['missing_columns'] else 'なし'}"
            ])
            
            if detailed and result['null_counts']:
                report_lines.append("  NULL値:")
                for col, count in result['null_counts'].items():
                    if count > 0:
                        report_lines.append(f"    {col}: {count}")
        
        report_lines.append("")
        
        # 価格整合性結果
        report_lines.extend([
            "💰 2. 価格データ整合性",
            "-" * 40
        ])
        
        for exchange, result in price_results.items():
            issues = result['bid_ask_violations'] + result['zero_prices'] + result['negative_prices']
            status = "✅" if issues == 0 else "⚠️" if issues < 10 else "❌"
            
            report_lines.extend([
                f"{status} {exchange.upper()}:",
                f"  bid > ask 違反: {result['bid_ask_violations']}",
                f"  ゼロ価格: {result['zero_prices']}",
                f"  負の価格: {result['negative_prices']}",
                f"  極端スプレッド(>5%): {result['extreme_spreads']}"
            ])
            
            if detailed and result['price_ranges']:
                report_lines.append("  価格レンジ:")
                for symbol, ranges in result['price_ranges'].items():
                    if ranges['count'] > 0:
                        report_lines.append(f"    {symbol}: BTC {ranges['bid_min']:.2f}-{ranges['bid_max']:.2f} ({ranges['count']}件)")
        
        report_lines.append("")
        
        # タイムスタンプ同期結果
        if 'error' not in timestamp_results:
            report_lines.extend([
                "⏰ 3. タイムスタンプ同期性",
                "-" * 40,
                f"データ期間: {timestamp_results['time_range']['duration_hours']:.1f}時間",
                f"開始時刻: {timestamp_results['time_range']['start']}",
                f"終了時刻: {timestamp_results['time_range']['end']}",
                ""
            ])
            
            for exchange, coverage in timestamp_results['exchange_coverage'].items():
                report_lines.append(f"📊 {exchange.upper()}: {coverage['data_points']:,}点 (カバー率: {coverage['coverage_ratio']*100:.1f}%)")
        
        report_lines.append("")
        
        # アービトラージ機会結果
        report_lines.extend([
            "🎯 4. アービトラージ機会分析",
            "-" * 40,
            f"発見された機会: {arbitrage_results['total_opportunities']}件",
            ""
        ])
        
        for symbol, stats in arbitrage_results['opportunities_by_symbol'].items():
            if stats['count'] > 0:
                report_lines.append(f"💎 {symbol}: {stats['count']}件 (平均スプレッド: {stats['avg_spread']:.3f}%, 最大: {stats['max_spread']:.3f}%)")
        
        if detailed and arbitrage_results['best_opportunities']:
            report_lines.extend([
                "",
                "🏆 上位アービトラージ機会:"
            ])
            for i, opp in enumerate(arbitrage_results['best_opportunities'][:5], 1):
                report_lines.append(
                    f"  {i}. {opp['symbol']}: {opp['spread_pct']:.3f}% "
                    f"({opp['sell_exchange']} ${opp['sell_price']:.2f} → {opp['buy_exchange']} ${opp['buy_price']:.2f})"
                )
        
        report_lines.extend([
            "",
            "=" * 80
        ])
        
        return "\n".join(report_lines)


def main():
    parser = argparse.ArgumentParser(description="価格データCSVファイルの品質検証")
    parser.add_argument("--date", required=True, help="検証する日付 (例: 20250623)")
    parser.add_argument("--data-dir", default="data/price_logs", help="データディレクトリパス")
    parser.add_argument("--detailed", action="store_true", help="詳細レポートを生成")
    parser.add_argument("--output", help="レポート出力ファイル")
    
    args = parser.parse_args()
    
    try:
        validator = PriceDataValidator(args.data_dir)
        validator.load_csv_files(args.date)
        
        if not validator.data_frames:
            logger.error("❌ データファイルが見つかりませんでした")
            return 1
            
        report = validator.generate_report(detailed=args.detailed)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"📄 レポートを保存しました: {args.output}")
        else:
            print(report)
            
        return 0
        
    except Exception as e:
        logger.error(f"❌ 検証中にエラーが発生しました: {e}")
        return 1


if __name__ == "__main__":
    exit(main())