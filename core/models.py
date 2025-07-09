from django.db import models
from django.contrib.auth.models import User
# details of the facebook page
class FacebookPage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    page_id = models.CharField(max_length=255, unique=True)
    page_name = models.CharField(max_length=255)
    user_access_token = models.TextField()
    page_access_token = models.TextField()
    instagram_business_account_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.page_name


# details of people who message our instagram business account
class InstagramSenderDetails(models.Model):
    ig_user_id = models.CharField(max_length=255, unique=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    conversation_id = models.CharField(max_length=255)
    page = models.ForeignKey(FacebookPage, on_delete=models.CASCADE)
    last_message_text = models.TextField(null=True, blank=True)
    last_message_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.username or self.ig_user_id
    



# sender's messages

class InstagramMessage(models.Model):
    message_id = models.CharField(max_length=255, unique=True)
    conversation_id = models.CharField(max_length=255)
    sender_id = models.CharField(max_length=255)
    sender_username = models.CharField(max_length=255, blank=True, null=True)
    message_text = models.TextField(blank=True, null=True)
    created_time = models.DateTimeField()
    direction = models.CharField(max_length=10, choices=[('inbound', 'Inbound'), ('outbound', 'Outbound')])
    page = models.ForeignKey(FacebookPage, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.direction.upper()} - {self.sender_username or self.sender_id}: {self.message_text[:30]}"

