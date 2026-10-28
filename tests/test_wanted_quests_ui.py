"""新版悬赏详情文案和四卡协作布局的回归检查。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tasks.WantedQuests.config import CooperationType, WantedQuestsConfig, WQType
from tasks.WantedQuests.script_task import ScriptTask


class WantedQuestsUiTest(unittest.TestCase):
    def make_task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.device = SimpleNamespace(image=None)
        task.screenshot = Mock()
        task.get_config = lambda: WantedQuestsConfig()
        return task

    def test_new_shard_label_preserves_destination_and_count(self):
        task = self.make_task()
        row = task.build_wq_info(
            Mock(ocr=Mock(return_value='式神碎片')),
            Mock(ocr=Mock(return_value='式神碎片第十八章（数量：14）')),
            task.I_GOTO_1, 20,
        )
        self.assertEqual((row.type, row.dest, row.number, row.do_num),
                         (WQType.CHALLENGE, '第十八章', 14, 2))

    def test_full_row_labels_do_not_become_part_of_destination(self):
        task = self.make_task()
        for kind, text, destination in (
            ('探索', '探索第十一章(数量:7)', '第十一章'),
            ('秘闻', '秘闻征服世界·柒(数量:2)', '征服世界·柒'),
            ('式神', '第七章(数量:14)', '第七章'),
        ):
            with self.subTest(kind=kind):
                row = task.build_wq_info(
                    Mock(ocr=Mock(return_value=kind)), Mock(ocr=Mock(return_value=text)),
                    task.I_GOTO_2, 10,
                )
                self.assertEqual(row.dest, destination)

    def test_target_header_keeps_only_monster_name(self):
        for text, expected in (
            ('悬赏目标：击败6个鲤鱼精', '鲤鱼精'),
            ('自己击败独眼小僧', '独眼小僧'),
            ('悬赏目标: 击败 12 个 酒吞童子', '酒吞童子'),
            ('阎魔', '阎魔'),
        ):
            with self.subTest(text=text):
                self.assertEqual(ScriptTask._wq_monster_name(text), expected)

    def test_unwanted_monster_is_still_skipped_with_new_target_header(self):
        task = self.make_task()
        task.appear = Mock(return_value=True)
        task.O_WQ_MONSTER_TYPE = Mock(detect_text=Mock(return_value='悬赏目标：击败6个阎魔'))
        task.unwanted_boss_name_list = ['阎魔']
        task.ui_click = Mock()
        task.get_ordered_wq_infos = Mock()
        self.assertFalse(task.execute_mission(6))
        task.ui_click.assert_called_once_with(task.I_TRACE_TRUE, task.I_TRACE_FALSE)
        task.get_ordered_wq_infos.assert_not_called()

    def test_fourth_cooperation_card_is_found_after_non_cooperation_cards(self):
        task = self.make_task()
        task.appear = lambda rule: any(rule is candidate for candidate in (
            task.I_WQ_INVITE_4, task.I_WQ_COOPERATION_TYPE_GOLD_4,
        ))
        result = task.get_cooperation_info()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], CooperationType.Gold)
        self.assertIs(result[0]['inviteBtn'], task.I_WQ_INVITE_4)

    def test_invitation_dispatch_checks_all_four_cards(self):
        task = self.make_task()
        task.invite_random = Mock()
        task.invite_five()
        self.assertEqual([call.args[0] for call in task.invite_random.call_args_list],
                         list(task.cooperation_buttons()))
        self.assertEqual(task.invite_random.call_count, 4)

    def test_named_invitation_does_not_require_first_card_to_be_cooperation(self):
        task = self.make_task()
        task.appear = lambda rule: rule is task.I_WQ_INVITE_4
        task.get_cooperation_info = Mock(return_value=[])
        self.assertFalse(task.all_cooperation_invite())
        task.get_cooperation_info.assert_called_once()

    def test_open_detail_recognizes_untracked_quest(self):
        task = self.make_task()
        task.appear = lambda rule: rule is task.I_WQ_TRACE_ONE_CHECK_OPENED
        task.click = Mock()
        self.assertTrue(task.open_wq_info())
        task.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
