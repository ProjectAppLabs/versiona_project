from __future__ import annotations

import ast
import copy
import json
import os
import tempfile
from pathlib import Path

# ── ANSI colours ────────────────────────────────────────────────────────────
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_EXCLUDE_PARTS = frozenset(
    {"tests", "migrations", "venv", "__pycache__", "conftest.py", ".git"}
)


def _colour(pct: float) -> str:
    if pct >= 90:
        return _GREEN
    if pct >= 70:
        return _YELLOW
    return _RED


def _bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _is_production(path: str) -> bool:
    """Return True if the path does not belong to tests/migrations/venv/etc."""
    parts = Path(path).parts
    return not any(part in _EXCLUDE_PARTS for part in parts)


def _combined_totals(
    totals: dict | None,
    functions_total: int | None,
    functions_covered: int | None,
) -> tuple[int, int] | None:
    combined_total = 0
    combined_covered = 0
    if isinstance(totals, dict):
        total_statements = totals.get("num_statements")
        missing_lines = totals.get("missing_lines")
        covered_lines = totals.get("covered_lines")
        if covered_lines is None and isinstance(total_statements, int) and isinstance(missing_lines, int):
            covered_lines = total_statements - missing_lines

        total_branches = totals.get("num_branches")
        missing_branches = totals.get("missing_branches")
        covered_branches = totals.get("covered_branches")
        if covered_branches is None and isinstance(total_branches, int) and isinstance(missing_branches, int):
            covered_branches = total_branches - missing_branches

        total_lines = totals.get("num_lines")
        line_total = total_lines if isinstance(total_lines, int) else total_statements

        if isinstance(total_statements, int) and isinstance(covered_lines, int):
            combined_total += total_statements
            combined_covered += covered_lines
        if isinstance(total_branches, int) and isinstance(covered_branches, int):
            combined_total += total_branches
            combined_covered += covered_branches
        if isinstance(line_total, int) and isinstance(covered_lines, int):
            combined_total += line_total
            combined_covered += covered_lines

    if isinstance(functions_total, int) and isinstance(functions_covered, int):
        combined_total += functions_total
        combined_covered += functions_covered

    if combined_total == 0:
        return None
    return combined_covered, combined_total


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ARG001
    try:
        import coverage as coverage_module
    except ImportError:
        return

    rootdir = Path(str(config.rootdir))
    data_file = rootdir / ".coverage"
    if not data_file.exists():
        return

    try:
        cov = coverage_module.Coverage(data_file=str(data_file))
        cov.load()

        # ── Dump to JSON for a stable public API ────────────────────────────
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(tmp_fd)
        try:
            cov.json_report(
                outfile=tmp_path,
                omit=[
                    "*/venv/*",
                    "*/migrations/*",
                    "*/tests/*",
                    "*/conftest*",
                    "*/__pycache__/*",
                ],
                ignore_errors=True,
            )
            with open(tmp_path, encoding="utf-8") as fh:
                report = json.load(fh)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        files_data = report.get("files", {})
        if not files_data:
            return

        totals = report.get("totals")

        def count_function_coverage(files: dict, coverage_data) -> tuple[int, int] | None:
            if not files or coverage_data is None:
                return None
            total_functions = 0
            covered_functions = 0
            for raw_path in files:
                if not isinstance(raw_path, str) or not _is_production(raw_path):
                    continue
                file_path = Path(raw_path)
                if not file_path.is_absolute():
                    file_path = rootdir / file_path
                if file_path.suffix != ".py":
                    continue
                try:
                    source = file_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    continue
                executed_lines = coverage_data.lines(raw_path)
                if executed_lines is None:
                    executed_lines = coverage_data.lines(str(file_path))
                executed_set = set(executed_lines or [])
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        lineno = getattr(node, "lineno", None)
                        end_lineno = getattr(node, "end_lineno", None)
                        if not isinstance(lineno, int):
                            continue
                        if not isinstance(end_lineno, int):
                            end_lineno = lineno
                        total_functions += 1
                        if end_lineno > lineno:
                            lines_range = range(lineno + 1, end_lineno + 1)
                        else:
                            lines_range = range(lineno, end_lineno + 1)
                        if any(line in executed_set for line in lines_range):
                            covered_functions += 1
            if total_functions == 0:
                return None
            return covered_functions, total_functions

        try:
            coverage_data = cov.get_data()
        except Exception:
            coverage_data = None
        function_metrics = count_function_coverage(files_data, coverage_data)
        functions_covered = None
        functions_total = None
        if function_metrics:
            functions_covered, functions_total = function_metrics

        rows: list[tuple[str, int, int, float]] = []
        for raw_path, info in files_data.items():
            if not _is_production(raw_path):
                continue
            summary = info.get("summary", {})
            stmts: int = summary.get("num_statements", 0)
            missing: int = summary.get("missing_lines", 0)
            pct: float = summary.get("percent_covered", 0.0)
            # Normalise to a relative display path regardless of abs/rel input
            p = Path(raw_path)
            if p.is_absolute():
                try:
                    display = str(p.relative_to(rootdir))
                except ValueError:
                    display = raw_path
            else:
                display = raw_path
            rows.append((display, stmts, missing, pct))

        if not rows:
            return

        rows.sort(key=lambda r: r[0])

        total_stmts = sum(r[1] for r in rows)
        total_missing = sum(r[2] for r in rows)
        total_pct = (
            ((total_stmts - total_missing) / total_stmts * 100)
            if total_stmts
            else 100.0
        )

        combined_result = _combined_totals(totals, functions_total, functions_covered)

        tw = terminalreporter

        # ── Header ───────────────────────────────────────────────────────────
        tw.write_sep("=", "Coverage Report  (production files)", bold=True)

        col_file = 60
        header = (
            f"{'File':<{col_file}}  {'Stmts':>6}  {'Miss':>6}  {'Cover':>6}  Bar"
        )
        tw.write_line(f"{_BOLD}{header}{_RESET}")
        tw.write_line(_DIM + "─" * (col_file + 42) + _RESET)

        for display, stmts, missing, pct in rows:
            c = _colour(pct)
            name = (display[:57] + "...") if len(display) > col_file else display
            bar = _bar(pct)
            line = f"{name:<{col_file}}  {stmts:>6}  {missing:>6}  {c}{pct:>5.1f}%{_RESET}  {c}{bar}{_RESET}"
            tw.write_line(line)

        # ── Total summary ────────────────────────────────────────────────────
        tc = _colour(total_pct)
        tw.write_line(_DIM + "─" * (col_file + 42) + _RESET)
        total_bar = _bar(total_pct)
        total_line = (
            f"{'TOTAL':<{col_file}}  {total_stmts:>6}  {total_missing:>6}  "
            f"{tc}{total_pct:>5.1f}%{_RESET}  {tc}{total_bar}{_RESET}"
        )
        tw.write_line(f"{_BOLD}{total_line}{_RESET}")
        if combined_result:
            combined_covered, combined_total = combined_result
            combined_pct = (combined_covered / combined_total) * 100
            combined_missing = combined_total - combined_covered
            combined_color = _colour(combined_pct)
            combined_bar = _bar(combined_pct)
            combined_line = (
                f"{'TOTAL (combined)':<{col_file}}  {combined_total:>6}  {combined_missing:>6}  "
                f"{combined_color}{combined_pct:>5.1f}%{_RESET}  {combined_color}{combined_bar}{_RESET}"
            )
            tw.write_line(f"{_BOLD}{combined_line}{_RESET}")

        # ── Top-10 focus list ────────────────────────────────────────────────
        focus = sorted(
            [r for r in rows if r[3] < 100.0],
            key=lambda r: r[3],
        )[:10]

        if focus:
            tw.write_sep(
                "-",
                f"Top-{len(focus)} files to focus on  "
                f"(lowest coverage — total project: {tc}{total_pct:.1f}%{_RESET})",
            )
            for rank, (display, stmts, missing, pct) in enumerate(focus, 1):
                c = _colour(pct)
                bar = _bar(pct, width=15)
                tw.write_line(
                    f"  {_BOLD}{rank:>2}.{_RESET} {c}{pct:>5.1f}%  {bar}{_RESET}"
                    f"  {display}"
                    f"  {_DIM}({missing} line{'s' if missing != 1 else ''} uncovered){_RESET}"
                )

    except Exception:
        pass


