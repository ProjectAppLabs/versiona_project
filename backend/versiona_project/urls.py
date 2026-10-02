import os

from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.urls import include, path
from accounts.views.auth import AuthTokenRefreshView, TokenObtainPairWithAdmissionView

from core.admin_site import admin_site


def health_check(request):
    # 'project'/'environment' let external probes verify WHO answered: a shared
    # codebase means the project name alone cannot tell prod from staging
    # (measured: /qa pilot #3).
    return JsonResponse({
        'status': 'ok',
        'project': settings.BASE_DIR.parent.name,
        # settings first: DJANGO_ENV lives in backend/.env and is read by
        # decouple, and the systemd units never export it, so os.getenv alone
        # would report 'development' in production.
        'environment': getattr(
            settings, 'DJANGO_ENV', os.getenv('DJANGO_ENV', 'development')
        ),
    })


urlpatterns = [
    path('api/health/', health_check, name='health-check'),
    path('admin/', admin_site.urls),
    path('api/token/', TokenObtainPairWithAdmissionView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', AuthTokenRefreshView.as_view(), name='token_refresh'),
    path('api/', include('accounts.urls')),
    path('api/', include('core.urls')),
    path('api/', include('orgs.urls')),
    path('api/', include('projects.urls')),
    path('api/', include('documents.urls')),
    path('api/', include('engine.urls')),
    path('api/', include('comparisons.urls')),
    path('api/', include('reviews.urls')),
    path('api/', include('notifications.urls')),
    path('api/', include('observations.urls')),
    path('api/', include('audit.urls')),
    path('api/', include('checks.urls')),
    path('api/', include('billing.urls')),
    path('api/public/', include('public_tools.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if getattr(settings, 'ENABLE_SILK', False):
    urlpatterns += [path('silk/', include('silk.urls', namespace='silk'))]
