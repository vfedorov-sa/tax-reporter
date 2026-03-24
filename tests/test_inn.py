from __future__ import annotations

import pytest

from tax_reporter.inn import complete_inn, is_valid_inn, is_valid_kpp


@pytest.mark.parametrize("value", ["5001112228", "6903334446", "500111222355", "690333444503"])
def test_accepts_correct_checksums(value: str) -> None:
    assert is_valid_inn(value)


@pytest.mark.parametrize(
    "value",
    [
        "5001112227",  # испорчен контрольный разряд организации
        "500111222354",  # испорчен последний разряд физлица
        "500111222365",  # испорчен одиннадцатый разряд
        "123456789012",  # случайные цифры
        "50011122",  # короче десяти
        "50011122283",  # одиннадцать цифр — такой длины ИНН не бывает
        "50011122822x",
        "",
    ],
)
def test_rejects_broken_values(value: str) -> None:
    assert not is_valid_inn(value)


@pytest.mark.parametrize("prefix", ["500111222", "7701234567", "000000000"])
def test_complete_inn_produces_valid_value(prefix: str) -> None:
    assert is_valid_inn(complete_inn(prefix))


def test_complete_inn_rejects_wrong_length() -> None:
    with pytest.raises(ValueError):
        complete_inn("123")


@pytest.mark.parametrize("value", ["500101001", "7714AB123"])
def test_kpp_format(value: str) -> None:
    assert is_valid_kpp(value)


@pytest.mark.parametrize("value", ["50010100", "5001010011", "AB01010011"])
def test_kpp_rejects_wrong_shape(value: str) -> None:
    assert not is_valid_kpp(value)
