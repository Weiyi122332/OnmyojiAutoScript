"""Parse warehouse OCR without treating missing text as a zero balance."""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import re
import unicodedata


RESOURCE_LABELS = {
    'coins': '金币',
    'stamina': '体力',
    'jade': '勾玉',
    'mystery_amulets': '蓝票',
}


@dataclass(frozen=True)
class ResourceAmount:
    quantity: int | None
    display: str
    exact: bool
    source: str
    error: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TextRegion:
    text: str
    left: float
    top: float
    width: float
    height: float


def normalize_text(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text)))


def parse_amount(text: str, *, allow_compact: bool = False) -> tuple[int, bool] | None:
    """Parse only a whole number field, preserving whether it was abbreviated."""
    text = normalize_text(text)
    match = re.fullmatch(r'(\d+|\d{1,3}(?:,\d{3})+)(?:\.(\d+))?([万亿]?)', text)
    if not match:
        return None
    whole, fraction, unit = match.groups()
    if (unit and not allow_compact) or (fraction and not unit):
        return None
    multiplier = {'': 1, '万': 10000, '亿': 100000000}[unit]
    try:
        number = Decimal(whole.replace(',', '') + (f'.{fraction}' if fraction else '')) * multiplier
    except InvalidOperation:
        return None
    if number != number.to_integral_value():
        return None
    return int(number), not bool(unit)


def owned_amount(texts: list[str], label: str, *, prefix: str = '持有') -> int | None:
    """Require the selected item's title and an explicitly labelled full count."""
    normalized = [normalize_text(text) for text in texts]
    if label not in normalized:
        return None
    for text in normalized:
        match = re.fullmatch(re.escape(prefix) + r'[:：]?(\d[\d,]*)', text)
        if match:
            parsed = parse_amount(match.group(1))
            if parsed is not None:
                return parsed[0]
    return None


def is_regular_amulet(texts: list[str]) -> bool:
    """Limited-time tickets must never pass the ordinary ticket title check."""
    normalized = [normalize_text(text) for text in texts]
    return ('神秘的符咒' in normalized
            and not any('限时' in text or '现时' in text for text in normalized))


def popup_owned_amount(regions: list[TextRegion], label: str) -> int | None:
    """Follow the popup title when the card moves with the randomized tap."""
    for title in regions:
        if normalize_text(title.text) != label:
            continue
        for count in regions:
            if abs(count.left - title.left) > 40 or not 16 <= count.top - title.top <= 80:
                continue
            quantity = owned_amount([label, count.text], label, prefix='已拥有')
            if quantity is not None:
                return quantity
    return None
