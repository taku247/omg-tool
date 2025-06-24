#!/usr/bin/env python3
"""
取引所手数料の差異を担保するテストコード
"""

import unittest
import sys
from pathlib import Path
from decimal import Decimal

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.fee_utils import get_exchange_fees, calculate_arbitrage_fees


class TestExchangeFees(unittest.TestCase):
    """取引所手数料の差異テスト"""
    
    def test_exchange_fee_differences(self):
        """各取引所の手数料が異なることを確認"""
        exchanges = ['hyperliquid', 'bybit', 'binance', 'gate', 'kucoin', 'bitget']
        fee_data = {}
        
        # 各取引所の手数料を取得
        for exchange in exchanges:
            fees = get_exchange_fees(exchange)
            fee_data[exchange] = {
                'maker': fees['maker_fee'],
                'taker': fees['taker_fee']
            }
        
        # 手数料が取引所間で異なることを確認
        maker_fees = [data['maker'] for data in fee_data.values()]
        taker_fees = [data['taker'] for data in fee_data.values()]
        
        # 少なくとも一つの取引所で手数料が異なることを確認
        assert len(set(maker_fees)) > 1, "Maker手数料が全取引所で同じです"
        assert len(set(taker_fees)) > 1, "Taker手数料が全取引所で同じです"
        
        print("✅ 取引所間で手数料が異なることを確認")
        for exchange, fees in fee_data.items():
            print(f"  {exchange}: Maker {float(fees['maker'])*100:.3f}%, Taker {float(fees['taker'])*100:.3f}%")
    
    def test_hyperliquid_specific_fees(self):
        """Hyperliquidの特殊な手数料設定を確認"""
        hl_fees = get_exchange_fees('hyperliquid')
        
        # Hyperliquidの期待される手数料
        expected_maker = Decimal('0.00013')  # 0.013%
        expected_taker = Decimal('0.000389') # 0.0389%
        
        assert hl_fees['maker_fee'] == expected_maker, f"Hyperliquid Maker手数料が期待値と異なります: {hl_fees['maker_fee']} != {expected_maker}"
        assert hl_fees['taker_fee'] == expected_taker, f"Hyperliquid Taker手数料が期待値と異なります: {hl_fees['taker_fee']} != {expected_taker}"
        
        print("✅ Hyperliquidの特殊手数料設定を確認")
        print(f"  Maker: {float(hl_fees['maker_fee'])*100:.4f}%")
        print(f"  Taker: {float(hl_fees['taker_fee'])*100:.4f}%")
    
    def test_arbitrage_fee_variations(self):
        """アービトラージペア間の手数料差異を確認"""
        position_size = Decimal('10000')
        
        # 異なる取引所ペアの組み合わせ
        test_pairs = [
            ('hyperliquid', 'bybit'),    # 低手数料ペア
            ('bitget', 'kucoin'),        # 高手数料ペア  
            ('binance', 'gate'),         # 中程度手数料ペア
            ('bybit', 'hyperliquid'),    # 逆方向ペア
        ]
        
        fee_results = {}
        
        for buy_ex, sell_ex in test_pairs:
            fee_info = calculate_arbitrage_fees(buy_ex, sell_ex, position_size)
            pair_name = f"{buy_ex}→{sell_ex}"
            fee_results[pair_name] = {
                'total_fee': fee_info['total_fee'],
                'buy_rate': fee_info['buy_fee_rate'],
                'sell_rate': fee_info['sell_fee_rate'],
                'total_rate': fee_info['total_fee'] / position_size
            }
        
        # 手数料が取引所ペア間で異なることを確認
        total_fees = [data['total_fee'] for data in fee_results.values()]
        assert len(set(total_fees)) > 1, "全ての取引所ペアで手数料が同じです"
        
        print("✅ アービトラージペア間の手数料差異を確認")
        for pair, data in fee_results.items():
            print(f"  {pair:20}: {float(data['total_rate'])*100:.3f}% (${float(data['total_fee']):.2f})")
        
        return fee_results
    
    def test_directional_fee_differences(self):
        """方向性による手数料差異を確認（A→B vs B→A）"""
        position_size = Decimal('10000')
        
        # 方向性テストペア
        directional_pairs = [
            ('hyperliquid', 'bybit'),
            ('binance', 'kucoin'),
            ('gate', 'bitget')
        ]
        
        for exchange_a, exchange_b in directional_pairs:
            # A→B方向
            fee_a_to_b = calculate_arbitrage_fees(exchange_a, exchange_b, position_size)
            # B→A方向  
            fee_b_to_a = calculate_arbitrage_fees(exchange_b, exchange_a, position_size)
            
            total_a_to_b = fee_a_to_b['total_fee']
            total_b_to_a = fee_b_to_a['total_fee']
            
            print(f"📊 {exchange_a.upper()}⇄{exchange_b.upper()}:")
            print(f"  {exchange_a}→{exchange_b}: {float(total_a_to_b/position_size)*100:.3f}%")
            print(f"  {exchange_b}→{exchange_a}: {float(total_b_to_a/position_size)*100:.3f}%")
            
            # 方向によって手数料が異なる可能性があることを確認
            # （必ずしも異なるとは限らないが、異なる場合があることを記録）
            if total_a_to_b != total_b_to_a:
                print(f"  ✅ 方向により手数料が異なります（差額: {float(abs(total_a_to_b - total_b_to_a)/position_size)*100:.4f}%）")
            else:
                print(f"  ℹ️  この組み合わせでは往復手数料が同じです")
    
    def test_fee_calculation_accuracy(self):
        """手数料計算の精度を確認"""
        # 既知の値での検証
        hyperliquid_fees = get_exchange_fees('hyperliquid')
        bybit_fees = get_exchange_fees('bybit')
        
        position_size = Decimal('1000')
        expected_hl_taker = position_size * hyperliquid_fees['taker_fee']  # 1000 * 0.000389 = 0.389
        expected_bybit_taker = position_size * bybit_fees['taker_fee']     # 1000 * 0.0006 = 0.6
        
        fee_info = calculate_arbitrage_fees('hyperliquid', 'bybit', position_size)
        
        assert fee_info['buy_fee'] == expected_hl_taker, f"買い手数料計算エラー: {fee_info['buy_fee']} != {expected_hl_taker}"
        assert fee_info['sell_fee'] == expected_bybit_taker, f"売り手数料計算エラー: {fee_info['sell_fee']} != {expected_bybit_taker}"
        assert fee_info['total_fee'] == expected_hl_taker + expected_bybit_taker, "総手数料計算エラー"
        
        print("✅ 手数料計算の精度を確認")
        print(f"  Hyperliquid buy fee: ${float(fee_info['buy_fee']):.3f}")
        print(f"  Bybit sell fee: ${float(fee_info['sell_fee']):.3f}")
        print(f"  Total fee: ${float(fee_info['total_fee']):.3f}")
    
    def test_lowest_and_highest_fee_pairs(self):
        """最低・最高手数料ペアの特定"""
        exchanges = ['hyperliquid', 'bybit', 'binance', 'gate', 'kucoin', 'bitget']
        position_size = Decimal('10000')
        
        fee_matrix = {}
        
        # 全ペアの手数料を計算
        for i, buy_ex in enumerate(exchanges):
            for j, sell_ex in enumerate(exchanges):
                if i != j:  # 同一取引所は除外
                    fee_info = calculate_arbitrage_fees(buy_ex, sell_ex, position_size)
                    pair_key = f"{buy_ex}→{sell_ex}"
                    fee_matrix[pair_key] = float(fee_info['total_fee'] / position_size) * 100
        
        # 最低・最高手数料ペアを特定
        min_fee_pair = min(fee_matrix.items(), key=lambda x: x[1])
        max_fee_pair = max(fee_matrix.items(), key=lambda x: x[1])
        
        print("📊 手数料ペア分析:")
        print(f"  🟢 最低手数料ペア: {min_fee_pair[0]} ({min_fee_pair[1]:.3f}%)")
        print(f"  🔴 最高手数料ペア: {max_fee_pair[0]} ({max_fee_pair[1]:.3f}%)")
        print(f"  📈 手数料差: {max_fee_pair[1] - min_fee_pair[1]:.3f}%")
        
        # 手数料に明確な差があることを確認
        fee_difference = max_fee_pair[1] - min_fee_pair[1]
        assert fee_difference > 0.01, f"手数料差が小さすぎます: {fee_difference:.4f}%"
        
        return fee_matrix
    
    def test_config_vs_hardcoded_consistency(self):
        """Config値とハードコード値の整合性確認"""
        # 期待される値（configに設定した値）
        expected_fees = {
            'hyperliquid': {'maker': Decimal('0.00013'), 'taker': Decimal('0.000389')},
            'bybit': {'maker': Decimal('0.0001'), 'taker': Decimal('0.0006')},
            'binance': {'maker': Decimal('0.0002'), 'taker': Decimal('0.0004')},
            'gate': {'maker': Decimal('0.0002'), 'taker': Decimal('0.0005')},
            'kucoin': {'maker': Decimal('0.0002'), 'taker': Decimal('0.0006')},
            'bitget': {'maker': Decimal('0.0002'), 'taker': Decimal('0.0006')}
        }
        
        for exchange, expected in expected_fees.items():
            actual_fees = get_exchange_fees(exchange)
            
            assert actual_fees['maker_fee'] == expected['maker'], \
                f"{exchange} Maker手数料不一致: {actual_fees['maker_fee']} != {expected['maker']}"
            assert actual_fees['taker_fee'] == expected['taker'], \
                f"{exchange} Taker手数料不一致: {actual_fees['taker_fee']} != {expected['taker']}"
        
        print("✅ Config値とコード値の整合性を確認")


