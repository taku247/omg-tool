#!/usr/bin/env python3
"""
backtest_engine.py
==================
過去に記録したCSV価格ログを読み込み、既存の `ArbitrageDetector` ロジックを用いて
"仮想両建てトレード"をシミュレートするバックテストエンジン。

主要仕様
--------
* **入力**: `data/price_logs/YYYYMMDD/<exchange>_prices_YYYYMMDD.csv(.gz)`
  - price_logger.py が生成したフォーマットに準拠。
* **対象期間**: CLI の `--start YYYY-MM-DD --end YYYY-MM-DD` で指定。
* **対象銘柄**: `--symbols` オプション、デフォルトは `BTC ETH`。
* **仮想ポジションルール**:
  1. `ArbitrageDetector.check_arbitrage()` でチャンス検出時に **両建てエントリー**。
  2. 乖離が `exit_threshold` 未満になったら **同ロットで決済**。
* **手数料/スリッページ** は簡易モデルで控除 (config or CLI)。
* **出力**:
  - `backtest_trades.csv`  … 個別トレード履歴
  - 終了時にコンソールで統計 (勝率, 平均利幅, 最大DD, 年率換算) を表示
"""

import argparse
import gzip
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal

import pandas as pd

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.arbitrage_detector import ArbitrageDetector, ArbitrageOpportunity
from src.interfaces.exchange import Ticker
from src.core.config import get_config

# ──────────────────────────────────────────────────────────────
# ヘルパ
# ──────────────────────────────────────────────────────────────

