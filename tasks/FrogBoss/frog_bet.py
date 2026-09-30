"""Shared fallback decisions and per-run notification content."""
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from numbers import Real
from typing import Optional


STRATEGY_NAMES = {
    'frog_majority': '人数多数',
    'frog_minority': '人数少数',
    'frog_bilibili': '哔哩哔哩',
    'frog_dashen': '大神博主',
    'frog_rss': 'RSS 跟押（面灵气喵）',
    'frog_oas': 'OAS 加权策略',
    'frog_always_red': '固定押红',
    'frog_always_blue': '固定押蓝',
}
SIDE_NAMES = {'LEFT': '左（红）', 'RIGHT': '右（蓝）'}


def majority_side(left, right) -> str:
    if not all(isinstance(n, Real) and isfinite(n) and n >= 0 for n in (left, right)) or left + right <= 0:
        raise ValueError('多数方兜底需要有效的左右下注人数')
    return 'LEFT' if left > right else 'RIGHT'


@dataclass
class RunReport:
    strategy: str
    round_at: datetime
    status: str = '尚未下注'
    side: Optional[str] = None
    counts: Optional[tuple] = None
    amount: Optional[int] = None
    confirmed: bool = False
    source: str = ''
    fallback_reason: str = ''
    settlements: list = field(default_factory=list)
    screenshot: Optional[bytes] = field(default=None, repr=False)

    def content(self, instance: str, next_run=None) -> str:
        lines = [f'实例：{instance}', f'场次：{self.round_at:%Y-%m-%d %H:%M}',
                 f'首选策略：{STRATEGY_NAMES.get(self.strategy, self.strategy)}',
                 f'运行结果：{self.status}']
        if self.settlements:
            lines.append('上局结算：' + '；'.join(self.settlements))
        if self.side:
            prefix = '下注' if self.confirmed else '计划下注'
            amount = '30 万金币' if self.amount == 300000 else '金额未确认'
            lines.append(f'{prefix}：{SIDE_NAMES[self.side]}，{amount}')
        if self.counts is not None:
            lines.append(f'人数：左 {self.counts[0]} / 右 {self.counts[1]}')
        if self.fallback_reason:
            lines.extend(['实际策略：人数多数（兜底）', f'兜底原因：{self.fallback_reason}'])
        else:
            lines.append('兜底：未使用')
        if self.source:
            lines.append(f'建议来源：{self.source}')
        if isinstance(next_run, datetime):
            lines.append(f'下次运行：{next_run:%Y-%m-%d %H:%M:%S}')
        return '\n'.join(lines)
