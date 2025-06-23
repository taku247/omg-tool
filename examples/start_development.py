#!/usr/bin/env python3
"""開発環境用のBot起動スクリプト"""

import asyncio
import yaml
import os
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(project_root))

from src.bot import ArbitrageBot

async def main():
    """開発環境でBotを起動"""
    
    # 開発環境用設定を読み込み
    config_path = project_root / "config" / "bot_config.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    print("=== 開発環境でのBot起動 ===")
    print(f"Development mode: {config.get('development_mode', False)}")
    print("実装ログが表示されます")
    print()
    
    # Botを初期化
    bot = ArbitrageBot(config)
    
    # 取引所を追加（デモ用）
    # await bot.add_exchange('hyperliquid', HyperliquidExchange(...))
    # await bot.add_exchange('bybit', BybitExchange(...))
    
    try:
        # Bot開始（開発モードなので実装ログが表示される）
        await bot.start()
        
        print("Bot started in development mode. Press Ctrl+C to stop.")
        
        # 実行継続
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down bot...")
        await bot.stop()
        print("Bot stopped.")

if __name__ == "__main__":
    asyncio.run(main())