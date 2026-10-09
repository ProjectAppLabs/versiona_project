import secrets

from django.db import models, transaction
from .user import User

class PasswordCode(models.Model):
    """
    Password reset code model.
    
    Stores 6-digit codes for password reset functionality.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_codes')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Code for {self.user.email} - {self.code}"
    
    @classmethod
    def generate_code(cls, user):
        """
        Issue a new 6-digit code for the user, drawn from the CSPRNG.

        Codes still pending are superseded first: an account holds at most one
        live code, so requesting more codes never multiplies the odds of a guess.
        Issuing takes the same user-row lock as the reset verification, so
        concurrent issuances and verifications run one after another.
        """
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            cls.objects.filter(user=user, used=False).update(used=True)
            code = f'{secrets.randbelow(1_000_000):06d}'
            return cls.objects.create(user=user, code=code)
    
    def is_valid(self):
        """
        Check if code is still valid (not used and less than 15 minutes old).
        """
        if self.used:
            return False
        
        from django.utils import timezone
        from datetime import timedelta
        age = timezone.now() - self.created_at
        return age < timedelta(minutes=15)
