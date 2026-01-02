"""
Contract Views - Django views for contract generation
(Same functionality as Flask version)
"""
import os
import time
import re
import json
import base64
import markdown
from datetime import datetime

from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib import messages

from apps.contracts.contract_config import get_contract_config, get_contract_sections, get_contract_section_descriptions
from apps.contracts.contract_types import ContractType
from core.services.contract_service import ContractService
from core.services.ocr_service import OCRService
from core.services.ai_service import AIService
from core.helpers import markdown_to_html
from core.file_utils import get_secure_filename
from core.jurisdiction_rules import get_available_jurisdictions


contract_service = ContractService()
ocr_service = OCRService()
ai_service = AIService()


def process_signature_file(sig_file, party_num, is_ajax=False):
    """
    Helper function to process signature file and convert to base64 data URL.
    Returns the base64 data URL string or None if processing fails.
    """
    if not sig_file or not sig_file.name:
        return None
    
    prefix = "AJAX" if is_ajax else "CONTRACT"
    print(f"[{prefix}] Processing Party {party_num} signature: {sig_file.name}")
    
    timestamp = int(time.time())
    filename = get_secure_filename(sig_file.name)
    file_path = os.path.join(settings.UPLOAD_FOLDER, f"sig{party_num}_{timestamp}_{filename}")
    
    # Save file
    with open(file_path, 'wb+') as destination:
        for chunk in sig_file.chunks():
            destination.write(chunk)
    
    # Convert to base64 for embedding in HTML
    file_ext = filename.lower().split('.')[-1]
    mime_type = 'image/png' if file_ext == 'png' else ('image/jpeg' if file_ext in ['jpg', 'jpeg'] else 'image/png')
    
    with open(file_path, 'rb') as f:
        signature_url = f"data:{mime_type};base64,{base64.b64encode(f.read()).decode()}"
    
    print(f"[{prefix}] Party {party_num} signature converted to base64 ({len(signature_url)} chars)")
    return signature_url


