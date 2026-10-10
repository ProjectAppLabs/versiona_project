from django.urls import path
from accounts.views import auth, security

urlpatterns = [
    path('sign_in/2fa/', auth.sign_in_2fa, name='sign-in-2fa'),
    path('me/google/link/', security.google_link, name='google-link'),
    path('me/security/', security.my_security, name='my-security'),
    path('me/2fa/setup/', security.twofa_setup, name='twofa-setup'),
    path('me/2fa/enable/', security.twofa_enable, name='twofa-enable'),
    path('me/2fa/disable/', security.twofa_disable, name='twofa-disable'),
    path('me/sessions/', security.my_sessions, name='my-sessions'),
    path('me/sessions/revoke_others/', security.sessions_revoke_others, name='sessions-revoke-others'),
    path('me/sessions/<int:session_id>/revoke/', security.session_revoke, name='session-revoke'),
    path('sign_up/', auth.sign_up, name='sign_up'),
    path('sign_in/', auth.sign_in, name='sign_in'),
    path('google_login/', auth.google_login, name='google_login'),
    path('send_passcode/', auth.send_passcode, name='send_passcode'),
    path('verify_passcode_and_reset_password/', auth.verify_passcode_and_reset_password, name='verify_passcode_reset'),
    path('update_password/', auth.update_password, name='update_password'),
    path('validate_token/', auth.validate_token, name='validate_token'),
]

from accounts.views.profile import me_profile  # noqa: E402

urlpatterns += [
    path('me/profile/', me_profile, name='me-profile'),
]
