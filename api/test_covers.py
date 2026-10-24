"""Course cover processing on save (api/covers.py, Course.save)."""

import io
import shutil
import tempfile
from unittest import mock

from django.contrib.admin.sites import site
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from PIL import Image

from .covers import MAX_WIDTH
from .models import Course, User


def image_bytes(size, mode='RGB', fmt='JPEG', color=(200, 60, 60), exif_orientation=None):
    img = Image.new(mode, size, color)
    if mode == 'RGB':
        # A dark block in the top-left corner, to check the rotation direction.
        img.paste((0, 0, 0), (0, 0, size[0] // 4, size[1] // 4))
    out = io.BytesIO()
    kwargs = {}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation  # Orientation
        kwargs['exif'] = exif
    img.save(out, fmt, **kwargs)
    return out.getvalue()


class CoverProcessingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')

    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        settings = override_settings(MEDIA_ROOT=media)
        settings.enable()
        self.addCleanup(settings.disable)

    def save_cover(self, data, name='photo.jpg', course=None):
        course = course or Course(title='Course', author=self.author)
        course.cover = ContentFile(data, name=name)
        course.save()
        course.refresh_from_db()
        return course

    def opened(self, course):
        course.cover.open('rb')
        self.addCleanup(course.cover.close)
        img = Image.open(course.cover)
        img.load()
        return img

    def test_large_photo_is_shrunk_to_1200_wide_webp(self):
        data = image_bytes((4000, 3000))
        course = self.save_cover(data, name='IMG_0001.JPG')

        img = self.opened(course)
        self.assertEqual((img.format, img.size), ('WEBP', (MAX_WIDTH, 900)))
        self.assertRegex(course.cover.name, r'^covers/IMG_0001(_\w+)?\.webp$')
        self.assertLess(course.cover.size, len(data))

    def test_exif_rotation_is_applied(self):
        # Stored landscape 3000x2000, Orientation 6 = shown rotated 90° clockwise.
        course = self.save_cover(image_bytes((3000, 2000), exif_orientation=6))

        img = self.opened(course)
        self.assertEqual(img.size, (1200, 1800))  # upright portrait, then shrunk
        self.assertNotIn(0x0112, img.getexif())
        # Rotated clockwise, the dark top-left block ends up top-right.
        self.assertLess(sum(img.convert('RGB').getpixel((1150, 50))), 60)
        self.assertGreater(sum(img.convert('RGB').getpixel((50, 50))), 200)

    def test_small_image_is_not_enlarged(self):
        img = self.opened(self.save_cover(image_bytes((400, 300), fmt='PNG'), name='small.png'))
        self.assertEqual((img.format, img.size), ('WEBP', (400, 300)))

    def test_transparency_is_kept(self):
        rgba = image_bytes((1600, 1200), mode='RGBA', fmt='PNG', color=(0, 0, 0, 0))
        img = self.opened(self.save_cover(rgba, name='logo.png'))
        self.assertEqual((img.mode, img.size), ('RGBA', (1200, 900)))
        self.assertEqual(img.getpixel((10, 10))[3], 0)

        palette = Image.new('P', (300, 200), 0)
        palette.info['transparency'] = 0
        out = io.BytesIO()
        palette.save(out, 'PNG', transparency=0)
        img = self.opened(self.save_cover(out.getvalue(), name='palette.png'))
        self.assertEqual(img.mode, 'RGBA')
        self.assertEqual(img.getpixel((10, 10))[3], 0)

    def test_cmyk_jpeg_becomes_rgb(self):
        img = self.opened(self.save_cover(image_bytes((2400, 1800), mode='CMYK', color=(0, 80, 80, 0)), name='print.jpg'))
        self.assertEqual((img.mode, img.size), ('RGB', (1200, 900)))

    def test_saves_without_a_new_cover_do_not_reprocess(self):
        course = self.save_cover(image_bytes((2000, 1500)))
        name, size = course.cover.name, course.cover.size

        with mock.patch('api.models.shrink_cover') as shrink:
            course.title = 'Renamed'
            course.save()
            Course.objects.get(pk=course.pk).save()
        shrink.assert_not_called()
        course.refresh_from_db()
        self.assertEqual((course.cover.name, course.cover.size), (name, size))

    def test_replacing_the_cover_processes_the_new_one(self):
        course = self.save_cover(image_bytes((2000, 1500)), name='first.jpg')
        course = self.save_cover(image_bytes((3000, 1000)), name='second.jpg', course=course)
        self.assertRegex(course.cover.name, r'^covers/second(_\w+)?\.webp$')
        self.assertEqual(self.opened(course).size, (1200, 400))

    def test_course_without_cover_saves_as_before(self):
        course = Course.objects.create(title='No cover', author=self.author)
        self.assertFalse(course.cover)

    def test_admin_upload_is_processed(self):
        # The admin's form assigns the upload and saves the model: the same path.
        admin_user = User.objects.create_superuser('boss', 'b@example.com', 'x')
        request = RequestFactory().get('/admin/')
        request.user = admin_user
        course = Course.objects.create(title='Course', author=self.author)
        form_class = site._registry[Course].get_form(request, course, fields=['cover'])
        upload = SimpleUploadedFile('phone.jpg', image_bytes((4032, 3024)), content_type='image/jpeg')

        form = form_class(data={}, files={'cover': upload}, instance=course)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        course.refresh_from_db()
        self.assertEqual(self.opened(course).size, (1200, 900))
        self.assertTrue(course.cover.name.endswith('.webp'))

    # --- Old files are deleted when the cover is replaced or removed ------------

    def storage(self):
        return Course._meta.get_field('cover').storage

    def test_replacing_deletes_the_old_file(self):
        course = self.save_cover(image_bytes((800, 600)), name='first.jpg')
        first = course.cover.name

        with self.captureOnCommitCallbacks(execute=True):  # the delete waits for the commit
            course = self.save_cover(image_bytes((800, 600)), name='second.jpg', course=course)

        self.assertFalse(self.storage().exists(first))
        self.assertTrue(self.storage().exists(course.cover.name))

    def test_removing_deletes_the_file(self):
        course = self.save_cover(image_bytes((800, 600)))
        name = course.cover.name

        with self.captureOnCommitCallbacks(execute=True):
            course.cover = None
            course.save()

        course.refresh_from_db()
        self.assertFalse(course.cover)
        self.assertFalse(self.storage().exists(name))

    def test_other_saves_keep_the_file(self):
        course = self.save_cover(image_bytes((800, 600)))
        name = course.cover.name

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            course.title = 'Renamed'
            course.save()
            Course.objects.get(pk=course.pk).save(update_fields=['title'])

        self.assertEqual(callbacks, [])
        self.assertTrue(self.storage().exists(name))

    def test_rolled_back_save_keeps_the_old_file(self):
        from django.db import transaction

        course = self.save_cover(image_bytes((800, 600)), name='kept.jpg')
        kept = course.cover.name

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                course.cover = None
                course.save()
                raise RuntimeError('the request fails after the save')

        self.assertEqual(callbacks, [])  # the rollback dropped the delete
        self.assertTrue(self.storage().exists(kept))
        self.assertEqual(Course.objects.get(pk=course.pk).cover.name, kept)

    def test_file_used_by_another_course_is_kept(self):
        course = self.save_cover(image_bytes((800, 600)))
        shared = course.cover.name
        Course.objects.create(title='Copy', author=self.author, cover=shared)

        with self.captureOnCommitCallbacks(execute=True):
            course.cover = None
            course.save()

        self.assertTrue(self.storage().exists(shared))

    def test_admin_replace_and_clear_delete_old_files(self):
        admin_user = User.objects.create_superuser('boss', 'b@example.com', 'x')
        request = RequestFactory().get('/admin/')
        request.user = admin_user
        course = self.save_cover(image_bytes((800, 600)), name='old.jpg')
        old = course.cover.name

        def admin_save(data, files=None):
            instance = Course.objects.get(pk=course.pk)  # as the change page loads it
            form_class = site._registry[Course].get_form(request, instance, fields=['cover'])
            form = form_class(data=data, files=files or {}, instance=instance)
            self.assertTrue(form.is_valid(), form.errors)
            with self.captureOnCommitCallbacks(execute=True):
                form.save()
            return Course.objects.get(pk=course.pk)

        upload = SimpleUploadedFile('new.png', image_bytes((900, 600), fmt='PNG'), content_type='image/png')
        replaced = admin_save({}, {'cover': upload})
        self.assertFalse(self.storage().exists(old))
        self.assertTrue(self.storage().exists(replaced.cover.name))

        cleared = admin_save({'cover-clear': 'on'})  # the admin's «Очистить» checkbox
        self.assertFalse(cleared.cover)
        self.assertFalse(self.storage().exists(replaced.cover.name))

    def test_admin_help_text(self):
        help_text = Course._meta.get_field('cover').help_text
        self.assertIn('800×600', help_text)
        self.assertIn('own artwork only', help_text)
