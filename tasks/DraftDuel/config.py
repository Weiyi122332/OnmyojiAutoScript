"""协同对弈匹配模式和通用邀请配置。"""

from enum import Enum

from pydantic import Field, model_validator

from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.GeneralInvite.config_invite import InviteConfig


class DraftMatchMode(str, Enum):
    SOLO = '单人'
    MEMBER = '队员'
    CAPTAIN = '队长'


class DraftDuelConfig(ConfigBase):
    match_mode: DraftMatchMode = Field(
        title='匹配模式', default=DraftMatchMode.SOLO,
        description='draft_duel_match_mode_help',
    )
    match_wait_seconds: int = Field(
        title='单次匹配等待时间', default=60, ge=1,
        description='draft_duel_match_wait_seconds_help',
    )
    round_count: int = Field(
        title='完成大轮数', default=1, ge=1,
        description='draft_duel_round_count_help',
    )
    @model_validator(mode='before')
    @classmethod
    def migrate_team_role(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if value.get('match_mode') == '组队':
                value['match_mode'] = value.get('role', '队长')
            value.pop('role', None)
        return value


class DraftDuel(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    draft_duel_config: DraftDuelConfig = Field(default_factory=DraftDuelConfig)
    invite_config: InviteConfig = Field(default_factory=InviteConfig)

    @model_validator(mode='before')
    @classmethod
    def migrate_invitation_settings(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        settings = dict(value.get('draft_duel_config') or {})
        invite = dict(value.get('invite_config') or {})
        old_names = settings.pop('invite_friend_list', None)
        old_wait = settings.pop('teammate_timeout_seconds', None)
        if old_names is not None:
            invite.setdefault('friend_list', old_names)
        if old_wait is not None:
            seconds = int(old_wait)
            invite.setdefault('wait_time', f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}')
        value['draft_duel_config'] = settings
        value['invite_config'] = invite
        return value
