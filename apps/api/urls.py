"""
API URL Configuration
"""
from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    path('', views.health_check, name='health_check'),
    path('contract-types/', views.contract_types, name='contract_types'),
    path('contract-types/<str:contract_type>/sections/', views.contract_sections, name='contract_sections'),
    path('generate/', views.generate_contract, name='generate_contract'),
    path('translate/', views.translate_text, name='translate'),
    path('extract-info/', views.extract_contract_info, name='extract_info'),
    path('jurisdictions/', views.jurisdictions, name='jurisdictions'),
]
