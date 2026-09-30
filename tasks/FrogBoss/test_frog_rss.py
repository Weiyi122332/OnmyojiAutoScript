"""RSS recommendations must match today's round before the task can bet."""
import unittest
from datetime import datetime, time, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from xml.etree.ElementTree import ParseError
from xml.sax.saxutils import escape

import requests

from module.config.config_model import ConfigModel
from module.exception import TaskEnd
from tasks.FrogBoss.config import FrogBossConfig, Strategy
from tasks.FrogBoss.frog_bet import RunReport
from tasks.FrogBoss.frog_rss import (
    CHINA_TIME, RSS_URL, RssPrediction, fetch_prediction, parse_prediction, round_start,
)
from tasks.FrogBoss.script_task import ScriptTask


NOW = datetime(2026, 9, 30, 19, 55, tzinfo=CHINA_TIME)
PUBLISHED = NOW - timedelta(minutes=20)


def item(body, published=PUBLISHED, title='', link='https://ds.163.com/feed/example'):
    date = format_datetime(published) if isinstance(published, datetime) else published
    return (f'<item><title>{escape(title)}</title><description><![CDATA[{body}]]></description>'
            f'<pubDate>{escape(date)}</pubDate><link>{escape(link)}</link></item>')


def feed(*items):
    return ('<rss><channel>' + ''.join(items) + '</channel></rss>').encode('utf-8')


class RssTests(unittest.TestCase):
    def test_current_round_and_sides(self):
        self.assertEqual(round_start(NOW).hour, 18)
        for hint, expected in [('左(红)', 'LEFT'), ('红', 'LEFT'), ('右(蓝)', 'RIGHT'), ('蓝', 'RIGHT')]:
            with self.subTest(hint=hint):
                prediction = parse_prediction(feed(item(f'【对弈竞猜】\n18:00 {hint}')), NOW)
                self.assertEqual(prediction.choose_side(0, 0), expected)
                self.assertEqual(prediction.round_start, round_start(NOW))

    def test_comeback_selects_minority_and_tie_right(self):
        prediction = parse_prediction(feed(item('【对弈竞猜】18:00 押翻盘 左(红)')), NOW)
        self.assertEqual(prediction.hint, '翻盘')
        self.assertEqual(prediction.choose_side(10, 20), 'LEFT')
        self.assertEqual(prediction.choose_side(20, 10), 'RIGHT')
        self.assertEqual(prediction.choose_side(10, 10), 'RIGHT')
        for left, right in [(0, 0), (None, 10), ('10', 20), (-1, 10), (float('nan'), 10)]:
            with self.subTest(counts=(left, right)), self.assertRaises(ValueError):
                prediction.choose_side(left, right)

    def test_html_escaped_content_and_utc_publication(self):
        published_utc = PUBLISHED.astimezone(timezone.utc)
        prediction = parse_prediction(feed(item(
            '&lt;p&gt;【对弈竞猜】&lt;br&gt;18：00&nbsp;<b>右(蓝)</b>&lt;/p&gt;'
            '<img src="left.png" alt="左">', published_utc)), NOW)
        self.assertEqual(prediction.choose_side(10, 20), 'RIGHT')
        self.assertEqual(prediction.published_at, PUBLISHED)

    def test_test_server_items_do_not_consume_five_item_limit(self):
        test_items = [item('对弈竞猜 18:00 左', title='体验服') for _ in range(6)]
        prediction = parse_prediction(feed(*test_items, item('对弈竞猜 18:00 右')), NOW)
        self.assertEqual(prediction.choose_side(10, 20), 'RIGHT')
        self.assertIsNone(parse_prediction(feed(
            *[item('普通动态') for _ in range(5)], item('对弈竞猜 18:00 左')), NOW))

    def test_rejects_yesterday_future_and_missing_publication_dates(self):
        for published in [PUBLISHED - timedelta(days=1), NOW + timedelta(minutes=1), '', 'bad date']:
            with self.subTest(published=published):
                self.assertIsNone(parse_prediction(feed(item('对弈竞猜 18:00 左', published)), NOW))
        # UTC publication can be on the previous date while China is already today.
        morning = NOW.replace(hour=1, minute=45)
        published_utc = (morning - timedelta(minutes=20)).astimezone(timezone.utc)
        self.assertIsNotNone(parse_prediction(feed(item('对弈竞猜 00:00 左', published_utc)), morning))

    def test_never_borrows_hint_from_another_round_or_previous_result(self):
        for body in ['对弈竞猜 18:00 暂无建议 20:00 右',
                     '对弈竞猜 18:00 待分析 上局 左(红)竞猜成功',
                     '对弈竞猜 16:00 左', '年度总结 18:00 右']:
            with self.subTest(body=body):
                self.assertIsNone(parse_prediction(feed(item(body)), NOW))
        prediction = parse_prediction(feed(item('对弈竞猜 16:00 右 18:00 左 20:00 蓝')), NOW)
        self.assertEqual(prediction.choose_side(10, 20), 'LEFT')

    def test_fetch_uses_timeout_and_surfaces_failed_requests(self):
        response = Mock(content=feed(item('对弈竞猜 18:00 左')))
        with patch('tasks.FrogBoss.frog_rss.requests.get', return_value=response) as get:
            self.assertEqual(fetch_prediction(NOW).hint, '左')
        get.assert_called_once_with(RSS_URL, timeout=(3, 5))
        response.raise_for_status.assert_called_once()
        response.raise_for_status.side_effect = requests.HTTPError('503')
        with patch('tasks.FrogBoss.frog_rss.requests.get', return_value=response), self.assertRaises(requests.HTTPError):
            fetch_prediction(NOW)

    def test_new_option_is_exposed_and_default_stays_compatible(self):
        field = next(arg for arg in ConfigModel().script_task('FrogBoss')['frog_boss_config']
                     if arg['name'] == 'strategy_frog')
        self.assertIn('frog_rss', field['enumEnum'])
        self.assertEqual(FrogBossConfig().strategy_frog, Strategy.Majority)
        self.assertEqual(FrogBossConfig(strategy_frog='frog_rss').strategy_frog, Strategy.Rss)


