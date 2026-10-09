"""
Seal — the approval act (docs/plan/02 §3.4 — flow D4, invariants I4/I6).

Append-only: a Seal row is NEVER updated or deleted. Withdrawing a seal
pre-approval (DP-08) is an append event (`revoked_at`, an explicit column the
signature does not cover, plus an AuditEvent), never a delete.

The signature binds the act to the exact binary: the canonical payload carries
the version sha256 + the covered sections with their body hashes, so a third
party can verify it offline with the public key (E4 groundwork).
"""

from django.conf import settings
from django.db import models

from core.models import PublicIdModel, TimestampedModel
from documents.models import DocumentVersion, Section


class Seal(PublicIdModel, TimestampedModel):
    document_version = models.ForeignKey(
        DocumentVersion, on_delete=models.CASCADE, related_name='seals'
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='seals'
    )
    covers_all = models.BooleanField(default=False)
    signed_payload = models.JSONField()
    # Base64 and a key fingerprint: case IS meaningful, so they opt out of the
    # accent/case-insensitive table default.
    signature = models.TextField(db_collation='utf8mb4_bin')
    key_id = models.CharField(max_length=40, db_collation='utf8mb4_bin')
    revoked_at = models.DateTimeField(null=True, blank=True)

    # I4 at the database layer. `revoked_at` is the only mutable column on this
    # append-only table (seal_service.revoke_seal); setting it drops the row out
    # of the unique index, which is precisely what
    # condition=Q(revoked_at__isnull=True) did on PostgreSQL. MySQL cannot
    # express that condition and Django would SKIP the constraint silently, so
    # it moves into the column.
    document_version_active = models.GeneratedField(
        expression=models.Case(
            models.When(revoked_at__isnull=True, then=models.F('document_version')),
            default=models.Value(None),
            output_field=models.BigIntegerField(),
        ),
        output_field=models.BigIntegerField(),
        db_persist=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['document_version_active', 'reviewer'],
                name='uniq_active_seal_per_reviewer',
            ),
        ]
        ordering = ['created_at']

    def __str__(self):
        return f'seal {self.reviewer} @ v{self.document_version.number}'

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    @property
    def covered_keys(self) -> list[str]:
        if self.covers_all:
            return ['*']
        # values_list() always queries, ignoring a prefetch: list readers that
        # prefetch `covered_sections__section` get their keys in memory instead.
        # SealSection rows are append-only, so the prefetched set cannot drift.
        prefetched = getattr(self, '_prefetched_objects_cache', {}).get('covered_sections')
        if prefetched is not None:
            return sorted(cover.section.stable_key for cover in prefetched)
        return sorted(
            self.covered_sections.values_list('section__stable_key', flat=True)
        )


class SealSection(TimestampedModel):
    """Explicit M2M: which sections the seal covers (docs/plan/02 §3.4)."""

    seal = models.ForeignKey(Seal, on_delete=models.CASCADE, related_name='covered_sections')
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='+')
    # The hash inside the signed payload: must compare byte-exact against
    # SectionVersion.body_hash, so it carries the same binary collation.
    body_hash = models.CharField(max_length=64, db_collation='utf8mb4_bin')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['seal', 'section'], name='uniq_seal_section'),
        ]

    def __str__(self):
        return f'{self.seal_id}:{self.section.stable_key}'