def index(request):
    """Main contract generation page - same as Flask"""
    generated_contract = None
    selected_contract_type = request.GET.get('type', ContractType.SERVICE_AGREEMENT.value)
    selected_jurisdiction = request.GET.get('jurisdiction', 'bangladesh')
    
    if request.method == 'POST':
        user_prompt = request.POST.get('user_prompt', '').strip()
        contract_type = request.POST.get('contract_type', ContractType.SERVICE_AGREEMENT.value)
        jurisdiction = request.POST.get('jurisdiction', 'bangladesh')
        selected_contract_type = contract_type
        selected_jurisdiction = jurisdiction
        
        if not user_prompt:
            messages.error(request, 'Please provide a prompt describing your contract requirements')
            return redirect(f'/?type={contract_type}')
        
        # Get contract configuration
        config = get_contract_config(contract_type)
        
        # STEP 1: Legal validation FIRST - Check if requirement is legal BEFORE generating
        print(f"[CONTRACT] Step 1/4: Analyzing requirements for legal compliance...")
        is_legal, validation_result, validation_error = ai_service.validate_legal_requirement(
            user_prompt, contract_type, jurisdiction
        )
        
        # If illegal, block generation and show error with references
        if not is_legal and validation_result:
            print(f"[CONTRACT] Illegal requirement detected - blocking generation")
            error_message = validation_result.get('warning_message', validation_result.get('reason', 'This requirement contains illegal or problematic elements.'))
            # Remove emojis from error_message
            error_message = re.sub(r'[🚫⚠️]', '', error_message).strip()
            
            # Build detailed error message with references
            references_text = ""
            if validation_result.get('references'):
                references_text = "\n\nLegal References:\n"
                for ref in validation_result.get('references', []):
                    references_text += f"- {ref.get('title', ref.get('url', ''))}: {ref.get('url', '')}\n"
            
            illegal_elements_text = ""
            if validation_result.get('illegal_elements'):
                illegal_elements_text = "\n\nIdentified Issues:\n"
                for element in validation_result.get('illegal_elements', []):
                    illegal_elements_text += f"- {element}\n"
            
            full_error = f"{error_message}{illegal_elements_text}{references_text}\n\nPlease review the legal references and consult with a legal professional."
            
            # Store in session for display
            references = validation_result.get('references', [])
            print(f"[CONTRACT] Storing legal error with {len(references)} references")
            if references:
                print(f"[CONTRACT] Sample reference: {references[0].get('url', 'N/A')}")
            
            request.session['legal_error'] = {
                'is_illegal': True,
                'reason': validation_result.get('reason', ''),
                'error_message': error_message,
                'illegal_elements': validation_result.get('illegal_elements', []),
                'references': references if references else [],  # Ensure it's always a list
                'warning_level': validation_result.get('warning_level', 'high')
            }
            
            print(f"[CONTRACT] Session legal_error stored with {len(request.session['legal_error'].get('references', []))} references")
            
            messages.error(request, error_message)
            return redirect(f'/?type={contract_type}')
        
        # STEP 2: If legal, proceed with contract generation
        print(f"[CONTRACT] Legal validation passed - proceeding with contract generation")
        
        # Extract legal references from validation result (even if legal)
        legal_references = []
        if validation_result and validation_result.get('references'):
            legal_references = validation_result.get('references', [])
            print(f"[CONTRACT] Extracted {len(legal_references)} legal references from validation result")
            if legal_references:
                print(f"[CONTRACT] Sample reference: {legal_references[0]}")
        else:
            print(f"[CONTRACT] WARNING: No references found in validation_result. validation_result keys: {list(validation_result.keys()) if validation_result else 'None'}")
        
        print(f"[CONTRACT] Step 2/4: Extracting contract information from prompt...")
        contract_info, error = ai_service.extract_contract_info_from_prompt(user_prompt, contract_type)
        
        if error:
            print(f"[CONTRACT] Error in extraction: {error}")
            messages.error(request, f'Error extracting contract information: {error}')
            return redirect(f'/?type={contract_type}')
        
        # Extract information from AI response
        party1 = contract_info.get('party1', config.get('party1_label', 'Party 1'))
        party2 = contract_info.get('party2', config.get('party2_label', 'Party 2'))
        start_date_str = contract_info.get('start_date')
        sections_data = contract_info.get('sections', {})
        
        print(f"[CONTRACT] Extraction successful - Party1: {party1}, Party2: {party2}")
        
        # Parse start date
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            start_date = datetime.today().date()
            start_date_str = start_date.strftime('%Y-%m-%d')
        
        # Handle supplementary file(s) - multiple files allowed like Flask
        supplementary_text = None
        if 'supplementary_file' in request.FILES:
            supp_files = request.FILES.getlist('supplementary_file')
            all_supplementary_texts = []
            
            for supp_file in supp_files:
                if supp_file and supp_file.name:
                    timestamp = int(time.time())
                    filename = get_secure_filename(supp_file.name)
                    file_path = os.path.join(settings.UPLOAD_FOLDER, f"{timestamp}_{filename}")
                    
                    with open(file_path, 'wb+') as destination:
                        for chunk in supp_file.chunks():
                            destination.write(chunk)
                    
                    supp_text, supp_error = ocr_service.extract_text_from_file(file_path)
                    if not supp_error and supp_text:
                        all_supplementary_texts.append(f"--- Content from file: {supp_file.name} ---\n{supp_text}")
                    elif supp_error:
                        messages.warning(request, f'Could not process supplementary file "{supp_file.name}": {supp_error}')
            
            if all_supplementary_texts:
                supplementary_text = "\n\n".join(all_supplementary_texts)
        
        # Handle template file (optional)
        template_text = None
        if 'template_file' in request.FILES:
            temp_file = request.FILES['template_file']
            if temp_file and temp_file.name:
                timestamp = int(time.time())
                filename = get_secure_filename(temp_file.name)
                file_path = os.path.join(settings.UPLOAD_FOLDER, f"{timestamp}_{filename}")
                
                with open(file_path, 'wb+') as destination:
                    for chunk in temp_file.chunks():
                        destination.write(chunk)
                
                print(f"[CONTRACT] Template file saved: {file_path}")
                temp_text, temp_error = ocr_service.extract_text_from_file(file_path)
                if not temp_error and temp_text:
                    template_text = temp_text
                    print(f"[CONTRACT] Template text extracted ({len(temp_text)} chars)")
                elif temp_error:
                    messages.warning(request, f'Could not process template file: {temp_error}')
        
        # Handle signature images
        party1_signature_url = None
        party2_signature_url = None
        
        if 'party1_signature' in request.FILES:
            party1_signature_url = process_signature_file(request.FILES['party1_signature'], 1, is_ajax=False)
        
        if 'party2_signature' in request.FILES:
            party2_signature_url = process_signature_file(request.FILES['party2_signature'], 2, is_ajax=False)
        
        print(f"[CONTRACT] Signature URLs - Party1: {bool(party1_signature_url)}, Party2: {bool(party2_signature_url)}")
        
        # Extract contact information for signatures (from form input or AI response)
        party1_contact_name = request.POST.get('party1_contact_name', '').strip() or (contract_info.get('party1_contact_name', '').strip() if contract_info else '')
        party1_contact_title = request.POST.get('party1_contact_title', '').strip() or (contract_info.get('party1_contact_title', '').strip() if contract_info else '')
        party2_contact_name = request.POST.get('party2_contact_name', '').strip() or (contract_info.get('party2_contact_name', '').strip() if contract_info else '')
        party2_contact_title = request.POST.get('party2_contact_title', '').strip() or (contract_info.get('party2_contact_title', '').strip() if contract_info else '')
        
        # Extract signature date from contract_info if available (may be in user prompt)
        signature_date = None
        if contract_info:
            # Check for various date fields that might indicate signature date
            signature_date = (contract_info.get('signature_date') or 
                            contract_info.get('execution_date') or 
                            contract_info.get('signing_date'))
        
        # Generate contract using extracted information
        print(f"[CONTRACT] Step 3/4: Generating contract content...")
        print(f"[CONTRACT] Passing {len(legal_references)} legal references to contract generation")
        generated_contract = contract_service.generate_full_contract(
            party1, party2, start_date, sections_data,
            user_prompt, supplementary_text, template_text, contract_type, jurisdiction,
            party1_contact_name, party1_contact_title, party2_contact_name, party2_contact_title,
            party1_signature_url, party2_signature_url, signature_date, legal_references
        )
        
        # Save generated contract in session for translation
        if generated_contract:
            print(f"[CONTRACT] Step 4/4: Contract generation completed ({len(generated_contract)} chars)")
            request.session['generated_contract'] = generated_contract
            request.session['contract_metadata'] = {
                'party1': party1,
                'party2': party2,
                'contract_type': contract_type,
                'jurisdiction': jurisdiction,
                'start_date': start_date_str
            }
    
    # Get contract configuration for selected type
    config = get_contract_config(selected_contract_type)
    contract_types = ContractType.get_all_types()
    
    # Get available jurisdictions
    jurisdictions = get_available_jurisdictions()
    
    # Get legal error from session if exists (for illegal requirements)
    legal_error = request.session.pop('legal_error', None)
    
    # Convert markdown to HTML if contract exists
    generated_contract_html = None
    if generated_contract:
        generated_contract_html = markdown_to_html(generated_contract)
    
    return render(request, 'contracts/index.html', {
        'contract_types': contract_types,
        'selected_contract_type': selected_contract_type,
        'sections': get_contract_sections(selected_contract_type),
        'section_descriptions': get_contract_section_descriptions(selected_contract_type),
        'party1_label': config.get('party1_label', 'Party 1'),
        'party2_label': config.get('party2_label', 'Party 2'),
        'party1_description': config.get('party1_description', ''),
        'party2_description': config.get('party2_description', ''),
        'examples': config.get('examples', []),
        'has_payment': config.get('has_payment', True),
        'generated_contract': generated_contract,
        'generated_contract_html': generated_contract_html,
        'jurisdictions': jurisdictions,
        'selected_jurisdiction': selected_jurisdiction,
        'legal_error': legal_error
    })