def run_comprehensive_fee_test():
    """包括的な手数料テストの実行"""
    print("=" * 80)
    print("🏦 取引所手数料差異担保テスト")
    print("=" * 80)
    
    test_instance = TestExchangeFees()
    
    try:
        print("\n1️⃣ 取引所間手数料差異テスト")
        test_instance.test_exchange_fee_differences()
        
        print("\n2️⃣ Hyperliquid特殊手数料テスト")
        test_instance.test_hyperliquid_specific_fees()
        
        print("\n3️⃣ アービトラージペア手数料差異テスト")
        test_instance.test_arbitrage_fee_variations()
        
        print("\n4️⃣ 方向性手数料差異テスト")
        test_instance.test_directional_fee_differences()
        
        print("\n5️⃣ 手数料計算精度テスト")
        test_instance.test_fee_calculation_accuracy()
        
        print("\n6️⃣ 最低・最高手数料ペア特定テスト")
        fee_matrix = test_instance.test_lowest_and_highest_fee_pairs()
        
        print("\n7️⃣ Config整合性テスト")
        test_instance.test_config_vs_hardcoded_consistency()
        
        print("\n" + "=" * 80)
        print("✅ 全テスト合格: 取引所間手数料差異が正しく実装されています")
        print("=" * 80)
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ テスト失敗: {e}")
        return False
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        return False


if __name__ == "__main__":
    success = run_comprehensive_fee_test()
    exit(0 if success else 1)