def load_csv(path: Path) -> pd.DataFrame:
    """price_logger が出力した CSV / GZ を読み込む"""
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as f:
                df = pd.read_csv(f)
        else:
            df = pd.read_csv(path)
        
        # 文字列 → datetime へ
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        
        # 価格データの型変換
        numeric_cols = ["bid", "ask", "last", "mark_price", "volume_24h"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        return df
    except Exception as e:
        print(f"⚠️ ファイル読み込みエラー {path}: {e}")
        return pd.DataFrame()


def read_logs(start: datetime, end: datetime, symbols: List[str], use_synchronized: bool = True) -> pd.DataFrame:
    """指定期間のCSVを読み込む（同期データまたは個別データ）"""
    if use_synchronized:
        return read_synchronized_logs(start, end, symbols)
    else:
        return read_individual_logs(start, end, symbols)


def read_synchronized_logs(start: datetime, end: datetime, symbols: List[str]) -> pd.DataFrame:
    """同期データセットを読み込む"""
    frames: List[pd.DataFrame] = []
    day = start.date()
    
    print(f"📅 読み込み期間: {start.date()} 〜 {end.date()} (同期データセット)")
    
    while day <= end.date():
        day_str = day.strftime("%Y%m%d")
        sync_file = PROJECT_ROOT / "data" / "processed" / f"synchronized_prices_{day_str}.csv"
        
        if sync_file.exists():
            df = load_csv(sync_file)
            if not df.empty:
                frames.append(df)
        else:
            print(f"⚠️ 同期データファイルが見つかりません: {sync_file}")
                        
        day += timedelta(days=1)
    
    if not frames:
        raise FileNotFoundError(f"期間内に同期データファイルが見つかりませんでした: {start.date()} - {end.date()}")
    
    # 全てのフレームを結合し、時系列順にソート
    combined_df = pd.concat(frames, ignore_index=True)
    combined_df = combined_df.sort_values("timestamp").reset_index(drop=True)
    
    # 同期データを個別レコード形式に変換
    converted_df = convert_synchronized_to_individual(combined_df, symbols)
    
    print(f"✅ {len(converted_df):,}レコード読み込み完了 (同期データセット)")
    print(f"📊 取引所: {sorted(converted_df['exchange'].unique())}")
    print(f"📊 シンボル: {sorted(converted_df['symbol'].unique())}")
    
    return converted_df


def read_individual_logs(start: datetime, end: datetime, symbols: List[str]) -> pd.DataFrame:
    """個別CSVファイルを読み込む（従来の方法）"""
    frames: List[pd.DataFrame] = []
    day = start.date()
    
    print(f"📅 読み込み期間: {start.date()} 〜 {end.date()} (個別ファイル)")
    
    while day <= end.date():
        day_str = day.strftime("%Y%m%d")
        day_dir = PROJECT_ROOT / "data" / "price_logs" / day_str
        
        if day_dir.exists():
            for file_path in day_dir.glob("*_prices_*.csv*"):
                df = load_csv(file_path)
                if not df.empty:
                    # 指定シンボルのみフィルタ
                    df = df[df["symbol"].isin(symbols)]
                    if not df.empty:
                        frames.append(df)
                        
        day += timedelta(days=1)
    
    if not frames:
        raise FileNotFoundError(f"期間内にログファイルが見つかりませんでした: {start.date()} - {end.date()}")
    
    # 全てのフレームを結合し、時系列順にソート
    combined_df = pd.concat(frames, ignore_index=True)
    combined_df = combined_df.sort_values("timestamp").reset_index(drop=True)
    
    print(f"✅ {len(combined_df):,}レコード読み込み完了")
    print(f"📊 取引所: {sorted(combined_df['exchange'].unique())}")
    print(f"📊 シンボル: {sorted(combined_df['symbol'].unique())}")
    
    return combined_df


def convert_synchronized_to_individual(sync_df: pd.DataFrame, symbols: List[str]) -> pd.DataFrame:
    """同期データを個別レコード形式に変換"""
    records = []
    exchanges = ["bybit", "hyperliquid", "gateio", "kucoin"]
    
    for _, row in sync_df.iterrows():
        timestamp = row["timestamp"]
        
        for exchange in exchanges:
            for symbol in symbols:
                bid_col = f"{exchange}_{symbol}_bid"
                ask_col = f"{exchange}_{symbol}_ask"
                last_col = f"{exchange}_{symbol}_last"
                
                if bid_col in row and ask_col in row:
                    bid_val = row[bid_col]
                    ask_val = row[ask_col]
                    last_val = row[last_col] if last_col in row else None
                    
                    # 有効な価格データがある場合のみレコード追加
                    if pd.notna(bid_val) and pd.notna(ask_val) and bid_val > 0 and ask_val > 0:
                        records.append({
                            "timestamp": timestamp,
                            "exchange": exchange.title(),  # 大文字にして統一
                            "symbol": symbol,
                            "bid": bid_val,
                            "ask": ask_val,
                            "last": last_val if pd.notna(last_val) else None,
                            "mark_price": None,
                            "volume_24h": 0
                        })
    
    return pd.DataFrame(records)


def csv_row_to_ticker(row: pd.Series) -> Ticker:
    """CSV行データをTickerオブジェクトに変換"""
    return Ticker(
        symbol=row["symbol"],
        bid=Decimal(str(row["bid"])) if pd.notna(row["bid"]) else None,
        ask=Decimal(str(row["ask"])) if pd.notna(row["ask"]) else None,
        last=Decimal(str(row["last"])) if pd.notna(row["last"]) else None,
        mark_price=Decimal(str(row["mark_price"])) if pd.notna(row["mark_price"]) else None,
        volume_24h=Decimal(str(row["volume_24h"])) if pd.notna(row["volume_24h"]) else Decimal("0"),
        timestamp=int(row["timestamp"].timestamp()) if pd.notna(row["timestamp"]) else 0
    )

# ──────────────────────────────────────────────────────────────
# バックテストコア
# ──────────────────────────────────────────────────────────────

class BacktestEngine:
    """バックテストエンジン"""
    
    def __init__(self, 
                 detector_config: Dict[str, Any],
                 fee_rate: float = 0.0004,
                 slippage: float = 0.0003,
                 exit_threshold: float = 0.1):
        """
        Args:
            detector_config: ArbitrageDetectorの設定
            fee_rate: 片道手数料率
            slippage: スリッページ率
            exit_threshold: 決済閾値(%)
        """
        self.detector = ArbitrageDetector(**detector_config)
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.exit_threshold = exit_threshold
        
        # ポジション管理
        self.open_positions: Dict[str, Dict[str, Any]] = {}  # {symbol: position_info}
        self.closed_trades: List[Dict[str, Any]] = []
        
    async def run_backtest(self, df: pd.DataFrame) -> pd.DataFrame:
        """バックテストを実行"""
        print(f"⚙️ バックテスト実行開始 ({len(df):,}レコード)")
        print(f"📈 最小スプレッド閾値: {float(self.detector.min_spread_threshold):.2f}%")
        print(f"💰 決済閾値: {self.exit_threshold:.2f}%")
        print(f"💸 手数料: {self.fee_rate:.4f}% (片道)")
        print(f"⚡ スリッページ: {self.slippage:.4f}%")
        
        total_rows = len(df)
        processed = 0
        
        for _, row in df.iterrows():
            processed += 1
            
            # 進捗表示
            if processed % 10000 == 0:
                progress = (processed / total_rows) * 100
                print(f"🔄 進捗: {processed:,}/{total_rows:,} ({progress:.1f}%)")
            
            # TickerオブジェクトにParse
            ticker = csv_row_to_ticker(row)
            
            # bid/askがNoneの場合はスキップ
            if ticker.bid is None or ticker.ask is None:
                continue
            
            # ArbitrageDetectorに価格を送信
            await self.detector.update_price(row["exchange"], ticker)
            
            # アービトラージチャンスをチェック
            opportunities = await self.detector.check_arbitrage(ticker.symbol)
            
            # 新しいポジションのエントリー
            for opp in opportunities:
                await self._try_enter_position(opp, row["timestamp"])
            
            # 既存ポジションの決済チェック
            await self._check_exit_positions(ticker.symbol, row["timestamp"])
        
        # 未決済ポジションを強制決済
        await self._force_close_all_positions(df.iloc[-1]["timestamp"])
        
        print(f"✅ バックテスト完了: {len(self.closed_trades)}件のトレード")
        
        return pd.DataFrame(self.closed_trades)
    
    async def _try_enter_position(self, opportunity: ArbitrageOpportunity, timestamp: pd.Timestamp):
        """ポジションエントリーを試行"""
        symbol = opportunity.symbol
        
        # 既に同じシンボルでポジションを持っている場合はスキップ
        if symbol in self.open_positions:
            return
        
        # エントリー時の実際の実行価格を取得
        symbol_prices = self.detector.price_cache.get(symbol, {})
        buy_exchange_ticker = symbol_prices.get(opportunity.buy_exchange)
        sell_exchange_ticker = symbol_prices.get(opportunity.sell_exchange)
        
        if not buy_exchange_ticker or not sell_exchange_ticker:
            return
        
        # 実際の執行価格（手数料・スリッページ考慮）
        entry_buy_price = float(buy_exchange_ticker.ask) * (1 + self.slippage)  # askで買い + スリッページ
        entry_sell_price = float(sell_exchange_ticker.bid) * (1 - self.slippage)  # bidで売り - スリッページ
        
        # ポジション情報を記録
        position = {
            "symbol": symbol,
            "entry_time": timestamp,
            "entry_spread": float(opportunity.spread_percentage),
            "buy_exchange": opportunity.buy_exchange,
            "sell_exchange": opportunity.sell_exchange,
            "entry_buy_price": entry_buy_price,    # 実際の買い執行価格
            "entry_sell_price": entry_sell_price,  # 実際の売り執行価格
            "opportunity_id": opportunity.id,
            "max_adverse_spread": float(opportunity.spread_percentage)  # 最大逆行スプレッドを追跡
        }
        
        self.open_positions[symbol] = position
        print(f"📊 エントリー: {opportunity.id} | {symbol} | "
              f"{opportunity.buy_exchange}→{opportunity.sell_exchange} | "
              f"スプレッド: {opportunity.spread_percentage:.3f}% | "
              f"買い価格: {entry_buy_price:.4f} | 売り価格: {entry_sell_price:.4f}")
    
    async def _check_exit_positions(self, symbol: str, timestamp: pd.Timestamp):
        """ポジション決済をチェック"""
        if symbol not in self.open_positions:
            return
        
        position = self.open_positions[symbol]
        
        # 現在のスプレッドを計算
        current_spread = self._compute_current_spread(
            symbol, 
            position["buy_exchange"], 
            position["sell_exchange"]
        )
        
        if current_spread is None:
            return
        
        # 最大逆行スプレッドを更新（スプレッドが拡大した場合）
        if abs(current_spread) > abs(position["max_adverse_spread"]):
            position["max_adverse_spread"] = current_spread
        
        # 決済条件をチェック（スプレッドが閾値以下になった）
        if abs(current_spread) <= self.exit_threshold:
            await self._close_position(position, current_spread, timestamp)
    
    def _compute_current_spread(self, symbol: str, buy_exchange: str, sell_exchange: str) -> Optional[float]:
        """現在のスプレッドを計算"""
        symbol_prices = self.detector.price_cache.get(symbol, {})
        
        if buy_exchange not in symbol_prices or sell_exchange not in symbol_prices:
            return None
        
        buy_ticker = symbol_prices[buy_exchange]
        sell_ticker = symbol_prices[sell_exchange]
        
        if buy_ticker.ask is None or sell_ticker.bid is None:
            return None
        
        # スプレッド計算：(売値 - 買値) / 買値 * 100
        spread = (sell_ticker.bid - buy_ticker.ask) / buy_ticker.ask * 100
        return float(spread)
    
    async def _close_position(self, position: Dict[str, Any], exit_spread: float, timestamp: pd.Timestamp):
        """ポジションを決済"""
        symbol = position["symbol"]
        buy_exchange = position["buy_exchange"]
        sell_exchange = position["sell_exchange"]
        
        # エグジット時の実際の実行価格を取得
        symbol_prices = self.detector.price_cache.get(symbol, {})
        buy_exchange_ticker = symbol_prices.get(buy_exchange)
        sell_exchange_ticker = symbol_prices.get(sell_exchange)
        
        if not buy_exchange_ticker or not sell_exchange_ticker:
            # 価格データがない場合は0利益として処理
            exit_buy_price = position["entry_buy_price"]
            exit_sell_price = position["entry_sell_price"]
        else:
            # 実際の決済価格（手数料・スリッページ考慮）
            exit_buy_price = float(buy_exchange_ticker.bid) * (1 - self.slippage)    # bidで売却 - スリッページ
            exit_sell_price = float(sell_exchange_ticker.ask) * (1 + self.slippage)  # askで買戻し + スリッページ
        
        # エントリー価格
        entry_buy_price = position["entry_buy_price"]
        entry_sell_price = position["entry_sell_price"]
        
        # 各ポジションの損益計算（%）
        long_pnl_pct = (exit_buy_price - entry_buy_price) / entry_buy_price * 100
        short_pnl_pct = (entry_sell_price - exit_sell_price) / entry_sell_price * 100
        
        # 総損益（手数料控除前）
        gross_profit_pct = long_pnl_pct + short_pnl_pct
        
        # 手数料控除（往復手数料を%で計算）
        total_fee_pct = self.fee_rate * 4 * 100  # 4回の取引（買い・売り・決済買い・決済売り）
        net_profit_pct = gross_profit_pct - total_fee_pct
        
        # 最大逆行幅を計算（エントリー時からの最大逆行）
        max_adverse_spread = position["max_adverse_spread"]
        entry_spread = position["entry_spread"]
        adverse_movement = abs(max_adverse_spread) - abs(entry_spread)
        
        # トレード記録を作成
        trade = {
            "entry_time": position["entry_time"],
            "exit_time": timestamp,
            "symbol": symbol,
            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,
            "entry_spread": entry_spread,
            "exit_spread": exit_spread,
            "max_adverse_spread": max_adverse_spread,
            "adverse_movement": adverse_movement,
            "entry_buy_price": entry_buy_price,
            "entry_sell_price": entry_sell_price,
            "exit_buy_price": exit_buy_price,
            "exit_sell_price": exit_sell_price,
            "long_pnl_pct": long_pnl_pct,
            "short_pnl_pct": short_pnl_pct,
            "gross_profit_pct": gross_profit_pct,
            "net_profit_pct": net_profit_pct,
            "total_fee_pct": total_fee_pct,
            "opportunity_id": position["opportunity_id"],
            "duration_minutes": (timestamp - position["entry_time"]).total_seconds() / 60
        }
        
        self.closed_trades.append(trade)
        
        print(f"💰 決済: {symbol} | {buy_exchange}→{sell_exchange} | "
              f"Long PnL: {long_pnl_pct:.3f}% | Short PnL: {short_pnl_pct:.3f}% | "
              f"総利益: {gross_profit_pct:.3f}% | 純利益: {net_profit_pct:.3f}% | "
              f"最大逆行: {adverse_movement:.3f}% | 期間: {trade['duration_minutes']:.1f}分")
        
        # ポジションを削除
        del self.open_positions[symbol]
    
    async def _force_close_all_positions(self, timestamp: pd.Timestamp):
        """未決済ポジションを強制決済"""
        print(f"⚠️ 強制決済: {len(self.open_positions)}件のポジションを決済します")
        
        for symbol in list(self.open_positions.keys()):
            position = self.open_positions[symbol]
            current_spread = self._compute_current_spread(
                symbol, 
                position["buy_exchange"], 
                position["sell_exchange"]
            )
            
            if current_spread is not None:
                await self._close_position(position, current_spread, timestamp)
            else:
                # スプレッドが計算できない場合は0として決済
                await self._close_position(position, 0.0, timestamp)

# ──────────────────────────────────────────────────────────────
# CLI & メイン処理
# ──────────────────────────────────────────────────────────────

def parse_cli() -> argparse.Namespace:
    """CLI引数をパース"""
    parser = argparse.ArgumentParser(description="Arbitrage backtest engine")
    parser.add_argument("--start", required=True, help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="終了日 YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH"], 
                       help="対象シンボル (デフォルト: BTC ETH)")
    parser.add_argument("--fee", type=float, default=0.0004, 
                       help="片道手数料率 (例 0.0004 = 0.04%)")
    parser.add_argument("--slippage", type=float, default=0.0003, 
                       help="スリッページ率 (例 0.0003 = 0.03%)")
    parser.add_argument("--min-spread", type=float, default=0.5, 
                       help="エントリー閾値 %% (デフォルト: 0.5)")
    parser.add_argument("--exit", type=float, default=0.1, 
                       help="イグジット閾値 %% (デフォルト: 0.1)")
    parser.add_argument("--max-position", type=float, default=10000, 
                       help="最大ポジションサイズUSD (デフォルト: 10000)")
    parser.add_argument("--min-profit", type=float, default=10, 
                       help="最小利益閾値USD (デフォルト: 10)")
    parser.add_argument("--use-individual", action="store_true",
                       help="個別CSVファイルを使用（デフォルト: 同期データセット使用）")
    
    return parser.parse_args()


