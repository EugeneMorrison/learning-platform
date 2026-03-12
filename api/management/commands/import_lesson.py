"""
Django management command to import HTML lesson into database.

Usage:
    python manage.py import_lesson path/to/lesson.html

This will:
1. Parse the HTML file
2. Create a Course
3. Create a Lesson
4. Create Blocks (TEXT, QUIZ, CODE)
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from bs4 import BeautifulSoup
from api.models import Course, Lesson, Block
import json
import re

User = get_user_model()


class Command(BaseCommand):
    help = 'Import HTML lesson file into database'

    def add_arguments(self, parser):
        parser.add_argument('html_file', type=str, help='Path to HTML file')
        parser.add_argument('--author', type=str, default='john_author', help='Author username')
        parser.add_argument('--course-title', type=str, help='Course title (auto-detected if not provided)')

    def handle(self, *args, **options):
        html_file = options['html_file']
        author_username = options['author']
        
        self.stdout.write(self.style.SUCCESS(f'📚 Importing lesson from: {html_file}'))
        
        # Get author
        try:
            author = User.objects.get(username=author_username)
            self.stdout.write(self.style.SUCCESS(f'✅ Author: {author.username}'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'❌ User {author_username} not found!'))
            return
        
        # Read HTML file
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'❌ File not found: {html_file}'))
            return
        
        # Parse HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Get title
        title_tag = soup.find('h2')
        if title_tag:
            lesson_title = title_tag.get_text().strip()
            # Clean up emoji and formatting
            lesson_title = re.sub(r'[⭐️]', '', lesson_title).strip()
        else:
            lesson_title = 'Imported Lesson'
        
        course_title = options.get('course_title') or f'Курс: {lesson_title}'
        
        self.stdout.write(f'📖 Lesson: {lesson_title}')
        
        # Create or get course
        course, created = Course.objects.get_or_create(
            title=course_title,
            author=author,
            defaults={
                'description': f'Автоматически импортированный курс из HTML файла',
                'is_published': True
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'✅ Created course: {course.title}'))
        else:
            self.stdout.write(f'📚 Using existing course: {course.title}')
        
        # Create lesson
        lesson_count = course.lessons.count()
        lesson = Lesson.objects.create(
            course=course,
            title=lesson_title,
            order_index=lesson_count + 1
        )
        self.stdout.write(self.style.SUCCESS(f'✅ Created lesson: {lesson.title}'))
        
        # Parse blocks
        blocks_created = 0
        order_index = 1
        
        # Find all step divs
        steps = soup.find_all('div', class_='step')
        
        if not steps:
            # If no steps found, create one TEXT block with all content
            main_content = soup.find('body')
            if main_content:
                # Remove step divs
                for step in main_content.find_all('div', class_='step'):
                    step.decompose()
                
                html_block = str(main_content)
                
                Block.objects.create(
                    lesson=lesson,
                    type='TEXT',
                    order_index=order_index,
                    content={'html': html_block}
                )
                blocks_created += 1
                self.stdout.write(f'  📝 Block {order_index}: TEXT (main content)')
        else:
            # Get content before first step as TEXT block
            body = soup.find('body')
            if body:
                # Get all content before first step
                content_parts = []
                for element in body.children:
                    if element.name == 'div' and 'step' in element.get('class', []):
                        break
                    if element.name in ['h1', 'h2', 'h3', 'p', 'pre', 'ul', 'blockquote']:
                        content_parts.append(str(element))
                
                if content_parts:
                    html_content = '\n'.join(content_parts)
                    Block.objects.create(
                        lesson=lesson,
                        type='TEXT',
                        order_index=order_index,
                        content={'html': html_content}
                    )
                    blocks_created += 1
                    self.stdout.write(f'  📝 Block {order_index}: TEXT (intro)')
                    order_index += 1
            
            # Process each step
            for step in steps:
                block_type_tag = step.find('b')
                if not block_type_tag:
                    continue
                
                block_type = block_type_tag.get_text().strip().lower()
                
                if block_type == 'choice':
                    # QUIZ block
                    question_p = step.find('p')
                    question = question_p.get_text().strip() if question_p else ''
                    
                    # Get code if exists
                    code_tag = step.find('pre')
                    if code_tag:
                        question += '\n\n' + code_tag.get_text()
                    
                    # Get options
                    options_div = step.find('div', class_='choice-options')
                    options = []
                    if options_div:
                        option_items = options_div.find_all('li')
                        for item in option_items:
                            # Clean up HTML entities
                            option_text = item.get_text().strip()
                            option_text = option_text.replace('⬜ ', '')
                            options.append(option_text)
                    
                    # Get answer from dataset
                    dataset = step.find('details', class_='dataset-block')
                    correct_answer = 0  # Default
                    
                    if dataset:
                        dataset_text = dataset.get_text()
                        # Try to parse JSON from dataset
                        try:
                            json_match = re.search(r'\{[^}]+\}', dataset_text, re.DOTALL)
                            if json_match:
                                data = json.loads(json_match.group())
                                # In this format, answer is usually option index 0
                                # We'll need to enhance this based on actual answer markers
                        except:
                            pass
                    
                    Block.objects.create(
                        lesson=lesson,
                        type='QUIZ',
                        order_index=order_index,
                        content={
                            'question': question,
                            'options': options,
                            'correct_answer': correct_answer,
                            'explanation': 'Проверьте свой ответ'
                        }
                    )
                    blocks_created += 1
                    self.stdout.write(f'  ❓ Block {order_index}: QUIZ ({len(options)} options)')
                    order_index += 1
                
                elif block_type == 'code':
                    # CODE block
                    # Get problem description
                    paragraphs = step.find_all('p')
                    prompt_parts = []
                    for p in paragraphs:
                        prompt_parts.append(p.get_text())
                    prompt = '\n'.join(prompt_parts)
                    
                    # Get test cases from table
                    tests = []
                    table = step.find('table')
                    if table:
                        rows = table.find_all('tr')[1:]  # Skip header
                        for row in rows:
                            cells = row.find_all('td')
                            if len(cells) >= 3:
                                test_input = cells[1].get_text().strip()
                                expected_output = cells[2].get_text().strip()
                                tests.append({
                                    'input': test_input,
                                    'expected': expected_output
                                })
                    
                    Block.objects.create(
                        lesson=lesson,
                        type='CODE',
                        order_index=order_index,
                        content={
                            'prompt': prompt,
                            'starter_code': '# Ваш код здесь\n',
                            'solution': '',
                            'tests': tests
                        }
                    )
                    blocks_created += 1
                    self.stdout.write(f'  💻 Block {order_index}: CODE ({len(tests)} tests)')
                    order_index += 1
        
        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*50))
        self.stdout.write(self.style.SUCCESS(f'✅ Import complete!'))
        self.stdout.write(f'   Course: {course.title} (id: {course.id})')
        self.stdout.write(f'   Lesson: {lesson.title} (id: {lesson.id})')
        self.stdout.write(f'   Blocks created: {blocks_created}')
        self.stdout.write(self.style.SUCCESS('='*50))
        self.stdout.write(f'\n📖 View lesson: http://127.0.0.1:9000/api/lessons/{lesson.id}/')
        self.stdout.write(f'📦 View blocks: http://127.0.0.1:9000/api/blocks/?lesson={lesson.id}')
