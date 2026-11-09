# This Python file uses the following encoding: utf-8
from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass
from time import sleep

import cv2
import numpy as np

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.atom.swipe import RuleSwipe
from module.base.timer import Timer
from module.logger import logger
from tasks.Component.QuickLoadout.config import (
    NamedQuickLoadoutConfig,
    QuickLoadoutConfig,
    QuickLoadoutMode,
)
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets
from tasks.base_task import BaseTask


class QuickLoadoutOcr(RuleOcr):
    """适配快捷配置面板的棕色/橙色文字。"""

    def pre_process(self, image):
        # 项目截图使用 RGB；该小面板的选中态文字在交换红蓝通道后识别更稳定。
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


@dataclass(frozen=True)
class QuickLoadoutLayout:
    """由“出战”锚点推导出的快捷配置面板运行时布局。"""

    panel: tuple[int, int, int, int]
    group_ocr: RuleOcr
    preset_ocr: RuleOcr
    group_swipe_to_top: RuleSwipe
    group_swipe_down: RuleSwipe
    preset_swipe_to_top: RuleSwipe
    preset_swipe_down: RuleSwipe
    scale_x: float = 1.0

    def column(self, offset: int) -> int:
        return self.panel[0] + round(offset * self.scale_x)


class QuickLoadout(BaseTask, SwitchSoulAssets):
    """战斗界面内的一键配置组件。

    每个接入任务必须提供三项任务资源：队伍预设入口图片、面板内“出战”
    锚点图片和面板外安全关闭点击区域；
    面板内部点击点、OCR 和滑动范围全部根据锚点动态生成。

    该官方功能会同时装配预设御魂和上阵阵容，并且切换操作不受任务页面
    下方的“阵容锁定”开关影响。完成切换后，接入任务仍应根据通用战斗
    配置独立确认阵容锁定状态。
    """

    PANEL_FROM_FIGHT = (-263, -331, 551, 386)
    GROUP_OCR_ROI = (17, 7, 101, 356)
    PRESET_OCR_ROI = (145, 7, 278, 320)
    GROUP_CLICK_X = 61
    GROUP_FIRST_Y = 31
    GROUP_ROW_HEIGHT = 51
    PRESET_SELECT_X = 300
    PRESET_EQUIP_X = 482
    PRESET_NUMBER_X = 157
    PRESET_NUMBER_Y = 7
    PRESET_NUMBER_SIZE = (24, 32)
    PRESET_FIRST_Y = 26
    PRESET_ROW_HEIGHT = 96
    PRESET_FULL_VISIBLE_ROWS = 3
    PRESET_VISIBLE_SLOTS = 4

    PANEL_OPEN_TIMEOUT = 8
    PANEL_CLOSE_TIMEOUT = 5
    CONFIRM_TIMEOUT = 1.5
    MAX_GROUP_SWIPES = 10
    MAX_PRESET_SWIPES = 15
    STAGE_NAME_MATCH_THRESHOLD = 0.75

    @staticmethod
    def _parse_custom_presets(
        value: str,
    ) -> dict[str, tuple[int, int] | tuple[str, str]]:
        """解析混合预设；数字元组按编号，字符串元组按 OCR 名称。"""
        presets = {}
        for raw_item in re.split(r'[;；]+', value):
            item = raw_item.strip()
            if not item:
                continue
            parts = re.split(r'[:：]', item, maxsplit=1)
            if len(parts) != 2 or not parts[0].strip():
                raise ValueError(f'Invalid custom quick loadout item: {item}')
            boss_name, target_text = parts[0].strip(), parts[1].strip()
            try:
                target = ast.literal_eval(target_text)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f'Invalid custom quick loadout target: {item}') from exc
            if not isinstance(target, (tuple, list)) or len(target) != 2:
                raise ValueError(f'Custom quick loadout target must contain two values: {item}')
            group, preset = target
            is_number_target = (
                isinstance(group, int) and not isinstance(group, bool)
                and isinstance(preset, int) and not isinstance(preset, bool)
            )
            is_ocr_target = isinstance(group, str) and isinstance(preset, str)
            if not is_number_target and not is_ocr_target:
                raise ValueError(
                    f'Custom quick loadout target must be two integers or two strings: {item}'
                )
            if is_number_target and (group < 1 or preset < 1):
                raise ValueError(f'Custom quick loadout numbers must be positive: {item}')
            if is_ocr_target:
                group, preset = group.strip(), preset.strip()
                if not group or not preset:
                    raise ValueError(f'Custom quick loadout target cannot be empty: {item}')
            presets[boss_name] = (group, preset)
        return presets

    def _read_quick_loadout_stage_name(self, name_ocr: RuleOcr) -> str:
        """在打开一键配置面板前读取任务关卡名称。"""
        best = ''
        for attempt in range(1, 4):
            self.screenshot()
            value = str(name_ocr.ocr(self.device.image)).strip()
            if len(self._normalize_name(value)) > len(self._normalize_name(best)):
                best = value
            logger.info(f'Quick loadout stage OCR {attempt}/3: {value}')
            if best:
                break
            sleep(0.3)
        return best

    @classmethod
    def _match_custom_preset(cls, stage_name, presets):
        """显式关卡名优先；没有显式匹配时使用 ALL。"""
        best_name = None
        best_target = None
        best_score = 0.0
        all_target = None
        for candidate, target in presets.items():
            if candidate.upper() == 'ALL':
                all_target = target
                continue
            score = cls._name_similarity(stage_name, candidate)
            if score > best_score:
                best_name, best_target, best_score = candidate, target, score
        if best_target is not None and best_score >= cls.STAGE_NAME_MATCH_THRESHOLD:
            return best_name, best_target, best_score
        if all_target is not None:
            return 'ALL', all_target, 1.0
        return None, None, 0.0

    def _resolve_named_quick_loadout(
        self,
        config: NamedQuickLoadoutConfig,
        name_ocr: RuleOcr,
    ) -> tuple[QuickLoadoutConfig, str | None]:
        """按 OCR 关卡名生成本轮配置，并返回用于一次性装魂的稳定键。"""
        stage_name = self._read_quick_loadout_stage_name(name_ocr)
        normalized_stage = self._normalize_name(stage_name)
        if not normalized_stage:
            logger.warning('Quick loadout stage name OCR is empty, use default preset')
            return config, None

        try:
            presets = self._parse_custom_presets(config.custom_preset)
        except ValueError as exc:
            logger.warning(str(exc))
            return config, normalized_stage

        best_name, best_target, best_score = self._match_custom_preset(stage_name, presets)
        if best_target is None:
            logger.info(f'No custom quick loadout for stage {stage_name}, use default preset')
            return config, normalized_stage

        group, preset = best_target
        if isinstance(group, int) and isinstance(preset, int):
            updates = {
                'mode': QuickLoadoutMode.NUMBER,
                'group_number': group,
                'preset_number': preset,
            }
        else:
            updates = {
                'mode': QuickLoadoutMode.OCR,
                'group_name': group,
                'preset_name': preset,
            }
        logger.info(
            f'Custom quick loadout matched stage {stage_name} -> '
            f'({group}, {preset}) [{best_score:.2f}]'
        )
        return config.model_copy(update=updates), self._normalize_name(best_name)

    @staticmethod
    def _result_center_y(result, roi_top: int) -> int:
        return int(round(float(np.mean(result.box[:, 1])))) + roi_top

    @staticmethod
    def _normalize_name(value: str) -> str:
        return re.sub(r'[\s·•,，.。:：_\-—]+', '', str(value)).strip()

    @classmethod
    def _name_similarity(cls, actual: str, expected: str) -> float:
        actual = cls._normalize_name(actual)
        expected = cls._normalize_name(expected)
        if not actual or not expected:
            return 0.0
        if expected in actual or actual in expected:
            return 1.0
        return difflib.SequenceMatcher(None, actual, expected).ratio()

    def _build_quick_loadout_layout(self, fight_anchor: RuleImage) -> QuickLoadoutLayout:
        anchor_x, anchor_y = fight_anchor.roi_front[:2]
        dx, dy, panel_width, panel_height = self.PANEL_FROM_FIGHT
        panel = anchor_x + dx, anchor_y + dy, panel_width, panel_height
        return self._quick_loadout_layout_at(panel)

    def _quick_loadout_layout_at(self, panel, *, reference_size=None, screen_size=(1280, 720)) -> QuickLoadoutLayout:
        x, y, width, height = panel
        if x < 0 or y < 0 or min(width, height) <= 0 or x + width > screen_size[0] or y + height > screen_size[1]:
            raise ValueError(f'Quick loadout panel is outside screen: {panel}')
        ref_width, ref_height = reference_size or (width, height)
        sx, sy = width / ref_width, height / ref_height

        def roi(relative):
            rx, ry, rw, rh = relative
            return x + round(rx * sx), y + round(ry * sy), max(1, round(rw * sx)), max(1, round(rh * sy))

        group_roi = roi(self.GROUP_OCR_ROI)
        preset_roi = roi(self.PRESET_OCR_ROI)
        group_ocr = QuickLoadoutOcr(roi=group_roi, area=group_roi, mode='Full', method='Default', keyword='', name='quick_loadout_group_name')
        preset_ocr = QuickLoadoutOcr(roi=preset_roi, area=preset_roi, mode='Full', method='Default', keyword='', name='quick_loadout_preset_name')

        def swipe(name, front, back):
            return RuleSwipe(roi_front=roi(front), roi_back=roi(back), mode='default', name=name)

        return QuickLoadoutLayout(
            panel, group_ocr, preset_ocr,
            swipe('quick_loadout_group_to_top', (55, 105, 25, 20), (55, 285, 25, 20)),
            swipe('quick_loadout_group_down', (55, 285, 25, 20), (55, 105, 25, 20)),
            swipe('quick_loadout_preset_to_top', (355, 105, 30, 20), (355, 280, 30, 20)),
            swipe('quick_loadout_preset_down', (355, 280, 30, 20), (355, 105, 30, 20)),
            scale_x=sx,
        )

    def _open_quick_loadout(self, entry: RuleImage, fight_anchor: RuleImage) -> bool:
        logger.info('Open quick loadout panel')
        timer = Timer(self.PANEL_OPEN_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(fight_anchor):
                return True
            self.appear_then_click(entry, interval=1)
        logger.warning('Cannot open quick loadout panel')
        return False

    def _dismiss_quick_loadout(self, fight_anchor: RuleImage, dismiss: RuleClick) -> bool:
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(fight_anchor):
                return True
            self.click(dismiss, interval=1)
        logger.warning('Cannot close quick loadout panel safely')
        return False

    def _rewind_list(self, ocr: RuleOcr, swipe: RuleSwipe, max_swipes: int) -> None:
        """将列表拖到顶部；OCR 内容连续不变时提前停止。"""
        previous = None
        stable_count = 0
        for _ in range(max_swipes):
            self.screenshot()
            results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
            current = tuple(result.ocr_text for result in results)
            if current and current == previous:
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0
            previous = current
            self.swipe(swipe)
            sleep(0.45)

    def _find_name_y(self, ocr: RuleOcr, target: str, results=None) -> tuple[int | None, float]:
        best_y = None
        best_score = 0.0
        if results is None:
            results = ocr.detect_and_ocr(self.device.image)
        for result in results:
            score = self._name_similarity(result.ocr_text, target)
            if score > best_score:
                best_score = score
                best_y = self._result_center_y(result, ocr.roi[1])
        return best_y, best_score

    def _find_number_y(self, ocr: RuleOcr, target: int, results=None) -> int | None:
        if results is None:
            results = ocr.detect_and_ocr(self.device.image)
        for result in results:
            numbers = [int(value) for value in re.findall(r'\d+', str(result.ocr_text))]
            if target in numbers:
                return self._result_center_y(result, ocr.roi[1])
        return None

    def _find_visible_preset_number_y(self, layout: QuickLoadoutLayout, target: int) -> int | None:
        """逐行识别预设左上角菱形编号，避免整块名称 OCR 丢弃小数字。"""
        panel_y = layout.panel[1]
        number_width, number_height = self.PRESET_NUMBER_SIZE
        for slot in range(self.PRESET_VISIBLE_SLOTS):
            roi = (
                panel_x + self.PRESET_NUMBER_X,
                panel_y + self.PRESET_NUMBER_Y + slot * self.PRESET_ROW_HEIGHT,
                number_width,
                number_height,
            )
            number_ocr = RuleOcr(
                roi=roi,
                area=roi,
                mode='Digit',
                method='Default',
                keyword='',
                name=f'quick_loadout_preset_number_{slot + 1}',
            )
            if number_ocr.ocr(self.device.image) == target:
                return panel_y + self.PRESET_FIRST_Y + slot * self.PRESET_ROW_HEIGHT
        return None

    def _select_group(self, layout: QuickLoadoutLayout, config: QuickLoadoutConfig) -> bool:
        self._rewind_list(layout.group_ocr, layout.group_swipe_to_top, self.MAX_GROUP_SWIPES)
        panel_x, panel_y, _, _ = layout.panel
        if config.mode == QuickLoadoutMode.NUMBER:
            y = panel_y + self.GROUP_FIRST_Y + (config.group_number - 1) * self.GROUP_ROW_HEIGHT
            self.device.click(layout.column(self.GROUP_CLICK_X), y, control_name='QUICK_LOADOUT_GROUP')
            sleep(0.6)
            return True

        previous = None
        stable_count = 0
        for _ in range(self.MAX_GROUP_SWIPES + 1):
            self.screenshot()
            results = layout.group_ocr.detect_and_ocr(self.device.image, logDisplay=False)
            current = tuple(result.ocr_text for result in results)
            y, score = self._find_name_y(layout.group_ocr, config.group_name, results)
            if y is not None and score >= 0.55:
                logger.info(f'Quick loadout group OCR matched {config.group_name} [{score:.2f}]')
                self.device.click(layout.column(self.GROUP_CLICK_X), y, control_name='QUICK_LOADOUT_GROUP_OCR')
                sleep(0.6)
                return True
            stable_count = stable_count + 1 if current and current == previous else 0
            if stable_count >= 2:
                break
            previous = current
            self.swipe(layout.group_swipe_down)
            sleep(0.6)
        logger.warning(f'Quick loadout group not found: {config.group_name}')
        return False

    def _select_preset_row(self, layout: QuickLoadoutLayout, config: QuickLoadoutConfig) -> int | None:
        self._rewind_list(layout.preset_ocr, layout.preset_swipe_to_top, self.MAX_PRESET_SWIPES)
        panel_y = layout.panel[1]
        if config.mode == QuickLoadoutMode.NUMBER and config.preset_number <= self.PRESET_FULL_VISIBLE_ROWS:
            return panel_y + self.PRESET_FIRST_Y + (config.preset_number - 1) * self.PRESET_ROW_HEIGHT

        previous = None
        stable_count = 0
        target_label = str(config.preset_number) if config.mode == QuickLoadoutMode.NUMBER else config.preset_name
        for _ in range(self.MAX_PRESET_SWIPES + 1):
            self.screenshot()
            results = layout.preset_ocr.detect_and_ocr(self.device.image, logDisplay=False)
            current = tuple(result.ocr_text for result in results)
            if config.mode == QuickLoadoutMode.NUMBER:
                y = self._find_visible_preset_number_y(layout, config.preset_number)
                score = 1.0 if y is not None else 0.0
            else:
                y, score = self._find_name_y(layout.preset_ocr, config.preset_name, results)
            if y is not None and score >= 0.55:
                logger.info(f'Quick loadout preset matched {target_label} [{score:.2f}]')
                return y
            stable_count = stable_count + 1 if current and current == previous else 0
            if stable_count >= 2:
                break
            previous = current
            self.swipe(layout.preset_swipe_down)
            sleep(0.6)
        logger.warning(f'Quick loadout preset not found: {target_label}')
        return None

    def _equip_quick_loadout_souls(self, layout: QuickLoadoutLayout, row_y: int) -> None:
        self.device.click(layout.column(self.PRESET_EQUIP_X), row_y, control_name='QUICK_LOADOUT_EQUIP_SOUL')
        timer = Timer(self.CONFIRM_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(self.I_SOU_SWITCH_SURE):
                sleep(0.15)
                continue
            logger.info('Confirm quick loadout soul equipment')
            self.ui_click_until_disappear(self.I_SOU_SWITCH_SURE, interval=0.6)
            return
        logger.info('Quick loadout soul confirmation did not appear; preset may already be equipped')

    def _deploy_quick_loadout(self, layout: QuickLoadoutLayout, fight_anchor: RuleImage, dismiss: RuleClick, row_y: int) -> bool:
        panel_x = layout.panel[0]
        self.device.click(panel_x + self.PRESET_SELECT_X, row_y, control_name='QUICK_LOADOUT_PRESET')
        sleep(0.4)
        self.click(fight_anchor)
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(fight_anchor):
                logger.info('Quick loadout deployed')
                return True
            sleep(0.2)
        logger.warning('Quick loadout deploy did not close panel')
        self._dismiss_quick_loadout(fight_anchor, dismiss)
        return False

    def run_quick_loadout(
        self,
        config: QuickLoadoutConfig,
        *,
        entry: RuleImage,
        fight_anchor: RuleImage,
        dismiss: RuleClick,
        name_ocr: RuleOcr | None = None,
    ) -> bool:
        """装配目标预设御魂并将该预设上阵。"""
        if not config.enable:
            return True
        if isinstance(config, NamedQuickLoadoutConfig) and config.custom_preset_enable:
            if name_ocr is None:
                logger.warning('Named quick loadout enabled without a stage-name OCR rule')
            else:
                config, _ = self._resolve_named_quick_loadout(config, name_ocr)
        config.validate_target()
        logger.hr('Quick loadout', 2)
        if not self._open_quick_loadout(entry, fight_anchor):
            return False
        try:
            layout = self._build_quick_loadout_layout(fight_anchor)
            logger.info(f'Quick loadout panel: {layout.panel}')
            if not self._select_group(layout, config):
                self._dismiss_quick_loadout(fight_anchor, dismiss)
                return False
            row_y = self._select_preset_row(layout, config)
            if row_y is None:
                self._dismiss_quick_loadout(fight_anchor, dismiss)
                return False
            self._equip_quick_loadout_souls(layout, row_y)
            return self._deploy_quick_loadout(layout, fight_anchor, dismiss, row_y)
        except Exception:
            self._dismiss_quick_loadout(fight_anchor, dismiss)
            raise
