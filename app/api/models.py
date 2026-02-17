from django.db import models


class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=64, blank=True, null=True)
    first_name = models.CharField(max_length=128, blank=True, null=True)
    last_name = models.CharField(max_length=128, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"tg:{self.telegram_id} ({self.username or ''})"


class FPLUpload(models.Model):
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    flight_number = models.CharField(max_length=64, blank=True, null=True)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"FPLUpload {self.flight_number or '<unknown>'} by {self.user} @ {self.created_at.isoformat()}"
