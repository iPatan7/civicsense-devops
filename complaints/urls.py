from django.urls import path

from . import views

app_name = "complaints"

urlpatterns = [
    path("", views.home, name="home"),
    path("file/", views.file_complaint, name="file_complaint"),
    path("mine/", views.my_complaints, name="my_complaints"),
    path("browse/", views.browse, name="browse"),
    path("track/", views.track, name="track"),
    path("api/analyse/", views.api_analyse, name="api_analyse"),
    path("c/<str:tracking_id>/", views.complaint_detail, name="detail"),
    path("c/<str:tracking_id>/support/", views.support_complaint, name="support"),
    path("c/<str:tracking_id>/feedback/", views.give_feedback, name="feedback"),
]