def print_statistics(trades_df: pd.DataFrame, args: argparse.Namespace):
    """統計情報を表示"""
    if trades_df.empty:
        print("😢 取引履歴がありません")
        return
    
    # 基本統計
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df["net_profit_pct"] > 0])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    
    total_gross = trades_df["gross_profit_pct"].sum()
    total_net = trades_df["net_profit_pct"].sum()
    avg_gross = trades_df["gross_profit_pct"].mean()
    avg_net = trades_df["net_profit_pct"].mean()
    
    max_profit = trades_df["net_profit_pct"].max()
    max_loss = trades_df["net_profit_pct"].min()
    
    avg_duration = trades_df["duration_minutes"].mean()
    
    # 手数料統計
    avg_fee = trades_df["total_fee_pct"].mean()
    total_fees = trades_df["total_fee_pct"].sum()
    
    # 逆行統計
    avg_adverse = trades_df["adverse_movement"].mean()
    max_adverse = trades_df["adverse_movement"].max()
    min_adverse = trades_df["adverse_movement"].min()
    
    print("\n" + "=" * 60)
    print("📊 バックテスト結果サマリー")
    print("=" * 60)
    print(f"🏷️  対象銘柄      : {', '.join(args.symbols)}")
    print(f"📅 期間          : {args.start} 〜 {args.end}")
    print(f"📈 エントリー閾値  : {args.min_spread:.2f}%")
    print(f"📉 決済閾値      : {args.exit:.2f}%")
    print(f"💸 手数料        : {args.fee:.4f}% (片道)")
    print(f"⚡ スリッページ  : {args.slippage:.4f}%")
    print("-" * 60)
    print(f"🔢 総取引数      : {total_trades:,}件")
    print(f"✅ 勝率          : {win_rate:.1f}% ({winning_trades}/{total_trades})")
    print(f"💰 総利益(総計)  : {total_gross:.4f}% (総), {total_net:.4f}% (純)")
    print(f"📊 平均利益      : {avg_gross:.4f}% (総), {avg_net:.4f}% (純)")
    print(f"💸 平均手数料    : {avg_fee:.4f}% | 総手数料: {total_fees:.4f}%")
    print(f"🚀 最大利益      : {max_profit:.4f}%")
    print(f"📉 最大損失      : {max_loss:.4f}%")
    print(f"⚠️  平均逆行幅    : {avg_adverse:.4f}% | 最大逆行: {max_adverse:.4f}%")
    print(f"⏱️  平均保有時間  : {avg_duration:.1f}分")
    
    # シンボル別統計
    print("\n📊 シンボル別統計:")
    for symbol in args.symbols:
        symbol_trades = trades_df[trades_df["symbol"] == symbol]
        if not symbol_trades.empty:
            symbol_count = len(symbol_trades)
            symbol_win_rate = (len(symbol_trades[symbol_trades["net_profit_pct"] > 0]) / symbol_count) * 100
            symbol_profit = symbol_trades["net_profit_pct"].sum()
            print(f"   {symbol}: {symbol_count}件, 勝率{symbol_win_rate:.1f}%, 利益{symbol_profit:.3f}%")
    
    print("=" * 60)


