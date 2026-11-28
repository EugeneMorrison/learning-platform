from .block_content import TASK_TYPES
from .models import Block, Progress


def meets_completion(solved, total):
    return total == 0 or solved * 100 >= total * 89


def course_completed(user, course):
    tasks = Block.objects.filter(lesson__course=course, type__in=TASK_TYPES)
    return meets_completion(Progress.objects.filter(student=user, block__in=tasks, is_correct=True).count(), tasks.count())
