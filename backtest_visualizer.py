#!/usr/bin/env python3
"""
バックテスト結果の可視化スクリプト
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
import argparse
from datetime import datetime

# 日本語フォント設定
plt.rcParams['font.family'] = ['DejaVu Sans', 'Arial Unicode MS', 'Hiragino Sans']
plt.rcParams['axes.unicode_minus'] = False

def load_backtest_results(csv_path: str) -> pd.DataFrame:
    """バックテスト結果CSVを読み込み"""
    df = pd.read_csv(csv_path)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    return df

def calculate_detailed_stats(df: pd.DataFrame) -> dict:
    """詳細統計を計算"""
    winning_trades = df[df['net_profit_pct'] > 0]
    losing_trades = df[df['net_profit_pct'] < 0]
    
    stats = {
        'total_trades': len(df),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'win_rate': len(winning_trades) / len(df) * 100 if len(df) > 0 else 0,
        'loss_rate': len(losing_trades) / len(df) * 100 if len(df) > 0 else 0,
        'total_pnl': df['net_profit_pct'].sum(),
        'avg_win_pnl': winning_trades['net_profit_pct'].mean() if len(winning_trades) > 0 else 0,
        'avg_loss_pnl': losing_trades['net_profit_pct'].mean() if len(losing_trades) > 0 else 0,
        'max_win': df['net_profit_pct'].max(),
        'max_loss': df['net_profit_pct'].min(),
        'avg_duration': df['duration_minutes'].mean(),
        'avg_adverse_movement': df['adverse_movement'].mean(),
        'max_adverse_movement': df['adverse_movement'].max(),
        'profit_factor': abs(winning_trades['net_profit_pct'].sum() / losing_trades['net_profit_pct'].sum()) if len(losing_trades) > 0 and losing_trades['net_profit_pct'].sum() != 0 else float('inf'),
        'sharpe_ratio': df['net_profit_pct'].mean() / df['net_profit_pct'].std() if df['net_profit_pct'].std() != 0 else 0
    }
    
    return stats

def create_comprehensive_dashboard(df: pd.DataFrame, output_dir: str = "backtest_charts"):
    """包括的なダッシュボードを作成"""
    
    # 出力ディレクトリ作成
    Path(output_dir).mkdir(exist_ok=True)
    
    # 統計計算
    stats = calculate_detailed_stats(df)
    
    # 1. 総合統計サマリー
    create_summary_chart(stats, f"{output_dir}/01_summary.png")
    
    # 2. PnL分布
    create_pnl_distribution(df, f"{output_dir}/02_pnl_distribution.png")
    
    # 3. 累積PnL
    create_cumulative_pnl(df, f"{output_dir}/03_cumulative_pnl.png")
    
    # 4. 勝ち負け分析
    create_win_loss_analysis(df, stats, f"{output_dir}/04_win_loss_analysis.png")
    
    # 5. シンボル別パフォーマンス
    create_symbol_performance(df, f"{output_dir}/05_symbol_performance.png")
    
    # 6. 取引所ペア分析
    create_exchange_pair_analysis(df, f"{output_dir}/06_exchange_pairs.png")
    
    # 7. 保有時間 vs PnL
    create_duration_vs_pnl(df, f"{output_dir}/07_duration_vs_pnl.png")
    
    # 8. 逆行分析
    create_adverse_movement_analysis(df, f"{output_dir}/08_adverse_movement.png")
    
    # 9. 時間別パフォーマンス
    create_time_analysis(df, f"{output_dir}/09_time_analysis.png")
    
    # 10. リスク・リターン分析
    create_risk_return_analysis(df, f"{output_dir}/10_risk_return.png")
    
    print(f"📊 グラフが {output_dir}/ に保存されました")
    print_detailed_stats(stats)

def create_summary_chart(stats: dict, filename: str):
    """総合統計サマリーチャート"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('🎯 バックテスト結果サマリー', fontsize=16, fontweight='bold')
    
    # 1. 勝率・負け率
    labels = ['勝ち', '負け']
    sizes = [stats['win_rate'], stats['loss_rate']]
    colors = ['#2ecc71', '#e74c3c']
    ax1.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    ax1.set_title(f'勝率: {stats["winning_trades"]}/{stats["total_trades"]} ({stats["win_rate"]:.1f}%)')
    
    # 2. PnL統計
    categories = ['総PnL', '平均勝ち', '平均負け', '最大勝ち', '最大負け']
    values = [stats['total_pnl'], stats['avg_win_pnl'], stats['avg_loss_pnl'], 
              stats['max_win'], stats['max_loss']]
    colors_bar = ['blue' if v >= 0 else 'red' for v in values]
    
    bars = ax2.bar(categories, values, color=colors_bar, alpha=0.7)
    ax2.set_title('PnL統計 (%)')
    ax2.tick_params(axis='x', rotation=45)
    ax2.grid(True, alpha=0.3)
    
    # 値をバーの上に表示
    for bar, value in zip(bars, values):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + (0.01 if height >= 0 else -0.05),
                f'{value:.3f}%', ha='center', va='bottom' if height >= 0 else 'top')
    
    # 3. リスク指標
    risk_metrics = ['平均保有時間', '平均逆行', '最大逆行', 'Profit Factor']
    risk_values = [stats['avg_duration'], stats['avg_adverse_movement'], 
                   stats['max_adverse_movement'], min(stats['profit_factor'], 5)]  # 上限5で表示
    
    ax3.bar(risk_metrics, risk_values, color='orange', alpha=0.7)
    ax3.set_title('リスク指標')
    ax3.tick_params(axis='x', rotation=45)
    ax3.grid(True, alpha=0.3)
    
    # 4. トレード数
    trade_counts = [stats['total_trades'], stats['winning_trades'], stats['losing_trades']]
    trade_labels = ['総取引数', '勝ちトレード', '負けトレード']
    
    ax4.bar(trade_labels, trade_counts, color=['gray', 'green', 'red'], alpha=0.7)
    ax4.set_title('取引数')
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_pnl_distribution(df: pd.DataFrame, filename: str):
    """PnL分布"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # ヒストグラム
    ax1.hist(df['net_profit_pct'], bins=20, alpha=0.7, color='steelblue', edgecolor='black')
    ax1.axvline(df['net_profit_pct'].mean(), color='red', linestyle='--', 
                label=f'平均: {df["net_profit_pct"].mean():.3f}%')
    ax1.axvline(0, color='black', linestyle='-', alpha=0.5)
    ax1.set_xlabel('純利益 (%)')
    ax1.set_ylabel('頻度')
    ax1.set_title('📊 PnL分布')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # ボックスプロット
    box_data = [df[df['net_profit_pct'] > 0]['net_profit_pct'].dropna(),
                df[df['net_profit_pct'] < 0]['net_profit_pct'].dropna()]
    box_labels = ['勝ちトレード', '負けトレード']
    
    bp = ax2.boxplot(box_data, labels=box_labels, patch_artist=True)
    bp['boxes'][0].set_facecolor('lightgreen')
    bp['boxes'][1].set_facecolor('lightcoral')
    
    ax2.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax2.set_ylabel('純利益 (%)')
    ax2.set_title('📈 勝ち負け別PnL分布')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_cumulative_pnl(df: pd.DataFrame, filename: str):
    """累積PnL"""
    # 取引順にソート
    df_sorted = df.sort_values('entry_time').reset_index(drop=True)
    df_sorted['cumulative_pnl'] = df_sorted['net_profit_pct'].cumsum()
    df_sorted['trade_number'] = range(1, len(df_sorted) + 1)
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # 累積PnLライン
    ax.plot(df_sorted['trade_number'], df_sorted['cumulative_pnl'], 
            linewidth=2, marker='o', markersize=4, color='steelblue')
    
    # 0ライン
    ax.axhline(0, color='black', linestyle='-', alpha=0.5)
    
    # 各取引の勝ち負けを色分け
    for i, row in df_sorted.iterrows():
        color = 'green' if row['net_profit_pct'] > 0 else 'red'
        ax.scatter(row['trade_number'], row['cumulative_pnl'], 
                  color=color, s=50, alpha=0.7, zorder=5)
    
    ax.set_xlabel('取引番号')
    ax.set_ylabel('累積純利益 (%)')
    ax.set_title('📈 累積PnL推移')
    ax.grid(True, alpha=0.3)
    
    # 最終結果を表示
    final_pnl = df_sorted['cumulative_pnl'].iloc[-1]
    ax.text(0.02, 0.98, f'最終PnL: {final_pnl:.3f}%', 
            transform=ax.transAxes, fontsize=12, fontweight='bold',
            bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7),
            verticalalignment='top')
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_win_loss_analysis(df: pd.DataFrame, stats: dict, filename: str):
    """勝ち負け詳細分析"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('🎯 勝ち負け詳細分析', fontsize=16, fontweight='bold')
    
    winning_trades = df[df['net_profit_pct'] > 0]
    losing_trades = df[df['net_profit_pct'] < 0]
    
    # 1. 勝ちトレードPnL分布
    if len(winning_trades) > 0:
        ax1.hist(winning_trades['net_profit_pct'], bins=10, alpha=0.7, 
                color='green', edgecolor='black')
        ax1.axvline(winning_trades['net_profit_pct'].mean(), color='darkgreen', 
                   linestyle='--', label=f'平均: {stats["avg_win_pnl"]:.3f}%')
        ax1.set_title(f'✅ 勝ちトレード分布 ({len(winning_trades)}件)')
        ax1.set_xlabel('純利益 (%)')
        ax1.legend()
    else:
        ax1.text(0.5, 0.5, '勝ちトレードなし', ha='center', va='center', transform=ax1.transAxes)
        ax1.set_title('✅ 勝ちトレード分布 (0件)')
    ax1.grid(True, alpha=0.3)
    
    # 2. 負けトレードPnL分布
    if len(losing_trades) > 0:
        ax2.hist(losing_trades['net_profit_pct'], bins=10, alpha=0.7, 
                color='red', edgecolor='black')
        ax2.axvline(losing_trades['net_profit_pct'].mean(), color='darkred', 
                   linestyle='--', label=f'平均: {stats["avg_loss_pnl"]:.3f}%')
        ax2.set_title(f'❌ 負けトレード分布 ({len(losing_trades)}件)')
        ax2.set_xlabel('純利益 (%)')
        ax2.legend()
    else:
        ax2.text(0.5, 0.5, '負けトレードなし', ha='center', va='center', transform=ax2.transAxes)
        ax2.set_title('❌ 負けトレード分布 (0件)')
    ax2.grid(True, alpha=0.3)
    
    # 3. 保有時間比較
    if len(winning_trades) > 0 and len(losing_trades) > 0:
        duration_data = [winning_trades['duration_minutes'], losing_trades['duration_minutes']]
        duration_labels = ['勝ちトレード', '負けトレード']
        
        bp = ax3.boxplot(duration_data, labels=duration_labels, patch_artist=True)
        bp['boxes'][0].set_facecolor('lightgreen')
        bp['boxes'][1].set_facecolor('lightcoral')
        
        ax3.set_ylabel('保有時間 (分)')
        ax3.set_title('⏱️ 保有時間比較')
    else:
        ax3.text(0.5, 0.5, 'データ不足', ha='center', va='center', transform=ax3.transAxes)
        ax3.set_title('⏱️ 保有時間比較')
    ax3.grid(True, alpha=0.3)
    
    # 4. Profit Factor表示
    pf = stats['profit_factor']
    if pf == float('inf'):
        pf_text = "∞ (負けなし)"
        pf_color = 'green'
    elif pf > 2:
        pf_text = f"{pf:.2f} (優秀)"
        pf_color = 'green'
    elif pf > 1:
        pf_text = f"{pf:.2f} (良好)"
        pf_color = 'orange'
    else:
        pf_text = f"{pf:.2f} (要改善)"
        pf_color = 'red'
    
    ax4.text(0.5, 0.7, 'Profit Factor', ha='center', va='center', 
             fontsize=16, fontweight='bold', transform=ax4.transAxes)
    ax4.text(0.5, 0.5, pf_text, ha='center', va='center', 
             fontsize=20, fontweight='bold', color=pf_color, transform=ax4.transAxes)
    ax4.text(0.5, 0.3, f'総勝ち: {stats["winning_trades"]*stats["avg_win_pnl"]:.3f}%\n総負け: {stats["losing_trades"]*stats["avg_loss_pnl"]:.3f}%', 
             ha='center', va='center', transform=ax4.transAxes)
    ax4.set_xlim(0, 1)
    ax4.set_ylim(0, 1)
    ax4.axis('off')
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_symbol_performance(df: pd.DataFrame, filename: str):
    """シンボル別パフォーマンス"""
    symbol_stats = df.groupby('symbol').agg({
        'net_profit_pct': ['count', 'sum', 'mean'],
        'duration_minutes': 'mean',
        'adverse_movement': 'mean'
    }).round(3)
    
    symbol_stats.columns = ['取引数', '総PnL', '平均PnL', '平均保有時間', '平均逆行']
    symbol_stats['勝率'] = df.groupby('symbol').apply(
        lambda x: (x['net_profit_pct'] > 0).sum() / len(x) * 100
    ).round(1)
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('💰 シンボル別パフォーマンス', fontsize=16, fontweight='bold')
    
    symbols = symbol_stats.index
    
    # 1. 総PnL
    colors = ['green' if x >= 0 else 'red' for x in symbol_stats['総PnL']]
    bars1 = ax1.bar(symbols, symbol_stats['総PnL'], color=colors, alpha=0.7)
    ax1.set_title('📊 総PnL (%)')
    ax1.set_ylabel('純利益 (%)')
    ax1.grid(True, alpha=0.3)
    ax1.axhline(0, color='black', linestyle='-', alpha=0.5)
    
    # 値をバーの上に表示
    for bar, value in zip(bars1, symbol_stats['総PnL']):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + (0.01 if height >= 0 else -0.05),
                f'{value:.3f}%', ha='center', va='bottom' if height >= 0 else 'top')
    
    # 2. 勝率
    bars2 = ax2.bar(symbols, symbol_stats['勝率'], color='steelblue', alpha=0.7)
    ax2.set_title('📈 勝率 (%)')
    ax2.set_ylabel('勝率 (%)')
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    
    for bar, value in zip(bars2, symbol_stats['勝率']):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{value:.1f}%', ha='center', va='bottom')
    
    # 3. 平均保有時間
    ax3.bar(symbols, symbol_stats['平均保有時間'], color='orange', alpha=0.7)
    ax3.set_title('⏱️ 平均保有時間 (分)')
    ax3.set_ylabel('時間 (分)')
    ax3.grid(True, alpha=0.3)
    
    # 4. 取引数
    ax4.bar(symbols, symbol_stats['取引数'], color='purple', alpha=0.7)
    ax4.set_title('🔢 取引数')
    ax4.set_ylabel('取引数')
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_exchange_pair_analysis(df: pd.DataFrame, filename: str):
    """取引所ペア分析"""
    df['pair'] = df['buy_exchange'] + '→' + df['sell_exchange']
    pair_stats = df.groupby('pair').agg({
        'net_profit_pct': ['count', 'sum', 'mean'],
        'duration_minutes': 'mean'
    }).round(3)
    
    pair_stats.columns = ['取引数', '総PnL', '平均PnL', '平均保有時間']
    pair_stats = pair_stats.sort_values('総PnL', ascending=False)
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))
    fig.suptitle('🔄 取引所ペア分析', fontsize=16, fontweight='bold')
    
    # 1. 総PnL
    colors = ['green' if x >= 0 else 'red' for x in pair_stats['総PnL']]
    bars = ax1.barh(range(len(pair_stats)), pair_stats['総PnL'], color=colors, alpha=0.7)
    ax1.set_yticks(range(len(pair_stats)))
    ax1.set_yticklabels(pair_stats.index)
    ax1.set_xlabel('総PnL (%)')
    ax1.set_title('📊 取引所ペア別総PnL')
    ax1.grid(True, alpha=0.3)
    ax1.axvline(0, color='black', linestyle='-', alpha=0.5)
    
    # 2. 取引数と平均PnL
    x = np.arange(len(pair_stats))
    width = 0.35
    
    ax2_twin = ax2.twinx()
    bars1 = ax2.bar(x - width/2, pair_stats['取引数'], width, label='取引数', color='blue', alpha=0.7)
    bars2 = ax2_twin.bar(x + width/2, pair_stats['平均PnL'], width, label='平均PnL', color='orange', alpha=0.7)
    
    ax2.set_xlabel('取引所ペア')
    ax2.set_ylabel('取引数', color='blue')
    ax2_twin.set_ylabel('平均PnL (%)', color='orange')
    ax2.set_title('📈 取引数 vs 平均PnL')
    ax2.set_xticks(x)
    ax2.set_xticklabels(pair_stats.index, rotation=45, ha='right')
    ax2.grid(True, alpha=0.3)
    
    # 凡例
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_twin.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc='upper right')
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_duration_vs_pnl(df: pd.DataFrame, filename: str):
    """保有時間 vs PnL"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # 散布図
    colors = ['green' if x > 0 else 'red' for x in df['net_profit_pct']]
    scatter = ax1.scatter(df['duration_minutes'], df['net_profit_pct'], 
                         c=colors, alpha=0.7, s=50)
    
    ax1.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax1.set_xlabel('保有時間 (分)')
    ax1.set_ylabel('純利益 (%)')
    ax1.set_title('⏱️ 保有時間 vs PnL')
    ax1.grid(True, alpha=0.3)
    
    # 相関係数を表示
    correlation = df['duration_minutes'].corr(df['net_profit_pct'])
    ax1.text(0.05, 0.95, f'相関係数: {correlation:.3f}', transform=ax1.transAxes,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7))
    
    # 保有時間別PnL
    # 時間でビンに分ける
    df['duration_bin'] = pd.cut(df['duration_minutes'], 
                               bins=[0, 1, 10, 60, float('inf')], 
                               labels=['即座(≤1分)', '短期(1-10分)', '中期(10-60分)', '長期(>60分)'])
    
    duration_pnl = df.groupby('duration_bin', observed=False)['net_profit_pct'].agg(['count', 'mean', 'sum'])
    
    colors_bar = ['green' if x >= 0 else 'red' for x in duration_pnl['mean']]
    bars = ax2.bar(range(len(duration_pnl)), duration_pnl['mean'], 
                  color=colors_bar, alpha=0.7)
    
    ax2.set_xticks(range(len(duration_pnl)))
    ax2.set_xticklabels(duration_pnl.index, rotation=45)
    ax2.set_ylabel('平均PnL (%)')
    ax2.set_title('📊 保有時間別平均PnL')
    ax2.grid(True, alpha=0.3)
    ax2.axhline(0, color='black', linestyle='-', alpha=0.5)
    
    # 取引数を表示
    for i, (bar, count) in enumerate(zip(bars, duration_pnl['count'])):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + (0.01 if height >= 0 else -0.05),
                f'{count}件', ha='center', va='bottom' if height >= 0 else 'top')
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_adverse_movement_analysis(df: pd.DataFrame, filename: str):
    """逆行分析"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('⚠️ 逆行分析', fontsize=16, fontweight='bold')
    
    # 1. 逆行分布
    ax1.hist(df['adverse_movement'], bins=20, alpha=0.7, color='orange', edgecolor='black')
    ax1.axvline(df['adverse_movement'].mean(), color='red', linestyle='--', 
                label=f'平均: {df["adverse_movement"].mean():.3f}%')
    ax1.set_xlabel('逆行幅 (%)')
    ax1.set_ylabel('頻度')
    ax1.set_title('📊 逆行幅分布')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. 逆行 vs PnL
    colors = ['green' if x > 0 else 'red' for x in df['net_profit_pct']]
    ax2.scatter(df['adverse_movement'], df['net_profit_pct'], c=colors, alpha=0.7, s=50)
    ax2.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax2.set_xlabel('逆行幅 (%)')
    ax2.set_ylabel('純利益 (%)')
    ax2.set_title('📈 逆行幅 vs PnL')
    ax2.grid(True, alpha=0.3)
    
    # 相関係数
    correlation = df['adverse_movement'].corr(df['net_profit_pct'])
    ax2.text(0.05, 0.95, f'相関係数: {correlation:.3f}', transform=ax2.transAxes,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7))
    
    # 3. 逆行レベル別分析
    df['adverse_level'] = pd.cut(df['adverse_movement'], 
                                bins=[0, 0.5, 1.0, 2.0, float('inf')], 
                                labels=['低(0-0.5%)', '中(0.5-1%)', '高(1-2%)', '極高(>2%)'])
    
    adverse_pnl = df.groupby('adverse_level', observed=False)['net_profit_pct'].agg(['count', 'mean'])
    
    colors_bar = ['green' if x >= 0 else 'red' for x in adverse_pnl['mean']]
    bars = ax3.bar(range(len(adverse_pnl)), adverse_pnl['mean'], 
                  color=colors_bar, alpha=0.7)
    
    ax3.set_xticks(range(len(adverse_pnl)))
    ax3.set_xticklabels(adverse_pnl.index, rotation=45)
    ax3.set_ylabel('平均PnL (%)')
    ax3.set_title('📊 逆行レベル別平均PnL')
    ax3.grid(True, alpha=0.3)
    ax3.axhline(0, color='black', linestyle='-', alpha=0.5)
    
    # 4. シンボル別逆行
    symbol_adverse = df.groupby('symbol')['adverse_movement'].agg(['mean', 'max'])
    
    x = np.arange(len(symbol_adverse))
    width = 0.35
    
    bars1 = ax4.bar(x - width/2, symbol_adverse['mean'], width, 
                   label='平均逆行', color='orange', alpha=0.7)
    bars2 = ax4.bar(x + width/2, symbol_adverse['max'], width, 
                   label='最大逆行', color='red', alpha=0.7)
    
    ax4.set_xlabel('シンボル')
    ax4.set_ylabel('逆行幅 (%)')
    ax4.set_title('📈 シンボル別逆行')
    ax4.set_xticks(x)
    ax4.set_xticklabels(symbol_adverse.index)
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_time_analysis(df: pd.DataFrame, filename: str):
    """時間分析"""
    df['hour'] = df['entry_time'].dt.hour
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))
    fig.suptitle('🕐 時間別分析', fontsize=16, fontweight='bold')
    
    # 1. 時間別取引数
    hourly_counts = df['hour'].value_counts().sort_index()
    ax1.bar(hourly_counts.index, hourly_counts.values, alpha=0.7, color='steelblue')
    ax1.set_xlabel('時間 (UTC)')
    ax1.set_ylabel('取引数')
    ax1.set_title('📊 時間別取引数')
    ax1.set_xticks(range(24))
    ax1.grid(True, alpha=0.3)
    
    # 2. 時間別平均PnL
    hourly_pnl = df.groupby('hour')['net_profit_pct'].mean()
    colors = ['green' if x >= 0 else 'red' for x in hourly_pnl.values]
    
    bars = ax2.bar(hourly_pnl.index, hourly_pnl.values, color=colors, alpha=0.7)
    ax2.set_xlabel('時間 (UTC)')
    ax2.set_ylabel('平均PnL (%)')
    ax2.set_title('📈 時間別平均PnL')
    ax2.set_xticks(range(24))
    ax2.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def create_risk_return_analysis(df: pd.DataFrame, filename: str):
    """リスク・リターン分析"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('⚖️ リスク・リターン分析', fontsize=16, fontweight='bold')
    
    # 1. リターン vs リスク (標準偏差)
    symbol_stats = df.groupby('symbol').agg({
        'net_profit_pct': ['mean', 'std'],
        'adverse_movement': 'mean'
    })
    
    returns = symbol_stats[('net_profit_pct', 'mean')]
    risks = symbol_stats[('net_profit_pct', 'std')]
    
    for i, symbol in enumerate(returns.index):
        ax1.scatter(risks.iloc[i], returns.iloc[i], s=100, alpha=0.7, label=symbol)
        ax1.annotate(symbol, (risks.iloc[i], returns.iloc[i]), 
                    xytext=(5, 5), textcoords='offset points')
    
    ax1.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax1.axvline(0, color='black', linestyle='-', alpha=0.5)
    ax1.set_xlabel('リスク (標準偏差) (%)')
    ax1.set_ylabel('リターン (平均PnL) (%)')
    ax1.set_title('📊 リスク・リターン散布図')
    ax1.grid(True, alpha=0.3)
    
    # 2. シャープレシオ
    sharpe_ratios = returns / risks
    sharpe_ratios = sharpe_ratios.fillna(0)  # NaN処理
    
    colors = ['green' if x >= 0 else 'red' for x in sharpe_ratios]
    bars = ax2.bar(range(len(sharpe_ratios)), sharpe_ratios.values, 
                  color=colors, alpha=0.7)
    ax2.set_xticks(range(len(sharpe_ratios)))
    ax2.set_xticklabels(sharpe_ratios.index)
    ax2.set_ylabel('シャープレシオ')
    ax2.set_title('📈 シンボル別シャープレシオ')
    ax2.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax2.grid(True, alpha=0.3)
    
    # 3. ドローダウン分析 (累積PnL)
    df_sorted = df.sort_values('entry_time').reset_index(drop=True)
    df_sorted['cumulative_pnl'] = df_sorted['net_profit_pct'].cumsum()
    df_sorted['running_max'] = df_sorted['cumulative_pnl'].expanding().max()
    df_sorted['drawdown'] = df_sorted['cumulative_pnl'] - df_sorted['running_max']
    
    ax3.fill_between(range(len(df_sorted)), df_sorted['drawdown'], 0, 
                    color='red', alpha=0.3, label='ドローダウン')
    ax3.plot(range(len(df_sorted)), df_sorted['drawdown'], color='red', linewidth=2)
    ax3.set_xlabel('取引番号')
    ax3.set_ylabel('ドローダウン (%)')
    ax3.set_title('📉 ドローダウン推移')
    ax3.grid(True, alpha=0.3)
    ax3.legend()
    
    # 最大ドローダウンを表示
    max_drawdown = df_sorted['drawdown'].min()
    ax3.text(0.02, 0.98, f'最大DD: {max_drawdown:.3f}%', 
            transform=ax3.transAxes, fontsize=12, fontweight='bold',
            bbox=dict(boxstyle="round,pad=0.3", facecolor="orange", alpha=0.7),
            verticalalignment='top')
    
    # 4. 取引成功率 vs 平均リターン
    symbol_winrates = df.groupby('symbol').apply(
        lambda x: (x['net_profit_pct'] > 0).sum() / len(x) * 100
    )
    symbol_returns = df.groupby('symbol')['net_profit_pct'].mean()
    
    for symbol in symbol_winrates.index:
        ax4.scatter(symbol_winrates[symbol], symbol_returns[symbol], 
                   s=100, alpha=0.7, label=symbol)
        ax4.annotate(symbol, (symbol_winrates[symbol], symbol_returns[symbol]), 
                    xytext=(5, 5), textcoords='offset points')
    
    ax4.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax4.set_xlabel('勝率 (%)')
    ax4.set_ylabel('平均リターン (%)')
    ax4.set_title('🎯 勝率 vs 平均リターン')
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

def print_detailed_stats(stats: dict):
    """詳細統計を出力"""
    print("\n" + "=" * 80)
    print("📊 詳細統計レポート")
    print("=" * 80)
    
    print(f"🔢 総取引数: {stats['total_trades']} 件")
    print(f"✅ 勝ちトレード: {stats['winning_trades']} 件 ({stats['win_rate']:.1f}%)")
    print(f"❌ 負けトレード: {stats['losing_trades']} 件 ({stats['loss_rate']:.1f}%)")
    print()
    
    print(f"💰 総PnL: {stats['total_pnl']:.4f}%")
    print(f"📈 平均勝ちPnL: {stats['avg_win_pnl']:.4f}%")
    print(f"📉 平均負けPnL: {stats['avg_loss_pnl']:.4f}%")
    print(f"🚀 最大勝ち: {stats['max_win']:.4f}%")
    print(f"💥 最大負け: {stats['max_loss']:.4f}%")
    print()
    
    print(f"⚖️ Profit Factor: {stats['profit_factor']:.3f}")
    print(f"📊 Sharpe Ratio: {stats['sharpe_ratio']:.3f}")
    print(f"⏱️ 平均保有時間: {stats['avg_duration']:.1f} 分")
    print(f"⚠️ 平均逆行: {stats['avg_adverse_movement']:.3f}%")
    print(f"🔥 最大逆行: {stats['max_adverse_movement']:.3f}%")
    
    print("=" * 80)

def main():
    parser = argparse.ArgumentParser(description="バックテスト結果可視化")
    parser.add_argument("--csv", default="backtest_trades.csv", 
                       help="バックテスト結果CSVファイル")
    parser.add_argument("--output", default="backtest_charts", 
                       help="出力ディレクトリ")
    
    args = parser.parse_args()
    
    # データ読み込み
    try:
        df = load_backtest_results(args.csv)
        print(f"📊 {len(df)} 件の取引データを読み込みました")
    except FileNotFoundError:
        print(f"❌ ファイルが見つかりません: {args.csv}")
        return
    except Exception as e:
        print(f"❌ データ読み込みエラー: {e}")
        return
    
    # ダッシュボード作成
    try:
        create_comprehensive_dashboard(df, args.output)
    except Exception as e:
        print(f"❌ グラフ作成エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()