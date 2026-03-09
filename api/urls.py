from django.urls import path
from . import views

urlpatterns = [
    path('hello/', views.hello_view, name='hello'),
    path('status/', views.status_view, name='status'),
    path('courses/', views.course_list_view, name='course-list'),
]