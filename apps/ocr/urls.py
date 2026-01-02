"""
OCR URL Configuration
"""
from django.urls import path
from . import views

app_name = 'ocr'

urlpatterns = [
    path('', views.pdf_contract, name='pdf_contract'),
    path('process/', views.process_file, name='process_file'),
    path('translate/', views.translate_text, name='translate'),
    path('extract/', views.extract_text, name='extract'),
]
