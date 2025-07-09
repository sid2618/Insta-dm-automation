from django.shortcuts import render,redirect
from django.contrib.auth.decorators import login_required
import requests
import json
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest,HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from urllib.parse import urlencode
import httpx
from .global_store import ig_page_tokens  # Import the global dict
from django.shortcuts import redirect
from django.contrib import messages
from .models import *
from django.views.decorators.http import require_POST
from django.http import HttpResponseRedirect
from django.utils.dateparse import parse_datetime
from django.utils.dateparse import parse_datetime
from django.utils.timezone import make_aware
import pytz
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login, logout, authenticate
from django.db.models import Q
from django.utils import timezone
import time

from django.core.paginator import Paginator

from .ai_utils import gemini_ai_reply
import google.generativeai as genai


# Create your views here.

graph_api_version = 'v23.0'  # or the latest version of the Graph API


def home(request):
    return render(request, "core/home.html")


def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # ✅ Check if this user has any Facebook pages
            if FacebookPage.objects.filter(user=user).exists():
                return redirect("dashboard")
            else:
                return redirect("connect_facebook")
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # ✅ Check for Facebook page ownership
            if FacebookPage.objects.filter(user=user).exists():
                return redirect("dashboard")
            else:
                return redirect("connect_facebook")
    else:
        form = AuthenticationForm()
    return render(request, "registration/login.html", {"form": form})

def logout_view(request):
    logout(request)
    return redirect("home")

def post_login_redirect(request):
    if not request.user.is_authenticated:
        return redirect("login")

    if FacebookPage.objects.filter(user=request.user).exists():
        return redirect("dashboard")
    return redirect("connect_facebook")




def connect_facebook_view(request):
    return render(request, "core/connect_facebook.html")



@login_required
def dashboard_view(request):
    pages = FacebookPage.objects.filter(user=request.user)
    return render(request, "core/dashboard.html", {
        "pages": pages
    })






