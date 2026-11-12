"""Frame-based preset selection for the MetaDemon panel."""
from pathlib import Path
from time import sleep

from module.atom.click import RuleClick
from module.atom.frame import RuleFrame
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.logger import logger
from tasks.Component.QuickLoadout.config import NamedQuickLoadoutConfig, QuickLoadoutConfig, QuickLoadoutMode
from tasks.Component.QuickLoadout.quick_loadout import QuickLoadout, QuickLoadoutLayout


class FrameQuickLoadout(QuickLoadout):
    GROUP_OCR_ROI = (8, 7, 105, 365)
    PANEL_SIZE = (555, 388)
    RENTAL_GROUP_NAME = '队伍租借'
    GROUP_BOTTOM_CLICK_Y = 371
    RENTAL_GROUP_MAX_SWIPES = 3

    def _build_quick_loadout_layout(self, frame: RuleFrame) -> QuickLoadoutLayout:
        if len(frame.roi_ranges) not in (2, 3):
            raise ValueError('Quick loadout frame requires range1=panel and range2=fight')
        panel = tuple(int(round(value)) for value in frame.matched_ranges[0])
        height, width = self.device.image.shape[:2]
        return self._quick_loadout_layout_at(panel, reference_size=self.PANEL_SIZE, screen_size=(width, height))

    def _panel_row(self, layout: QuickLoadoutLayout, offset: int) -> int:
        _, y, _, height = layout.panel
        return y + round(offset * height / self.PANEL_SIZE[1])

    def _quick_loadout_fight(self, frame: RuleFrame, *, fight_file: str | None = None) -> RuleImage:
        if len(frame.roi_ranges) not in (2, 3):
            raise ValueError('Quick loadout frame requires range1=panel and range2=fight')
        # range1 仅用于布局；不执行其中的操作，也不改写 frame 的检测范围。
        specs, targets = frame.range_targets(self.device.image.shape, allow_missing_image=True)
        if fight_file and specs[1]['type'] == 'image' and not isinstance(targets[1], RuleImage):
            area = tuple(int(round(value)) for value in frame.matched_ranges[1])
            targets[1] = RuleImage(
                roi_front=area, roi_back=area, method=specs[1]['method'],
                threshold=specs[1]['threshold'], file=fight_file,
            )
        if specs[1]['type'] != 'image' or not isinstance(targets[1], RuleImage):
            raise ValueError('Quick loadout frame range2 must include its fight image')
        if not Path(targets[1].file).is_file():
            raise ValueError(f'Quick loadout frame range2 image does not exist: {targets[1].file}')
        return targets[1]

    def _quick_loadout_panel_visible(self, frame: RuleFrame) -> bool:
        return bool(self.appear(frame) and self.appear(self._quick_loadout_fight(frame)))

    def _open_quick_loadout(self, frame: RuleFrame) -> bool:
        logger.info('Open quick loadout panel')
        timer = Timer(self.PANEL_OPEN_TIMEOUT).start()
        entry_clicked = False
        fallback_timer = Timer(1)
        while not timer.reached():
            self.screenshot()
            if self._quick_loadout_panel_visible(frame):
                return True
            if self.appear(frame):
                if entry_clicked and len(frame.roi_ranges) == 3 and fallback_timer.reached():
                    specs, targets = frame.range_targets(self.device.image.shape, allow_missing_image=True)
                    if specs[2]['type'] != 'click':
                        raise ValueError('Quick loadout frame range3 must be a Click operation')
                    logger.info('Quick loadout entry did not open panel, try range3')
                    self.click(targets[2], interval=1)
                    fallback_timer.reset()
                elif not entry_clicked or len(frame.roi_ranges) == 2:
                    entry = RuleClick(
                        roi_front=tuple(frame.roi_badge), roi_back=tuple(frame.roi_badge),
                        name='QUICK_LOADOUT_ENTRY',
                    )
                    if self.click(entry, interval=1):
                        entry_clicked = True
                        fallback_timer.reset()
        logger.warning('Cannot open quick loadout panel')
        return False

    def _dismiss_quick_loadout(self, frame: RuleFrame, dismiss: RuleClick | None = None) -> bool:
        target = dismiss if dismiss is not None else self.C_MD_CLOSE_PRESET
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self._quick_loadout_panel_visible(frame):
                return True
            self.click(target, interval=1)
        logger.warning('Cannot close quick loadout panel safely')
        return False

    def _select_group(self, layout: QuickLoadoutLayout, config: QuickLoadoutConfig) -> bool:
        rental_tab = self.appear(self.I_MD_RENTAL_TAB)
        if config.mode == QuickLoadoutMode.NUMBER:
            index = config.group_number - 1 + int(rental_tab)
            # 末尾的个人分组在租借分组存在时只露出一部分，点击可见部分。
            offset = min(self.GROUP_FIRST_Y + index * self.GROUP_ROW_HEIGHT, self.GROUP_BOTTOM_CLICK_Y)
            y = self._panel_row(layout, offset)
        elif config.group_name == self.RENTAL_GROUP_NAME:
            if not rental_tab:
                logger.info('队伍租借分组不可见，向下滑动分组列表回到顶部')
                for _ in range(self.RENTAL_GROUP_MAX_SWIPES):
                    self.swipe(layout.group_swipe_to_top)
                    sleep(0.45)
                    self.screenshot()
                    rental_tab = self.appear(self.I_MD_RENTAL_TAB)
                    if rental_tab:
                        break
            if not rental_tab:
                logger.warning('滑动后仍未找到队伍租借分组')
                return False
            y = self._panel_row(layout, self.GROUP_FIRST_Y)
        else:
            y, score = self._find_name_y(layout.group_ocr, config.group_name)
            if y is None or score < 0.55:
                logger.warning(f'快速预设可见分组中未找到 {config.group_name}')
                return False
        self.device.click(layout.column(self.GROUP_CLICK_X), y, control_name='QUICK_LOADOUT_GROUP')
        sleep(0.4)
        return True

    def _preset_number_at(self, layout: QuickLoadoutLayout, y: int) -> int:
        roi = (layout.column(self.PRESET_NUMBER_X), y - 13, 26, 27)
        number_ocr = RuleOcr(roi=roi, area=roi, mode='Digit', method='Default',
                             keyword='', name='quick_loadout_preset_number')
        return number_ocr.ocr(self.device.image)

    def _select_preset_row(self, layout: QuickLoadoutLayout, config: QuickLoadoutConfig) -> int | None:
        if config.group_name == self.RENTAL_GROUP_NAME:
            self.screenshot()
            results = layout.preset_ocr.detect_and_ocr(self.device.image, logDisplay=False)
            matches = [result for result in results if config.preset_name in self._normalize_name(result.ocr_text)]
            if len(matches) == 1:
                return self._result_center_y(matches[0], layout.preset_ocr.roi[1])
            logger.warning(f'队伍租借中无法确认 {config.preset_name} 阵容')
            return None

        if config.mode != QuickLoadoutMode.NUMBER:
            return super()._select_preset_row(layout, config)

        target = config.preset_number
        self.screenshot()
        if target <= self.PRESET_VISIBLE_SLOTS:
            y = self._panel_row(layout, self.PRESET_FIRST_Y + (target - 1) * self.PRESET_ROW_HEIGHT)
            if self._preset_number_at(layout, y) == target:
                return y

        self._rewind_list(layout.preset_ocr, layout.preset_swipe_to_top, self.MAX_PRESET_SWIPES)
        previous = None
        for _ in range(self.MAX_PRESET_SWIPES + 1):
            self.screenshot()
            results = layout.preset_ocr.detect_and_ocr(self.device.image, logDisplay=False)
            for result in results:
                y = self._result_center_y(result, layout.preset_ocr.roi[1])
                if self._preset_number_at(layout, y) == target:
                    return y
            current = tuple(result.ocr_text for result in results)
            if current and current == previous:
                break
            previous = current
            self.swipe(layout.preset_swipe_down)
            sleep(0.4)
        logger.warning(f'快速预设中未找到第 {target} 队')
        return None

    def _deploy_quick_loadout(
        self, layout: QuickLoadoutLayout, frame: RuleFrame, row_y: int, *,
        equip_soul: bool, dismiss: RuleClick | None = None,
    ) -> bool:
        self.device.click(layout.column(self.PRESET_SELECT_X), row_y, control_name='QUICK_LOADOUT_PRESET')
        sleep(0.4)
        self.screenshot()
        if not self._quick_loadout_panel_visible(frame):
            return False
        self.click(self._quick_loadout_fight(frame))
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        soul_change_cancelled = False
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_MD_PRESET_SOUL_PROMPT):
                if equip_soul:
                    self.appear_then_click(self.I_SOU_SWITCH_SURE, interval=0.8)
                else:
                    self.click(self.C_MD_PRESET_SOUL_CANCEL, interval=0.8)
                    soul_change_cancelled = True
                continue
            if soul_change_cancelled:
                logger.warning('个人预设需要装配御魂才能出战，本组关闭了切换御魂')
                self._dismiss_quick_loadout(frame, dismiss=dismiss)
                return False
            if not self._quick_loadout_panel_visible(frame):
                logger.info('Quick loadout deployed')
                return True
            sleep(0.2)
        logger.warning('Quick loadout deploy did not close panel')
        self._dismiss_quick_loadout(frame, dismiss=dismiss)
        return False

    def run_quick_loadout(
        self,
        config: QuickLoadoutConfig,
        *,
        frame: RuleFrame,
        name_ocr: RuleOcr | None = None,
        dismiss: RuleClick | None = None,
        skip_equip_soul: bool = False,
    ) -> bool:
        """在同一面板上阵个人预设或租借阵容。"""
        if not config.enable:
            return True
        if isinstance(config, NamedQuickLoadoutConfig) and config.custom_preset_enable:
            if name_ocr is None:
                logger.warning('Named quick loadout enabled without a stage-name OCR rule')
            else:
                config, _ = self._resolve_named_quick_loadout(config, name_ocr)
        config.validate_target()
        equip_soul = not skip_equip_soul and config.group_name != self.RENTAL_GROUP_NAME
        target = (frame.name, config.group_name.strip(), config.preset_name.strip(),
                  config.mode, config.group_number, config.preset_number, equip_soul)
        if getattr(self, '_last_quick_loadout', None) == target:
            logger.info(f'Quick loadout unchanged, keep current lineup: {target[1:3]}')
            return True
        # A failed attempt may have changed souls or selected another preset.
        self._last_quick_loadout = None
        logger.hr('Quick loadout', 2)
        if not self._open_quick_loadout(frame):
            return False
        try:
            layout = self._build_quick_loadout_layout(frame)
            logger.info(f'Quick loadout panel: {layout.panel}')
            if not self._select_group(layout, config):
                self._dismiss_quick_loadout(frame, dismiss=dismiss)
                return False
            row_y = self._select_preset_row(layout, config)
            if row_y is None:
                self._dismiss_quick_loadout(frame, dismiss=dismiss)
                return False
            deployed = self._deploy_quick_loadout(layout, frame, row_y, equip_soul=equip_soul, dismiss=dismiss)
            if deployed:
                self._last_quick_loadout = target
            return deployed
        except Exception:
            self._dismiss_quick_loadout(frame, dismiss=dismiss)
            raise
