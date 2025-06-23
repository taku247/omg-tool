#!/usr/bin/env python3
"""Bitget API 構造デバッグ"""

import asyncio
import aiohttp
import json

async def debug_bitget_api():
    """Bitget API 構造確認"""
    
    print("🔍 Bitget API 構造デバッグ")
    print("=" * 60)
    
    base_url = "https://api.bitget.com"
    
    async with aiohttp.ClientSession() as session:
        
        # 1. 利用可能な契約一覧
        print("\n📜 利用可能な契約一覧:")
        contracts_url = f"{base_url}/api/mix/v1/market/contracts"
        params = {"productType": "UMCBL"}  # USDT Perpetuals
        
        async with session.get(contracts_url, params=params) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                result = await response.json()
                print(f"Response: {json.dumps(result, indent=2)[:1000]}...")
                
                if result.get("code") == "00000":
                    data = result.get("data", [])
                    print(f"Total contracts: {len(data)}")
                    
                    # BTC関連の契約を探す
                    btc_contracts = [c for c in data if "BTC" in c.get("symbol", "")]
                    print(f"BTC-related contracts:")
                    for contract in btc_contracts[:5]:
                        print(f"  Symbol: {contract.get('symbol')}")
                        print(f"  Base: {contract.get('baseCoin')}")
                        print(f"  Quote: {contract.get('quoteCoin')}")
                        print(f"  Status: {contract.get('symbolStatus')}")
                        print(f"  Product Type: {contract.get('productType')}")
                        print("-" * 30)
            else:
                print(f"Error: {await response.text()}")
        
        # 2. ティッカー情報テスト（複数の形式で試す）
        print("\n📊 ティッカー情報テスト:")
        ticker_url = f"{base_url}/api/mix/v1/market/ticker"
        
        # 複数のシンボル形式で試す
        test_symbols = ["BTCUSDT_UMCBL", "BTCUSDT", "BTC-USDT"]
        
        for symbol in test_symbols:
            print(f"\nテスト中: {symbol}")
            params = {"symbol": symbol}
            
            async with session.get(ticker_url, params=params) as response:
                print(f"Status: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") == "00000":
                        print(f"✅ 成功: {symbol}")
                        data = result.get("data")
                        if data:
                            print(f"   Last: {data.get('last')}")
                            print(f"   BestBid: {data.get('bestBid')}")
                            print(f"   BestAsk: {data.get('bestAsk')}")
                    else:
                        print(f"❌ API Error: {result.get('msg')}")
                else:
                    error_text = await response.text()
                    print(f"❌ HTTP Error: {error_text}")

if __name__ == "__main__":
    try:
        asyncio.run(debug_bitget_api())
    except Exception as e:
        print(f"Error: {e}")