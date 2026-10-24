"""
Course cover processing (Course.save, api/models.py).

Authors upload whatever a phone or a designer produces: a 4000 px, 4 MB photo
would otherwise go to every catalog card as is. A newly assigned cover is
turned upright (EXIF orientation), shrunk to at most MAX_WIDTH pixels wide
(aspect ratio kept, never enlarged) and re-encoded as WebP. WebP keeps
transparency, so transparent PNGs need no flattening, and re-encoding drops
the photo's metadata (camera, GPS). The original upload is not kept.
"""

import io
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_WIDTH = 1200  # px; cards show covers at about 400 px wide, x2 for dense screens, with room
WEBP_QUALITY = 82


def _has_alpha(img):
    return img.mode in ('RGBA', 'LA', 'PA') or (img.mode == 'P' and 'transparency' in img.info)


def shrink_cover(upload):
    """The upload (any image Pillow opens) as a WebP ContentFile named after it:
    upright, at most MAX_WIDTH wide. Raises PIL's errors for a non-image (the
    admin's ImageField rejects those before the model is saved)."""
    upload.seek(0)
    with Image.open(upload) as original:
        img = ImageOps.exif_transpose(original)  # a copy, rotated as the camera meant
        img = img.convert('RGBA' if _has_alpha(img) else 'RGB')  # also CMYK, 16-bit, palettes
        if img.width > MAX_WIDTH:
            height = max(1, round(img.height * MAX_WIDTH / img.width))
            img = img.resize((MAX_WIDTH, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, 'WEBP', quality=WEBP_QUALITY, method=6)
    name = (PurePosixPath(upload.name or 'cover').stem or 'cover') + '.webp'
    return ContentFile(out.getvalue(), name=name)
