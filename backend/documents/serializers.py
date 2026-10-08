"""Document/version/section serializers (flows C1/C2/C3 — docs/plan/03 §3).
Thumbnails travel as short-TTL presigned URLs computed in the serializer
(kit 1 — no extra endpoint)."""

from rest_framework import serializers

from .models import Document, DocumentVersion, SectionVersion
from .services import storage_service


def _thumb_url(version):
    if version.thumb_status != DocumentVersion.ThumbStatus.READY or not version.thumb_key:
        return None
    try:
        return storage_service.presign_view(version.thumb_key, 'image/png')
    except storage_service.StorageUnavailable:
        return None


class CheckSummaryMixin:
    def get_check_summary(self, obj):
        if hasattr(obj, '_list_check_run_id'):
            if obj._list_check_run_id is None:
                return None
            return {
                outcome: getattr(obj, f'_list_check_{outcome}')
                for outcome in ('pass', 'warn', 'fail')
            }
        from checks.services import summary_for

        return summary_for(obj)


class VersionListSerializer(CheckSummaryMixin, serializers.ModelSerializer):
    author_email = serializers.EmailField(source='author.email', default=None)
    thumb_url = serializers.SerializerMethodField()
    is_draft = serializers.SerializerMethodField()
    is_trashed = serializers.BooleanField(read_only=True)
    # E3 traffic light: {pass, warn, fail} of the latest check run (or null).
    check_summary = serializers.SerializerMethodField()

    class Meta:
        model = DocumentVersion
        fields = (
            'public_id', 'number', 'message', 'sha256', 'size_bytes', 'page_count',
            'source_scenario', 'analysis_status', 'error_detail', 'is_approved',
            'is_draft', 'is_trashed', 'author_email', 'thumb_url', 'check_summary',
            'created_at',
        )

    def get_thumb_url(self, obj):
        return _thumb_url(obj)

    def get_is_draft(self, obj):
        if hasattr(obj, '_list_has_seal'):
            return not (obj.is_approved or obj._list_has_seal or obj._list_has_open_review)
        return obj.is_draft


class SectionSerializer(serializers.ModelSerializer):
    stable_key = serializers.CharField(source='section.stable_key')
    level = serializers.IntegerField(source='section.level')

    class Meta:
        model = SectionVersion
        fields = (
            'stable_key', 'heading_text', 'level', 'order_index',
            'page_start', 'page_end', 'bboxes', 'body_hash', 'char_count',
        )


class VersionDetailSerializer(VersionListSerializer):
    sections = SectionSerializer(source='section_versions', many=True, read_only=True)

    class Meta(VersionListSerializer.Meta):
        fields = VersionListSerializer.Meta.fields + ('sections',)


class DocumentListSerializer(serializers.ModelSerializer):
    latest_version = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ('public_id', 'title', 'slug', 'latest_number', 'latest_version', 'created_at', 'updated_at')

    def get_latest_version(self, obj):
        latest = (obj._list_latest_version if hasattr(obj, '_list_latest_version')
                  else obj.versions.order_by('-number').first())
        return VersionListSerializer(latest).data if latest else None


class DocumentCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)


class UploadCompleteSerializer(serializers.Serializer):
    upload_id = serializers.CharField(max_length=64)
    message = serializers.CharField(allow_blank=True, required=False, default='')


class VersionMessageSerializer(serializers.Serializer):
    message = serializers.CharField(allow_blank=True, max_length=2000)
