from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', User.Role.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        ADMIN = 'admin', 'Admin'

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=50, blank=True)

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # User preferences (kit 7 — docs/audit/02 G28). `language` drives the UI
    # dictionaries and email templates (es/en, operator decision 2026-07-12);
    # `timezone` (IANA) formats every date shown to this user. Declared after
    # date_joined: the field name shadows django.utils.timezone inside the
    # class body.
    class Language(models.TextChoices):
        SPANISH = 'es', 'Español'
        ENGLISH = 'en', 'English'

    language = models.CharField(max_length=5, choices=Language.choices, default=Language.SPANISH)
    timezone = models.CharField(max_length=64, default='America/Bogota')

    # A3 — TOTP 2FA: secret set at setup, enabled_at marks activation, backup
    # codes stored as sha256 (plaintext shown exactly once).
    totp_secret = models.CharField(max_length=64, blank=True, default='')
    totp_enabled_at = models.DateTimeField(null=True, blank=True)
    totp_backup_codes = models.JSONField(default=list, blank=True)

    # Provider identity is opaque: MySQL must compare subjects exactly.
    google_subject = models.CharField(
        max_length=255, null=True, blank=True, unique=True, db_collation='utf8mb4_bin'
    )
    auth_version = models.PositiveIntegerField(default=0)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email