@csrf_exempt
def webhook_view(request):
    if request.method == 'GET':
        verify_token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        mode = request.GET.get("hub.mode")

        if verify_token == "1234" and mode == "subscribe":
            return HttpResponse(challenge, status=200)
        else:
            return HttpResponse("Invalid verification", status=403)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)

            for entry in data.get('entry', []):
                ig_account_id = entry.get("id")

                for messaging_event in entry.get('messaging', []):
                    message = messaging_event.get("message")
                    if not message or message.get("is_echo") or "text" not in message:
                        continue
                    
                    ig_user_id = messaging_event["sender"]["id"]
                    message_text = message["text"]
                    print(f"✅ Incoming message from {ig_user_id}: {message_text}") 
                    message_id = message["mid"]
                    created_time_raw = message.get("timestamp")
                    if created_time_raw:
                        created_time = timezone.datetime.fromtimestamp(created_time_raw / 1000, tz=timezone.utc)
                    else:
                        created_time = timezone.now()  # fallback if timestamp is missing
                    # created_time = timezone.datetime.fromtimestamp(created_time_raw / 1000, tz=timezone.utc)

                    # 🔁 Get page
                    try:
                        page = FacebookPage.objects.get(instagram_business_account_id=ig_account_id)
                    except FacebookPage.DoesNotExist:
                        continue

                    # ✅ Get or fetch conversation_id
                    try:
                        sender = InstagramSenderDetails.objects.get(ig_user_id=ig_user_id, page=page)
                        conversation_id = sender.conversation_id
                        username = sender.username
                    except InstagramSenderDetails.DoesNotExist:
                        # 📡 Fetch conversation_id from API
                        convo_url = f"https://graph.facebook.com/v23.0/{page.page_id}/conversations"
                        convo_params = {
                            "platform": "instagram",
                            "user_id": ig_user_id,
                            "access_token": page.page_access_token
                        }
                        convo_res = requests.get(convo_url, params=convo_params).json()
                        conversation_id = convo_res.get("data", [{}])[0].get("id")

                        # 🧠 Fetch full message for username
                        msg_url = f"https://graph.facebook.com/v23.0/{message_id}"
                        msg_params = {
                            "fields": "from,to,message",
                            "access_token": page.page_access_token
                        }
                        msg_data = requests.get(msg_url, params=msg_params).json()
                        username = msg_data.get("from", {}).get("username", "Unknown")

                        # 💾 Save sender info
                        InstagramSenderDetails.objects.update_or_create(
                            ig_user_id=ig_user_id,
                            page=page,
                            defaults={
                                "username": username,
                                "conversation_id": conversation_id,
                                "last_message_text": message_text,
                                "last_message_time": created_time
                            }
                        )

                    # 💾 Save inbound message
                    InstagramMessage.objects.update_or_create(
                        message_id=message_id,
                        defaults={
                            "conversation_id": conversation_id,
                            "sender_id": ig_user_id,
                            "sender_username": username,
                            "message_text": message_text,
                            "created_time": created_time,
                            "direction": "inbound",
                            "page": page
                        }
                    )
                    # 🔁 Update sender record with last message
                    InstagramSenderDetails.objects.filter(
                        ig_user_id=ig_user_id, page=page
                    ).update(
                        last_message_text=message_text,
                        last_message_time=timezone.now()
                    )

                    # 🤖 AI Reply
                    try:
                        ai_reply = gemini_ai_reply(message_text)
                    except Exception as e:
                        print("❌ AI failed, using fallback message:", e)
                        ai_reply = "Thanks for your message! We'll get back to you shortly."

                    # ✅ Send reply
                    reply_message(ig_user_id, ai_reply, ig_account_id)
                    business_sender = InstagramSenderDetails.objects.filter(
                        ig_user_id=page.instagram_business_account_id,
                        page=page
                    ).first()

                    business_username = business_sender.username

                    # 💾 Save outbound reply
                    reply_id = f"{message_id}_reply"  # Custom ID to prevent duplication
                    InstagramMessage.objects.update_or_create(
                        message_id=reply_id,
                        defaults={
                            "conversation_id": conversation_id,
                            "sender_id": page.instagram_business_account_id,
                            "sender_username": business_username,
                            "message_text": ai_reply,
                            "created_time": timezone.now(),
                            "direction": "outbound",
                            "page": page
                        }
                    )

                    # 🔁 Update sender record with last message
                    InstagramSenderDetails.objects.filter(
                        ig_user_id=page.instagram_business_account_id, page=page
                    ).update(
                        last_message_text=ai_reply,
                        last_message_time=timezone.now()
                    )

            return JsonResponse({"status": "ok"})

        except Exception as e:
            print("Webhook error:", e)
            return JsonResponse({"error": str(e)}, status=500)

    return HttpResponse(status=400)







