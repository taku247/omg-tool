#!/usr/bin/env python3
"""本番環境用のBot起動スクリプト"""

import asyncio
import yaml
import os
from pathlib import Path
import logging

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(project_root))

from src.bot import ArbitrageBot

def setup_production_logging():
    """本番環境用のログ設定"""
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/arbitrage_bot_prod.log'),
            logging.StreamHandler()  # 最小限のコンソール出力
        ]
    )

async def main():
    """本番環境でBotを起動"""
    
    # 本番環境用設定を読み込み
    config_path = project_root / "config" / "production_config.yaml"
    
    if not config_path.exists():
        print("ERROR: Production config file not found!")
        print(f"Expected: {config_path}")
        return
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 本番環境用ログ設定
    setup_production_logging()
    
    # 本番環境チェック
    if config.get('development_mode', True):
        print("WARNING: development_mode is enabled in production config!")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            return
    
    print("=== 本番環境でのBot起動 ===")
    print(f"Development mode: {config.get('development_mode', False)}")
    print("実装ログは表示されません")
    print()
    
    # 環境変数チェック
    required_env_vars = [
        'HYPERLIQUID_API_KEY', 'HYPERLIQUID_API_SECRET',
        'BYBIT_API_KEY', 'BYBIT_API_SECRET'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        print(f"ERROR: Missing environment variables: {missing_vars}")
        return
    
    # Botを初期化
    bot = ArbitrageBot(config)
    
    # 取引所を追加
    # await bot.add_exchange('hyperliquid', HyperliquidExchange(...))
    # await bot.add_exchange('bybit', BybitExchange(...))
    
    try:
        # Bot開始（本番モードなので実装ログは表示されない）
        await bot.start()
        
        print("Bot started in production mode.")
        
        # 実行継続
        while True:
            await asyncio.sleep(10)  # 本番環境では少し長めの間隔
            
    except KeyboardInterrupt:
        print("\nShutting down bot...")
        await bot.stop()
        print("Bot stopped.")
    except Exception as e:
        logging.error(f"Bot crashed: {e}")
        await bot.stop()
        raise

if __name__ == "__main__":
    asyncio.run(main())