from asgiref.sync import sync_to_async
from django.core.handlers.asgi import ASGIRequest
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from api.models import Course, CourseExportJob
from . import jobs


class ExportOptions(serializers.Serializer):
    format = serializers.ChoiceField(choices=['mhtml', 'zip'])
    author_materials = serializers.BooleanField(default=False)

    def validate(self, data):
        if data['author_materials'] and data['format'] != 'zip':
            raise serializers.ValidationError('Материалы автора доступны только в STEP (ZIP).')
        return data


class PrivateExportView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'course_export'

    def course(self, request, course_id):
        course = get_object_or_404(Course.objects.only('author_id', 'slug'), pk=course_id)
        if not jobs.can_export(request.user, course):
            raise Http404
        return course

    def job(self, request, course_id, job_id):
        course = self.course(request, course_id)
        job = get_object_or_404(CourseExportJob, course=course, pk=job_id, requester=request.user)
        job.course = course  # Reuse the metadata already read for authorization.
        return job

    def finalize_response(self, *args, **kwargs):
        response = super().finalize_response(*args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response


class CourseExportView(PrivateExportView):
    def post(self, request, course_id):
        course = self.course(request, course_id)
        options = ExportOptions(data=request.data)
        options.is_valid(raise_exception=True)
        job = jobs.enqueue(course, request.user, options.validated_data['format'],
                           options.validated_data['author_materials'])
        return Response({'id': job.pk, 'state': job.state}, status=202)


class ExportStatusView(PrivateExportView):
    def get(self, request, course_id, job_id):
        job = self.job(request, course_id, job_id)
        if job.state == 'queued' and timezone.now() - job.created_at > jobs.QUEUE_TTL:
            jobs.transition(job, 'queued', 'failed', jobs.TIME_ERROR)
            job.refresh_from_db()
        return Response({'state': job.state, 'error': job.error, 'filename': jobs.filename(job)})


class DownloadResponse(FileResponse):
    block_size = 64 * 1024

    def __init__(self, stream, path, request, job):
        self.artifact_path = path
        super().__init__(stream, as_attachment=True, filename=jobs.filename(job),
                         content_type='application/zip' if job.format == 'zip' else 'application/octet-stream')
        if isinstance(request._request, ASGIRequest):
            # Django otherwise adapts a synchronous file iterator by loading it all.
            async def chunks():
                read = sync_to_async(stream.read, thread_sensitive=False)
                while chunk := await read(self.block_size):
                    yield chunk
            self.streaming_content = chunks()
        self['X-Content-Type-Options'] = 'nosniff'
        self['X-Accel-Buffering'] = 'no'

    def close(self):
        super().close()
        jobs.remove_file(self.artifact_path)


class ExportDownloadView(PrivateExportView):
    def post(self, request, course_id, job_id):
        job = self.job(request, course_id, job_id)
        if job.state != 'ready' or timezone.now() - job.updated_at >= jobs.READY_TTL:
            return Response({'detail': 'Файл недоступен. Запустите экспорт ещё раз.'}, status=409)
        path = jobs.artifact(job)
        try:
            stream = path.open('rb')
        except FileNotFoundError:
            jobs.transition(job, 'ready', 'failed', jobs.TIME_ERROR)
            return Response({'detail': 'Файл больше недоступен.'}, status=410)
        try:
            if not jobs.transition(job, 'ready', 'downloaded'):
                stream.close()
                return Response({'detail': 'Файл уже скачан.'}, status=409)
            return DownloadResponse(stream, path, request, job)
        except BaseException:
            stream.close()
            raise