async def main():
    """メイン処理"""
    args = parse_cli()
    
    # 期間設定
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    
    print("=" * 60)
    print("🔄 Arbitrage Backtest Engine")
    print("=" * 60)
    
    # CSVログを読み込み
    try:
        use_synchronized = not args.use_individual
        df = read_logs(start, end, args.symbols, use_synchronized)
    except FileNotFoundError as e:
        print(f"❌ エラー: {e}")
        print("💡 ヒント: --use-individual オプションで個別CSVファイルの使用も可能です")
        return
    
    # バックテストエンジンを設定
    detector_config = {
        "min_spread_threshold": Decimal(str(args.min_spread)),
        "max_position_size": Decimal(str(args.max_position)),
        "min_profit_threshold": Decimal(str(args.min_profit))
    }
    
    engine = BacktestEngine(
        detector_config=detector_config,
        fee_rate=args.fee,
        slippage=args.slippage,
        exit_threshold=args.exit
    )
    
    # バックテスト実行
    trades = await engine.run_backtest(df)
    
    # 結果を保存
    if not trades.empty:
        output_path = PROJECT_ROOT / "backtest_trades.csv"
        trades.to_csv(output_path, index=False)
        print(f"💾 取引履歴保存: {output_path}")
    
    # 統計表示
    print_statistics(trades, args)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())