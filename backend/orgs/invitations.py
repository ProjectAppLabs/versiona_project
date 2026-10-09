"""A2 invitation services: create + email, accept with email match, revoke."""

import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from audit import services as audit
from documents.services.version_service import DomainError
from notifications.services import notify

from .models import Invitation, OrganizationMembership

logger = logging.getLogger(__name__)

INVITATION_TTL_DAYS = 14
PROJECT_ROLES = {'admin', 'editor', 'reviewer', 'viewer'}


@transaction.atomic
def create_invitation(project, invited_by, *, email: str, role: str, request=None) -> Invitation:
    from django.contrib.auth import get_user_model

    email = (email or '').strip().lower()
    if not email:
        raise DomainError('La invitación necesita un email.', 400)
    if role not in PROJECT_ROLES:
        raise DomainError(f'Rol inválido: {role}.', 400)
    from projects.models import ProjectMembership

    User = get_user_model()
    existing_user = User.objects.filter(email=email).first()
    if existing_user and ProjectMembership.objects.filter(
        project=project, user=existing_user
    ).exists():
        raise DomainError(f'{email} ya es miembro de este proyecto.', 409)
    if Invitation.objects.filter(
        project=project, email=email, status=Invitation.Status.PENDING
    ).exists():
        raise DomainError(f'Ya hay una invitación pendiente para {email}.', 409)

    from billing.services import check_member_limit

    check_member_limit(project.organization)
    invitation = Invitation.objects.create(
        organization=project.organization,
        project=project,
        email=email,
        role=role,
        token=secrets.token_urlsafe(32),
        invited_by=invited_by,
        expires_at=timezone.now() + timedelta(days=INVITATION_TTL_DAYS),
    )
    audit.record(
        org=project.organization, project=project, actor=invited_by,
        event_type='invitation.created', obj=invitation,
        payload={'email': email, 'role': role}, request=request,
    )
    _send_invitation_email(invitation)
    return invitation


def _send_invitation_email(invitation: Invitation):
    from django.conf import settings
    from django.core.mail import send_mail

    link = f'{settings.FRONTEND_URL}/invite/{invitation.token}'
    project_name = invitation.project.name if invitation.project else invitation.organization.name
    try:
        send_mail(
            subject=f'{invitation.invited_by.email} te invitó a "{project_name}" en Versiona',
            message=(
                f'Te invitaron como {invitation.role} al proyecto "{project_name}".\n\n'
                f'Acepta la invitación aquí: {link}\n\n'
                f'El enlace vence en {INVITATION_TTL_DAYS} días. '
                'Si no esperabas este correo, ignóralo.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
    except Exception as exc:
        # The invitation stays pending and revocable. The warning carries the
        # error class only: never the invitee address, the token or the link.
        logger.warning(
            'Invitation email not delivered: phase=invitation_email error_class=%s',
            type(exc).__name__,
            extra={'phase': 'invitation_email', 'error_class': type(exc).__name__},
        )


def invitation_public_state(token: str) -> dict:
    """What the /invite/[token] page may show BEFORE authentication."""
    invitation = Invitation.objects.filter(token=token).select_related(
        'project', 'organization', 'invited_by'
    ).first()
    if invitation is None:
        raise DomainError('Invitación no encontrada.', 404)
    expired = invitation.expires_at < timezone.now()
    return {
        'status': 'expired' if (expired and invitation.status == 'pending')
        else invitation.status,
        'email': invitation.email,
        'role': invitation.role,
        'project_name': invitation.project.name if invitation.project else None,
        'org_name': invitation.organization.name,
        'invited_by': invitation.invited_by.email,
    }


@transaction.atomic
def accept_invitation(token: str, user, request=None) -> dict:
    from projects.models import ProjectMembership

    invitation = Invitation.objects.select_for_update().filter(token=token).first()
    if invitation is None:
        raise DomainError('Invitación no encontrada.', 404)
    if invitation.status == Invitation.Status.REVOKED:
        raise DomainError('La invitación fue revocada.', 409)
    if invitation.status == Invitation.Status.ACCEPTED:
        raise DomainError('La invitación ya fue usada.', 409)
    if invitation.expires_at < timezone.now():
        raise DomainError('La invitación venció: pide una nueva.', 409)
    if user.email.lower() != invitation.email.lower():
        raise DomainError(
            f'La invitación es para {invitation.email}; inicia sesión con esa cuenta.', 403
        )

    from billing.services import check_member_limit

    if not OrganizationMembership.objects.filter(
        organization=invitation.organization, user=user
    ).exists():
        check_member_limit(invitation.organization)
    OrganizationMembership.objects.get_or_create(
        organization=invitation.organization, user=user,
        defaults={'role': OrganizationMembership.Role.MEMBER},
    )
    landing = None
    if invitation.project:
        ProjectMembership.objects.update_or_create(
            project=invitation.project, user=user,
            defaults={'role': invitation.role},
        )
        landing = f'/projects/{invitation.project.public_id}'

    invitation.status = Invitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=['status', 'accepted_at', 'accepted_by', 'updated_at'])

    audit.record(
        org=invitation.organization, project=invitation.project, actor=user,
        event_type='invitation.accepted', obj=invitation,
        payload={'role': invitation.role}, request=request,
    )
    if invitation.invited_by:
        notify(
            user=invitation.invited_by, event_key='invitation.accepted',
            org=invitation.organization, project=invitation.project,
            context={'email': user.email,
                     'project': invitation.project.name if invitation.project else
                     invitation.organization.name},
            link=landing or '/projects',
            payload={'invitation': str(invitation.public_id)},
        )
    return {'landing': landing or '/projects'}


@transaction.atomic
def revoke_invitation(invitation: Invitation, actor, request=None) -> Invitation:
    if invitation.status != Invitation.Status.PENDING:
        raise DomainError('Solo se revocan invitaciones pendientes.', 409)
    invitation.status = Invitation.Status.REVOKED
    invitation.save(update_fields=['status', 'updated_at'])
    audit.record(
        org=invitation.organization, project=invitation.project, actor=actor,
        event_type='invitation.revoked', obj=invitation,
        payload={'email': invitation.email}, request=request,
    )
    return invitation