class RssTaskTests(unittest.TestCase):
    def setUp(self):
        self.task = ScriptTask.__new__(ScriptTask)
        self.task.device = SimpleNamespace(image=object())
        self.task.config = SimpleNamespace(model=SimpleNamespace(frog_boss=SimpleNamespace(
            frog_boss_config=SimpleNamespace(strategy_frog=Strategy.Rss, before_end_frog=time(0, 10)))))
        self.task.screenshot = Mock()
        self.task.appear = Mock(return_value=True)
        self.task.O_LEFT_COUNT = SimpleNamespace(ocr=Mock(return_value=10))
        self.task.O_RIGHT_COUNT = SimpleNamespace(ocr=Mock(return_value=20))
        self.task.set_next_run = Mock()
        self.task.goto_page = Mock()
        self.task.ui_click_until_disappear = Mock()
        self.prediction = RssPrediction('翻盘', round_start(NOW), PUBLISHED, '对弈竞猜', 'post')
        self.task.run_report = RunReport('frog_rss', round_start(NOW))
        for name, kwargs in [
            ('fetch_prediction', {'return_value': self.prediction}),
            ('round_start', {'return_value': round_start(NOW)}),
            ('fingerprint', {'return_value': '0' * 512}),
            ('beijing_now', {'return_value': NOW.replace(tzinfo=None)}),
            ('datetime', {}),
        ]:
            patcher = patch(f'tasks.FrogBoss.script_task.{name}', **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.datetime.now.return_value = NOW.replace(tzinfo=None)

    def assert_retry_without_betting(self):
        with self.assertRaises(TaskEnd):
            self.task.do_bet()
        self.task.ui_click_until_disappear.assert_not_called()
        self.task.set_next_run.assert_called_once_with(
            task='FrogBoss', target=NOW.replace(tzinfo=None) + timedelta(minutes=1))
        self.task.goto_page.assert_called_once()

    def test_valid_advice_uses_refreshed_ocr(self):
        def refresh():
            self.task.O_LEFT_COUNT.ocr.return_value = 30
        self.task.screenshot.side_effect = refresh
        self.assertIs(self.task.get_rss(), self.task.I_BET_RIGHT)
        self.task.set_next_run.assert_not_called()

    def test_missing_advice_uses_majority_with_refreshed_counts(self):
        self.fetch_prediction.return_value = None
        self.task.screenshot.side_effect = lambda: setattr(self.task.O_LEFT_COUNT.ocr, 'return_value', 30)
        self.assertIs(self.task.get_rss(), self.task.I_BET_LEFT)
        self.assertIn('没有今天本场建议', self.task.run_report.fallback_reason)
        self.task.set_next_run.assert_not_called()

    def test_request_or_xml_failure_uses_majority(self):
        for error in [requests.Timeout('timeout'), ParseError('bad RSS')]:
            with self.subTest(error=error):
                self.fetch_prediction.side_effect = error
                self.assertIs(self.task.get_rss(), self.task.I_BET_RIGHT)
                self.assertIn('获取或解析建议失败', self.task.run_report.fallback_reason)
                self.task.set_next_run.assert_not_called()

    def test_round_or_lineup_change_defers_without_betting(self):
        self.round_start.side_effect = [round_start(NOW), round_start(NOW), round_start(NOW + timedelta(hours=2))]
        self.assert_retry_without_betting()
        self.task.set_next_run.reset_mock()
        self.task.goto_page.reset_mock()
        self.round_start.side_effect = None
        self.fingerprint.side_effect = ['0' * 512, '1' * 512]
        self.assert_retry_without_betting()

    def test_closed_window_or_invalid_minority_counts_defers(self):
        self.task.appear.return_value = False
        self.assert_retry_without_betting()
        self.task.set_next_run.reset_mock()
        self.task.goto_page.reset_mock()
        self.task.appear.return_value = True
        self.task.O_LEFT_COUNT.ocr.return_value = 0
        self.task.O_RIGHT_COUNT.ocr.return_value = 0
        self.assert_retry_without_betting()


if __name__ == '__main__':
    unittest.main()
