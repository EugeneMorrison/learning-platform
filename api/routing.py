from django.urls import re_path

from .consumers import ChatConsumer


websocket_urlpatterns = [
    # ws/chat/<course-uuid>/<other-user-id>/?token=<jwt>
    re_path(
        r'^ws/chat/(?P<course_id>[0-9a-f-]+)/(?P<other_user_id>\d+)/$',
        ChatConsumer.as_asgi(),
    ),
]
