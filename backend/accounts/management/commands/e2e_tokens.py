"""
Print JWT pairs for the deterministic E2E actors (docs/plan/06 §5.1).

Playwright's globalSetup runs BEFORE the webServer starts, so it cannot log
in over HTTP; this command mints the tokens directly (simplejwt) and the
setup writes them as storageState cookies. Only meant for dev/CI seeds.
"""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from accounts.services.token_service import mint_token_pair

ALIASES = ('owner', 'admin', 'editor', 'reviewer', 'viewer')


class Command(BaseCommand):
    help = 'Print JWT tokens for the seeded E2E users as JSON'

    def handle(self, *args, **options):
        User = get_user_model()
        tokens = {}
        for alias in ALIASES:
            user = User.objects.filter(email=f'{alias}@versiona.test').first()
            if user is None:
                raise CommandError(
                    f'Usuario e2e "{alias}" no existe: corre create_fake_data --scenario=e2e'
                )
            tokens[alias] = mint_token_pair(user)
        self.stdout.write(json.dumps(tokens))
