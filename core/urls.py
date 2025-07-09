from django.urls import path,include
# from .views import webhook_view
from . import views

urlpatterns = [
    
    path('', views.home, name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path("post-login/", views.post_login_redirect, name="post_login_redirect"),

     # 🔐 Auth routes from Django
    path('accounts/', include('django.contrib.auth.urls')),


    path('webhook', views.webhook_view, name='webhook'),
    path('facebook/login-url/', views.facebook_login_url),
    path('facebook/callback/', views.facebook_callback),

    path("connect-facebook/", views.connect_facebook_view, name="connect_facebook"),
    path("dashboard/", views.dashboard_view, name="dashboard"),

    
    path("conversations/<str:page_id>/", views.list_conversations_view, name="conversation_list"),
    path("conversations/<str:ig_user_id>/<str:page_id>/", views.conversation_view, name="conversation_view"),

      # New: Message send view
    path("conversations/<str:ig_user_id>/<str:page_id>/send/", views.send_dm_view, name="send_dm_view"),

]
