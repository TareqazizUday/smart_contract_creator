"""
Contract URL Configuration
"""
from django.urls import path
from . import views

app_name = 'contracts'

urlpatterns = [
    path('', views.index, name='index'),
    path('generate/', views.generate, name='generate'),
    path('translate/', views.translate_contract, name='translate'),
    path('download/markdown/', views.download_markdown, name='download_markdown'),
    path('download/html/', views.download_html, name='download_html'),
    path('sections/<str:contract_type>/', views.get_sections_view, name='get_sections'),
]