def reply_message(recipient_id, text, ig_account_id):
    try:
        page = FacebookPage.objects.get(instagram_business_account_id=ig_account_id)
    except FacebookPage.DoesNotExist:
        print(f"❌ No page found for IG account ID: {ig_account_id}")
        return

    token = page.page_access_token
    page_id = page.page_id

    url = f"https://graph.facebook.com/v23.0/{page_id}/messages?access_token={token}"
    payload = {
        "messaging_type": "RESPONSE",
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print("❌ Failed to send reply:", response.status_code, response.json())
    else:
        print("✅ Reply sent:", response.json())






@require_POST
@csrf_exempt  # You can remove this if CSRF token is correctly used
def send_dm_view(request, ig_user_id, page_id):
    message = request.POST.get("message")
    if not message:
        return JsonResponse({"error": "Message content is required"}, status=400)

    try:
        page = FacebookPage.objects.get(page_id=page_id)
    except FacebookPage.DoesNotExist:
        return JsonResponse({"error": "Page not found"}, status=404)

    token = page.page_access_token
    url = f"https://graph.facebook.com/v23.0/{page_id}/messages?access_token={token}"

    payload = {
        "messaging_type": "RESPONSE",
        "recipient": {"id": ig_user_id},
        "message": {"text": message}
    }

    res = requests.post(url, json=payload)
    if res.status_code != 200:
        print("❌ Error sending message:", res.text)
        return JsonResponse({"error": res.json()}, status=500)

    # ✅ After successful send, save to DB
    try:
        # Fetch or create conversation_id
        sender = InstagramSenderDetails.objects.filter(ig_user_id=ig_user_id, page=page).first()

        if sender:
            conversation_id = sender.conversation_id
        else:
            # Fetch via API
            convo_url = f"https://graph.facebook.com/v23.0/{page.page_id}/conversations"
            convo_params = {
                "platform": "instagram",
                "user_id": ig_user_id,
                "access_token": page.page_access_token
            }
            convo_res = requests.get(convo_url, params=convo_params).json()
            conversation_id = convo_res.get("data", [{}])[0].get("id")

        # Get sender username of the business
        business_sender = InstagramSenderDetails.objects.filter(
            ig_user_id=page.instagram_business_account_id,
            page=page
        ).first()
        sender_username = business_sender.username if business_sender else page.page_name

        # 💾 Save message
        InstagramMessage.objects.create(
            message_id=f"manual_{int(time.time())}",  # Prevent collision
            conversation_id=conversation_id,
            sender_id=page.instagram_business_account_id,
            sender_username=sender_username,
            message_text=message,
            created_time=timezone.now(),
            direction="outbound",
            page=page
        )

        # 🔁 Optionally update sender's last message info
        InstagramSenderDetails.objects.update_or_create(
            ig_user_id=page.instagram_business_account_id,
            page=page,
            defaults={
                "username": sender_username,
                "conversation_id": conversation_id,
                "last_message_text": message,
                "last_message_time": timezone.now(),
            }
        )

    except Exception as e:
        print("⚠️ Error while saving sent message:", str(e))

    return redirect("conversation_view", ig_user_id=ig_user_id, page_id=page_id)





@login_required
def list_conversations_view(request, page_id):
    try:
        page = FacebookPage.objects.get(page_id=page_id)
        page_name = page.page_name
    except FacebookPage.DoesNotExist:
        return JsonResponse({"error": "Page not found"}, status=404)

    # ⛔️ Filter out messages from the business account itself
    senders = InstagramSenderDetails.objects.filter(
        page=page
    ).exclude(
        ig_user_id=page.instagram_business_account_id
    ).order_by('-last_message_time')

    return render(request, "core/conversation_list.html", {
        "senders": senders,
        "page_id": page_id,
        "page_name": page_name
    })








@login_required
def conversation_view(request, ig_user_id, page_id):
    try:
        page = FacebookPage.objects.get(page_id=page_id)
    except FacebookPage.DoesNotExist:
        return JsonResponse({"error": "Page not found"}, status=404)

    # 🔍 Get sender info
    sender = InstagramSenderDetails.objects.filter(
        ig_user_id=ig_user_id, page=page
    ).first()

    if not sender or not sender.conversation_id:
        return JsonResponse({"error": "Conversation not found in database."}, status=404)

    # 📥 Fetch messages from DB
    messages = InstagramMessage.objects.filter(
        conversation_id=sender.conversation_id,
        page=page
    ).order_by("-created_time")  # newest to oldest

    return render(request, "core/conversations.html", {
        "messages": messages,
        "ig_user_id": ig_user_id,
        "page_id": page_id,
        "sender": sender
    })


# below function can be used if pagination needs to be applied

# @login_required
# def conversation_view(request, ig_user_id, page_id):
#     page_obj = FacebookPage.objects.get(page_id=page_id)
#     sender = InstagramSenderDetails.objects.filter(ig_user_id=ig_user_id, page=page_obj).first()

#     all_messages = InstagramMessage.objects.filter(
#         conversation_id=sender.conversation_id,
#         page=page_obj
#     ).order_by("-created_time")

#     paginator = Paginator(all_messages, 20)  # 20 messages per page
#     page_number = request.GET.get("page") or 1
#     messages = paginator.get_page(page_number)

#     return render(request, "core/conversations.html", {
#         "messages": messages,
#         "ig_user_id": ig_user_id,
#         "page_id": page_id,
#         "sender": sender
#     })











def get_conversation_messages(ig_user_id, page_id): 
    try:
        page = FacebookPage.objects.get(page_id=page_id)
    except FacebookPage.DoesNotExist:
        print("❌ Page not found in database.")
        return []

    page_access_token = page.page_access_token
    if not page_access_token:
        print("❌ No access token available.")
        return []

    # 1️⃣ Get conversation ID
    convo_url = f"https://graph.facebook.com/v23.0/{page_id}/conversations"
    convo_params = {
        "platform": "instagram",
        "user_id": ig_user_id,
        "access_token": page_access_token
    }
    convo_res = requests.get(convo_url, params=convo_params)
    convo_data = convo_res.json()
    # print("🧾 convo_data:", json.dumps(convo_data, indent=2))  # 🔍

    conversation_id = convo_data.get("data", [{}])[0].get("id")
    if not conversation_id:
        print("❌ No conversation found.")
        return []

    # 2️⃣ Fetch messages in that conversation
    msg_list_url = f"https://graph.facebook.com/v23.0/{conversation_id}"
    msg_list_params = {
        "fields": "messages",
        "access_token": page_access_token
    }
    messages_res = requests.get(msg_list_url, params=msg_list_params).json()
    # print("📨 messages_res:", json.dumps(messages_res, indent=2))  # 🔍
    message_ids = [m["id"] for m in messages_res.get("messages", {}).get("data", [])]

    # 3️⃣ Fetch message details
    full_messages = []
    ist = pytz.timezone("Asia/Kolkata")

    for msg_id in message_ids:
        msg_url = f"https://graph.facebook.com/v23.0/{msg_id}"
        msg_params = {
            "fields": "id,created_time,from,to,message",
            "access_token": page_access_token
        }
        msg_data = requests.get(msg_url, params=msg_params).json()
        # print(f"🗨️ msg_data for {msg_id}:", json.dumps(msg_data, indent=2))  # 🔍
        full_messages.append(msg_data)

        from_id = msg_data["from"]["id"]
        direction = "outbound" if from_id == page.instagram_business_account_id else "inbound"

        utc_time = parse_datetime(msg_data["created_time"])
        if utc_time:
            if utc_time.tzinfo is None:
                utc_time = make_aware(utc_time)
            ist_time = utc_time.astimezone(ist)
        else:
            ist_time = None
        
        InstagramMessage.objects.update_or_create(
            message_id=msg_data["id"],
            defaults={
                "conversation_id": conversation_id,
                "sender_id": from_id,
                "sender_username": msg_data["from"].get("username"),
                "message_text": msg_data.get("message"),
                "created_time": ist_time,
                "direction": direction,
                "page": page
            }
        )

    # 4️⃣ Update InstagramSenderDetails from the latest message
    if full_messages:
        last_msg = full_messages[-1]
        sender_info = last_msg.get("from", {})
        last_created = parse_datetime(last_msg.get("created_time"))

        if last_created:
            if last_created.tzinfo is None:
                last_created = make_aware(last_created)
            ist_created = last_created.astimezone(ist)
        else:
            ist_created = None

        

        if sender_info and sender_info.get("id") and sender_info["id"] != page.instagram_business_account_id:
            InstagramSenderDetails.objects.update_or_create(
                ig_user_id=sender_info["id"],
                defaults={
                    "username": sender_info.get("username"),
                    "conversation_id": conversation_id,
                    "page": page,
                    "last_message_text": last_msg.get("message"),
                    "last_message_time": ist_created,
                }
            )

    return full_messages





 












@login_required
def facebook_login_url(request):
    fb_auth_url = "https://www.facebook.com/v23.0/dialog/oauth"
    print(f"🔁 redirect_uri used before facebook login: '{settings.FB_REDIRECT_URI}'")
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": settings.FB_REDIRECT_URI,
        "scope": "pages_show_list,pages_messaging,instagram_basic,instagram_manage_messages,pages_read_engagement,pages_manage_metadata,business_management",
        "response_type": "code",
        
    }
    login_url = f"{fb_auth_url}?{urlencode(params)}"
    return JsonResponse({"facebook_login_url": login_url})



