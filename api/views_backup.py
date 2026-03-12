from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime


@api_view(['GET'])
def hello_view(request):
    """Simple hello endpoint"""
    return Response({'message': 'Hello World!'})


@api_view(['GET'])
def status_view(request):
    """API status with timestamp"""
    return Response({
        'status': 'ok',
        'message': 'Learning Platform API is running',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })


@api_view(['GET', 'POST'])
def course_list_view(request):
    """
    GET: Return list of courses
    POST: Create new course
    """

    if request.method == 'GET':
        # Hardcoded data for now
        courses = [
            {
                'id': 1,
                'title': 'Python Basics',
                'description': 'Learn Python from scratch',
                'students': 120
            },
            {
                'id': 2,
                'title': 'Django Web Development',
                'description': 'Build web apps with Django',
                'students': 85
            },
            {
                'id': 3,
                'title': 'React Frontend',
                'description': 'Modern frontend development',
                'students': 64
            }
        ]
        return Response(courses)

    elif request.method == 'POST':
        # Get data from request
        title = request.data.get('title')
        description = request.data.get('description')

        # Simple validation
        if not title:
            return Response(
                {'error': 'Title is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create new course (fake ID for now)
        new_course = {
            'id': 4,
            'title': title,
            'description': description,
            'students': 0
        }

        return Response(
            new_course,
            status=status.HTTP_201_CREATED
        )