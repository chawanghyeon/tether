from demo_app.pricing import price_with_vat


def test_price_with_vat() -> None:
    assert price_with_vat(1000) == 1100
