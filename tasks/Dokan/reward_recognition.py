"""Read mystery amulet quantities from saved dojo reward screenshots."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


BLUE_TICKET_TEMPLATE = Path(__file__).with_name('res') / 'dokan_reward_blue_ticket.png'
REWARD_AREA = (250, 160, 805, 270)
BLUE_TICKET_MATCH_THRESHOLD = 0.88


@lru_cache(maxsize=1)
def _blue_ticket_template() -> np.ndarray:
    template = cv2.imdecode(np.fromfile(BLUE_TICKET_TEMPLATE, dtype=np.uint8), cv2.IMREAD_COLOR)
    if template is None:
        raise ValueError('Cannot load the dojo blue ticket template')
    return cv2.cvtColor(template, cv2.COLOR_BGR2RGB)


def _read_quantity(image: np.ndarray) -> tuple[str, float]:
    # Reuse OAS's local OCR service; never send reward screenshots to a vision API.
    from module.ocr.models import get_ocr_model

    return get_ocr_model().ocr_single_line(image)


def count_blue_tickets_in_png(image_bytes: bytes) -> int | None:
    if not image_bytes:
        return None
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    return count_blue_tickets(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def count_blue_tickets(image: np.ndarray,
                       read_quantity: Callable[[np.ndarray], tuple[str, float]] | None = None) -> int | None:
    """Return zero if no blue ticket is shown, or None if its count is unreadable.

    Input uses OAS's RGB image format and the game's native 1280 by 720 layout.
    """
    if image is None or image.shape != (720, 1280, 3):
        return None
    x, y, w, h = REWARD_AREA
    reward_area = image[y:y + h, x:x + w]
    template = _blue_ticket_template()
    scores = cv2.matchTemplate(reward_area, template, cv2.TM_CCOEFF_NORMED)
    total = 0
    while True:
        _, score, _, position = cv2.minMaxLoc(scores)
        if score < BLUE_TICKET_MATCH_THRESHOLD:
            return total
        px, py = position
        # The template excludes the number. Read only the card's lower right corner.
        quantity = reward_area[py + 66:py + 97, px + 46:px + 90]
        if quantity.shape[:2] != (31, 44):
            return None
        white = (quantity.min(axis=2) > 160) & (np.ptp(quantity, axis=2) < 65)
        if np.count_nonzero(white) < 8:
            # A single reward has no printed quantity in the game UI.
            count = 1
        else:
            # Reward animation backgrounds can make otherwise clear digits unreadable.
            # Retry with only the white number, keeping the same confidence requirement.
            number_only = cv2.cvtColor(white.astype(np.uint8) * 255, cv2.COLOR_GRAY2RGB)
            count = None
            for candidate in (quantity, number_only):
                enlarged = cv2.resize(candidate, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                text, confidence = (read_quantity or _read_quantity)(enlarged)
                text = str(text).strip()
                if confidence >= 0.8 and re.fullmatch(r'[1-9]\d{0,2}', text):
                    count = int(text)
                    break
            if count is None:
                return None
        total += count
        # Suppress neighboring hits of this same icon, while preserving other cards.
        th, tw = template.shape[:2]
        scores[max(0, py - th // 2):py + th // 2 + 1,
               max(0, px - tw // 2):px + tw // 2 + 1] = -1
