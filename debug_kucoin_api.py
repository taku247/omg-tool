#!/usr/bin/env python3
"""KuCoin API 構造デバッグ"""

import asyncio
import aiohttp
import json

async def debug_kucoin_api():
    """KuCoin API 構造確認"""
    
    print("🔍 KuCoin API 構造デバッグ")
    print("=" * 60)
    
    base_url = "https://api-futures.kucoin.com"
    
    async with aiohttp.ClientSession() as session:
        
        # 1. 利用可能な契約一覧
        print("\n📜 利用可能な契約一覧:")
        contracts_url = f"{base_url}/api/v1/contracts/active"
        
        async with session.get(contracts_url) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                result = await response.json()
                print(f"Response type: {type(result)}")
                
                if result.get("code") == "200000":
                    data = result.get("data", [])
                    print(f"Total contracts: {len(data)}")
                    
                    # BTC関連の契約を探す
                    btc_contracts = [c for c in data if "BTC" in c.get("symbol", "") or "XBT" in c.get("symbol", "")]
                    print(f"BTC-related contracts:")
                    for contract in btc_contracts[:5]:
                        print(f"  Symbol: {contract.get('symbol')}")
                        print(f"  BaseCurrency: {contract.get('baseCurrency')}")
                        print(f"  QuoteCurrency: {contract.get('quoteCurrency')}")
                        print(f"  Status: {contract.get('status')}")
                        print(f"  Type: {contract.get('type')}")
                        print("-" * 30)
                else:
                    print(f"API Error: {result.get('msg')}")
            else:
                print(f"Error: {await response.text()}")
        
        # 2. ティッカー情報テスト（複数の形式で試す）
        print("\n📊 ティッカー情報テスト:")
        ticker_url = f"{base_url}/api/v1/ticker"
        
        # 複数のシンボル形式で試す
        test_symbols = ["XBTUSDTM", "BTCUSDTM", "XBTUSDM"]
        
        for symbol in test_symbols:
            print(f"\nテスト中: {symbol}")
            params = {"symbol": symbol}
            
            async with session.get(ticker_url, params=params) as response:
                print(f"Status: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") == "200000":
                        print(f"✅ 成功: {symbol}")
                        data = result.get("data")
                        if data:
                            print(f"   Price: {data.get('price')}")
                            print(f"   BestBidPrice: {data.get('bestBidPrice')}")
                            print(f"   BestAskPrice: {data.get('bestAskPrice')}")
                    else:
                        print(f"❌ API Error: {result.get('msg')}")
                else:
                    error_text = await response.text()
                    print(f"❌ HTTP Error: {error_text}")
                    
        # 3. 板情報テスト（複数のエンドポイントで試す）
        print("\n📋 板情報テスト:")
        
        # 複数の板情報エンドポイントを試す
        orderbook_endpoints = [
            "/api/v1/level2_market_data",
            "/api/v1/level2/snapshot",
            "/api/v1/level2/depth20",
            "/api/v1/level2/depth100"
        ]
        
        for endpoint in orderbook_endpoints:
            print(f"\nテスト中: {endpoint}")
            url = f"{base_url}{endpoint}"
            params = {"symbol": "XBTUSDTM"}
            
            async with session.get(url, params=params) as response:
                print(f"Status: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") == "200000":
                        print(f"✅ 成功: {endpoint}")
                        data = result.get("data")
                        if data:
                            bids = data.get("bids", [])
                            asks = data.get("asks", [])
                            print(f"   Bids count: {len(bids)}")
                            print(f"   Asks count: {len(asks)}")
                            if bids:
                                print(f"   Best bid: {bids[0]}")
                            if asks:
                                print(f"   Best ask: {asks[0]}")
                    else:
                        print(f"❌ API Error: {result.get('msg')}")
                else:
                    error_text = await response.text()
                    print(f"❌ HTTP Error: {error_text}")

if __name__ == "__main__":
    try:
        asyncio.run(debug_kucoin_api())
    except Exception as e:
        print(f"Error: {e}")