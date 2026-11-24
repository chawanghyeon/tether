VAT_RATE = 0.1


def price_with_vat(net: int) -> int:
    return round(net * (1 + VAT_RATE))
