#!/usr/bin/env python3
"""price_logger.py の動作確認用テストスクリプト"""

import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from price_logger import main


async def test_price_logger():
    """価格ロガーを短時間テスト"""
    print("🧪 価格ロガーテスト（10秒間）")
    print("=" * 60)
    
    # テスト用の引数を設定（全6取引所対応）
    test_args = [
        "--symbols", "BTC", "ETH",
        "--interval", "1.0",
        # 全6取引所を指定（デフォルトと同じなので--exchangesは不要だが明示的に指定）
        "--exchanges", "Hyperliquid", "Bybit", "Binance", "Gateio", "Bitget", "KuCoin"
    ]
    
    # sys.argvを一時的に置き換え
    original_argv = sys.argv
    sys.argv = ["test_price_logger.py"] + test_args
    
    try:
        # 10秒後にキャンセル
        task = asyncio.create_task(main())
        await asyncio.sleep(10)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
            
        print("\n✅ テスト完了！")
        print("\n📁 出力ファイルを確認してください:")
        
        # 出力ディレクトリを確認
        data_dir = Path("data/price_logs")
        if data_dir.exists():
            for file in data_dir.rglob("*.csv*"):
                print(f"   {file}")
                
    finally:
        # sys.argvを元に戻す
        sys.argv = original_argv


if __name__ == "__main__":
    try:
        asyncio.run(test_price_logger())
    except KeyboardInterrupt:
        print("\n👋 テスト中断")
    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()