"""Read four warehouse balances using ADB screenshots and the shared OCR RPC."""

from datetime import datetime
from pathlib import Path
import time

import cv2
import numpy as np

from tasks.ResourceInventory.recognition import (
    RESOURCE_LABELS, ResourceAmount, is_regular_amulet, normalize_text,
    owned_amount, parse_amount, popup_owned_amount, TextRegion,
)


class InventoryRecognitionError(RuntimeError):
    pass


class WarehouseReader:
    HEADER = (80, 10, 160, 52)
    SIDEBAR = (45, 175, 190, 495)
    GRID = (265, 182, 520, 488)
    DETAIL = (850, 108, 265, 89)
    POPUP = (270, 96, 795, 134)
    # The entire icon search area ends at x=740; the plus starts near x=819.
    STAMINA_SAFE_REGION = (660, 2, 80, 55)
    MAX_SCROLLS = 8

    def __init__(self, transport, ocr, evidence_dir: Path | None = None):
        self.transport = transport
        self.ocr = ocr
        self.evidence_dir = evidence_dir
        self.image: np.ndarray | None = None
        self.evidence: dict[str, str] = {}
        self.templates: dict[str, np.ndarray] = {}

    def capture(self) -> np.ndarray:
        self.image = self.transport.capture()
        return self.image

    def _crop(self, roi: tuple[int, int, int, int]) -> np.ndarray:
        x, y, w, h = roi
        return self.image[y:y + h, x:x + w]

    def _texts(self, roi) -> list[str]:
        return [item.ocr_text for item in self.ocr.detect_and_ocr(self._crop(roi))
                if item.score >= 0.8]

    def _find_text(self, text: str, roi) -> tuple[int, int, int, int] | None:
        for item in self.ocr.detect_and_ocr(self._crop(roi)):
            if item.score < 0.8 or normalize_text(item.ocr_text) != text:
                continue
            left, top = np.min(item.box, axis=0)
            right, bottom = np.max(item.box, axis=0)
            return (round(roi[0] + left + 3), round(roi[1] + top + 3),
                    max(1, round(right - left - 6)), max(1, round(bottom - top - 6)))
        return None

    def _tap(self, area: tuple[int, int, int, int], delay: float = 0.45) -> None:
        self.transport.tap_area(area)
        time.sleep(delay)
        self.capture()

    def _in_warehouse(self) -> bool:
        return '纳物库' in ''.join(self._texts(self.HEADER))

    def _dismiss_popup(self) -> None:
        # Warehouse title strip: no currency plus, item, use, or purchase control.
        self._tap((273, 22, 56, 31), delay=0.2)

    def _save_evidence(self, name: str) -> None:
        if self.evidence_dir is None:
            return
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        filename = f'{name}.png'
        ok, encoded = cv2.imencode('.png', cv2.cvtColor(self.image, cv2.COLOR_RGB2BGR))
        if not ok:
            raise InventoryRecognitionError(f'Could not encode {name} evidence')
        (self.evidence_dir / filename).write_bytes(encoded.tobytes())
        self.evidence[name] = filename

    def open_warehouse(self) -> None:
        self.capture()
        if self._in_warehouse():
            self._dismiss_popup()
            return
        entry = self._find_text('纳物库', (0, 570, 1280, 145))
        if entry is None:
            raise InventoryRecognitionError('庭院底栏未找到「纳物库」，请先回到庭院并展开底栏')
        self._tap(entry)
        for _ in range(5):
            if self._in_warehouse():
                return
            time.sleep(0.4)
            self.capture()
        raise InventoryRecognitionError('点击纳物库后未识别到纳物库标题')

    def _read_header(self, name: str, roi, *, allow_compact: bool = False) -> ResourceAmount:
        previous = None
        for _ in range(4):
            self.capture()
            text, score = self.ocr.ocr_single_line(self._crop(roi))
            parsed = parse_amount(text, allow_compact=allow_compact) if score >= 0.8 else None
            if parsed is not None and parsed == previous:
                self._save_evidence(name)
                quantity, exact = parsed
                return ResourceAmount(quantity, normalize_text(text), exact, 'warehouse_header')
            previous = parsed
            time.sleep(0.2)
        raise InventoryRecognitionError(f'{RESOURCE_LABELS[name]}顶部数量未能稳定识别')

    def _read_stamina(self) -> ResourceAmount:
        self._dismiss_popup()
        icons = self._template_matches('stamina_icon', self.STAMINA_SAFE_REGION, 0.88)
        if not icons:
            raise InventoryRecognitionError('未找到体力图标，停止点击以避开右侧加号')
        self._tap(icons[0])
        try:
            previous = None
            for _ in range(4):
                self.capture()
                regions = []
                for item in self.ocr.detect_and_ocr(self._crop(self.POPUP)):
                    if item.score < 0.8:
                        continue
                    left, top = np.min(item.box, axis=0)
                    right, bottom = np.max(item.box, axis=0)
                    regions.append(TextRegion(item.ocr_text, left, top, right - left, bottom - top))
                quantity = popup_owned_amount(regions, '体力')
                if quantity is not None and quantity == previous:
                    self._save_evidence('stamina')
                    return ResourceAmount(quantity, str(quantity), True, 'warehouse_owned_popup')
                previous = quantity
                time.sleep(0.25)
            self._save_evidence('stamina_popup_error')
            raise InventoryRecognitionError('体力弹窗未识别到完整的「已拥有」数量')
        finally:
            self._dismiss_popup()

    def _template(self, name: str) -> np.ndarray:
        if name not in self.templates:
            path = Path(__file__).with_name('res') / f'{name}.png'
            image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise InventoryRecognitionError(f'Could not load inventory template: {name}')
            self.templates[name] = image
        return self.templates[name]

    def _template_matches(self, name: str, roi, threshold: float) -> list[tuple[int, int, int, int]]:
        template = self._template(name)
        gray = cv2.cvtColor(self._crop(roi), cv2.COLOR_RGB2GRAY)
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        height, width = template.shape
        centers = []
        for _ in range(30):
            _, score, _, point = cv2.minMaxLoc(scores)
            if score < threshold:
                break
            x, y = point
            centers.append((roi[0] + x + 5, roi[1] + y + 5, width - 10, height - 10))
            scores[max(0, y - height // 2):y + height // 2 + 1,
                   max(0, x - width // 2):x + width // 2 + 1] = -1
        return centers

    def _select_basic_resources(self) -> None:
        self._dismiss_popup()
        search = ''.join(self._texts((48, 116, 220, 39)))
        if '搜索全部' not in normalize_text(search):
            raise InventoryRecognitionError('纳物库搜索条件未清空，无法安全判断普通蓝票数量')
        def basic_button():
            for template in ('basic_selected', 'basic_unselected'):
                matches = self._template_matches(template, self.SIDEBAR, 0.88)
                if matches:
                    return matches[0]
            return None

        basic = basic_button()
        if basic is None:
            resources = self._find_text('资源', self.SIDEBAR)
            if resources is None:
                raise InventoryRecognitionError('纳物库侧栏未找到「资源」')
            self._tap(resources)
            basic = basic_button()
        if basic is None:
            raise InventoryRecognitionError('资源分类展开后未找到「基础」')
        self._tap(basic)
        for _ in range(4):
            if self._template_matches('basic_selected', self.SIDEBAR, 0.88):
                return
            time.sleep(0.25)
            self.capture()
        raise InventoryRecognitionError('未确认已选中资源→基础分类')

    def _selected_amulet_count(self) -> int | None:
        texts = self._texts(self.DETAIL)
        if not is_regular_amulet(texts):
            return None
        previous = owned_amount(texts, '神秘的符咒')
        for _ in range(3):
            time.sleep(0.2)
            self.capture()
            texts = self._texts(self.DETAIL)
            if not is_regular_amulet(texts):
                return None
            quantity = owned_amount(texts, '神秘的符咒')
            if quantity is not None and quantity == previous:
                return quantity
            previous = quantity
        raise InventoryRecognitionError('普通蓝票名称已确认，但「持有」数量未能稳定识别')

    def _read_amulets(self) -> ResourceAmount:
        self._select_basic_resources()
        unchanged = 0
        ambiguous = False
        for _ in range(self.MAX_SCROLLS + 1):
            quantity = self._selected_amulet_count()
            if quantity is not None:
                self._save_evidence('mystery_amulets')
                return ResourceAmount(quantity, str(quantity), True, 'warehouse_item_detail')
            for point in self._template_matches('ordinary_amulet', self.GRID, 0.83):
                self._tap(point)
                quantity = self._selected_amulet_count()
                if quantity is not None:
                    self._save_evidence('mystery_amulets')
                    return ResourceAmount(quantity, str(quantity), True, 'warehouse_item_detail')
                title = ''.join(self._texts(self.DETAIL))
                if '限时' not in title and '现时' not in title:
                    ambiguous = True
            before = cv2.resize(self._crop(self.GRID), (104, 98))
            self.transport.scroll_down()
            time.sleep(0.55)
            self.capture()
            after = cv2.resize(self._crop(self.GRID), (104, 98))
            difference = float(np.mean(cv2.absdiff(before, after)))
            unchanged = unchanged + 1 if difference < 3 else 0
            if unchanged >= 2:
                if ambiguous:
                    raise InventoryRecognitionError('存在未确认名称的蓝票候选，未将识别失败当作零张')
                self._save_evidence('mystery_amulets')
                return ResourceAmount(0, '0', True, 'warehouse_basic_full_scan')
        raise InventoryRecognitionError('基础分类未扫描到底，无法确认普通蓝票数量')

    def read(self, config_name: str) -> dict:
        self.open_warehouse()
        amounts = {}
        try:
            readers = {
                'coins': lambda: self._read_header('coins', (514, 13, 108, 37), allow_compact=True),
                'jade': lambda: self._read_header('jade', (928, 13, 94, 37)),
                'stamina': self._read_stamina,
                'mystery_amulets': self._read_amulets,
            }
            for name, reader in readers.items():
                try:
                    amounts[name] = reader()
                except InventoryRecognitionError as exc:
                    amounts[name] = ResourceAmount(None, '', False, 'unrecognized', str(exc))
                    self._save_evidence(f'{name}_error')
            return {
                'schema_version': 1,
                'config_name': config_name,
                'captured_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                'status': 'complete' if all(item.quantity is not None for item in amounts.values()) else 'partial',
                'resources': {name: item.to_dict() for name, item in amounts.items()},
                'evidence': dict(self.evidence),
            }
        finally:
            self._dismiss_popup()
            if self._in_warehouse():
                self._tap((20, 17, 40, 40))
