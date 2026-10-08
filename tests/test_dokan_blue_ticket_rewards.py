"""Recognize only blue tickets and include task scoped counts with reward images."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tasks.Dokan.reward_recognition import count_blue_tickets, count_blue_tickets_in_png
from tasks.Dokan.script_task import ScriptTask


FIXTURES = Path(__file__).with_name('fixtures') / 'dokan_rewards'


def reward_image(name):
    crop = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[160:430, 250:1055] = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    return image


def reward_png(name):
    image = cv2.cvtColor(reward_image(name), cv2.COLOR_RGB2BGR)
    success, encoded = cv2.imencode('.png', image)
    assert success
    return encoded.tobytes()


class DokanBlueTicketRecognitionTest(unittest.TestCase):
    def test_no_blue_ticket_is_zero_and_does_not_read_other_item_numbers(self):
        reader = Mock(side_effect=AssertionError('read an unrelated item'))
        self.assertEqual(count_blue_tickets(reward_image('without_blue.png'), reader), 0)
        reader.assert_not_called()

    def test_native_blue_ticket_samples_and_single_icon_deduplication(self):
        for name, expected in (('blue_three.png', 3), ('blue_two.png', 2)):
            with self.subTest(image=name):
                reader = Mock(return_value=(str(expected), 0.99))
                self.assertEqual(count_blue_tickets(reward_image(name), reader), expected)
                reader.assert_called_once()
                self.assertEqual(reader.call_args.args[0].shape, (93, 132, 3))

    def test_position_is_not_fixed_and_second_row_is_supported(self):
        source = reward_image('blue_three.png')[171:279, 667:775]
        for x, y in ((263, 171), (937, 171), (532, 306)):
            with self.subTest(position=(x, y)):
                image = np.zeros((720, 1280, 3), dtype=np.uint8)
                image[y:y + 108, x:x + 108] = source
                reader = Mock(return_value=('3', 0.99))
                self.assertEqual(count_blue_tickets(image, reader), 3)
                reader.assert_called_once()

    def test_clear_two_with_animation_background_is_read_after_ocr_retry(self):
        reader = Mock(side_effect=[('', 0.0), ('2', 0.99)])
        self.assertEqual(count_blue_tickets(reward_image('blue_two_background.png'), reader), 2)
        self.assertEqual(reader.call_count, 2)
        original, cleaned = [call.args[0] for call in reader.call_args_list]
        self.assertEqual(cleaned.shape, original.shape)
        self.assertGreater(np.count_nonzero(np.ptp(original, axis=2)), 0)
        self.assertTrue(np.all(np.ptp(cleaned, axis=2) == 0))
        self.assertEqual(cleaned.max(), 255)

    def test_retry_does_not_accept_low_confidence_or_invalid_numbers(self):
        for text, confidence in (('2', 0.79), ('', 0.0), ('0', 0.99), ('2张', 0.99)):
            with self.subTest(text=text):
                reader = Mock(side_effect=[('', 0.0), (text, confidence)])
                self.assertIsNone(count_blue_tickets(reward_image('blue_two_background.png'), reader))

    def test_distinct_blue_ticket_cards_are_added_without_duplicate_matches(self):
        image = reward_image('blue_three.png')
        image[171:279, 263:371] = image[171:279, 667:775].copy()
        reader = Mock(return_value=('3', 0.99))
        self.assertEqual(count_blue_tickets(image, reader), 6)
        self.assertEqual(reader.call_count, 2)

    def test_ticket_without_a_printed_quantity_means_one(self):
        image = reward_image('blue_three.png')
        image[249:280, 732:776] = 0
        reader = Mock(side_effect=AssertionError('no printed quantity'))
        self.assertEqual(count_blue_tickets(image, reader), 1)
        reader.assert_not_called()

    def test_bad_or_low_confidence_quantities_remain_unknown(self):
        for text, confidence in (('3', 0.79), ('', 0.99), ('30O', 0.99),
                                 ('0', 0.99), ('332 3', 0.99)):
            with self.subTest(text=text, confidence=confidence):
                self.assertIsNone(count_blue_tickets(
                    reward_image('blue_three.png'), Mock(return_value=(text, confidence))))

    def test_invalid_images_are_unknown_instead_of_zero(self):
        self.assertIsNone(count_blue_tickets(None))
        self.assertIsNone(count_blue_tickets(np.zeros((360, 640, 3), dtype=np.uint8)))
        self.assertIsNone(count_blue_tickets_in_png(b'invalid png'))
        self.assertIsNone(count_blue_tickets_in_png(b''))


class DokanBlueTicketPushTest(unittest.TestCase):
    def make_task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(notifier=SimpleNamespace(
            enable=True, push_images=Mock(return_value=True)))
        task.conf = SimpleNamespace(dokan_config=SimpleNamespace(push_reward_images=True))
        return task

    def test_samples_are_summarized_in_one_dated_push_and_deleted_after_delivery(self):
        task = self.make_task()
        images = [reward_png(name) for name in (
            'without_blue.png', 'blue_three.png', 'blue_two.png', 'blue_two_background.png')]
        with tempfile.TemporaryDirectory() as directory:
            task._dokan_reward_run_directory = Path(directory)
            for index, image in enumerate(images):
                (Path(directory) / f'{index}.png').write_bytes(image)
            with patch('tasks.Dokan.reward_recognition._read_quantity',
                       side_effect=[('3', 0.99), ('2', 0.99), ('', 0.0), ('2', 0.99)]):
                task._push_current_run_reward_images()
            self.assertFalse(Path(directory).exists())
        task.config.notifier.push_images.assert_called_once_with(
            images, title=f'{datetime.now():%Y-%m-%d} 道馆结算奖励',
            content='蓝票合计：7 张\n截图 1：蓝票0 张\n截图 2：蓝票3 张\n截图 3：蓝票2 张\n截图 4：蓝票2 张')

    def test_recognition_failure_does_not_prevent_images_from_being_sent(self):
        task = self.make_task()
        with patch('tasks.Dokan.script_task.count_blue_tickets_in_png',
                   side_effect=[3, RuntimeError('OCR unavailable')]):
            summary = task._dokan_reward_blue_ticket_summary([b'first', b'second'])
        self.assertIn('蓝票已识别合计：3 张', summary)
        self.assertIn('另有 1 张截图数量未识别', summary)
        self.assertIn('截图 2：蓝票数量未识别', summary)

        with tempfile.TemporaryDirectory() as directory:
            task._dokan_reward_run_directory = Path(directory)
            (Path(directory) / '1.png').write_bytes(b'first')
            with patch('tasks.Dokan.script_task.count_blue_tickets_in_png',
                       side_effect=RuntimeError('OCR unavailable')):
                task._push_current_run_reward_images()
        self.assertEqual(task.config.notifier.push_images.call_args.args[0], [b'first'])
        self.assertIn('数量未识别', task.config.notifier.push_images.call_args.kwargs['content'])

    def test_failed_notification_keeps_original_images(self):
        task = self.make_task()
        task.config.notifier.push_images.return_value = False
        with tempfile.TemporaryDirectory() as directory:
            task._dokan_reward_run_directory = Path(directory)
            screenshot = Path(directory) / '1.png'
            screenshot.write_bytes(reward_png('without_blue.png'))
            task._push_current_run_reward_images()
            self.assertTrue(screenshot.exists())


if __name__ == '__main__':
    unittest.main()
