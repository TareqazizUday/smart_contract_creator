"""
File handling utilities
"""
import os
import io
import time
import fitz  # PyMuPDF
from PIL import Image
from django.utils.text import slugify
import base64


def extract_images_from_pdf(pdf_path):
    """Extract images from a PDF file using PyMuPDF"""
    try:
        pdf_document = fitz.open(pdf_path)
        images = []
        
        # Extract images from each page
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            # Create a high-resolution image of the page
            pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))
            img_bytes = pix.tobytes("jpeg")
            
            # Convert to PIL Image
            img = Image.open(io.BytesIO(img_bytes))
            images.append(img)
        
        # Clean up
        pdf_document.close()
        
        return images, None
    except Exception as e:
        return None, f"Error extracting images from PDF: {str(e)}"


def encode_image_to_base64(image):
    """Convert PIL Image to base64 encoding for API"""
    # Convert image to RGB mode to ensure JPEG compatibility
    if image.mode in ('RGBA', 'P'):
        image = image.convert('RGB')
        
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str


def get_secure_filename(original_filename, prefix=""):
    """Generate a secure filename with timestamp"""
    timestamp = int(time.time())
    # Get the file extension
    if '.' in original_filename:
        name, ext = original_filename.rsplit('.', 1)
        safe_name = slugify(name)[:50]  # Limit length
        filename = f"{timestamp}_{prefix}_{safe_name}.{ext}" if prefix else f"{timestamp}_{safe_name}.{ext}"
    else:
        safe_name = slugify(original_filename)[:50]
        filename = f"{timestamp}_{prefix}_{safe_name}" if prefix else f"{timestamp}_{safe_name}"
    return filename

