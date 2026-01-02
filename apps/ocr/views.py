"""
OCR Views - Django views for OCR processing
"""
import os
import time

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from core.services.ocr_service import OCRService
from core.file_utils import get_secure_filename


ocr_service = OCRService()


def pdf_contract(request):
    """PDF/Image OCR processing page"""
    return render(request, 'ocr/pdf_contract.html')


@csrf_exempt
@require_http_methods(["POST"])
def process_file(request):
    """Process uploaded file for OCR"""
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)
        
        uploaded_file = request.FILES['file']
        file_type = request.POST.get('file_type', 'image')
        page_selection = request.POST.get('page_selection', 'all')
        specific_page = int(request.POST.get('specific_page', 1))
        prompt_template = request.POST.get('prompt_template', '')
        
        if not prompt_template:
            prompt_template = """Extract ALL text from this image exactly as it appears. 
Preserve the original structure, formatting, headings, paragraphs, and layout.
Return only the text content without any explanations or notes."""
        
        # Save uploaded file
        filename = get_secure_filename(uploaded_file.name)
        timestamp = int(time.time())
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(settings.UPLOAD_FOLDER, unique_filename)
        
        with open(file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)
        
        # Process the file
        preview_path, text_result, pages_result, error = ocr_service.process_file(
            file_path, file_type, page_selection, specific_page, prompt_template
        )
        
        if error:
            return JsonResponse({'status': 'error', 'message': error}, status=500)
        
        response_data = {'status': 'success'}
        
        if preview_path:
            # Return relative path for preview
            response_data['preview_url'] = f'/results/{os.path.basename(preview_path)}'
        
        if text_result:
            response_data['text'] = text_result
        
        if pages_result:
            response_data['pages'] = pages_result
        
        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def translate_text(request):
    """Translate text to specified language"""
    try:
        import json
        data = json.loads(request.body)
        
        text = data.get('text', '')
        target_language = data.get('target_language', 'Bengali')
        
        if not text:
            return JsonResponse({'status': 'error', 'message': 'No text provided'}, status=400)
        
        translated_text, error = ocr_service.ai_service.translate_text(text, target_language)
        
        if error:
            return JsonResponse({'status': 'error', 'message': error}, status=500)
        
        return JsonResponse({
            'status': 'success',
            'translated_text': translated_text
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def extract_text(request):
    """Extract text from uploaded file"""
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)
        
        uploaded_file = request.FILES['file']
        
        # Save uploaded file
        filename = get_secure_filename(uploaded_file.name)
        timestamp = int(time.time())
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(settings.UPLOAD_FOLDER, unique_filename)
        
        with open(file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)
        
        # Extract text
        text, error = ocr_service.extract_text_from_file(file_path)
        
        if error:
            return JsonResponse({'status': 'error', 'message': error}, status=500)
        
        return JsonResponse({
            'status': 'success',
            'text': text
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
