"""协同对弈：selection。"""

import re
import time
from module.logger import logger
from tasks.DraftDuel.strategy import choose_pick, normalize_name


class DraftDuelSelectionMixin:
    @staticmethod
    def _parse_select_number(text):
        text = re.sub(r'\s+', '', text or '')
        match = re.search(r'请选择第([1-5一二三四五])名(?:角色|式神)', text)
        if not match:
            return None
        return dict(zip('12345一二三四五', (1, 2, 3, 4, 5) * 2))[match[1]]

    def _log_selection_wait(self, reason):
        """等待原因变化时记录一次，避免静默等待和逐帧刷屏。"""
        if getattr(self, '_draft_selection_wait_reason', None) != reason:
            logger.info(f'DraftDuel selection waiting: {reason}')
            self._draft_selection_wait_reason = reason

    def _select_shikigami(self) -> bool:
        """按轮次选人，空位消失确认成功；仅进入等待匹配，不接入战斗。"""
        if not hasattr(self, 'draft_selected'):
            self.draft_selected = []
        confirmed = set(range(1, len(self.draft_selected) + 1))
        saved = getattr(self, '_draft_selection_pending', None)
        pending = (saved[0], saved[1], getattr(self, f'I_SELECT_{saved[2]}')) if saved else None
        absent_frames = 0
        last_click = 0
        deadline = time.monotonic() + 600
        while True:
            self.device.stuck_record_clear()
            self.screenshot()
            self._observe_duel_lobby()
            self._save_draft_checkpoint('select')
            if self.appear(self.I_POST_DRAFT_RANK):
                # 最后一选可能直接切页，来不及在选人页观察两帧空位消失。
                # 明确进入等待匹配且本轮空位消失时，补记已点击的候选。
                if pending:
                    round_number, name, _ = pending
                    if not self.appear(getattr(self, f'I_SELECT_NONE_{round_number}')):
                        confirmed.add(round_number)
                        self.draft_selected.append(name)
                        self._draft_selection_pending = None
                        self._save_draft_checkpoint('rank')
                        logger.info(f'DraftDuel pick {round_number} confirmed on rank page: {name}')
                logger.info('DraftDuel entered post_draft_rank')
                return True
            if time.monotonic() >= deadline:
                logger.warning('DraftDuel selection made no progress for 600s')
                return False
            if not self.appear(self.I_POST_DRAFT_SELECT):
                self._log_selection_wait('未识别到 post_draft_select')
                time.sleep(0.3)
                continue
            raw_number = self.O_SELECT_NUMBER.ocr(self.device.image)
            number = self._parse_select_number(raw_number)
            if pending:
                round_number, name, button = pending
                empty = getattr(self, f'I_SELECT_NONE_{round_number}')
                if not self.appear(empty):
                    absent_frames += 1
                    if absent_frames >= 2:
                        confirmed.add(round_number)
                        self.draft_selected.append(name)
                        logger.info(f'DraftDuel pick {round_number} confirmed: {name}')
                        pending = None
                        self._draft_selection_pending = None
                        self._save_draft_checkpoint('select')
                        deadline = time.monotonic() + 600
                else:
                    absent_frames = 0
                    if number == round_number and time.monotonic() - last_click >= 2:
                        if self.appear_then_click(button, interval=1):
                            last_click = time.monotonic()
                time.sleep(0.3)
                continue
            if number is None or number in confirmed:
                self._log_selection_wait(f'轮次文字={raw_number!r}，解析结果={number}，已选轮次={sorted(confirmed)}')
                time.sleep(0.3)
                continue
            if number != len(self.draft_selected) + 1:
                self._log_selection_wait(f'识别到第{number}名，记录中已选{len(self.draft_selected)}名，等待轮次一致')
                # 不跳轮记录，确保五个名字与头像位置始终一一对应。
                time.sleep(0.3)
                continue
            # 必须先看到本轮空位，避免队友等待期间误点旧候选。
            if not self.appear(getattr(self, f'I_SELECT_NONE_{number}')):
                self._log_selection_wait(f'第{number}名空位 select_none_{number} 未识别')
                time.sleep(0.3)
                continue
            raw_names = [getattr(self, f'O_SHIKIGAMI_NAME_{i}').ocr(self.device.image) for i in (1, 2, 3)]
            names = [normalize_name(name) for name in raw_names]
            if not all(names):
                self._log_selection_wait(f'候选 OCR={raw_names!r}，归一化={names!r}')
                time.sleep(0.3)
                continue
            try:
                pick = choose_pick(names, team=self.draft_selected)
            except ValueError as exc:
                logger.warning(f'DraftDuel candidates cannot be selected: {exc}')
                time.sleep(0.3)
                continue
            button = getattr(self, f'I_SELECT_{names.index(pick.name) + 1}')
            logger.info(f'DraftDuel pick {number}: {names} -> {pick.name}, score={pick.score}')
            if self.appear_then_click(button, interval=1):
                self._draft_selection_wait_reason = None
                pending = (number, pick.name, button)
                self._draft_selection_pending = (number, pick.name, names.index(pick.name) + 1)
                self._save_draft_checkpoint('select')
                absent_frames = 0
                last_click = time.monotonic()
            time.sleep(0.3)
