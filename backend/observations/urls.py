from django.urls import path

from . import views

urlpatterns = [
    path('versions/<uuid:ver>/observations/', views.version_observations, name='version-observations'),
    path('observations/<uuid:obs>/', views.observation_detail, name='observation-detail'),
    path('observations/<uuid:obs>/replies/', views.observation_reply, name='observation-reply'),
    path('observations/<uuid:obs>/status/', views.observation_status, name='observation-status'),
    path('observations/<uuid:obs>/anchors/', views.observation_anchors, name='observation-anchors'),
    path('observations/<uuid:obs>/content/', views.observation_content, name='observation-content'),
    path(
        'observations/<uuid:obs>/replies/<uuid:reply>/content/',
        views.observation_reply_content, name='observation-reply-content',
    ),
    path(
        'observations/<uuid:obs>/anchors/<int:version_number>/content/',
        views.observation_anchor_content, name='observation-anchor-content',
    ),
]