def pytest_sessionstart(session) -> None:
    cov_plugin = session.config.pluginmanager.get_plugin("_cov")
    if cov_plugin is None:
        return
    hook = session.config.pluginmanager.hook.pytest_terminal_summary
    for impl in hook.get_hookimpls():
        if impl.plugin is cov_plugin:
            impl.function = lambda *args, **kw: None
            break


# ---------------------------------------------------------------------------
# Shared API fixtures (available to every app's test suite)
# ---------------------------------------------------------------------------
import pytest
from django.core.cache import cache
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _isolate_auth_throttle(settings):
    """Keep non-quota tests independent from the shared authentication bucket."""
    original_framework = copy.deepcopy(settings.REST_FRAMEWORK)
    framework = copy.deepcopy(settings.REST_FRAMEWORK)
    rates = dict(framework.get('DEFAULT_THROTTLE_RATES', {}))
    rates['auth'] = '1000/min'
    framework['DEFAULT_THROTTLE_RATES'] = rates
    settings.REST_FRAMEWORK = framework
    cache.clear()

    yield

    cache.clear()
    settings.REST_FRAMEWORK = original_framework


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def existing_user(db):
    """Regular authenticated user for use in tests requiring a logged-in customer."""
    User = get_user_model()
    return User.objects.create_user(
        email='user@example.com',
        password='existingpassword',
        first_name='Test',
        last_name='User',
    )