def facebook_callback(request):
    code = request.GET.get("code")
    if not code:
        return JsonResponse({"error": "Authorization code missing"}, status=400)
    print("🔁 redirect_uri used after facebook login and before generating access token with the code sent by facebook:", settings.FB_REDIRECT_URI)
    # 1. Exchange code for short-lived user token
    token_url = "https://graph.facebook.com/v23.0/oauth/access_token"
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": settings.FB_REDIRECT_URI,
        "client_secret": settings.FB_APP_SECRET,
        "code": code
    }

    print("🔍 Token Request Params:", params)  # Debug print

    try:
        res = requests.get(token_url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        short_lived_user_token = data.get("access_token")
    except requests.RequestException as e:
        try:
            error_details = res.json()
        except Exception:
            error_details = str(e)
        return JsonResponse({
            "error": "Token exchange failed",
            "details": error_details
        }, status=500)

    # 2. Convert to long-lived user token
    long_token_url = "https://graph.facebook.com/v23.0/oauth/access_token"
    exchange_params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.FB_APP_ID,
        "client_secret": settings.FB_APP_SECRET,
        "fb_exchange_token": short_lived_user_token
    }
    try:
        long_res = requests.get(long_token_url, params=exchange_params, timeout=10)
        long_res.raise_for_status()
        long_user_token = long_res.json().get("access_token")
        print("✅ Long-Lived User Token:", long_user_token)
    except requests.RequestException as e:
        return JsonResponse({
            "error": "Failed to get long-lived user token",
            "details": str(e)
        }, status=500)

    # 3. Fetch Pages using long-lived user token
    try:
        pages_res = requests.get("https://graph.facebook.com/v23.0/me/accounts", params={
            "access_token": long_user_token
        }, timeout=10)
        pages_res.raise_for_status()
        pages_data = pages_res.json()
        
    except requests.RequestException as e:
        return JsonResponse({"error": "Failed to fetch pages", "details": str(e)}, status=500)

    for page in pages_data.get("data", []):
        page_id = page["id"]
        page_name = page["name"]
        short_page_token = page.get("access_token")
        long_page_token = short_page_token  # Usually already long-lived

        # 5. Get Instagram Business Account ID
        try:
            ig_res = requests.get(f"https://graph.facebook.com/v23.0/{page_id}", params={
                "fields": "instagram_business_account",
                "access_token": long_user_token
            }, timeout=10)
            ig_res.raise_for_status()
            ig_data = ig_res.json()
            ig_account_id = ig_data.get("instagram_business_account", {}).get("id")
        except requests.RequestException:
            ig_account_id = None

        # 6. Save to DB
        FacebookPage.objects.update_or_create(
            page_id=page_id,
            defaults={
                "user": request.user,
                "page_name": page_name,
                "user_access_token": long_user_token,
                "page_access_token": long_page_token,
                "instagram_business_account_id": ig_account_id,
            }
        )
        print(f"✅ Saved page {page_name} to DB")

        # 7. Subscribe to messaging
        try:
            sub_url = f"https://graph.facebook.com/v23.0/{page_id}/subscribed_apps"
            sub_params = {
                "subscribed_fields": "messages",
                "access_token": long_page_token
            }
            sub_res = requests.post(sub_url, data=sub_params, timeout=10)
            sub_res.raise_for_status()
            print(f"✅ Subscribed app to messaging events for Page ID {page_id}")
        except requests.RequestException as e:
            print(f"❌ Failed to subscribe app to Page ID {page_id}: {e}")

    messages.success(request, "Facebook connected and saved to database.")
    return redirect("/dashboard/")












