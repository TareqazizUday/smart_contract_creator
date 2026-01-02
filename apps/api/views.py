"""
API Views - REST API endpoints for contract generation and OCR
"""
import json
from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from apps.contracts.contract_config import CONTRACT_CONFIGS, get_contract_config
from core.services.contract_service import ContractService
from core.services.ai_service import AIService
from core.helpers import markdown_to_html


contract_service = ContractService()
ai_service = AIService()


@require_http_methods(["GET"])
def contract_types(request):
    """Get all available contract types"""
    try:
        types = []
        for key, config in CONTRACT_CONFIGS.items():
            types.append({
                'id': key,
                'name': key.replace('_', ' ').title(),
                'description': config.get('description', ''),
                'party1_label': config.get('party1_label', 'Party 1'),
                'party2_label': config.get('party2_label', 'Party 2'),
            })
        
        return JsonResponse({
            'status': 'success',
            'contract_types': types
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@require_http_methods(["GET"])
def contract_sections(request, contract_type):
    """Get sections for a specific contract type"""
    try:
        config = get_contract_config(contract_type)
        
        sections = []
        for key, section_info in config.get('sections', {}).items():
            sections.append({
                'id': key,
                'label': section_info.get('label', key.replace('_', ' ').title()),
                'description': section_info.get('description', ''),
                'placeholder': section_info.get('placeholder', '')
            })
        
        return JsonResponse({
            'status': 'success',
            'contract_type': contract_type,
            'sections': sections,
            'party1_label': config.get('party1_label', 'Party 1'),
            'party2_label': config.get('party2_label', 'Party 2'),
            'description': config.get('description', '')
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def generate_contract(request):
    """Generate a contract via API"""
    try:
        data = json.loads(request.body)
        
        party1 = data.get('party1', 'Party One')
        party2 = data.get('party2', 'Party Two')
        start_date_str = data.get('start_date', '')
        user_prompt = data.get('user_prompt', '')
        contract_type = data.get('contract_type', 'service_agreement')
        jurisdiction = data.get('jurisdiction', 'bangladesh')
        sections_data = data.get('sections', {})
        supplementary_text = data.get('supplementary_text')
        template_text = data.get('template_text')
        output_format = data.get('output_format', 'both')  # 'html', 'markdown', or 'both'
        
        # Parse date
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            except ValueError:
                start_date = datetime.now()
        else:
            start_date = datetime.now()
        
        # Generate using API method
        result = contract_service.generate_full_contract_api(
            party1, party2, start_date, sections_data, user_prompt,
            supplementary_text, template_text, contract_type, jurisdiction
        )
        
        if 'error' in result:
            return JsonResponse({'status': 'error', 'message': result['error']}, status=500)
        
        response_data = {'status': 'success'}
        
        if output_format in ['html', 'both']:
            response_data['html'] = result.get('full_html', '')
        
        if output_format in ['markdown', 'both']:
            response_data['markdown'] = result.get('full_markdown', '')
        
        return JsonResponse(response_data)

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def translate_text(request):
    """Translate text via API"""
    try:
        data = json.loads(request.body)
        
        text = data.get('text', '')
        target_language = data.get('target_language', 'Bengali')
        
        if not text:
            return JsonResponse({'status': 'error', 'message': 'No text provided'}, status=400)
        
        translated_text, error = ai_service.translate_text(text, target_language)
        
        if error:
            return JsonResponse({'status': 'error', 'message': error}, status=500)
        
        return JsonResponse({
            'status': 'success',
            'original_text': text,
            'translated_text': translated_text,
            'target_language': target_language
        })

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def extract_contract_info(request):
    """Extract contract info using AI"""
    try:
        data = json.loads(request.body)
        
        prompt = data.get('prompt', '')
        contract_type = data.get('contract_type', 'service_agreement')
        
        if not prompt:
            return JsonResponse({'status': 'error', 'message': 'No prompt provided'}, status=400)
        
        result, error = ai_service.extract_contract_info(prompt, contract_type)
        
        if error:
            return JsonResponse({'status': 'error', 'message': error}, status=500)
        
        return JsonResponse({
            'status': 'success',
            'extracted_info': result
        })

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@require_http_methods(["GET"])
def jurisdictions(request):
    """Get available jurisdictions"""
    from core.jurisdiction_rules import JURISDICTION_RULES
    
    try:
        jurisdictions = []
        for key, rules in JURISDICTION_RULES.items():
            jurisdictions.append({
                'id': key,
                'name': key.title(),
                'governing_law': rules.get('governing_law', ''),
                'arbitration_body': rules.get('arbitration_body', '')
            })
        
        return JsonResponse({
            'status': 'success',
            'jurisdictions': jurisdictions
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@require_http_methods(["GET"])
def health_check(request):
    """API health check"""
    return JsonResponse({
        'status': 'healthy',
        'service': 'SignifyAI Django API',
        'version': '1.0.0'
    })
