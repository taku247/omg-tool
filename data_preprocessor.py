#!/usr/bin/env python3
"""
data_preprocessor.py
====================
不規則時系列データの変換・前処理スクリプト

閾値ベースで記録された価格データを、バックテスト用に
時間同期された規則的なデータセットに変換します。

主な機能:
- 時間窓ベースのデータ集約
- 欠損データの補間処理
- 取引所間の価格データ同期
- バックテスト用データセットの出力

使い方:
    python data_preprocessor.py --date 20250623 --window 30s
    python data_preprocessor.py --date 20250623 --window 1min --interpolate
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import logging
from typing import Dict, List, Optional, Tuple
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DataPreprocessor:
    """価格データの前処理クラス"""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.exchanges = ["bybit", "hyperliquid", "gateio", "kucoin"]
        self.symbols = ["BTC", "ETH", "SOL", "XRP"]
        self.raw_data = {}
        self.processed_data = {}
        
    def load_data(self, date: str) -> Dict[str, pd.DataFrame]:
        """指定日の生データを読み込み"""
        logger.info(f"📂 {date}の価格データを読み込み中...")
        
        date_dir = self.data_dir / date
        if not date_dir.exists():
            raise FileNotFoundError(f"データディレクトリが見つかりません: {date_dir}")
            
        for exchange in self.exchanges:
            csv_file = date_dir / f"{exchange}_prices_{date}.csv"
            
            if csv_file.exists():
                try:
                    df = pd.read_csv(csv_file)
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    
                    # データクリーニング
                    df = self._clean_data(df, exchange)
                    
                    if len(df) > 0:
                        self.raw_data[exchange] = df
                        logger.info(f"✅ {exchange}: {len(df)}行 読み込み完了")
                    else:
                        logger.warning(f"⚠️ {exchange}: クリーニング後にデータが空になりました")
                        
                except Exception as e:
                    logger.error(f"❌ {exchange}: データ読み込みエラー - {e}")
            else:
                logger.warning(f"⚠️ {exchange}: CSVファイルが見つかりません")
                
        logger.info(f"📊 読み込み完了: {len(self.raw_data)}取引所")
        return self.raw_data
        
    def _clean_data(self, df: pd.DataFrame, exchange: str) -> pd.DataFrame:
        """データクリーニング"""
        original_len = len(df)
        
        # 必須カラムの存在確認
        required_cols = ['timestamp', 'symbol', 'bid', 'ask']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"⚠️ {exchange}: 必須カラムが不足 - {missing_cols}")
            return pd.DataFrame()
            
        # 無効なデータを除去
        mask = (
            df['bid'].notna() & df['ask'].notna() &
            (df['bid'] > 0) & (df['ask'] > 0) &
            (df['bid'] <= df['ask'])  # bid > ask の異常データを除去
        )
        
        df_clean = df[mask].copy()
        
        # 重複データを除去 (同一タイムスタンプ・シンボル)
        df_clean = df_clean.drop_duplicates(subset=['timestamp', 'symbol'], keep='first')
        
        removed = original_len - len(df_clean)
        if removed > 0:
            logger.info(f"🧹 {exchange}: {removed}行の異常データを除去")
            
        return df_clean
        
    def create_time_windows(self, window_size: str = "30s", 
                          start_time: Optional[datetime] = None, 
                          end_time: Optional[datetime] = None) -> pd.DatetimeIndex:
        """時間窓の作成"""
        if not self.raw_data:
            raise ValueError("データが読み込まれていません")
            
        # 全取引所の時間範囲を取得
        all_timestamps = []
        for df in self.raw_data.values():
            all_timestamps.extend(df['timestamp'].tolist())
            
        if not all_timestamps:
            raise ValueError("タイムスタンプデータが見つかりません")
            
        data_start = start_time or min(all_timestamps)
        data_end = end_time or max(all_timestamps)
        
        # 時間窓を作成
        time_windows = pd.date_range(
            start=data_start.floor(window_size),
            end=data_end.ceil(window_size),
            freq=window_size
        )
        
        logger.info(f"⏰ 時間窓作成: {len(time_windows)}個 ({window_size}間隔)")
        logger.info(f"📅 期間: {data_start} ～ {data_end}")
        
        return time_windows
        
    def aggregate_data(self, window_size: str = "30s", 
                      method: str = "last") -> Dict[str, pd.DataFrame]:
        """時間窓でのデータ集約"""
        logger.info(f"📊 データ集約中: {window_size}窓, {method}方式...")
        
        time_windows = self.create_time_windows(window_size)
        
        for exchange, df in self.raw_data.items():
            aggregated_data = []
            
            for symbol in self.symbols:
                symbol_data = df[df['symbol'] == symbol].copy()
                if len(symbol_data) == 0:
                    continue
                    
                # タイムスタンプでソート
                symbol_data = symbol_data.sort_values('timestamp')
                
                # 各時間窓でのデータ集約
                window_data = []
                for i in range(len(time_windows) - 1):
                    window_start = time_windows[i]
                    window_end = time_windows[i + 1]
                    
                    # 該当時間窓のデータを抽出
                    mask = (symbol_data['timestamp'] >= window_start) & \
                           (symbol_data['timestamp'] < window_end)
                    window_df = symbol_data[mask]
                    
                    if len(window_df) > 0:
                        # 集約方法に応じてデータを処理
                        if method == "last":
                            aggregated = window_df.iloc[-1].copy()
                        elif method == "mean":
                            aggregated = window_df.select_dtypes(include=[np.number]).mean()
                            aggregated['symbol'] = symbol
                            aggregated['exchange'] = exchange
                        elif method == "ohlc":
                            # OHLC形式での集約
                            ohlc_data = {
                                'open_bid': window_df['bid'].iloc[0],
                                'high_bid': window_df['bid'].max(),
                                'low_bid': window_df['bid'].min(),
                                'close_bid': window_df['bid'].iloc[-1],
                                'open_ask': window_df['ask'].iloc[0],
                                'high_ask': window_df['ask'].max(),
                                'low_ask': window_df['ask'].min(),
                                'close_ask': window_df['ask'].iloc[-1],
                                'volume': window_df['volume_24h'].sum() if 'volume_24h' in window_df.columns else 0,
                                'symbol': symbol,
                                'exchange': exchange
                            }
                            aggregated = pd.Series(ohlc_data)
                        else:
                            aggregated = window_df.iloc[-1].copy()
                            
                        aggregated['timestamp'] = window_start
                        window_data.append(aggregated)
                        
                if window_data:
                    symbol_aggregated = pd.DataFrame(window_data)
                    aggregated_data.append(symbol_aggregated)
                    
            if aggregated_data:
                self.processed_data[exchange] = pd.concat(aggregated_data, ignore_index=True)
                logger.info(f"✅ {exchange}: {len(self.processed_data[exchange])}行に集約")
            else:
                logger.warning(f"⚠️ {exchange}: 集約後にデータが空になりました")
                
        return self.processed_data
        
    def interpolate_missing_data(self, method: str = "forward_fill") -> Dict[str, pd.DataFrame]:
        """欠損データの補間"""
        logger.info(f"🔧 欠損データ補間中: {method}方式...")
        
        for exchange, df in self.processed_data.items():
            original_len = len(df)
            
            if method == "forward_fill":
                # 前値埋め
                df = df.sort_values(['symbol', 'timestamp'])
                df[['bid', 'ask', 'last']] = df.groupby('symbol')[['bid', 'ask', 'last']].fillna(method='ffill')
                
            elif method == "linear":
                # 線形補間
                df = df.sort_values(['symbol', 'timestamp'])
                for symbol in self.symbols:
                    mask = df['symbol'] == symbol
                    df.loc[mask, ['bid', 'ask', 'last']] = \
                        df.loc[mask, ['bid', 'ask', 'last']].interpolate(method='linear')
                        
            elif method == "spline":
                # スプライン補間
                df = df.sort_values(['symbol', 'timestamp'])
                for symbol in self.symbols:
                    mask = df['symbol'] == symbol
                    symbol_data = df.loc[mask, ['bid', 'ask', 'last']]
                    if len(symbol_data) >= 4:  # スプライン補間には最低4点必要
                        df.loc[mask, ['bid', 'ask', 'last']] = \
                            symbol_data.interpolate(method='spline', order=3)
                            
            # 残った欠損値を前値埋めで処理
            df[['bid', 'ask', 'last']] = df.groupby('symbol')[['bid', 'ask', 'last']].fillna(method='ffill')
            
            self.processed_data[exchange] = df
            
            filled_count = original_len - len(df.dropna(subset=['bid', 'ask']))
            if filled_count > 0:
                logger.info(f"🔧 {exchange}: {filled_count}箇所の欠損データを補間")
                
        return self.processed_data
        
    def create_synchronized_dataset(self) -> pd.DataFrame:
        """取引所間で同期されたデータセットを作成"""
        logger.info("🔄 取引所間データ同期中...")
        
        if not self.processed_data:
            raise ValueError("処理済みデータがありません")
            
        synchronized_data = []
        
        # 共通の時間窓を取得
        all_timestamps = set()
        for df in self.processed_data.values():
            all_timestamps.update(df['timestamp'].dt.floor('30S').unique())
            
        common_timestamps = sorted(all_timestamps)
        
        for timestamp in common_timestamps:
            timestamp_data = {'timestamp': timestamp}
            
            # 各取引所・シンボルの価格を収集
            for exchange, df in self.processed_data.items():
                exchange_data = df[df['timestamp'].dt.floor('30S') == timestamp]
                
                for symbol in self.symbols:
                    symbol_data = exchange_data[exchange_data['symbol'] == symbol]
                    
                    if len(symbol_data) > 0:
                        latest = symbol_data.iloc[-1]
                        timestamp_data[f"{exchange}_{symbol}_bid"] = latest['bid']
                        timestamp_data[f"{exchange}_{symbol}_ask"] = latest['ask']
                        if 'last' in latest and pd.notna(latest['last']):
                            timestamp_data[f"{exchange}_{symbol}_last"] = latest['last']
                            
            # データが十分にある時間窓のみ追加
            price_columns = [k for k in timestamp_data.keys() if k.endswith(('_bid', '_ask'))]
            if len(price_columns) >= 8:  # 最低4シンボル×2価格
                synchronized_data.append(timestamp_data)
                
        if synchronized_data:
            sync_df = pd.DataFrame(synchronized_data)
            logger.info(f"✅ 同期データセット作成完了: {len(sync_df)}行")
            return sync_df
        else:
            raise ValueError("同期可能なデータが不足しています")
            
    def save_processed_data(self, output_dir: str, date: str, 
                          save_individual: bool = True, 
                          save_synchronized: bool = True) -> List[Path]:
        """処理済みデータを保存"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        saved_files = []
        
        # 個別取引所データを保存
        if save_individual and self.processed_data:
            for exchange, df in self.processed_data.items():
                file_path = output_path / f"{exchange}_processed_{date}.csv"
                df.to_csv(file_path, index=False)
                saved_files.append(file_path)
                logger.info(f"💾 {exchange}データ保存: {file_path}")
                
        # 同期データセットを保存
        if save_synchronized:
            try:
                sync_df = self.create_synchronized_dataset()
                sync_path = output_path / f"synchronized_prices_{date}.csv"
                sync_df.to_csv(sync_path, index=False)
                saved_files.append(sync_path)
                logger.info(f"💾 同期データセット保存: {sync_path}")
            except ValueError as e:
                logger.warning(f"⚠️ 同期データセット作成失敗: {e}")
                
        return saved_files
        
    def generate_preprocessing_report(self) -> str:
        """前処理レポートを生成"""
        if not self.raw_data and not self.processed_data:
            return "データが読み込まれていません"
            
        report_lines = [
            "=" * 80,
            "📊 DATA PREPROCESSING REPORT",
            "=" * 80,
            f"処理時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]
        
        # 生データ統計
        if self.raw_data:
            report_lines.extend([
                "📂 生データ統計:",
                "-" * 40
            ])
            
            total_raw = 0
            for exchange, df in self.raw_data.items():
                total_raw += len(df)
                report_lines.append(f"  {exchange}: {len(df):,}行")
                
            report_lines.extend([
                f"  合計: {total_raw:,}行",
                ""
            ])
            
        # 処理済みデータ統計
        if self.processed_data:
            report_lines.extend([
                "🔧 処理済みデータ統計:",
                "-" * 40
            ])
            
            total_processed = 0
            for exchange, df in self.processed_data.items():
                total_processed += len(df)
                # データ期間を計算
                if len(df) > 0:
                    start_time = df['timestamp'].min()
                    end_time = df['timestamp'].max()
                    duration = (end_time - start_time).total_seconds() / 3600
                    report_lines.extend([
                        f"  {exchange}: {len(df):,}行",
                        f"    期間: {start_time} ～ {end_time}",
                        f"    時間: {duration:.1f}時間"
                    ])
                else:
                    report_lines.append(f"  {exchange}: データなし")
                    
            report_lines.extend([
                f"  合計: {total_processed:,}行",
                ""
            ])
            
            # データ品質統計
            report_lines.extend([
                "📈 データ品質:",
                "-" * 40
            ])
            
            for exchange, df in self.processed_data.items():
                if len(df) > 0:
                    # 各シンボルのデータ点数
                    symbol_counts = df['symbol'].value_counts()
                    missing_data = df[['bid', 'ask']].isna().sum().sum()
                    
                    report_lines.append(f"  {exchange}:")
                    for symbol, count in symbol_counts.items():
                        report_lines.append(f"    {symbol}: {count}点")
                    report_lines.append(f"    欠損データ: {missing_data}箇所")
                    
        report_lines.extend([
            "",
            "=" * 80
        ])
        
        return "\n".join(report_lines)


def main():
    parser = argparse.ArgumentParser(description="価格データの前処理とバックテスト用データセット作成")
    parser.add_argument("--date", required=True, help="処理する日付 (例: 20250623)")
    parser.add_argument("--data-dir", default="data/price_logs", help="入力データディレクトリ")
    parser.add_argument("--output-dir", default="data/processed", help="出力ディレクトリ")
    parser.add_argument("--window", default="30s", help="時間窓サイズ (例: 30s, 1min, 5min)")
    parser.add_argument("--method", default="last", 
                       choices=["last", "mean", "ohlc"], 
                       help="集約方法")
    parser.add_argument("--interpolate", action="store_true", 
                       help="欠損データの補間を実行")
    parser.add_argument("--interpolate-method", default="forward_fill",
                       choices=["forward_fill", "linear", "spline"],
                       help="補間方法")
    parser.add_argument("--report", help="レポート出力ファイル")
    
    args = parser.parse_args()
    
    try:
        preprocessor = DataPreprocessor(args.data_dir)
        
        # データ読み込み
        preprocessor.load_data(args.date)
        
        if not preprocessor.raw_data:
            logger.error("❌ データファイルが見つかりませんでした")
            return 1
            
        # データ集約
        preprocessor.aggregate_data(args.window, args.method)
        
        # 補間処理
        if args.interpolate:
            preprocessor.interpolate_missing_data(args.interpolate_method)
            
        # データ保存
        saved_files = preprocessor.save_processed_data(
            args.output_dir, args.date, 
            save_individual=True, 
            save_synchronized=True
        )
        
        # レポート生成
        report = preprocessor.generate_preprocessing_report()
        
        if args.report:
            with open(args.report, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"📄 レポートを保存しました: {args.report}")
        else:
            print(report)
            
        logger.info(f"✅ 前処理完了: {len(saved_files)}ファイル保存")
        for file_path in saved_files:
            logger.info(f"📁 {file_path}")
            
        return 0
        
    except Exception as e:
        logger.error(f"❌ 前処理中にエラーが発生しました: {e}")
        return 1


if __name__ == "__main__":
    exit(main())