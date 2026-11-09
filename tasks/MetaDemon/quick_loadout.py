"""Frame-based preset selection for the MetaDemon panel."""
from pathlib import Path
from time import sleep

from module.atom.click import RuleClick
from module.atom.frame import RuleFrame
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.logger import logger
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.QuickLoadout.config import NamedQuickLoadoutConfig, QuickLoadoutConfig
from tasks.Component.QuickLoadout.quick_loadout import QuickLoadout, QuickLoadoutLayout


class FrameQuickLoadout(QuickLoadout):
    GROUP_OCR_ROI = (8, 7, 105, 365)

    def _build_quick_loadout_layout(self, frame: RuleFrame) -> QuickLoadoutLayout:
        if len(frame.roi_ranges) not in (2, 3):
            raise ValueError('Quick loadout frame requires range1=panel and range2=fight')
        panel = tuple(int(round(value)) for value in frame.matched_ranges[0])
        height, width = self.device.image.shape[:2]
        return self._quick_loadout_layout_at(panel, reference_size=(555, 388), screen_size=(width, height))

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
        """未指定关闭区域时，使用左侧安全区域随机点击。"""
        target = dismiss if dismiss is not None else GeneralBattleAssets.C_RANDOM_LEFT
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self._quick_loadout_panel_visible(frame):
                return True
            self.click(target, interval=1)
        logger.warning('Cannot close quick loadout panel safely')
        return False

    def _deploy_quick_loadout(self, layout: QuickLoadoutLayout, frame: RuleFrame, row_y: int, dismiss: RuleClick | None = None) -> bool:
        self.device.click(layout.column(self.PRESET_SELECT_X), row_y, control_name='QUICK_LOADOUT_PRESET')
        sleep(0.4)
        self.screenshot()
        if not self._quick_loadout_panel_visible(frame):
            return False
        self.click(self._quick_loadout_fight(frame))
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
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
        """将目标预设上阵，默认先装配御魂。"""
        if not config.enable:
            return True
        if isinstance(config, NamedQuickLoadoutConfig) and config.custom_preset_enable:
            if name_ocr is None:
                logger.warning('Named quick loadout enabled without a stage-name OCR rule')
            else:
                config, _ = self._resolve_named_quick_loadout(config, name_ocr)
        config.validate_target()
        target = (frame.name, config.group_name.strip(), config.preset_name.strip(),
                  config.mode, config.group_number, config.preset_number, skip_equip_soul)
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
            if not skip_equip_soul:
                self._equip_quick_loadout_souls(layout, row_y)
            deployed = self._deploy_quick_loadout(layout, frame, row_y, dismiss=dismiss)
            if deployed:
                self._last_quick_loadout = target
            return deployed
        except Exception:
            self._dismiss_quick_loadout(frame, dismiss=dismiss)
            raise
