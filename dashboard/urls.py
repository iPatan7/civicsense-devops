from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("queue/", views.queue, name="queue"),
    path("duplicates/", views.duplicates, name="duplicates"),
    path("reports/", views.reports, name="reports"),
    path("api/charts/", views.api_charts, name="api_charts"),
    path("c/<str:tracking_id>/", views.detail, name="detail"),
    path("c/<str:tracking_id>/status/", views.update_status, name="update_status"),
    path("c/<str:tracking_id>/assign/", views.assign, name="assign"),
    path("c/<str:tracking_id>/reclassify/", views.reclassify, name="reclassify"),
    path("c/<str:tracking_id>/merge/", views.merge, name="merge"),
    path("c/<str:tracking_id>/unmerge/", views.unmerge, name="unmerge"),
]
