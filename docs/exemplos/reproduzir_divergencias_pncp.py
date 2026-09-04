"""Experimento offline: reproduz os 15 totais divergentes de Xique-Xique.

Dados observados na API pública em 04/09/2026. Não acessa rede ou banco,
não altera registros e NÃO representa o código interno de nenhuma plataforma.
A transformação é uma hipótese sobre a origem dos números, não uma correção.
"""

from decimal import Decimal

CASES = [
    (2, '12', '1226.70', '1472040000000.0001'),
    (3, '36', '1348.88', '485596800000.0001'),
    (5, '12', '1785.48', '2142576000000.0002'),
    (7, '12', '1129.24', '1355088000000.0001'),
    (15, '6', '476.88', '2861279999999.9997'),
    (21, '12', '1263.76', '1516511999999.9999'),
    (23, '6', '1220.12', '732071999999.9999'),
    (27, '20', '1027.88', '2055760000000.0002'),
    (36, '12', '433.62', '5203440000000.0005'),
    (37, '180', '4523.22', '814179600000.0001'),
    (38, '40', '4722.22', '1888888000000.0002'),
    (39, '36', '613.53', '2208707999999.9998'),
    (42, '6', '425.63', '2553779999999.9997'),
    (45, '6', '512.12', '3072720000000.0003'),
    (46, '12', '1225.88', '1471056000000.0001'),
]


def candidate(quantity: str, unit_price: str) -> tuple[str, Decimal]:
    binary_product_text = str(float(quantity) * float(unit_price))
    # Hipótese: uma conversão remove o separador e recoloca quatro casas.
    assert 'e' not in binary_product_text.lower(), 'Experimento limitado a estes casos'
    scaled = Decimal(binary_product_text.replace('.', '')) / Decimal(10000)
    return binary_product_text, scaled


def main() -> None:
    for item, quantity, unit_price, observed in CASES:
        text, reproduced = candidate(quantity, unit_price)
        expected = Decimal(quantity) * Decimal(unit_price)
        assert reproduced == Decimal(observed), (item, reproduced, observed)
        print(f'Item {item}: decimal={expected}; float={text}; reproduzido={reproduced}')

    # Controle negativo: a mesma hipótese produziria erro, mas a API está correta.
    _, first_hypothesis = candidate('24', '674.44')
    assert first_hypothesis != Decimal('16186.5600')
    assert Decimal('24') * Decimal('674.44') == Decimal('16186.5600')
    print('15/15 divergencias reproduzidas exatamente, incluindo quatro casas decimais.')
    print('Controle negativo: item 1 NAO segue a transformacao. Nao e regra universal.')

    # Caso USP: divergência no campo quantidade, não na multiplicação do total.
    assert Decimal('91100000') * Decimal('91100') == Decimal('8299210000000')
    assert Decimal('1') * Decimal('91100') == Decimal('91100')
    print('USP: total publicado reproduzido a partir da quantidade divergente.')


if __name__ == '__main__':
    main()
