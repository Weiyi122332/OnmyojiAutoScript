"""协同对弈：round_state。"""

import time
from module.logger import logger
from tasks.GameUi.assets import GameUiAssets


class DraftDuelRoundStateMixin:
    def _initialize_duel_state(self):
        """初始化内存容器；初始化本身不代表观察到新一轮。"""
        self.draft_heads = ()
        self.draft_named_heads = ()
        self.draft_selected = []
        self.draft_fielded = ()
        self.draft_deployment_rounds = []
        self.draft_peer_picks = ()
        self.draft_peer_rounds = ()
        self._draft_session = ''
        self._draft_published_state = None
        self._draft_exchange_since = time.time()
        self._draft_auto_ready_after = None
        self.draft_finished_small_games = 0
        self.draft_small_game = 0
        self._draft_matching_bout_active = False
        self._draft_round_had_battle = False
        self._draft_battle_seen = False
        self._draft_clock_candidate = None
        self._draft_deploy_clock_wall = None
        self._draft_end_recorded = False
        self._draft_deployment_state = None
        self._draft_match_state = None
        self._draft_selection_pending = None
        self._draft_field_weights = None
        self.draft_unresolved_slots = []
        self._initialize_round_statistics()

    def _observe_duel_lobby(self):
        """只有重新进入组队大厅，才开启新大轮；连续大厅截图只计一次。"""
        in_lobby = bool(self.appear(self.I_WAIT_FIGHT_LOBBY))
        if in_lobby and not getattr(self, '_draft_wait_lobby_seen', False):
            self._draft_wait_lobby_seen = True
            if getattr(self, '_draft_round_had_battle', False):
                self._finalize_round_stats(completed=True, reason='返回wait_fight_lobby')
                self.draft_completed_rounds = getattr(self, 'draft_completed_rounds', 0) + 1
                self._draft_round_had_battle = False
                target = self.config.draft_duel.draft_duel_config.round_count
                logger.info(f'DraftDuel completed big rounds: {self.draft_completed_rounds}/{target}')
                if self.draft_completed_rounds >= target:
                    self._leave_draft_team(f'已完成{self.draft_completed_rounds}大轮协斗')
                    return
            self._initialize_duel_state()
            self.draft_big_round = getattr(self, 'draft_big_round', 0) + 1
            logger.info(f'DraftDuel new big round: {self.draft_big_round}')
        if in_lobby:
            self._draft_wait_lobby_seen = True
        elif getattr(self, '_draft_wait_lobby_seen', False) and any(self.appear(rule) for rule in (
                self.I_POST_DRAFT_SELECT, self.I_POST_DRAFT_RANK, self.I_POST_DRAFT_FIGHT,
                self.I_FIGHT_WAIT, GameUiAssets.I_CHECK_TOWN)):
            # 邀请面板或单帧漏识别不算离开大厅，避免重新看到大厅时误清本轮。
            self._draft_wait_lobby_seen = False

    def _begin_small_game(self):
        """post_draft_rank 发起的小局；取消匹配重试不增加小局次数。"""
        if not getattr(self, '_draft_matching_bout_active', False):
            self._draft_battle_seen = False
            self._draft_end_recorded = False
            self.draft_small_game = getattr(self, 'draft_small_game', 0) + 1
            self._draft_matching_bout_active = True
            self.draft_fielded = ()
            self.draft_deployment_rounds = []
            self.draft_peer_rounds = ()
            self._draft_deployment_state = None
            self._draft_field_weights = None
            self.draft_unresolved_slots = []
            logger.info(f'DraftDuel small game {self.draft_small_game} in current big round')
