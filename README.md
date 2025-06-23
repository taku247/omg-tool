# Arbitrage Bot

Hyperliquid と CEX 間のアービトラージを自動実行する Python Bot

## 概要

このプロジェクトは、Hyperliquid（DEX）と複数の CEX（Bybit、Binance、Gate.io、Bitget、KuCoin）間の価格乖離を検出し、自動的に両建てアービトラージを実行するシステムです。

**🚀 現在 6 取引所（Hyperliquid、Bybit、Binance、Gate.io、Bitget、KuCoin）でリアルタイム価格監視が稼働中！**

## 主な機能

-   **リアルタイム価格監視**: WebSocket を使用した複数取引所の価格データ収集
-   **アービトラージ検出**: 設定可能な閾値による価格乖離の自動検出
-   **自動取引実行**: 両建てポジションの自動開閉
-   **リスク管理**: 包括的なリスク制御とポジションサイズ管理
-   **統計・ログ**: 詳細な取引ログと統計情報の記録

## アーキテクチャ

詳細なアーキテクチャについては [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照してください。

## セットアップ

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env` ファイルを作成し、各取引所の API 認証情報を設定：

```bash
# Hyperliquid
HYPERLIQUID_API_KEY=your_api_key
HYPERLIQUID_API_SECRET=your_api_secret

# Bybit
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret

# Bitget
BITGET_API_KEY=your_api_key
BITGET_API_SECRET=your_api_secret

# Gate.io
GATE_API_KEY=your_api_key
GATE_API_SECRET=your_api_secret

# KuCoin
KUCOIN_API_KEY=your_api_key
KUCOIN_API_SECRET=your_api_secret
KUCOIN_PASSPHRASE=your_passphrase
```

### 3. 設定ファイルの調整

`config/bot_config.yaml` で Bot の動作パラメータを設定

## プロジェクト構造

```
omg-tool/
├── src/
│   ├── interfaces/          # 取引所統一インターフェース
│   ├── core/               # コア機能モジュール
│   ├── exchanges/          # 各取引所の実装
│   └── bot.py             # メインBotクラス
├── config/
│   └── bot_config.yaml    # 設定ファイル
├── docs/
│   └── ARCHITECTURE.md    # アーキテクチャドキュメント
├── tests/                 # テストファイル
├── logs/                  # ログファイル
└── data/                  # データファイル
```

## 実行コマンド

### 🚀 メイン監視システム（推奨）

```bash
# リアルタイムアービトラージ監視（30秒）
python run_arbitrage_monitor.py
```

### 🧪 個別取引所テスト

```bash
# Hyperliquid単体テスト（REST APIのみ）
python tests/test_hyperliquid_rest_only.py

# Bybit単体テスト（REST + WebSocket）
python tests/test_bybit.py

# Binance単体テスト（REST + WebSocket）
python tests/test_binance.py
```

### 📊 アービトラージ検出テスト

```bash
# 2取引所アービトラージ（Hyperliquid vs Bybit）
python tests/test_arbitrage_detection.py

# 3取引所統合アービトラージ（Hyperliquid vs Bybit vs Binance）
python tests/test_three_exchanges_arbitrage.py
```

### 🔧 L2Book 解析テスト（修正検証）

```bash
# Hyperliquid L2Book解析単体テスト
python tests/test_hyperliquid_l2book_parsing.py

# Hyperliquid WebSocket統合テスト
python tests/test_hyperliquid_websocket_integration.py

# 全取引所L2Book解析テスト
python tests/test_all_exchanges_l2book.py
```

### 🐛 デバッグ・解析ツール

```bash
# Hyperliquid WebSocketデータ形式デバッグ
python debug_hyperliquid_websocket.py
```

### 📝 ログ確認

```bash
# リアルタイムログ監視
tail -f arbitrage_monitor.log

# 過去のログ確認
cat arbitrage_monitor.log

# ログファイル一覧
ls -la *.log
```

### 📚 実装ログ確認

```bash
# 実装ログ一覧
ls -la _docs/

# 最新の実装ログ
cat _docs/2024-12-21_binance-implementation.md
cat _docs/2024-12-21_bybit-implementation.md
```

### 🎯 用途別推奨コマンド

**リアルタイム監視したい場合:**

```bash
python run_arbitrage_monitor.py
```

**システム動作確認したい場合:**

```bash
python tests/test_three_exchanges_arbitrage.py
```

**修正検証したい場合:**

```bash
python tests/test_hyperliquid_websocket_integration.py
```

**問題調査したい場合:**

```bash
tail -f arbitrage_monitor.log
```

### 📈 実行結果例

リアルタイム監視システム実行時の出力例：

```
🔥 アービトラージ監視システム
================================================================================
🚀 アービトラージ監視システム起動中...
📊 監視シンボル: ['BTC', 'ETH', 'SOL']
⏱️ 監視時間: 30秒
📈 アービトラージ検出閾値: 0.1%
================================================================================
✅ 全取引所接続完了
📊 価格監視開始... (Ctrl+Cで停止)
------------------------------------------------------------
[21:05:13] Hyperliquid BTC: Bid=103891.0 Ask=103892.0 (更新#100)
[21:05:13] Bybit       BTC: Bid=103878.00 Ask=103878.10 (更新#10)
[21:05:13] Binance     BTC: Bid=103881.40 Ask=103881.50 (更新#210)

📈 監視結果:
   Hyperliquid価格更新: 395回 (2.8%)
   Bybit価格更新: 1592回 (11.4%)
   Binance価格更新: 11979回 (85.8%)
   総価格更新: 13966回
   検出されたアービトラージ機会: 0件

💰 最新価格:
   BTC: Hyperliquid $103,891 vs Bybit $103,878 vs Binance $103,881
   ETH: Hyperliquid $2,441.75 vs Bybit $2,441.79 vs Binance $2,441.94
   SOL: Hyperliquid $142.20 vs Bybit $142.19 vs Binance $142.20
```

## 設定項目

### アービトラージ検出

-   `min_spread_threshold`: 最小スプレッド閾値（%）
-   `max_position_size`: 最大ポジションサイズ（USD）
-   `min_profit_threshold`: 最小利益閾値（USD）

### リスク管理

-   `max_total_exposure`: 最大総エクスポージャー
-   `max_positions_per_symbol`: シンボルあたり最大ポジション数
-   `stop_loss_percentage`: ストップロス率
-   `max_daily_loss`: 最大日次損失

## 開発・テスト

### 📊 現在の進捗状況

**実装完了度: 100%** （価格監視システム）

✅ **完成済み機能:**

-   統一インターフェース設計
-   6 取引所実装（Hyperliquid、Bybit、Binance、Gate.io、Bitget、KuCoin）
-   5 取引所デフォルト価格監視（Binance除外で安定化）
-   リアルタイムアービトラージ検出
-   価格差計算・分析
-   設定ファイル管理システム

⚠️ **注意事項:**

-   **Binance**: デフォルトで除外（高頻度データによるシステム負荷のため）
-   必要時は `--exchanges` オプションで明示的に指定可能

🔄 **開発中:**

-   バックテストシステム
-   注文実行機能実装
-   実取引システムテスト

### テスト実行

```bash
# 全テスト実行
python -m pytest tests/ -v

# 特定のテスト実行
python tests/test_hyperliquid_l2book_parsing.py
python tests/test_three_exchanges_arbitrage.py
```

### コードフォーマット・品質

```bash
# フォーマット
black src/
flake8 src/

# 型チェック
mypy src/
```

## ロードマップ

### Phase 1: 基盤構築 ✅

-   [x] アーキテクチャ設計
-   [x] インターフェース定義
-   [x] コアモジュール実装

### Phase 2: 取引所実装 ✅

-   [x] Hyperliquid 実装（WebSocket 接続、L2Book 解析修正済み）
-   [x] Bybit 実装（完全動作）
-   [x] Binance 実装（完全動作）
-   [x] Gate.io 実装（完全動作）
-   [x] Bitget 実装（完全動作）
-   [x] KuCoin 実装（完全動作）

### Phase 3: 高度な機能

-   [ ] バックテスト機能（開発中）
    -   [ ] price_logger.py - リアルタイム価格記録
    -   [ ] backtest_engine.py - バックテスト実行
    -   [ ] plot_results.py - 結果可視化
-   [ ] Web UI ダッシュボード
-   [ ] アラート通知

### Phase 4: Rust 移植

-   [ ] Rust 実装設計
-   [ ] パフォーマンス最適化

## バックテストシステム 🧪

### 概要

リアルタイム価格データの記録と、過去データを使用したアービトラージ戦略のバックテストを行うシステムです。

### 構成

**1. price_logger.py** - リアルタイム価格記録

-   4取引所（Hyperliquid、Bybit、Gateio、KuCoin）からの価格データを閾値ベースで CSV に記録
-   日付別・取引所別にファイル自動ローテート
-   bid/ask 価格、サイズ、出来高などの詳細情報を保存
-   価格変化の閾値を満たした時のみ保存される差分ログ形式

**2. data_preprocessor.py** - データ前処理・時間同期

-   不規則時系列データを規則的な時間窓に集約
-   取引所間での価格データ同期
-   欠損データの補間処理
-   バックテスト用の統一データセット作成

**3. backtest_engine.py** - バックテスト実行エンジン

-   CSV ファイルから過去データを読み込み
-   アービトラージ機会の検出とシミュレーション
-   手数料、スリッページ、約定遅延を考慮した現実的な取引実行
-   パフォーマンス指標の計算（収益、勝率、最大ドローダウン等）

**4. plot_results.py** - 結果可視化

-   価格差推移グラフ
-   アービトラージ機会のヒートマップ
-   累積収益曲線
-   ドローダウン分析
-   取引頻度分布

### 使用方法

```bash
# 1. 価格データの記録開始（24時間以上推奨）
# デフォルト実行（4取引所で安定動作）
python price_logger.py --symbols BTC ETH SOL XRP

# 2. データ前処理（不規則時系列を時間同期）
python data_preprocessor.py --date 20250623 --window 30s --interpolate

# 3. バックテスト実行
python backtest_engine.py --start 2025-06-21 --end 2025-06-21 --symbols BTC ETH

# 4. 結果の可視化
python plot_results.py --input results/backtest_20240101_20240131.json
```

### データ前処理について

**不規則時系列データの課題:**
- 価格変化の閾値を満たした時のみ保存される差分ログ形式
- 取引所ごとに異なるタイムスタンプでの価格更新
- バックテスト時の取引所間価格比較が困難

**data_preprocessor.pyによる解決:**
- 30秒間隔の規則的な時間窓に集約
- 全取引所で統一されたタイムスタンプ
- 欠損データの前値補間処理
- `synchronized_prices_YYYYMMDD.csv`として同期データセット出力

**使用方法:**
```bash
# 基本実行（30秒窓で集約）
python data_preprocessor.py --date 20250623

# 詳細オプション
python data_preprocessor.py --date 20250623 --window 30s --interpolate --method last
```

### バックテスト実行コマンド

#### 基本実行

```bash
# 単日バックテスト（今日のデータを使用）
python backtest_engine.py --start 2025-06-21 --end 2025-06-21

# 期間指定バックテスト
python backtest_engine.py --start 2025-06-01 --end 2025-06-30
```

#### パラメータ調整

```bash
# 閾値を調整したバックテスト
python backtest_engine.py \
  --start 2025-06-21 --end 2025-06-21 \
  --min-spread 0.1 \
  --exit 0.05 \
  --symbols BTC ETH

# 手数料・スリッページを考慮
python backtest_engine.py \
  --start 2025-06-21 --end 2025-06-21 \
  --fee 0.0004 \
  --slippage 0.0003 \
  --min-profit 10
```

#### 利用可能オプション

| オプション       | デフォルト | 説明                       |
| ---------------- | ---------- | -------------------------- |
| `--start`        | 必須       | 開始日 (YYYY-MM-DD)        |
| `--end`          | 必須       | 終了日 (YYYY-MM-DD)        |
| `--symbols`      | BTC ETH    | 対象銘柄 (スペース区切り)  |
| `--min-spread`   | 0.5        | エントリー閾値 (%)         |
| `--exit`         | 0.1        | 決済閾値 (%)               |
| `--fee`          | 0.0004     | 片道手数料率 (0.04%)       |
| `--slippage`     | 0.0003     | スリッページ率 (0.03%)     |
| `--max-position` | 10000      | 最大ポジションサイズ (USD) |
| `--min-profit`   | 10         | 最小利益閾値 (USD)         |

#### 実行結果例

```
============================================================
🔄 Arbitrage Backtest Engine
============================================================
📅 読み込み期間: 2025-06-21 〜 2025-06-21
✅ 1,219レコード読み込み完了
📊 取引所: ['Binance', 'Bitget', 'Bybit', 'Gateio', 'Hyperliquid', 'KuCoin']
📊 シンボル: ['BTC', 'ETH']
⚙️ バックテスト実行開始 (1,219レコード)
📈 最小スプレッド閾値: 0.10%
💰 決済閾値: 0.05%
💸 手数料: 0.0004% (片道)
⚡ スリッページ: 0.0003%
📊 エントリー: ARB_000002 | ETH | Bybit→Binance | スプレッド: 2.970%
💰 決済: ETH | スプレッド: 2.970% → -0.017% | 総利益: 2.987% | 純利益: 2.986% | 期間: 0.0分
✅ バックテスト完了: 9件のトレード
💾 取引履歴保存: /Users/moriwakikeita/tools/omg-tool/backtest_trades.csv

============================================================
📊 バックテスト結果サマリー
============================================================
🔢 総取引数      : 9件
✅ 勝率          : 100.0% (9/9)
💰 総利益(総計)  : 6.5917% (総), 6.5818% (純)
📊 平均利益      : 0.7324% (総), 0.7313% (純)
🚀 最大利益      : 2.9856%
📉 最大損失      : 0.0568%
⏱️  平均保有時間  : 3.8分
============================================================
```

### chatGPT レビュー

### 🏁 バックテスト実行結果の読み解き方

| 指標               | 値                  | 何を意味するか                   | コメント                                                    |
| ------------------ | ------------------- | -------------------------------- | ----------------------------------------------------------- |
| **取引数**         | 9 件 (BTC 3・ETH 6) | 期間中にエントリー → 決済が 9 回 | 試験用 log が数時間分なので妥当                             |
| **勝率**           | 100 %               | 9/9 でネット利益 > 0             | 手数料・スリッページ控除後も全勝。閾値設計が甘い可能性あり  |
| **平均ネット利幅** | 0.73 %              | 1 取引当たりの純益（%）          | 高め。リアル運用では 0.1–0.3 % 程度に落ちる事が多い         |
| **最大利幅**       | 2.99 %              | Bybit→Binance（ETH）             | 約 3 % はかなり大きい乖離：実ログで本当に発生したか要再確認 |

---

### CSV を見るポイント

| 列                                | 備考                                                                                                                                      |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `entry_time = exit_time` が複数行 | **秒未満**の同時エントリー → 即収束。<br>1 行で数% 取れている場合は「始値終値の小数精度不足」や<br>閾値設定の甘さで過大計上している可能性 |
| `duration_minutes = 0`            | = 同上。Tick 解像度では 0.0 分でも実際は数百 ms 継続かもしれない                                                                          |
| `gross_profit` ↔ `net_profit` 差  | 手数料 + スリッページ（0.04 + 0.03 %）しか引いてない → <br>高利幅に対しコストが極小 → 勝率 100 % になりやすい                             |

---

## なぜ勝率 100 % になった？

1. **exit_threshold 0.1 %** が広く、乖離が戻り切らずとも利幅が残る
2. **手数料 (0.04 %) + スリッページ (0.03 %)** が小さい
3. **価格ログの粒度**：

    - min/max が潰れて **瞬間 3 % spike** だけが残った可能性
    - `entry_time = exit_time` 行は“同一秒内で peak→ 谷”を捉えきれていない

---

## 改善して再テストするチェックリスト

| 施策                                                                                       | 期待効果                               |
| ------------------------------------------------------------------------------------------ | -------------------------------------- |
| **もっと厳しい `min_spread`**<br>(例 0.8 %) と<br>**狭い `exit_threshold`**<br>(例 0.05 %) | エントリーを減らして勝率妥当化         |
| **tick ログ (interval = 0)** で収集し<br>`backtest` 前に 250 ms 足へリサンプリング         | 「entry=exit」問題の解消               |
| **手数料 0.1–0.15 %**、<br>スリッページ 0.1–0.2 % に上げる                                 | 実戦に近いコストでネット利幅を現実的に |
| **size × 価格で PnL(USD) 計算**                                                            | % だけでなくドル建て損益を可視化       |
| **同時複数ポジ未許可** + <br>`open_pos` を銘柄ごと管理                                     | 同じ乖離ペアで “多重カウント” を防止   |
| **最大保持時間** (例 5 分) を設け、<br>未収束なら損切り                                    | 長時間含み損リスクを再現               |

---

## まとめ

-   **コード自体は正しく動き、機会を拾えている**
    → ロジック・閾値・コストの現実度を上げると、勝率・利幅が落ち着くはず
-   **次のステップ**

    1. 高解像度ログで再収集（or ログ粒度を検証）
    2. 閾値とコストパラメータを現実的に設定し直して再バックテスト
    3. 結果を基にポジションサイズや資金効率を試算

調整後また結果を見せてもらえれば、さらに細かく改善アドバイスできます！

### データ仕様

**CSV 形式:**

```csv
timestamp,exchange,symbol,bid,ask,bid_size,ask_size,last,volume_24h
2024-01-01T00:00:00Z,Hyperliquid,BTC,42000.5,42001.0,1.5,2.0,42000.8,1234.56
```

**データ量見積もり:**

-   1 秒間隔 × 6 取引所 × 3 銘柄 × 24 時間 = 約 155 万行/日
-   圧縮推奨（gzip 使用で約 80%削減）

### バックテスト設定

**評価指標:**

-   年率リターン（Annual Return）
-   最大ドローダウン（Maximum Drawdown）
-   シャープレシオ（Sharpe Ratio）
-   勝率（Win Rate）
-   平均利益/損失（Average P&L）

**考慮事項:**

-   取引手数料: maker 0.02%, taker 0.06%
-   スリッページ: 0.01-0.05%（流動性による）
-   約定遅延: 100-500ms（ネットワーク遅延）
-   最小取引単位: 各取引所の制限に準拠