@pytest.fixture
def admin_user(db):
    """Staff/admin user for use in tests requiring elevated permissions."""
    User = get_user_model()
    user = User.objects.create_user(
        email='admin@example.com',
        password='adminpassword',
        first_name='Admin',
        last_name='User',
    )
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=['is_staff', 'is_superuser'])
    return user


@pytest.fixture
def authenticated_client(api_client, existing_user):
    """APIClient pre-authenticated as a regular user."""
    api_client.force_authenticate(user=existing_user)
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user):
    """APIClient pre-authenticated as a staff/admin user."""
    api_client.force_authenticate(user=admin_user)
    return api_client


# ---------------------------------------------------------------------------
# Versiona domain fixtures — one org/project with the 7 audit actors
# (docs/audit/03 §0.2: owner, admin, editor, reviewer, viewer, non_member,
# anonymous). Used by the P01–P04 integration matrices.
# ---------------------------------------------------------------------------
from types import SimpleNamespace


@pytest.fixture
def versiona_context(db, django_user_model):
    from orgs.models import Organization, OrganizationMembership
    from projects.models import Project, ProjectConfigVersion, ProjectMembership

    def make_user(alias):
        return django_user_model.objects.create_user(
            email=f'{alias}@versiona.test', password='secreta123', first_name=alias.title()
        )

    users = {alias: make_user(alias) for alias in
             ('owner', 'admin', 'editor', 'reviewer', 'viewer', 'non_member')}

    # The context org exercises EVERY flow: free limits have their own tests
    # that flip the plan explicitly (F1).
    org = Organization.objects.create(name='Acme', slug='acme-test', plan='enterprise')
    OrganizationMembership.objects.create(
        organization=org, user=users['owner'], role=OrganizationMembership.Role.OWNER
    )
    for alias in ('admin', 'editor', 'reviewer', 'viewer'):
        OrganizationMembership.objects.create(
            organization=org, user=users[alias], role=OrganizationMembership.Role.MEMBER
        )

    other_org = Organization.objects.create(name='Ajena', slug='ajena-test')
    OrganizationMembership.objects.create(
        organization=other_org, user=users['non_member'],
        role=OrganizationMembership.Role.OWNER,
    )

    project = Project.objects.create(organization=org, name='Torre Central', slug='torre-central')
    for alias, role in (
        ('admin', ProjectMembership.Role.ADMIN),
        ('editor', ProjectMembership.Role.EDITOR),
        ('reviewer', ProjectMembership.Role.REVIEWER),
        ('viewer', ProjectMembership.Role.VIEWER),
    ):
        ProjectMembership.objects.create(project=project, user=users[alias], role=role)

    config = ProjectConfigVersion.current_for(project)

    return SimpleNamespace(
        org=org, other_org=other_org, project=project, config=config, users=users
    )


@pytest.fixture
def client_as(versiona_context):
    """client_as('editor') -> APIClient authenticated as that audit actor.

    'anonymous' returns a bare client. Foreign-org actor: 'non_member'.
    """
    from rest_framework.test import APIClient

    def _make(alias):
        client = APIClient()
        if alias != 'anonymous':
            client.force_authenticate(user=versiona_context.users[alias])
        return client

    return _make


