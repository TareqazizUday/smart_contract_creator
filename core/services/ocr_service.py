"""
OCR Service - Handles OCR and file processing operations
"""
import os
import time
from PIL import Image
from django.conf import settings
from core.services.ai_service import AIService
from core.file_utils import extract_images_from_pdf, encode_image_to_base64, get_secure_filename
from core.helpers import clean_output


class OCRService:
    """Service for OCR and file processing operations"""
    
    def __init__(self):
        self.ai_service = AIService()
    
    def extract_text_from_file(self, file_path, upload_folder=None, results_folder=None):
        """Extract text from uploaded file (PDF or image) for supplementary/template use"""
        if upload_folder is None:
            upload_folder = settings.UPLOAD_FOLDER
        if results_folder is None:
            results_folder = settings.RESULTS_FOLDER
        
        try:
            if not os.path.exists(file_path):
                return None, "File not found"
            
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.pdf':
                import fitz
                pdf_document = fitz.open(file_path)
                text_content = ""
                for page_num in range(len(pdf_document)):
                    page = pdf_document.load_page(page_num)
                    text_content += page.get_text()
                pdf_document.close()
                
                cleaned_text = text_content.strip()
                if len(cleaned_text) < 50:
                    # Use OCR for scanned PDFs
                    images, error = extract_images_from_pdf(file_path)
                    if error:
                        return None, error
                    
                    all_text = []
                    for i, img in enumerate(images):
                        prompt_template = """Extract ALL text from this image exactly as it appears. 
Preserve the original structure, formatting, headings, paragraphs, and layout.
Return only the text content without any explanations or notes."""
                        extracted_text, ocr_error = self.ai_service.refine_text_with_vision("", img, prompt_template)
                        if ocr_error:
                            continue
                        all_text.append(f"--- Page {i+1} ---\n{extracted_text}")
                    
                    if all_text:
                        return "\n\n".join(all_text), None
                    else:
                        return None, "Could not extract text from scanned PDF"
                
                return text_content, None
            elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
                image = Image.open(file_path)
                prompt_template = """Extract all text from this image. Return only the text content without any explanations or formatting notes."""
                extracted_text, error = self.ai_service.refine_text_with_vision("", image, prompt_template)
                if error:
                    return None, error
                return clean_output(extracted_text), None
            else:
                return None, f"Unsupported file type: {file_ext}"
        except Exception as e:
            return None, f"Error extracting text: {str(e)}"
    
    def process_file(self, file_path, file_type, page_selection, specific_page, prompt_template, 
                     upload_folder=None, results_folder=None):
        """Process uploaded file (image or PDF)"""
        if upload_folder is None:
            upload_folder = str(settings.UPLOAD_FOLDER)
        if results_folder is None:
            results_folder = str(settings.RESULTS_FOLDER)
        
        try:
            if not os.path.exists(file_path):
                return None, None, None, "File not found"
            
            if file_type == "image":
                image = Image.open(file_path)
                
                if not self.ai_service.gemini_api_key:
                    return image, "ERROR: Gemini API key is not configured.", None, None
                
                refined_text, error = self.ai_service.refine_text_with_vision("", image, prompt_template)
                if error:
                    return image, f"ERROR: {error}", None, None
                
                refined_text = clean_output(refined_text)
                
                timestamp = int(time.time())
                image_preview_path = os.path.join(results_folder, f"preview_{timestamp}.jpg")
                image.save(image_preview_path)
                
                return image_preview_path, refined_text, None, None
            
            elif file_type == "pdf":
                images, error = extract_images_from_pdf(file_path)
                
                if error:
                    return None, None, None, error
                
                if not self.ai_service.gemini_api_key:
                    return None, None, None, "ERROR: Gemini API key is not configured."
                
                timestamp = int(time.time())
                
                if page_selection == "specific":
                    if specific_page <= 0 or specific_page > len(images):
                        return None, None, None, f"Invalid page number. PDF has {len(images)} pages."
                    
                    image = images[specific_page - 1]
                    refined_text, error = self.ai_service.refine_text_with_vision("", image, prompt_template)
                    if error:
                        return None, None, None, f"ERROR: {error}"
                    
                    refined_text = clean_output(refined_text)
                    
                    image_preview_path = os.path.join(results_folder, f"preview_{timestamp}.jpg")
                    image.save(image_preview_path)
                    
                    pages_result = [{
                        'page_number': specific_page,
                        'text': refined_text
                    }]
                    
                    return image_preview_path, None, pages_result, None
                
                else:  # Process all pages
                    first_image = images[0]
                    image_preview_path = os.path.join(results_folder, f"preview_{timestamp}.jpg")
                    first_image.save(image_preview_path)
                    
                    pages_result = []
                    all_text_for_file = f"PDF with {len(images)} pages\n\n"
                    
                    for i, img in enumerate(images):
                        refined, error = self.ai_service.refine_text_with_vision("", img, prompt_template)
                        if error:
                            refined = f"Error processing page {i+1}: {error}"
                        else:
                            refined = clean_output(refined)
                        
                        pages_result.append({
                            'page_number': i + 1,
                            'text': refined
                        })
                        
                        all_text_for_file += f"--- PAGE {i+1} ---\n{refined}\n\n"
                    
                    return image_preview_path, all_text_for_file, pages_result, None
        
        except Exception as e:
            return None, None, None, f"Error processing file: {str(e)}"
