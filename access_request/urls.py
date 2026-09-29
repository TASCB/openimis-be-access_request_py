"""Public (unauthenticated) DRF endpoints; see ``views.py``."""
from django.urls import path

from access_request.views import (
    AccessProfileListView, SectionListView, LocationListView,
    AccessRequestSubmitView, AccessRequestStatusView,
)

urlpatterns = [
    # PUBLIC — no authentication required
    path('profiles/', AccessProfileListView.as_view()),
    path('sections/', SectionListView.as_view()),
    path('locations/', LocationListView.as_view()),
    path('submit/', AccessRequestSubmitView.as_view()),
    path('status/<str:ref_code>/', AccessRequestStatusView.as_view()),
]
