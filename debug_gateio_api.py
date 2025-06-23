#!/usr/bin/env python3
"""Gate.io API レスポンス構造デバッグ"""

import asyncio
import aiohttp
import json

async def debug_gateio_api():
    """Gate.io API レスポンス構造確認"""
    
    print("🔍 Gate.io API レスポンス構造デバッグ")
    print("=" * 60)
    
    base_url = "https://api.gateio.ws"
    
    async with aiohttp.ClientSession() as session:
        
        # 1. ティッカー情報テスト
        print("\n📊 ティッカー情報テスト:")
        ticker_url = f"{base_url}/api/v4/futures/usdt/tickers"
        
        async with session.get(ticker_url) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Response type: {type(data)}")
                if isinstance(data, list) and data:
                    print(f"Array length: {len(data)}")
                    print(f"First item keys: {list(data[0].keys())}")
                    print(f"First few items:")
                    for i, item in enumerate(data[:3]):
                        print(f"  [{i}]: {item}")
                else:
                    print(f"Data: {data}")
            else:
                print(f"Error: {await response.text()}")
        
        # 2. 特定契約のティッカーテスト
        print("\n📊 特定契約ティッカーテスト (BTC_USDT):")
        ticker_url_specific = f"{base_url}/api/v4/futures/usdt/tickers"
        params = {"contract": "BTC_USDT"}
        
        async with session.get(ticker_url_specific, params=params) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Response: {json.dumps(data, indent=2)}")
            else:
                print(f"Error: {await response.text()}")
        
        # 3. 板情報テスト
        print("\n📋 板情報テスト (BTC_USDT):")
        book_url = f"{base_url}/api/v4/futures/usdt/order_book"
        book_params = {"contract": "BTC_USDT", "limit": 5}
        
        async with session.get(book_url, params=book_params) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Response: {json.dumps(data, indent=2)}")
            else:
                print(f"Error: {await response.text()}")
        
        # 4. 利用可能な契約一覧
        print("\n📜 利用可能な契約一覧:")
        contracts_url = f"{base_url}/api/v4/futures/usdt/contracts"
        
        async with session.get(contracts_url) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                data = await response.json()
                if isinstance(data, list):
                    print(f"Total contracts: {len(data)}")
                    btc_contracts = [c for c in data if "BTC" in c.get("name", "")]
                    print(f"BTC-related contracts: {[c.get('name') for c in btc_contracts[:5]]}")
                else:
                    print(f"Data: {data}")
            else:
                print(f"Error: {await response.text()}")


if __name__ == "__main__":
    try:
        asyncio.run(debug_gateio_api())
    except Exception as e:
        print(f"Error: {e}")