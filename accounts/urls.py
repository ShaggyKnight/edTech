from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    # Preview de emails transaccionales — solo staff.
    path('emails/', views.emails_index, name='emails_index'),
    path('emails/<slug:slug>/', views.email_preview, name='email_preview'),
    path('emails/<slug:slug>/enviar/', views.email_enviar_demo, name='email_enviar_demo'),
]
