"""Проверка контрольных разрядов ИНН по методике ФНС."""

from __future__ import annotations

_LEGAL_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_PERSON_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_PERSON_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _control_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(weights, digits, strict=True)) % 11 % 10


def is_valid_inn(value: str) -> bool:
    """ИНН организации — 10 цифр с одним контрольным разрядом, физлица — 12 с двумя."""
    if not value or not value.isdigit():
        return False

    digits = [int(c) for c in value]
    if len(digits) == 10:
        return _control_digit(digits[:9], _LEGAL_WEIGHTS) == digits[9]
    if len(digits) == 12:
        return (
            _control_digit(digits[:10], _PERSON_WEIGHTS_11) == digits[10]
            and _control_digit(digits[:11], _PERSON_WEIGHTS_12) == digits[11]
        )
    return False


def is_valid_kpp(value: str) -> bool:
    """КПП — 9 знаков: 4 цифры кода налогового органа, 2 знака причины, 3 цифры номера."""
    if len(value) != 9:
        return False
    return value[:4].isdigit() and value[4:6].isalnum() and value[6:].isdigit()


def complete_inn(prefix: str) -> str:
    """Дописывает контрольные разряды к префиксу — нужно для синтетических данных."""
    if not prefix.isdigit():
        raise ValueError("префикс ИНН должен состоять из цифр")

    digits = [int(c) for c in prefix]
    if len(prefix) == 9:
        return prefix + str(_control_digit(digits, _LEGAL_WEIGHTS))
    if len(prefix) == 10:
        eleventh = _control_digit(digits, _PERSON_WEIGHTS_11)
        twelfth = _control_digit(digits + [eleventh], _PERSON_WEIGHTS_12)
        return f"{prefix}{eleventh}{twelfth}"
    raise ValueError("ожидается 9 цифр для организации или 10 для физлица")