@csrf_exempt
@require_http_methods(["POST"])
def generate(request):
    """Generate a contract via AJAX"""
    try:
        user_prompt = request.POST.get('user_prompt', '').strip()
        contract_type = request.POST.get('contract_type', 'service_agreement')
        jurisdiction = request.POST.get('jurisdiction', 'bangladesh')
        
        if not user_prompt:
            return JsonResponse({'status': 'error', 'message': 'Please provide contract requirements'}, status=400)
        
        # Validate for negative amounts in prompt
        negative_amount_pattern = r'-\s*[\$৳₹£€]\s*[\d,]+(?:\.\d+)?|[\$৳₹£€]\s*-\s*[\d,]+(?:\.\d+)?|-[\d,]+(?:\.\d+)?\s*[\$৳₹£€]|\b-[\d,]+(?:\.\d+)?\s*(?:dollars?|taka|tk|bdt|usd|inr|rupees?|pounds?|euros?)\b'
        negative_matches = re.findall(negative_amount_pattern, user_prompt, re.IGNORECASE)
        if negative_matches:
            return JsonResponse({
                'status': 'error', 
                'message': f'Invalid amount detected: "{negative_matches[0]}". Financial amounts cannot be negative. Please provide a valid positive amount.',
                'error_type': 'validation'
            }, status=400)
        
        # STEP 1: Legal validation FIRST - Check if requirement is legal BEFORE generating
        is_legal, validation_result, validation_error = ai_service.validate_legal_requirement(
            user_prompt, contract_type, jurisdiction
        )
        
        # Extract references from validation result (even if legal)
        legal_references = []
        if validation_result and validation_result.get('references'):
            legal_references = validation_result.get('references', [])
        
        # If illegal, block generation and return error with references
        if not is_legal and validation_result:
            error_message = validation_result.get('warning_message', validation_result.get('reason', 'This requirement contains illegal or problematic elements.'))
            # Remove emojis from error_message
            error_message = re.sub(r'[🚫⚠️]', '', error_message).strip()
            references = validation_result.get('references', [])
            
            print(f"[CONTRACT] AJAX: Illegal requirement, returning {len(references)} references")
            if references:
                print(f"[CONTRACT] AJAX: Sample reference URL: {references[0].get('url', 'N/A')}")
            
            return JsonResponse({
                'status': 'error',
                'message': error_message,
                'error_type': 'legal_validation',
                'legal_error': {
                    'is_illegal': True,
                    'reason': validation_result.get('reason', ''),
                    'error_message': error_message,
                    'illegal_elements': validation_result.get('illegal_elements', []),
                    'references': references if isinstance(references, list) else [],  # Ensure it's always a list
                    'warning_level': validation_result.get('warning_level', 'high')
                }
            }, status=400)
        
        # STEP 2: If legal, proceed with contract generation
        # Get contract configuration
        config = get_contract_config(contract_type)
        
        # Extract contract information from prompt using AI
        contract_info, error = ai_service.extract_contract_info_from_prompt(user_prompt, contract_type)
        
        if error:
            return JsonResponse({'status': 'error', 'message': f'Error: {error}'}, status=500)
        
        # Extract information from AI response
        party1 = contract_info.get('party1', config.get('party1_label', 'Party 1'))
        party2 = contract_info.get('party2', config.get('party2_label', 'Party 2'))
        start_date_str = contract_info.get('start_date')
        sections_data = contract_info.get('sections', {})
        
        # Parse start date
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            start_date = datetime.today().date()
        
        # Handle supplementary files (multiple files allowed)
        supplementary_text = None
        if 'supplementary_file' in request.FILES:
            supp_files = request.FILES.getlist('supplementary_file')
            all_supplementary_texts = []
            
            for supp_file in supp_files:
                if supp_file and supp_file.name:
                    filename = get_secure_filename(supp_file.name)
                    file_path = os.path.join(settings.UPLOAD_FOLDER, f"{int(time.time())}_{filename}")
                    with open(file_path, 'wb+') as destination:
                        for chunk in supp_file.chunks():
                            destination.write(chunk)
                    extracted_text, _ = ocr_service.extract_text_from_file(file_path)
                    if extracted_text:
                        all_supplementary_texts.append(f"=== File: {supp_file.name} ===\n{extracted_text}\n")
            
            if all_supplementary_texts:
                supplementary_text = "\n\n".join(all_supplementary_texts)
        
        # Handle template file
        template_text = None
        if 'template_file' in request.FILES:
            temp_file = request.FILES['template_file']
            filename = get_secure_filename(temp_file.name)
            file_path = os.path.join(settings.UPLOAD_FOLDER, f"{int(time.time())}_{filename}")
            with open(file_path, 'wb+') as destination:
                for chunk in temp_file.chunks():
                    destination.write(chunk)
            template_text, _ = ocr_service.extract_text_from_file(file_path)
        
        # Handle signature images
        party1_signature_url = None
        party2_signature_url = None
        
        if 'party1_signature' in request.FILES:
            party1_signature_url = process_signature_file(request.FILES['party1_signature'], 1, is_ajax=True)
        
        if 'party2_signature' in request.FILES:
            party2_signature_url = process_signature_file(request.FILES['party2_signature'], 2, is_ajax=True)
        
        print(f"[CONTRACT] AJAX: Signature URLs - Party1: {bool(party1_signature_url)}, Party2: {bool(party2_signature_url)}")
        
        # Extract contact info from form (user input) or AI response
        party1_contact_name = request.POST.get('party1_contact_name', '').strip() or contract_info.get('party1_contact_name', '')
        party1_contact_title = request.POST.get('party1_contact_title', '').strip() or contract_info.get('party1_contact_title', '')
        party2_contact_name = request.POST.get('party2_contact_name', '').strip() or contract_info.get('party2_contact_name', '')
        party2_contact_title = request.POST.get('party2_contact_title', '').strip() or contract_info.get('party2_contact_title', '')
        
        # Extract signature date from contract_info if available (may be in user prompt)
        signature_date = None
        if contract_info:
            # Check for various date fields that might indicate signature date
            signature_date = (contract_info.get('signature_date') or 
                            contract_info.get('execution_date') or 
                            contract_info.get('signing_date'))
        
        # Check if streaming is requested
        use_streaming = request.POST.get('stream', 'false').lower() == 'true'
        
        if use_streaming:
            # Stream the contract generation
            def generate_stream():
                accumulated_text = ""
                cover_page_html = ""
                separator = "\n\n---\n\n"
                try:
                    # Generate and send cover page first (as HTML)
                    cover_page_html = contract_service._generate_cover_page(
                        contract_type, party1, party2, start_date, jurisdiction
                    )
                    if cover_page_html:
                        # Send cover page as HTML (will be rendered directly)
                        yield f"data: {json.dumps({'status': 'cover_page', 'html': cover_page_html})}\n\n"
                    
                    # Stream AI-generated contract content
                    for chunk_data in ai_service.stream_contract_content(
                        party1, party2, start_date, sections_data, user_prompt,
                        supplementary_text, template_text, contract_type, jurisdiction
                    ):
                        chunk_json = json.loads(chunk_data)
                        if "error" in chunk_json:
                            yield f"data: {json.dumps({'status': 'error', 'message': chunk_json['error']})}\n\n"
                            return
                        elif "chunk" in chunk_json:
                            content = chunk_json["chunk"]
                            accumulated_text += content
                            yield f"data: {json.dumps({'status': 'streaming', 'chunk': content})}\n\n"
                        elif "done" in chunk_json:
                            # Append signature block
                            signature_block = contract_service._generate_signature_block(
                                party1_contact_name, party1_contact_title,
                                party2_contact_name, party2_contact_title,
                                party1_signature_url, party2_signature_url, signature_date
                            )
                            accumulated_text += signature_block
                            
                            # Append references section if legal references are provided
                            if legal_references and isinstance(legal_references, list) and len(legal_references) > 0:
                                print(f"[CONTRACT] Streaming: Adding {len(legal_references)} references to contract")
                                references_block = contract_service._generate_references_block(legal_references)
                                accumulated_text += references_block
                            
                            # Save to session (cover page + separator + contract content)
                            full_contract_md = (cover_page_html + separator + accumulated_text) if cover_page_html else accumulated_text
                            request.session['generated_contract'] = full_contract_md
                            
                            # Convert markdown content to HTML
                            contract_html = markdown_to_html(accumulated_text)
                            
                            # Combine cover page HTML with contract HTML
                            final_html = (cover_page_html + contract_html) if cover_page_html else contract_html
                            
                            # Send final response
                            yield f"data: {json.dumps({'status': 'success', 'contract_html': final_html, 'contract_md': full_contract_md})}\n\n"
                            return
                except Exception as e:
                    yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            
            response = StreamingHttpResponse(generate_stream(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        else:
            # Generate the contract (non-streaming)
            contract_md = contract_service.generate_full_contract(
                party1, party2, start_date, sections_data, user_prompt,
                supplementary_text, template_text, contract_type, jurisdiction,
                party1_contact_name, party1_contact_title,
                party2_contact_name, party2_contact_title,
                party1_signature_url, party2_signature_url, signature_date, legal_references
            )
            
            # Save to session
            request.session['generated_contract'] = contract_md
            
            # Convert to HTML
            contract_html = markdown_to_html(contract_md)
            
            return JsonResponse({
                'status': 'success',
                'contract_html': contract_html,
                'contract_md': contract_md
            })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def translate_contract(request):
    """Translate contract to target language with streaming support"""
    import json
    import re
    
    try:
        data = json.loads(request.body)
        target_language = data.get('target_language', 'English')
        contract_md = data.get('contract_md', '')
        contract_text = data.get('contract_text', '')
        use_streaming = data.get('stream', 'false').lower() == 'true'
        
        # Use contract_md if available, fallback to contract_text
        full_contract_text = contract_md or contract_text
        
        # Get contract from session if not provided
        if not full_contract_text:
            full_contract_text = request.session.get('generated_contract', '')
        
        if not full_contract_text:
            if use_streaming:
                def error_stream():
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Contract text required. Generate contract first.'})}\n\n"
                return StreamingHttpResponse(error_stream(), content_type='text/event-stream')
            return JsonResponse({'status': 'error', 'message': 'Contract text required. Generate contract first.'}, status=400)
        
        # If target is English, just return the original
        if target_language.lower() in ['english', 'en']:
            # Extract cover page if exists (same logic as translation)
            separator = "\n\n---\n\n"
            cover_page_html = ""
            text_without_cover = full_contract_text
            
            if separator in full_contract_text:
                parts = full_contract_text.split(separator, 1)
                if len(parts) == 2:
                    cover_page_html = parts[0].strip()
                    text_without_cover = parts[1].strip()
                    
                    if not cover_page_html.startswith('<div') or 'page-break-after' not in cover_page_html:
                        cover_page_html = ""
                        text_without_cover = full_contract_text
                else:
                    cover_page_html = ""
                    text_without_cover = full_contract_text
            
            translated_html = markdown_to_html(text_without_cover) if text_without_cover.strip() else ""
            final_html = (cover_page_html + translated_html) if cover_page_html else translated_html
            
            return JsonResponse({
                'status': 'success',
                'translated_md': full_contract_text,
                'translated_html': final_html,
                'target_language': target_language
            })
        
        # Extract cover page if exists (HTML cover page before separator)
        # Pattern: cover page HTML + separator + markdown content
        separator = "\n\n---\n\n"
        cover_page_html = ""
        text_to_translate = full_contract_text
        original_cover_page_html = ""
        
        # Check if cover page exists (look for the separator pattern)
        if separator in full_contract_text:
            # Split by separator
            parts = full_contract_text.split(separator, 1)
            if len(parts) == 2:
                original_cover_page_html = parts[0].strip()
                text_to_translate = parts[1].strip()
                
                # Verify that first part is HTML (contains <div>)
                if original_cover_page_html.startswith('<div') and 'page-break-after' in original_cover_page_html:
                    cover_page_html = original_cover_page_html
                else:
                    # Not a cover page, treat as regular content
                    cover_page_html = ""
                    text_to_translate = full_contract_text
            else:
                # Separator found but split failed, treat as regular content
                cover_page_html = ""
                text_to_translate = full_contract_text
        else:
            # No separator, check if starts with HTML (might be cover page without separator)
            if full_contract_text.strip().startswith('<div') and 'page-break-after' in full_contract_text:
                # Try to extract cover page HTML
                cover_page_match = re.search(r'<div[^>]*style="[^"]*page-break-after:\s*always[^"]*"[^>]*>.*?</div>', full_contract_text, re.DOTALL)
                if cover_page_match:
                    cover_page_html = cover_page_match.group(0)
                    original_cover_page_html = cover_page_html
                    # Remove cover page from text
                    text_to_translate = full_contract_text.replace(cover_page_html, '').strip()
                else:
                    cover_page_html = ""
                    text_to_translate = full_contract_text
            else:
                # No cover page
                cover_page_html = ""
                text_to_translate = full_contract_text
        
        if use_streaming:
            # Stream the translation
            def translate_stream():
                try:
                    # Translate cover page if exists (non-streaming, small content)
                    translated_cover_page_html = cover_page_html
                    if cover_page_html:
                        print(f"[TRANSLATE] Translating cover page HTML ({len(cover_page_html)} chars)...")
                        translated_cover_page_html, error = ai_service.translate_html_content(cover_page_html, target_language)
                        if error:
                            print(f"[TRANSLATE] Cover page translation failed: {error}, using original")
                            translated_cover_page_html = cover_page_html
                        else:
                            print(f"[TRANSLATE] Cover page translated successfully")
                    
                    # Send translated cover page first if exists
                    if translated_cover_page_html:
                        yield f"data: {json.dumps({'status': 'cover_page', 'html': translated_cover_page_html})}\n\n"
                    
                    accumulated_text = ""
                    # Stream translation of contract content
                    for chunk_data in ai_service.stream_translate_text(text_to_translate, target_language):
                        chunk_json = json.loads(chunk_data)
                        if "error" in chunk_json:
                            yield f"data: {json.dumps({'status': 'error', 'message': chunk_json['error']})}\n\n"
                            return
                        elif "chunk" in chunk_json:
                            content = chunk_json["chunk"]
                            accumulated_text += content
                            yield f"data: {json.dumps({'status': 'streaming', 'chunk': content})}\n\n"
                        elif "done" in chunk_json:
                            translated_text = chunk_json.get("translated_text", accumulated_text)
                            
                            # Convert markdown to HTML
                            translated_html = markdown_to_html(translated_text)
                            
                            # Combine translated cover page with translated content
                            final_html = (translated_cover_page_html + translated_html) if translated_cover_page_html else translated_html
                            
                            # Save full translated contract (translated cover page + separator + translated content)
                            full_translated_md = (translated_cover_page_html + separator + translated_text) if translated_cover_page_html else translated_text
                            
                            yield f"data: {json.dumps({'status': 'success', 'translated_html': final_html, 'translated_md': full_translated_md, 'target_language': target_language})}\n\n"
                            return
                except Exception as e:
                    yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            
            response = StreamingHttpResponse(translate_stream(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        else:
            # Non-streaming translation (original behavior)
            # Translate cover page if exists
            translated_cover_page_html = cover_page_html
            if cover_page_html:
                print(f"[TRANSLATE] Translating cover page HTML ({len(cover_page_html)} chars)...")
                translated_cover_page_html, error = ai_service.translate_html_content(cover_page_html, target_language)
                if error:
                    print(f"[TRANSLATE] Cover page translation failed: {error}, using original")
                    translated_cover_page_html = cover_page_html
                else:
                    print(f"[TRANSLATE] Cover page translated successfully")
            
            print(f"[TRANSLATE] Starting translation to {target_language} ({len(text_to_translate)} chars)...")
            
            translated_text, error = ai_service.translate_text(text_to_translate, target_language)
            
            if error:
                print(f"[TRANSLATE] Translation failed: {error}")
                return JsonResponse({'status': 'error', 'message': error}, status=500)
            
            print(f"[TRANSLATE] Translation completed ({len(translated_text)} chars)")
            
            # Convert to HTML
            translated_html = markdown_to_html(translated_text)
            
            # Combine translated cover page with translated content
            final_html = (translated_cover_page_html + translated_html) if translated_cover_page_html else translated_html
            
            # Full translated contract (translated cover page + separator + translated content)
            full_translated_md = (translated_cover_page_html + separator + translated_text) if translated_cover_page_html else translated_text
            
            return JsonResponse({
                'status': 'success',
                'translated_md': full_translated_md,
                'translated_html': final_html,
                'target_language': target_language
            })
    
    except json.JSONDecodeError:
        if use_streaming:
            def error_stream():
                yield f"data: {json.dumps({'status': 'error', 'message': 'Invalid JSON'})}\n\n"
            return StreamingHttpResponse(error_stream(), content_type='text/event-stream')
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        if use_streaming:
            def error_stream():
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            return StreamingHttpResponse(error_stream(), content_type='text/event-stream')
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def download_markdown(request):
    """Download contract as Markdown file"""
    try:
        contract_md = request.POST.get('contract_md', '')
        contract_type = request.POST.get('contract_type', 'contract')
        
        if not contract_md:
            return JsonResponse({'status': 'error', 'message': 'No contract content'}, status=400)
        
        timestamp = int(time.time())
        filename = f"{contract_type}_{timestamp}.md"
        
        response = HttpResponse(contract_md, content_type='text/markdown')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def download_html(request):
    """Download contract as HTML file"""
    try:
        contract_md = request.POST.get('contract_md', '')
        contract_type = request.POST.get('contract_type', 'contract')
        
        if not contract_md:
            return JsonResponse({'status': 'error', 'message': 'No contract content'}, status=400)
        
        html_content = markdown_to_html(contract_md)
        
        full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{contract_type.replace('_', ' ').title()}</title>
    <style>
        body {{ font-family: 'Times New Roman', Times, serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 40px; }}
        h1 {{ text-align: center; color: #2c3e50; }}
        h2 {{ color: #2c3e50; border-bottom: 1px solid #ddd; padding-bottom: 10px; }}
        h3 {{ color: #34495e; }}
        p {{ text-align: justify; }}
        hr {{ margin: 30px 0; border: none; border-top: 1px solid #ddd; }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""
        
        timestamp = int(time.time())
        filename = f"{contract_type}_{timestamp}.html"
        
        response = HttpResponse(full_html, content_type='text/html')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def get_sections_view(request, contract_type):
    """Get sections for a specific contract type (API view)"""
    try:
        config = get_contract_config(contract_type)
        return JsonResponse({
            'status': 'success',
            'sections': config.get('sections', {}),
            'party1_label': config.get('party1_label', 'Party 1'),
            'party2_label': config.get('party2_label', 'Party 2'),
            'description': config.get('description', '')
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
