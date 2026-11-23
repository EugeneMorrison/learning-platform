import asyncio
from asgiref.sync import sync_to_async
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from slugify import slugify

from api.models import Course, User
from .access import can_export
from . import downloads


class ExportOptions(serializers.Serializer):
    format = serializers.ChoiceField(choices=['mhtml', 'zip'])
    author_materials = serializers.BooleanField(default=False)

    def validate(self, data):
        if data['author_materials'] and data['format'] != 'zip':
            raise serializers.ValidationError('Материалы автора доступны только в STEP (ZIP).')
        return data


class ExportAuthorization(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'course_export'

    def post(self, request, course_id):
        course = get_object_or_404(Course.objects.only('author_id', 'slug'), pk=course_id)
        if not can_export(request.user, course):
            raise Http404
        options = ExportOptions(data=request.data)
        options.is_valid(raise_exception=True)
        return Response(dict(options.validated_data, user_id=request.user.pk, slug=course.slug))


def reauthorize(user_id, course_id):
    user = get_object_or_404(User, pk=user_id)
    course = get_object_or_404(Course.objects.only('author_id'), pk=course_id)
    if not can_export(user, course):
        raise Http404


class DownloadResponse(FileResponse):
    block_size = 64 * 1024

    def __init__(self, lease, filename, fmt):
        super().__init__(lease.file, as_attachment=True, filename=filename,
                         content_type='application/zip' if fmt == 'zip' else 'application/octet-stream')
        self.lease = lease
        self.timer = asyncio.get_running_loop().call_later(downloads.DOWNLOAD_SECONDS, self.close)

        async def chunks():
            try:
                while not lease.file.closed:
                    chunk = lease.file.read(self.block_size)
                    if not chunk:
                        break
                    yield chunk
                    await asyncio.sleep(0)
            finally:
                self.close()

        self.streaming_content = chunks()
        self['Cache-Control'] = 'private, no-store'
        self['X-Content-Type-Options'] = 'nosniff'
        self['X-Accel-Buffering'] = 'no'

    def close(self):
        self.timer.cancel()
        super().close()
        self.lease.close()


@csrf_exempt
async def export_course(request, course_id):
    gate = ExportAuthorization()
    # DRF owns JWT/session authentication, CSRF, permissions and validation.
    response = await sync_to_async(gate.dispatch)(request, course_id=course_id)
    if response.status_code != 200:
        response['Cache-Control'] = 'private, no-store'
        return await sync_to_async(response.render)()
    options = response.data
    lease = None
    try:
        lease = downloads.Lease(options['user_id'])
        await downloads.generate(lease, course_id, options['user_id'], options['format'], options['author_materials'])
        await sync_to_async(reauthorize)(options['user_id'], course_id)
        stem = slugify(options['slug'], max_length=48) or 'course'
        suffix = '-author' if options['author_materials'] else ''
        filename = f"{stem}-{course_id}{suffix}.{options['format']}"
        result = DownloadResponse(lease, filename, options['format'])
        lease = None  # Response owns the file and lock through completion.
        return result
    except Exception as error:
        if not isinstance(error, (downloads.ExportFailure, Http404, downloads.Throttled)):
            error = downloads.ExportFailure()
        response = gate.handle_exception(error)
        response = gate.finalize_response(gate.request, response)
        response['Cache-Control'] = 'private, no-store'
        return await sync_to_async(response.render)()
    finally:
        if lease is not None:
            lease.close()
