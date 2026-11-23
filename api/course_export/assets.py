"""Resolve references through Django media storage without fetching arbitrary URLs."""
import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.http.request import validate_host


EXTENSIONS = {
    'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp',
    'image/svg+xml': '.svg', 'image/avif': '.avif', 'application/pdf': '.pdf',
    'text/plain': '.txt', 'audio/mpeg': '.mp3', 'audio/ogg': '.ogg', 'audio/wav': '.wav',
    'video/mp4': '.mp4', 'video/webm': '.webm', 'application/zip': '.zip',
}


def resource_prefix(url):
    return '/' + urlsplit(url).path.strip('/') + '/'


class AssetUnavailable(ValueError):
    """An asset resolution failure with a reason safe to print in a job log."""


class ExportTooLarge(RuntimeError):
    """The course exceeds the budget for a dashboard download."""


class Assets:
    def __init__(self, warn, byte_limit=None):
        self.warn = warn
        self.byte_limit = byte_limit
        self.total_bytes = 0
        self.references = {}
        self.files = {}

    def _read_stream(self, stream):
        if self.byte_limit is None:
            return stream.read()
        data = stream.read(self.byte_limit + 1)
        if len(data) > self.byte_limit:
            raise ExportTooLarge()
        return data

    def _read(self, reference, storage_name):
        media = urlsplit(settings.MEDIA_URL)
        static = urlsplit(settings.STATIC_URL)
        storage = default_storage
        if storage_name is None:
            url = urlsplit(reference)
            if url.scheme == 'data':
                header, _, body = reference.partition(',')
                types = {'data:image/png;base64': 'image/png', 'data:image/jpeg;base64': 'image/jpeg',
                         'data:image/gif;base64': 'image/gif', 'data:image/webp;base64': 'image/webp'}
                if header not in types:
                    raise AssetUnavailable('unsupported inline media')
                return base64.b64decode(body, validate=True), types[header]
            if url.scheme not in ('', 'http', 'https') or (
                url.netloc and url.netloc not in (media.netloc, static.netloc) and
                not validate_host(url.hostname or '', [h for h in settings.ALLOWED_HOSTS if h != '*'])
            ):
                raise AssetUnavailable('external resource')
            path = unquote(url.path)
            prefix = resource_prefix(settings.MEDIA_URL)
            if path.startswith(resource_prefix(settings.STATIC_URL)):
                prefix = resource_prefix(settings.STATIC_URL)
                storage = staticfiles_storage
            if not path.startswith(prefix):
                raise AssetUnavailable('outside configured storage')
            storage_name = path[len(prefix):]
        if any(part in ('', '.', '..') for part in storage_name.split('/')) or any(
                char in storage_name for char in ('\\', ':', '\x00')):
            raise AssetUnavailable('invalid media path')
        mime = mimetypes.guess_type(storage_name)[0] or 'application/octet-stream'
        if storage is staticfiles_storage:
            source = finders.find(storage_name)
            if source:
                local = Path(source).resolve()
                if local.is_file() and any(local.is_relative_to(Path(root).resolve()) for root in finders.searched_locations):
                    with local.open('rb') as stream:
                        return self._read_stream(stream), mime
                raise AssetUnavailable('invalid static asset')
        try:
            local = Path(storage.path(storage_name)).resolve()
        except NotImplementedError:
            pass  # Remote Django storage still enforces its own key namespace.
        else:
            if not local.is_relative_to(Path(storage.path('')).resolve()) or not local.is_file():
                raise AssetUnavailable('missing or invalid media file')
        with storage.open(storage_name, 'rb') as source:
            return self._read_stream(source), mime

    def resolve(self, reference, where, *, storage_name=None):
        if reference in self.references:
            return self.references[reference]
        try:
            data, mime = self._read(reference, storage_name)
        except (OSError, ValueError, SuspiciousFileOperation) as error:
            # References may contain signed URLs or embedded data. Only log location.
            reason = str(error) if isinstance(error, AssetUnavailable) else type(error).__name__
            self.warn(f'{where}: asset unavailable ({reason})')
            path = None
        else:
            digest = hashlib.sha256(data).hexdigest()
            path = f"assets/{digest}{EXTENSIONS.get(mime, '.bin')}"
            if self.byte_limit is not None and path not in self.files:
                self.total_bytes += len(data)
                if self.total_bytes > self.byte_limit:
                    raise ExportTooLarge()
            self.files.setdefault(path, (mime, data))
        self.references[reference] = path
        return path

    def html(self, value, where, *, offline):
        if not isinstance(value, str) or '<' not in value:
            return value
        soup = BeautifulSoup(value, 'html.parser')
        for tag in soup.select('img[srcset], source[srcset]'):
            # Native uploads use src. For imported responsive images, collect
            # candidates and choose a local fallback for the static reading view.
            candidates = re.findall(r'(data:[^\s]+|[^\s,]+)(?:\s+[^,]+)?(?:,|$)', tag['srcset'].strip())
            for candidate in candidates:
                candidate = candidate.rstrip(',')
                available = self.resolve(candidate, where)
                if offline and available:
                    if tag.name == 'img' and not tag.get('src'):
                        tag['src'] = candidate
                    elif tag.name == 'source' and tag.parent.name == 'picture':
                        image = tag.parent.find('img')
                        if image and not image.get('src'):
                            image['src'] = candidate
        # The lesson preview renderer supports rich text and images. Keep an
        # offline file link for authored audio/video in imported rich text.
        if offline:
            for tag in soup.select('video, audio'):
                source = tag.get('src') or next((s['src'] for s in tag.select('source[src]')), '')
                local = self.resolve(source, where)
                if local:
                    link = soup.new_tag('a', href=local)
                    link.string = 'Медиафайл'
                    tag.replace_with(link)
                else:
                    tag.replace_with('[Медиафайл недоступен]')
            for tag in soup.select('iframe, object, embed'):
                tag.replace_with('[Встроенный материал доступен онлайн]')
                self.warn(f'{where}: embedded player unavailable offline')
        for tag in soup.find_all(['img', 'a', 'video', 'audio', 'source']):
            attributes = ('href',) if tag.name == 'a' else ('src', 'poster')
            for attr in attributes:
                ref = tag.get(attr)
                if not ref:
                    continue
                if tag.name == 'a':
                    try:
                        path = urlsplit(ref).path
                    except ValueError:
                        path = ''
                    if not path.startswith((resource_prefix(settings.MEDIA_URL), resource_prefix(settings.STATIC_URL))):
                        continue  # An ordinary navigation link, not an embedded asset.
                path = self.resolve(ref, where)
                if offline:
                    if path:
                        tag[attr] = path
                    elif tag.name == 'img':
                        tag.replace_with('[Изображение недоступно: ' + (tag.get('alt') or 'файл') + ']')
                        break
                    else:
                        tag.attrs.pop(attr, None)
                        tag.append(' [Файл недоступен]')
        return str(soup) if offline else value


def visit_rich_text(kind, content, transform):
    """Visit native rich-text fields only. Code and sample input can contain literal HTML."""
    for field in ('prompt', 'question', 'html', 'explanation', 'feedback_correct', 'feedback_incorrect'):
        if isinstance(content.get(field), str):
            content[field] = transform(content[field])
    if kind == 'QUIZ':
        content['options'] = [transform(option) for option in content.get('options', [])]
    if kind in ('SORT', 'MATCH') and content.get('html') is True:
        items = [item for field in ('items', 'left', 'right') for item in content.get(field, [])]
        for pair in content.get('pairs', []):
            items.extend([pair['left'], pair['right']])
        for item in items:
            item['text'] = transform(item['text'])
