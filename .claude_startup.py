#!/usr/bin/env python3
"""
Claude Code起動時に実行されるスクリプト
実装ログの読み込みと表示を行う
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """Claude Code起動時のメイン処理"""
    try:
        from src.utils.implementation_logger import log_startup_summary
        
        print("=" * 60)
        print("🤖 CLAUDE CODE STARTUP - OMG ARBITRAGE BOT PROJECT")
        print("=" * 60)
        
        # 実装ログサマリーを表示
        log_startup_summary()
        
        print("=" * 60)
        print("Ready for development! 🚀")
        print("=" * 60)
        print()
        
    except Exception as e:
        print(f"Warning: Could not load implementation logs: {e}")
        print("Continuing without log summary...")

if __name__ == "__main__":
    main()