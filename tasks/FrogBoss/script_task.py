# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from cached_property import cached_property
from datetime import datetime
import requests
import re
import json
from pathlib import Path
from io import BytesIO
from typing import NoReturn
from xml.etree.ElementTree import ParseError

from PIL import Image

from module.exception import GameStuckError, TaskEnd
from module.logger import logger
from module.notify.task_notify import resolve_task_notifier
from module.atom.image import RuleImage
from module.base.timer import Timer

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.config_base import TimeDelta
from tasks.FrogBoss.assets import FrogBossAssets
from tasks.FrogBoss.config import Strategy
from tasks.FrogBoss.frog_bet import RunReport, majority_side
from tasks.FrogBoss.frog_oas import OasHistory, fetch_predictions, fingerprint, same_lineup
from tasks.FrogBoss.frog_rss import fetch_prediction, round_start
from tasks.FrogBoss.frog_schedule import beijing_now, next_bet_time


class ScriptTask(RightActivity, FrogBossAssets, GeneralBattleAssets):
    @cached_property
    def run_report(self):
        strategy = self.config.model.frog_boss.frog_boss_config.strategy_frog
        return RunReport(str(getattr(strategy, 'value', strategy)), round_start())

    @cached_property
    def oas_history(self):
        instance = re.sub(r'[^\w.-]', '_', self.config.config_name)
        return OasHistory(Path('data/frog_oas') / f'{instance}.jsonl')

    def record_oas_result(self):
        if self.config.model.frog_boss.frog_boss_config.strategy_frog != Strategy.Oas:
            return
        winner = self.detect()
        if winner is not None:
            result = self.oas_history.settle(
                fingerprint(self.device.image), 'LEFT' if winner else 'RIGHT')
            logger.info(f'frog_oas result: {result}')

    def enter_frog_boss(self):
        self.screenshot()
        if self.appear(self.I_FROG_CHECK):
            return
        self.enter(self.I_FROG_BOSS_ENTER)
        if not self.wait_until_appear(self.I_FROG_CHECK, wait_time=10):
            raise GameStuckError('FrogBoss page not detected after entering activity')

    def run(self):
        # A task object may be reused; each run gets its own single summary.
        self.__dict__.pop('run_report', None)
        report = self.run_report
        try:
            self._run()
        except TaskEnd:
            raise
        except Exception as exc:
            report.status = f'运行异常：{type(exc).__name__}：{exc}'
            raise
        finally:
            self.push_run_report()

    def push_run_report(self):
        try:
            notifier = resolve_task_notifier(
                self.config, getattr(self.config.model.frog_boss, 'notification_config', None))
            if not notifier.enable:
                return
            scheduler = getattr(self.config.model.frog_boss, 'scheduler', None)
            content = self.run_report.content(
                getattr(self.config, 'config_name', ''), getattr(scheduler, 'next_run', None))
            screenshot = self.run_report.screenshot
            if screenshot is not None and getattr(notifier, 'provider_name', '').lower() == 'gocqhttp':
                try:
                    if notifier.push_image(screenshot, title='对弈竞猜运行结果', content=content):
                        return
                except Exception as exc:
                    logger.warning(f'FrogBoss screenshot notification failed: {exc}')
                content += '\n截图发送失败，已改发文字摘要。'
                logger.warning('FrogBoss image notification failed; send text summary instead')
            elif screenshot is not None:
                content += '\n当前推送渠道不支持附带截图。'
            if not notifier.push(title='对弈竞猜运行结果', content=content):
                logger.warning('FrogBoss run notification was not sent')
        except Exception as exc:
            logger.warning(f'FrogBoss run notification failed: {exc}')

    def capture_bet_screenshot(self):
        # Freeze the same RGB frame that matched I_BETTED before navigation.
        if self.run_report.screenshot is not None:
            return
        try:
            with BytesIO() as stream:
                Image.fromarray(self.device.image).save(stream, format='PNG')
                self.run_report.screenshot = stream.getvalue()
        except Exception as exc:
            logger.warning(f'FrogBoss bet screenshot capture failed: {exc}')

    def _run(self):
        self.ensure_bet_time()
        self.enter_frog_boss()
        # 进入主界面
        while 1:
            self.screenshot()

            # 已经下注
            if self.appear(self.I_BETTED):
                logger.info('You have betted')
                self.run_report.status = '下注成功' if self.run_report.confirmed else '本场已下注，未重复下注'
                self.capture_bet_screenshot()
                break
            # 休息中
            if self.appear(self.I_FROG_BOSS_REST):
                logger.info('Frog Boss Rest')
                self.run_report.status = '活动休息中'
                break
            # 竞猜成功
            if self.appear(self.I_BET_SUCCESS):
                logger.info('You bet win')
                if '竞猜成功' not in self.run_report.settlements:
                    self.run_report.settlements.append('竞猜成功')
                self.record_oas_result()
                self.detect()
                while 1:
                    self.screenshot()
                    if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                        break
                    if self.appear_then_click(self.I_BET_SUCCESS_BOX, interval=1):
                        continue
                    if self.appear_then_click(self.I_REWARD, interval=2):
                        continue
                    if self.appear_then_click(self.I_NEXT_COMPETITION, interval=4):
                        continue
                continue
            # 竞猜失败
            if self.appear(self.I_BET_FAILURE):
                logger.info('You bet lose')
                if '竞猜失败' not in self.run_report.settlements:
                    self.run_report.settlements.append('竞猜失败')
                self.record_oas_result()
                self.ui_click_until_disappear(self.I_NEXT_COMPETITION)
                self.detect()
                continue
            # 正式竞猜
            if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                self.do_bet()
                continue

        logger.info('FrogBoss end')
        self.next_run()
        raise TaskEnd('FrogBoss')

    def next_run(self):
        before_end = self.config.model.frog_boss.frog_boss_config.before_end_frog
        now = beijing_now()
        completed_round = self.run_report.round_at.replace(tzinfo=None)
        current_round = now.replace(hour=now.hour // 2 * 2, minute=0, second=0, microsecond=0)
        target = next_bet_time(now, before_end, skip_current=completed_round == current_round)
        self.set_next_run(task='FrogBoss', target=target)

    def ensure_bet_time(self):
        now = beijing_now()
        before_end = self.config.model.frog_boss.frog_boss_config.before_end_frog
        target = next_bet_time(now, before_end)
        if target > now:
            self.run_report.status = f'等待下注时间：{target:%Y-%m-%d %H:%M:%S}'
            logger.info(f'FrogBoss betting not due; next window starts at {target}')
            self.set_next_run(task='FrogBoss', target=target)
            raise TaskEnd('FrogBoss')

    def do_bet(self):
        # Also check after navigation/rewards, which can cross a round boundary.
        self.ensure_bet_time()
        logger.hr('do bet', level=2)
        self.screenshot()
        flag_glod_30 = 0
        self.run_report.round_at = round_start()
        count_left, count_right = self.read_bet_counts()
        match self.config.model.frog_boss.frog_boss_config.strategy_frog:
            case Strategy.Majority:
                click_image = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
            case Strategy.Minority:
                click_image = self.I_BET_LEFT if count_left < count_right else self.I_BET_RIGHT
            case Strategy.Bilibili:
                click_image = self.fallback_majority('哔哩哔哩策略尚未接入有效建议')
            case Strategy.Dashen:
                signature, current_round = fingerprint(self.device.image), round_start()
                try:
                    click_image = self.get_dashen(count_left, count_right)
                except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
                    logger.warning(f'Dashen advice unavailable: {exc}')
                    click_image = None
                self.refresh_betting(signature, current_round)
                self.read_bet_counts()
                if click_image is None:
                    click_image = self.fallback_majority('大神策略未获取到本场有效押注建议', refresh=False)
            case Strategy.Rss:
                click_image = self.get_rss()
            case Strategy.Oas:
                click_image = self.get_oas()
            case Strategy.AlwaysRed:
                click_image = self.I_BET_LEFT
            case Strategy.AlwaysBlue:
                click_image = self.I_BET_RIGHT
            case _:
                raise ValueError(f'Unknown bet mode: {self.config.model.frog_boss.frog_boss_config.strategy_frog}')
        logger.info(f'You strategy is {self.config.model.frog_boss.frog_boss_config.strategy_frog} and bet on {click_image}')
        self.run_report.side = 'LEFT' if click_image is self.I_BET_LEFT else 'RIGHT'
        self.run_report.status = '准备下注，尚未确认成功'
        self.ui_click_until_disappear(click_image)
        gold_30_timer = Timer(10)
        gold_30_timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_GOLD_30_CHECK):
                self.run_report.amount = 300000
                break
            if gold_30_timer.reached():
                logger.info('Gold 30 not appear')
                break
            if self.appear_then_click(self.I_GOLD_30, interval=3):
                continue
        # 正式下注
        logger.info('Formal bet')
        while 1:
            self.screenshot()
            if self.appear(self.I_BETTED):
                self.run_report.confirmed = True
                self.run_report.status = '下注成功'
                self.capture_bet_screenshot()
                break
            if self.appear_then_click(self.I_BET_SURE, interval=2) and flag_glod_30 == 1:
                continue
            if self.appear_then_click(self.I_GOLD_30, interval=2):
                flag_glod_30 = 1
                continue
            if self.appear_then_click(self.I_UI_CONFIRM, interval=2):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2):
                continue

    def retry_bet(self, reason: str) -> NoReturn:
        before_end = self.config.model.frog_boss.frog_boss_config.before_end_frog
        target = next_bet_time(beijing_now() + TimeDelta(minutes=1), before_end)
        logger.warning(f'对弈竞猜：{reason}，下次重试 {target}')
        self.run_report.status = f'暂缓下注：{reason}'
        self.set_next_run(task='FrogBoss', target=target)
        self.goto_page(page_main)
        raise TaskEnd('FrogBoss')

    def read_bet_counts(self):
        counts = (self.O_LEFT_COUNT.ocr(self.device.image), self.O_RIGHT_COUNT.ocr(self.device.image))
        self.run_report.counts = counts
        return counts

    def refresh_betting(self, signature, current_round):
        self.screenshot()
        if current_round != round_start():
            self.retry_bet('获取建议期间场次已切换')
        if not (self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT)):
            self.retry_bet('下注窗口已关闭')
        if not same_lineup(signature, fingerprint(self.device.image)):
            self.retry_bet('获取建议期间阵容已变化')

    def fallback_majority(self, reason: str, refresh: bool = True) -> RuleImage:
        self.run_report.fallback_reason = reason
        if refresh:
            self.screenshot()
        if not (self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT)):
            self.retry_bet('下注窗口已关闭')
        try:
            side = majority_side(*self.read_bet_counts())
        except ValueError as exc:
            self.retry_bet(str(exc))
        logger.warning(f'对弈竞猜使用人数多数兜底：{reason}，下注={side}，人数={self.run_report.counts}')
        return self.I_BET_LEFT if side == 'LEFT' else self.I_BET_RIGHT

    def get_rss(self) -> RuleImage:
        signature = fingerprint(self.device.image)
        current_round = round_start()
        prediction = None
        reason = '最近 5 条正式服动态中没有今天本场建议'
        try:
            prediction = fetch_prediction()
        except (requests.RequestException, ParseError, ValueError) as exc:
            reason = f'RSS 获取或解析建议失败：{exc}'
        self.refresh_betting(signature, current_round)
        if prediction is None:
            return self.fallback_majority(reason, refresh=False)

        if prediction.round_start != current_round:
            return self.fallback_majority('RSS 建议不属于当前场次', refresh=False)
        # 翻盘 uses fresh counts after the network request.
        try:
            side = prediction.choose_side(*self.read_bet_counts())
        except ValueError as exc:
            return self.fallback_majority(str(exc), refresh=False)
        self.run_report.source = f'面灵气喵：{prediction.hint}，{prediction.link}'
        logger.info(f'RSS 跟押（面灵气喵）：{prediction.round_start:%Y-%m-%d %H:%M} '
                    f'建议={prediction.hint}，下注={side}，动态={prediction.link}')
        return self.I_BET_LEFT if side == 'LEFT' else self.I_BET_RIGHT

    def get_oas(self) -> RuleImage:
        signature, current_round = fingerprint(self.device.image), round_start()
        reason = 'OAS 策略未获取到本场有效博主建议'
        try:
            predictions = fetch_predictions(self.oas_history)
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            predictions = []
            reason = f'OAS 获取或解析建议失败：{exc}'
        self.refresh_betting(signature, current_round)
        count_left, count_right = self.read_bet_counts()
        fallback_side = None
        if not predictions:
            try:
                fallback_side = majority_side(count_left, count_right)
            except ValueError as exc:
                self.run_report.fallback_reason = reason
                self.retry_bet(str(exc))
        decision = self.oas_history.choose(
            signature, count_left, count_right, predictions,
            fallback_side=fallback_side, fallback_reason=reason if fallback_side else '')
        self.run_report.fallback_reason = decision.get('fallback_reason', '')
        self.run_report.source = f"OAS：{decision['mode']}"
        logger.info(f'frog_oas decision: {decision}')
        return self.I_BET_LEFT if decision['side'] == 'LEFT' else self.I_BET_RIGHT

    def detect(self) -> bool:
        """
        检测是左边赢了还是右边赢的
        :return: True 左边赢了
        """
        if self.appear(self.I_SUCCESS_LEFT) and self.appear(self.I_FAILURE_RIGHT):
            result = True
            logger.info('Left win')
        elif self.appear(self.I_SUCCESS_RIGHT) and self.appear(self.I_FAILURE_LEFT):
            result = False
            logger.info('Right win')
        else:
            result = None
        return result

    def get_bilibili(self) -> RuleImage:
        """
        获取博主的策略选择
        :return:
        """
        pass

    def get_dashen(self, count_left, count_right) -> RuleImage:
        """
        获取博主的策略选择，整合多个博主的投注策略，并返回最终的下注建议
        :return: 'left' 或 'right' 的下注目标
        """
        logger.info('Fetching strategy from multiple Dashen UPer')
        # 定义正则表达式
        red_regex = re.compile(r'(押红|押左|压红|压左|红方|红色|我红|我左|红优|左|红六|红七|红八|红九|红十|91开|82开|73开|64开)')
        blue_regex = re.compile(r'(押蓝|押右|压蓝|压右|蓝方|蓝色|我蓝|我右|蓝优|右|蓝六|蓝七|蓝八|蓝九|蓝十|19开|28开|37开|46开)')

        # 获取 feedId 的函数
        def get_feed_id(uid):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds?feedTypes=1,2,3,4,6,7,10,11&someOneUid={uid}'
            response = requests.get(url, timeout=(3, 5))
            if response.status_code == 200:
                data = response.json()
                if 'result' in data and 'feeds' in data['result'] and len(data['result']['feeds']) > 0:
                    return data['result']['feeds'][0]['id']
            return None
        
        # 获取 feed 详细信息的函数
        def get_feed_details(feed_id):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/facade?feedId={feed_id}'
            response = requests.get(url, timeout=(3, 5))
            if response.status_code == 200:
                data = response.json()
                try:
                    user_nick = data['result']['userInfos'][0]['user']['nick']
                    create_time = data['result']['feed']['createTime']
                    content_json = data['result']['feed']['content']
                    content_data = json.loads(content_json)
                    body_text = content_data['body']['text']
                    return {
                        'user_nick': user_nick,
                        'create_time': create_time,
                        'body_text': body_text
                    }
                except (KeyError, IndexError, json.JSONDecodeError):
                    return None
            return None
        
        # 检查发布时间是否符合规则
        def is_time_valid(create_time):
            # 定义时间段
            valid_time_ranges = [(10, 12), (12, 14), (14, 16), (16, 18), (18, 20), (20, 22), (22, 24)]
            now = datetime.now()
            # now = datetime(year=2024, month=10, day=3, hour=19, minute=45, second=0)  # 指定时间读取历史文章
            
            # 获取发布时间
            try:
                post_time = datetime.fromtimestamp(float(create_time) / 1000)
            except (TypeError, ValueError, OverflowError, OSError):
                return False
            if post_time.date() != now.date() or post_time > now:
                return False
            post_hour = post_time.hour
            
            # 检查发布时间是否在有效时间段内
            for start, end in valid_time_ranges:
                if start <= post_hour < end and start <= now.hour < end:
                    return True
            return False

        # 分析 body_text 来判断投注结果
        def analyze_bet(body_text):
            red_span=9999
            blue_span=9999
            if red_regex.search(body_text):
                red_span=red_regex.search(body_text).start()
            if blue_regex.search(body_text):
                blue_span=blue_regex.search(body_text).start()
            if red_span < blue_span:
                return 'LEFT'
            elif red_span > blue_span:
                return 'RIGHT'
            return 'Unknown'

        # 提供的 uid 列表
        uids = [
            {"name": "面灵气喵", "id": "462382f1127b46c5add1185d88f0ea40"},
            {"name": "余岁岁", "id": "54399446d5084a0e8878dac8f6ff56d0"},
            {"name": "七面相", "id": "840742d60e4a43208605ae68ca8c3f64"},
            {"name": "待机中的徐ok", "id": "c3c989fae4074d04b478b8ba47ae4120"},
            {"name": "雯雯", "id": "aaa923436aa440df9ac1ee3f47387b99"},
            {"name": "晨时微凉", "id": "72584a679e2f45b6859566b5523400d5"},
            {"name": "梅布斯尼", "id": "3d4726d99f2642a485729695b798cb8c"},
            {"name": "鸽海成路", "id": "1d2dcbbd7e3d481c8d0f27ba4ff0dc71"},
            {"name": "徐清林", "id": "21657a558bdd4ddfb6501298350336e7"},
            {"name": "不包邮哦亲", "id": "0e4e0c5a1e494a1fa9a58ac55de689c1"},
            {"name": "天真珈百璃", "id": "30e383c884f844a18a7a76fe3c1e888f"},
            {"name": "薛定谔家查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "嘤嘤井", "id": "e7107cd3010e418da26672669d8eeb5e"},
            {"name": "Prince班崎", "id": "74adeb1bfb2b4cf382edbbb430da2149"},
            {"name": "靠脸混饭", "id": "e87f855f36f24b34b9d8f8a4fb2d62b2"},
            {"name": "夜神月丶L", "id": "82de68c7672e4b6da65493fb829b57b6"},
            {"name": "是大荣啦", "id": "f6d6bb15d6024200a985752e2ab4c373"},
            {"name": "炒饭菌", "id": "06e2bba14a914012bc8064601cfa19ea"},
            {"name": "清流不加班", "id": "8982241de1844638b4bb455139b8dcc0"},
            {"name": "槐夏三十", "id": "a9724e98c1cb4a4e931ebc3f467ea73d"},
            {"name": "落沫颜", "id": "e9b0a16325af46628e8dfb9e7942cf1d"},
            {"name": "Mico林木森", "id": "b6b5bc8277e34f69aeca018db0081397"},
            {"name": "查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "CC南浔", "id": "74db771d92a54c28ae3e98d19aa565a3"},
            {"name": "冰七喜Den", "id": "e498e524252041e29999b38e57c4df1d"},
            {"name": "行水姑娘", "id": "30b0c2923faa483f95572c324a5bc910"},
            {"name": "更慕林", "id": "e32aedbdd8da46a5b5b497a16c4b7658"}
            # ... 可以添加更多 uid
        ]


        # 主函数，遍历这批 uid
        count_uper_left = 0  # 统计博主投注左侧红方次数
        count_uper_right = 0  # 统计博主投注右侧蓝方次数

        for user in uids:
            uid = user['id']
            name = user['name']
            try:
                feed_id = get_feed_id(uid)
                details = get_feed_details(feed_id) if feed_id else None
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
                logger.warning(f'Dashen advice unavailable for {name}: {exc}')
                continue
            if feed_id:
                # 检查 create_time 和 body_text
                if details and is_time_valid(details['create_time']) and details['body_text']:
                    bet_result = analyze_bet(details['body_text'])
                    bet_rate = (re.compile(r"([5-9]\d%|\d+开|[一二三四五六七八九十零]+开|([红蓝][一二三四五六七八九十零,0-9])+)")
                            .search(details.get('body_text')))
                    if bet_rate:
                        bet_rate = ',' + bet_rate.group()
                    else:
                        bet_rate = ''
                    # 输出博主结论，可省略
                    # logger.info(f"{name}({details['user_nick']}) has bet on the {bet_result}{bet_rate}")

                    # 根据投注结果更新统计
                    if bet_result == 'LEFT':
                        count_uper_left += 1
                    elif bet_result == 'RIGHT':
                        count_uper_right += 1

        # No advice is handled by the shared majority fallback in do_bet.
        if count_uper_left + count_uper_right == 0:
            return None
        self.run_report.source = f'大神博主：左 {count_uper_left} / 右 {count_uper_right}'
        # 最终输出决策
        if count_uper_left > count_uper_right:
            logger.info(f"Final decision: The best bet is LEFT({count_uper_left}:{count_uper_right})")
            return self.I_BET_LEFT  # 返回下注的目标是左边
        elif count_uper_right > count_uper_left:
            logger.info(f"Final decision: The best bet is RIGHT({count_uper_right}:{count_uper_left})")
            return self.I_BET_RIGHT  # 返回下注的目标是右边
        else:
            logger.info("Final decision:Left and right bets are equal, default bet is minority")
            # 若五五开则投注少数博反压奖励
            if count_left < count_right:
                return self.I_BET_LEFT
            else:
                return self.I_BET_RIGHT


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()