@pytest.fixture
def document_with_versions(versiona_context):
    """Document + N analyzed versions with deterministic fake storage keys.

    Engine-independent (view/permission tests); engine tests use testdata/.
    """
    from documents.models import Document, DocumentVersion

    def _make(n_versions=1, document_slug='contrato', **version_overrides):
        document = Document.objects.create(
            project=versiona_context.project, title=document_slug.title(), slug=document_slug
        )
        versions = []
        for number in range(1, n_versions + 1):
            versions.append(DocumentVersion.objects.create(
                document=document,
                number=number,
                message=f'versión {number}',
                sha256=f'{number:064d}',
                file_key=f'test/docs/{document.public_id}/v{number}/original.pdf',
                analysis_status=DocumentVersion.AnalysisStatus.READY,
                config_version=versiona_context.config,
                author=versiona_context.users['editor'],
                **version_overrides,
            ))
        document.latest_number = n_versions
        document.save(update_fields=['latest_number'])
        return document, versions

    return _make


# ── Object storage ──────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _object_storage_root(settings, tmp_path_factory):
    """Give every test a private, throwaway object root.

    Before this existed the suite wrote to a real MinIO on 127.0.0.1:9000 (it
    had accumulated 124 MB under the `test/` prefix). Forcing the filesystem
    backend made the suite hermetic and removed the external dependency; the
    per-module `_test_storage_prefix` fixtures still namespace keys inside the
    already-isolated root, so they stay harmless.

    The bucket override is gone with the S3 backend itself (2026-08-02) — the
    filesystem backend is now the only one, so there is nothing left to force.
    The throwaway root still matters: it keeps tests from writing into the
    developer's real OBJECT_STORAGE_ROOT.
    """
    settings.OBJECT_STORAGE_ROOT = str(tmp_path_factory.mktemp('objects'))
    settings.OBJECT_STORAGE_SENDFILE_ROOT = ''


@pytest.fixture(autouse=True)
def _not_production(settings):
    """Never run the suite as production, whatever backend/.env says.

    IS_PRODUCTION is computed at import time from DJANGO_ENV, so the per-module
    `settings.DJANGO_ENV = 'test'` fixtures do not move it. Once the box carried
    a production .env it flipped to True and the seal signer began demanding a
    real SEAL_SIGNING_KEY_PATH instead of generating an ephemeral one.
    """
    settings.DJANGO_ENV = 'test'
    settings.IS_PRODUCTION = False
    # Fleet-contract switches: staging turns these off in its .env, which would
    # make every task-body test assert against an early return. Pin them ON so
    # the suite exercises the real work; the guards themselves are covered by
    # dedicated tests in accounts/tests/commands/test_tasks.py.
    settings.BACKUPS_ENABLED = True
    settings.ENABLE_SLOW_QUERIES_REPORT = True


@pytest.fixture(autouse=True)
def _trash_versions_before_flush(request):
    """Transactional tests only: send every DocumentVersion to the trash before
    the harness wipes the tables.

    Django's TransactionTestCase teardown always flushes with
    `DELETE FROM ...` (reset_sequences is hardcoded False there), and the I2
    trigger rejects a physical delete of a version that never went through the
    trash — correctly. PostgreSQL never surfaced this because its flush uses
    TRUNCATE CASCADE, which does not fire row triggers; MySQL's DELETE does.

    So the fixture satisfies the invariant instead of bypassing it. It runs
    before the flush because the `db` fixture is set up first and therefore
    torn down last.
    """
    yield
    marker = request.node.get_closest_marker('django_db')
    if not (marker and marker.kwargs.get('transaction')):
        return
    from django.utils import timezone

    from documents.models import DocumentVersion

    DocumentVersion.all_objects.filter(deleted_at__isnull=True).update(
        deleted_at=timezone.now()
    )


@pytest.fixture(autouse=True)
def _eager_celery(settings):
    """Run tasks inline, regardless of what backend/.env says.

    The suite is written around eager Celery ("real MinIO + eager Celery" in the
    older docstrings): fixtures like `approved_version` expect the analysis to
    have completed by the time complete_upload returns. That used to work only
    because the developer's .env happened to set CELERY_TASK_ALWAYS_EAGER=true —
    so the moment the box carried a production .env (eager off), 13 tests failed
    at fixture setup. Pin it here instead of depending on the machine.

    app.conf is set as well as settings: Celery resolves its config from
    django.conf at app configuration time and caches it, so flipping the Django
    setting alone does not reach an already-built app.
    """
    from versiona_project.celery import app

    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
