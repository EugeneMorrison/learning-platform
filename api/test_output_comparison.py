"""Comparison semantics, author validation and grading/runner boundaries."""

import subprocess
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .output_comparison import (
    COMPARISON_MODES, MAX_SET_DEPTH, MAX_SET_ELEMENTS, MAX_SET_OUTPUT_CHARS,
    InvalidSetOutput, outputs_match, parse_set_output,
)


class OutputComparisonTests(SimpleTestCase):
    def test_exact_preserves_existing_whitespace_behavior(self):
        self.assertTrue(outputs_match('  one\ntwo\n', '\none\ntwo  '))
        for actual in ('two\none', 'one two', 'one \ntwo', 'one\n\ntwo'):
            self.assertFalse(outputs_match('one\ntwo', actual))
        self.assertTrue(outputs_match('', ' \n'))

    def test_unordered_lines_preserves_duplicates_and_line_contents(self):
        self.assertTrue(outputs_match('a\nb\na', 'a\na\nb', 'unordered_lines'))
        self.assertTrue(outputs_match('a\nb', 'b\r\na', 'unordered_lines'))
        for expected, actual in (
            ('a\na\nb', 'a\nb'), ('red blue', 'blue red'),
            ('a\n\nb', 'b\na'), ('a \nb', 'b\na'), ('a\n b', 'a\nb'),
        ):
            self.assertFalse(outputs_match(expected, actual, 'unordered_lines'))

    def test_unordered_tokens_preserves_duplicates_and_punctuation(self):
        self.assertTrue(outputs_match('1 2 2', '2\n1\t2', 'unordered_tokens'))
        self.assertTrue(outputs_match('red blue', 'blue red', 'unordered_tokens'))
        for expected, actual in (
            ('1 2 2', '1 2'), ('12 3', '1 23'), ('ab', 'ba'),
            ('{1, 2, 3}', '{3, 1, 2}'), ('a,b', 'b,a'),
        ):
            self.assertFalse(outputs_match(expected, actual, 'unordered_tokens'))

    def test_sets_follow_python_equality_for_supported_values(self):
        pairs = (
            ('{1, 2, 3}', '{3, 1, 2}'), ('{1}', '{True}'), ('{True}', '{1.0}'),
            ('{0}', '{False}'), ('{-0.0}', '{0}'), ('{-2}', '{-2.0}'),
            ('{0x10}', '{16}'), ('{None, "a,b", "red blue"}', "{'red blue', 'a,b', None}"),
            ('{(1, "x")}', "{(True, 'x')}"), ('{((), (None,))}', '{((), (None,))}'),
            ('set()', 'set()'), (' { 1, 2, } \n set() ', '{2, 1}\nset()'),
            (r"{'a\'b', '\\', '{x}'}", r'''{"{x}", "a'b", '\\'}'''),
        )
        for expected, actual in pairs:
            with self.subTest(expected=expected, actual=actual):
                self.assertTrue(outputs_match(expected, actual, 'python_sets'))

    def test_sets_retain_type_string_tuple_and_line_distinctions(self):
        for expected, actual in (
            ('{1}', "{'1'}"), ('{1, 2}', '{1, 3}'),
            ('{1}\n{2}', '{2}\n{1}'), ('{1}\n{1}', '{1}'),
            ('{(1, 2)}', '{(2, 1)}'), ("{'red blue'}", "{'blue red'}"),
            ('{9007199254740993}', '{9007199254740992.0}'),
        ):
            self.assertFalse(outputs_match(expected, actual, 'python_sets'))

    def test_duplicate_printed_values_are_invalid_including_numeric_aliases(self):
        for text in ('{1, 1}', '{1, True}', '{1, 1.0}', '{False, -0.0}',
                     '{(1,), (True,)}', "{'a', '\\x61'}"):
            with self.subTest(text=text):
                with self.assertRaises(InvalidSetOutput):
                    parse_set_output(text)
                # Even identical malformed outputs must not pass.
                self.assertFalse(outputs_match(text, text, 'python_sets'))
                self.assertFalse(outputs_match('{1}', text, 'python_sets'))

    def test_malformed_unsupported_and_executable_outputs_are_rejected(self):
        invalid = (
            '', '{}', '[1, 2]', '{1,', '{1 2}', '{1}\n\n{2}', 'Result: {1}',
            '{nan}', '{1e9999}', '{1j}', "{b'a'}", '{...}', '{[1]}', '{frozenset()}',
            '{x for x in [1]}', '{1 + 2}', '{-True}', '{--1}', '{*set()}',
            "{'a' 'b'}", '{1} # comment', 'set([1])', 'set(*[])',
            "{__import__('os').system('echo unsafe')}", '{1}\nprint(1)',
        )
        with mock.patch('builtins.eval', side_effect=AssertionError('must not execute')):
            for text in invalid:
                with self.subTest(text=text):
                    self.assertFalse(outputs_match('{1}', text, 'python_sets'))

    def test_parser_limits_before_and_after_parsing(self):
        invalid = (
            ' ' * (MAX_SET_OUTPUT_CHARS + 1),
            '{' + '(' * MAX_SET_DEPTH + '1' + ')' * MAX_SET_DEPTH + '}',
            '{' + ','.join(map(str, range(MAX_SET_ELEMENTS + 1))) + '}',
            '{' + ','.join(map(str, range(2500))) + '}',  # token budget
            '{' + '1' * 257 + '}',
        )
        for text in invalid:
            with self.subTest(length=len(text)):
                with self.assertRaises(InvalidSetOutput):
                    parse_set_output(text)
                self.assertFalse(outputs_match('{1}', text, 'python_sets'))
        self.assertTrue(outputs_match('{"' + '(' * 100 + '"}',
                                      '{"' + '(' * 100 + '"}', 'python_sets'))


class OutputComparisonApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='output_author', role='AUTHOR')
        cls.student = User.objects.create_user(username='output_student', role='STUDENT')
        cls.course = Course.objects.create(title='Output comparison', author=cls.author)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Output', order_index=1)
        Enrollment.objects.create(course=cls.course, student=cls.student)
        cls.block = Block.objects.create(lesson=cls.lesson, type='CODE', order_index=1, content={
            'prompt': 'Print values', 'starter_code': '# code',
            'tests': [{'input': '', 'expected': '1 2', 'visible': True}],
        })

    def setUp(self):
        cache.clear()

    def save_content(self, **changes):
        content = {**self.block.content, **changes}
        self.client.force_authenticate(self.author)
        return self.client.patch(f'/api/blocks/{self.block.pk}/', {'content': content}, format='json')

    def configure(self, mode, expected):
        self.block.content.update(output_comparison=mode, tests=[{
            'input': '', 'expected': expected, 'visible': True,
        }])
        self.block.save()

    def submit(self, **extra):
        self.client.force_authenticate(self.student)
        return self.client.post('/api/run-tests/', {
            'block_id': str(self.block.pk), 'code': 'print("answer")',
            'version': 'Python 3.12', **extra,
        }, format='json')

    def test_author_saves_each_mode_and_it_roundtrips_to_student(self):
        for mode in COMPARISON_MODES:
            response = self.save_content(output_comparison=mode, tests=[{
                'input': '', 'expected': '{1, 2}', 'visible': True,
            }])
            self.assertEqual(response.status_code, 200, response.data)
            self.block.refresh_from_db()
            self.assertEqual(self.block.content['output_comparison'], mode)
            self.client.force_authenticate(self.student)
            response = self.client.get(f'/api/blocks/{self.block.pk}/')
            self.assertEqual(response.data['content']['output_comparison'], mode)

    def test_invalid_modes_are_rejected(self):
        for mode in ('unknown', None, True, [], {}):
            response = self.save_content(output_comparison=mode)
            self.assertEqual(response.status_code, 400)
            self.assertIn('режим', str(response.data['content']))

    def test_bad_expected_output_has_test_number_and_understandable_error(self):
        for expected in ('{1, True}', '{1,', '{}', '', '{1e9999}', '{set([1])}'):
            response = self.save_content(output_comparison='python_sets', tests=[
                '{1}', {'input': '', 'expected': expected, 'visible': False},
            ])
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('Тест 2', str(response.data['content']))
        self.block.refresh_from_db()
        self.assertNotIn('output_comparison', self.block.content)

    def test_expected_output_and_test_structure_must_be_valid(self):
        for tests in ({}, None, [1], [{'expected': ['1']}], [{'expected': None}]):
            response = self.save_content(output_comparison='unordered_lines', tests=tests)
            self.assertEqual(response.status_code, 400)

    def test_create_validates_expected_sets_too(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/blocks/', {
            'lesson': str(self.lesson.pk), 'type': 'CODE', 'order_index': 2,
            'content': {**self.block.content, 'output_comparison': 'python_sets', 'tests': ['{1, 1}']},
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Block.objects.count(), 1)

    def test_legacy_string_tests_and_ordinary_output_remain_supported(self):
        response = self.save_content(output_comparison='python_sets', tests=['{1, 2}'])
        self.assertEqual(response.status_code, 200)
        response = self.save_content(tests=['ordinary string'])
        self.assertEqual(response.status_code, 200)

    def test_all_modes_grade_from_saved_configuration_without_runner_changes(self):
        for mode, expected, actual in (
            ('exact', '1 2', '1 2\n'),
            ('unordered_lines', 'a\nb\na', 'b\na\na'),
            ('unordered_tokens', '1 2 2', '2\n2 1'),
            ('python_sets', '{1, 2}', '{2, True}'),
        ):
            with self.subTest(mode=mode):
                self.configure(mode, expected)
                with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess(
                        [], 0, actual, '')) as run:
                    response = self.submit(output_comparison='unknown', tests=['fake'])
                self.assertEqual(response.data['status'], 'success', response.data)
                self.assertTrue(response.data['is_correct'])
                run.assert_called_once_with('print("answer")', stdin='', version='Python 3.12',
                                            header='', footer='')

    def test_student_cannot_relax_legacy_exact_or_edit_saved_mode(self):
        with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess([], 0, '2 1', '')):
            response = self.submit(output_comparison='unordered_tokens')
        self.assertEqual(response.data['status'], 'wrong_answer')
        self.client.force_authenticate(self.student)
        response = self.client.patch(f'/api/blocks/{self.block.pk}/', {
            'content': {**self.block.content, 'output_comparison': 'unordered_tokens'},
        }, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Progress.objects.get(student=self.student, block=self.block).is_correct)

    def test_mode_is_per_assignment(self):
        self.configure('unordered_tokens', '1 2')
        other = Block.objects.create(lesson=self.lesson, type='CODE', order_index=2, content={
            'prompt': 'Other', 'starter_code': '# code', 'tests': ['1 2'],
        })
        with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess([], 0, '2 1', '')):
            self.assertEqual(self.submit().data['status'], 'success')
            self.assertEqual(self.submit(block_id=str(other.pk)).data['status'], 'wrong_answer')

    def test_hidden_sets_use_same_mode_and_do_not_expose_outputs(self):
        self.configure('python_sets', '{1, 2}')
        self.block.content['tests'].append({
            'input': 'SECRET-INPUT', 'expected': "{'SECRET-OUTPUT', 1}", 'visible': False,
        })
        self.block.save()
        for hidden_output, status in (("{True, 'SECRET-OUTPUT'}", 'success'), ('{1, True}', 'wrong_answer')):
            with mock.patch('api.views.run_python', side_effect=[
                subprocess.CompletedProcess([], 0, '{2, 1}', ''),
                subprocess.CompletedProcess([], 0, hidden_output, ''),
            ]):
                response = self.submit()
            self.assertEqual(response.data['status'], status)
            self.assertEqual(response.data['results'][1]['hidden'], True)
            self.assertNotIn('SECRET', response.content.decode())
            if status == 'wrong_answer':
                self.assertNotIn('actual', response.data)
                self.assertNotIn('expected', response.data)

    def test_malformed_student_sets_are_wrong_answers_and_recorded(self):
        self.configure('python_sets', '{1}')
        with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess([], 0, '{1, True}', '')):
            response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'wrong_answer')
        self.assertFalse(Progress.objects.get(student=self.student, block=self.block).is_correct)
        self.assertEqual(Attempt.objects.filter(block=self.block, is_correct=False).count(), 1)

    def test_timeout_and_runtime_error_still_take_precedence(self):
        self.configure('python_sets', '{1}')
        with mock.patch('api.views.run_python', side_effect=subprocess.TimeoutExpired('python', 5)):
            response = self.submit()
        self.assertEqual(response.data['status'], 'error')
        self.assertIn('Time limit', response.data['stderr'])
        with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess([], 1, '{1}', 'Traceback')):
            response = self.submit()
        self.assertEqual(response.data['status'], 'error')
        self.assertEqual(response.data['stderr'], 'Traceback')

    def test_nonzero_exit_rejects_matching_stdout_before_comparison_in_every_mode(self):
        for mode in (None, *COMPARISON_MODES):
            for visible in (True, False):
                self.configure(mode or 'exact', '{1}')
                if mode is None:
                    self.block.content.pop('output_comparison')
                self.block.content['tests'][0]['visible'] = visible
                self.block.save()
                for returncode, stderr in ((1, 'RuntimeError: SECRET'), (7, ''), (-9, 'SECRET')):
                    with self.subTest(mode=mode, visible=visible, returncode=returncode):
                        with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess(
                                [], returncode, '{1}\n', stderr)), \
                                mock.patch('api.views.outputs_match', return_value=True) as compare:
                            response = self.submit()
                        compare.assert_not_called()
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.data['status'], 'error')
                        self.assertFalse(response.data['is_correct'])
                        self.assertTrue(response.data['recorded'])
                        self.assertEqual(response.data['passed'], 0)
                        self.assertEqual(response.data['results'], [])
                        self.assertFalse(Progress.objects.get(student=self.student, block=self.block).is_correct)
                        self.assertFalse(Attempt.objects.filter(block=self.block, is_correct=True).exists())
                        if not visible:
                            self.assertNotIn('SECRET', response.content.decode())
                            self.assertNotIn('stderr', response.data)

    def test_timeout_rejects_matching_partial_stdout_before_comparison_in_every_mode(self):
        for mode in (None, *COMPARISON_MODES):
            for visible in (True, False):
                with self.subTest(mode=mode, visible=visible):
                    self.configure(mode or 'exact', '{1}')
                    if mode is None:
                        self.block.content.pop('output_comparison')
                    self.block.content['tests'][0]['visible'] = visible
                    self.block.save()
                    timeout = subprocess.TimeoutExpired('python', 5, output='{1}\n', stderr='SECRET')
                    with mock.patch('api.views.run_python', side_effect=timeout), \
                            mock.patch('api.views.outputs_match', return_value=True) as compare:
                        response = self.submit()
                    compare.assert_not_called()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data['status'], 'error')
                    self.assertFalse(response.data['is_correct'])
                    self.assertTrue(response.data['recorded'])
                    self.assertEqual(response.data['passed'], 0)
                    self.assertEqual(response.data['results'], [])
                    self.assertNotIn('SECRET', response.content.decode())
                    self.assertFalse(Progress.objects.get(student=self.student, block=self.block).is_correct)
                    self.assertFalse(Attempt.objects.filter(block=self.block, is_correct=True).exists())

    def test_runtime_failure_after_a_passed_test_stops_and_cannot_solve_assignment(self):
        self.configure('python_sets', '{1}')
        self.block.content['tests'] *= 3
        self.block.save()
        with mock.patch('api.views.run_python', side_effect=[
            subprocess.CompletedProcess([], 0, '{True}', ''),
            subprocess.CompletedProcess([], 1, '{1}', 'RuntimeError'),
        ]) as run:
            response = self.submit()
        self.assertEqual(run.call_count, 2)  # The third test must not run.
        self.assertEqual(response.data['status'], 'error')
        self.assertEqual(response.data['test_number'], 2)
        self.assertEqual(response.data['passed'], 1)
        self.assertFalse(response.data['is_correct'])
        self.assertFalse(Progress.objects.get(student=self.student, block=self.block).is_correct)

    def test_failed_practice_is_rejected_without_revoking_an_earlier_solution(self):
        self.configure('python_sets', '{1}')
        Progress.objects.create(student=self.student, block=self.block, lesson=self.lesson,
                                completed=True, is_correct=True, answer={'code': 'print({1})'}, attempts=1)
        with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess([], 1, '{1}', 'RuntimeError')):
            response = self.submit()
        self.assertEqual(response.data['status'], 'error')
        self.assertFalse(response.data['is_correct'])
        self.assertFalse(response.data['recorded'])
        progress = Progress.objects.get(student=self.student, block=self.block)
        self.assertTrue(progress.is_correct)
        self.assertEqual(progress.answer, {'code': 'print({1})'})
        self.assertEqual(progress.attempts, 1)
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())

    def test_hidden_runtime_errors_remain_private(self):
        self.configure('python_sets', '{1}')
        self.block.content['tests'][0]['visible'] = False
        self.block.save()
        with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess([], 1, '{1}', 'SECRET')):
            response = self.submit()
        self.assertEqual(response.data['status'], 'error')
        self.assertTrue(response.data['hidden'])
        self.assertNotIn('SECRET', response.content.decode())
