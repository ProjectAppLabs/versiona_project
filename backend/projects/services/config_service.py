"""B3: versioned project configuration — editing ALWAYS creates a new row
(I8 structural non-retroactivity: every DocumentVersion keeps its pinned
config; new rules only govern versions uploaded after them)."""

from django.db import transaction

from audit import services as audit
from documents.services.version_service import DomainError, ensure_writable

from ..models import ProjectConfigVersion, ProjectMembership

CHECK_TYPES = {'required_section', 'required_text', 'forbidden_text'}
SEVERITIES = {'fail', 'warn'}


def validate_checklist(items: list) -> list:
    seen = set()
    for item in items or []:
        key = (item.get('key') or '').strip()
        if not key or key in seen:
            raise DomainError('Cada check necesita una clave única.', 400)
        seen.add(key)
        if item.get('type') not in CHECK_TYPES:
            raise DomainError(
                f'Tipo de check inválido: {item.get("type")} '
                f'(usa {", ".join(sorted(CHECK_TYPES))}).', 400
            )
        if not (item.get('param') or '').strip():
            raise DomainError(f'El check "{key}" necesita un parámetro.', 400)
        if item.get('severity', 'fail') not in SEVERITIES:
            raise DomainError(f'Severidad inválida en "{key}".', 400)
        if not (item.get('label') or '').strip():
            raise DomainError(f'El check "{key}" necesita una etiqueta visible.', 400)
    return items or []


def validate_owners(project, owners: dict) -> dict:
    if not owners:
        return {}
    member_ids = set(
        ProjectMembership.objects.filter(project=project).values_list('user_id', flat=True)
    )
    for stable_key, user_ids in owners.items():
        if not isinstance(user_ids, list):
            raise DomainError('Los dueños de sección deben ser listas de usuarios.', 400)
        strangers = [uid for uid in user_ids if uid not in member_ids]
        if strangers:
            raise DomainError(
                f'Dueños de "{stable_key}" que no son miembros del proyecto: {strangers}.', 400
            )
    return owners


@transaction.atomic
def update_config(project, actor, *, checklist=None, d5_mode=None,
                  approval_policy=None, section_owners=None, request=None) -> ProjectConfigVersion:
    ensure_writable(project)
    current = ProjectConfigVersion.current_for(project)

    if d5_mode is not None and d5_mode not in ProjectConfigVersion.D5Mode.values:
        raise DomainError(f'd5_mode inválido: {d5_mode}.', 400)

    new_config = ProjectConfigVersion.objects.create(
        project=project,
        number=current.number + 1,
        approval_policy=approval_policy if approval_policy is not None
        else current.approval_policy,
        d5_mode=d5_mode if d5_mode is not None else current.d5_mode,
        coordinators=current.coordinators,
        checklist=validate_checklist(checklist) if checklist is not None
        else current.checklist,
        section_owners=validate_owners(project, section_owners)
        if section_owners is not None else current.section_owners,
        created_by=actor,
    )
    audit.record(
        org=project.organization, project=project, actor=actor,
        event_type='project.config_updated', obj=project,
        payload={'config_version': new_config.number,
                 'changed': [k for k, v in {
                     'checklist': checklist, 'd5_mode': d5_mode,
                     'approval_policy': approval_policy,
                     'section_owners': section_owners}.items() if v is not None]},
        request=request,
    )
    return new_config


@transaction.atomic
def apply_template(project, actor, template, request=None) -> ProjectConfigVersion:
    """Kit 2 copy-on-apply: the template's items are COPIED into a new config
    version; later template edits never touch this project (I8)."""
    if template.organization_id != project.organization_id:
        raise DomainError('La plantilla pertenece a otra organización.', 400)
    new_config = update_config(project, actor, checklist=list(template.items), request=request)
    audit.record(
        org=project.organization, project=project, actor=actor,
        event_type='project.template_applied', obj=project,
        payload={'template': template.name, 'config_version': new_config.number},
        request=request,
    )
    return new_config
