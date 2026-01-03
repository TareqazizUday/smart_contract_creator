"""
AI Service - Handles all AI/LLM interactions
"""
import os
import json
import re
import time
import logging
from datetime import datetime
from django.conf import settings

logger = logging.getLogger(__name__)


class AIService:
    """Service for AI/LLM operations"""
    
    def __init__(self):
        self.gemini_api_key = settings.GEMINI_API_KEY
        self.genai = None
        # Single, explicit model from environment (no hard-coded fallbacks)
        env_model = settings.GEMINI_MODEL
        self.model_names = [env_model]
        self.model_name = env_model
        
        # Import google.generativeai inside __init__ to avoid import errors
        try:
            import google.generativeai as genai
            # Direct Google Generative AI initialization
            if self.gemini_api_key:
                genai.configure(api_key=self.gemini_api_key)
                self.genai = genai
            else:
                # Still set genai even without API key (will fail later with better error)
                self.genai = genai
        except ImportError as e:
            self.genai = None
            logger.warning(f"google.generativeai not installed: {e}")
        except Exception as e:
            self.genai = None
            logger.warning(f"Error initializing Gemini API: {e}")
    
    def _make_api_call_with_retry(self, prompt, max_retries=3, retry_delay=8):
        """Make API call with retry logic for quota/rate limit errors"""
        # Start with first model
        current_model_index = 0
        
        for attempt in range(max_retries * len(self.model_names)):
            try:
                # Use current model from the list
                current_model = self.model_names[current_model_index]
                model = self.genai.GenerativeModel(current_model)
                response = model.generate_content(
                    prompt,
                    generation_config=self.genai.types.GenerationConfig(
                        temperature=0
                    )
                )
                # Update self.model_name to the working model
                self.model_name = current_model
                return response.text.strip(), None
            except Exception as e:
                error_str = str(e)
                
                # Check for 404 model not found errors - try next model
                if "404" in error_str or "not found" in error_str.lower() or "not supported" in error_str.lower():
                    if current_model_index < len(self.model_names) - 1:
                        current_model_index += 1
                        logger.info(f"Model '{self.model_names[current_model_index - 1]}' not available. Trying '{self.model_names[current_model_index]}'...")
                        continue
                    else:
                        return None, f"None of the available models are supported. Please check your API access. Last error: {error_str[:200]}"
                
                # Check for quota/rate limit errors
                if "429" in error_str or "quota" in error_str.lower() or "rate limit" in error_str.lower():
                    retry_seconds = retry_delay
                    delay_match = re.search(r'retry in ([\d.]+)s', error_str.lower())
                    if delay_match:
                        retry_seconds = float(delay_match.group(1)) + 1
                    
                    if current_model_index < len(self.model_names) - 1:
                        current_model_index += 1
                        logger.info(f"Quota exceeded for '{self.model_names[current_model_index - 1]}'. Switching to '{self.model_names[current_model_index]}'...")
                        continue
                    elif attempt < max_retries - 1:
                        logger.info(f"Quota/Rate limit exceeded. Retrying in {retry_seconds} seconds... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_seconds)
                        continue
                    else:
                        return None, f"API quota/rate limit exceeded. Please wait a few minutes and try again. Error: {error_str[:200]}"
                
                if current_model_index < len(self.model_names) - 1:
                    current_model_index += 1
                    logger.info(f"Error with '{self.model_names[current_model_index - 1]}'. Trying '{self.model_names[current_model_index]}'...")
                    continue
                
                return None, f"Error calling Gemini API: {error_str[:200]}"
        
        return None, "Failed to get response after trying all models"
    
    def extract_contract_info_from_prompt(self, user_prompt, contract_type="service_agreement"):
        """Extract contract information from user prompt using AI"""
        from apps.contracts.contract_config import get_contract_config
        
        today_date = datetime.now().strftime('%Y-%m-%d')
        config = get_contract_config(contract_type)
        
        party1_label = config.get("party1_label", "Party 1")
        party2_label = config.get("party2_label", "Party 2")
        sections = config.get("sections", [])
        section_descriptions = config.get("section_descriptions", {})
        
        # Build sections JSON structure
        sections_json = "{\n"
        for section in sections:
            desc = section_descriptions.get(section, f"Details for {section} based on the prompt")
            sections_json += f'        "{section}": "{desc}",\n'
        sections_json = sections_json.rstrip(',\n') + "\n    }"
        
        # SOP needs different validation
        if contract_type == "sop":
            extraction_prompt = self._build_sop_extraction_prompt(
                user_prompt, party1_label, party2_label, sections_json, today_date
            )
        elif contract_type == "developer_agreement":
            extraction_prompt = self._build_developer_extraction_prompt(
                user_prompt, party1_label, party2_label, sections_json, today_date
            )
        else:
            extraction_prompt = self._build_standard_extraction_prompt(
                user_prompt, contract_type, party1_label, party2_label, sections_json, today_date
            )
        
        try:
            # Prefer OpenAI if configured
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if openai_api_key:
                result, error = self._call_openai(extraction_prompt)
                if error:
                    return None, error
            else:
                if not self.genai:
                    return None, "Google Generative AI package not installed. Please run: pip install google-generativeai"
                
                if not self.gemini_api_key:
                    return None, "Gemini API key is not configured. Please set GEMINI_API_KEY in your .env file."
                
                result, error = self._make_api_call_with_retry(extraction_prompt)
                if error:
                    return None, error
            
            # Remove markdown code blocks if present
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                result = result.split("```")[1].split("```")[0].strip()
            
            result = result.strip()
            contract_info = json.loads(result)
            
            if not contract_info.get('valid', True):
                error_msg = contract_info.get('error', 'The prompt is not relevant for contract generation.')
                return None, error_msg
            
            if 'valid' in contract_info:
                del contract_info['valid']
            if 'error' in contract_info:
                del contract_info['error']
            
            # Validate and set defaults
            if not contract_info.get('party1'):
                contract_info['party1'] = party1_label
            if not contract_info.get('party2'):
                contract_info['party2'] = party2_label
            # Do NOT auto-fill start_date - let it remain empty so placeholder is used
            # if not contract_info.get('start_date'):
            #     contract_info['start_date'] = today_date
            
            if not contract_info.get('sections'):
                default_sections = {}
                for section in sections:
                    default_sections[section] = section_descriptions.get(section, f"Details for {section}")
                contract_info['sections'] = default_sections
            
            return contract_info, None
        except json.JSONDecodeError as e:
            return None, f"Error parsing AI response: {str(e)}"
        except Exception as e:
            return None, f"Error extracting contract information: {str(e)}"
    
    def _build_sop_extraction_prompt(self, user_prompt, party1_label, party2_label, sections_json, today_date):
        """Build extraction prompt for SOP"""
        return f"""You are a document information extractor for Statement of Purpose / Motivation Letter / Personal Statement. Your task is to:
1. FIRST: Validate if the user prompt is relevant for generating a Statement of Purpose
2. SECOND: If valid, extract all relevant information needed to generate the document

User Prompt:
{user_prompt}

VALIDATION RULES:
1. The prompt MUST be related to creating a Statement of Purpose, Motivation Letter, or Personal Statement
2. The prompt MUST mention or imply an applicant and an institution/program
3. REJECT if the prompt is completely irrelevant or too vague

If VALID, extract the following information and return ONLY a valid JSON object:
{{
    "valid": true,
    "party1": "{party1_label} name (extract applicant name from prompt, or use 'Applicant' if not specified)",
    "party2": "{party2_label} name (extract institution/program name from prompt, or use 'Institution' if not specified)",
    "start_date": "Application date in YYYY-MM-DD format (extract from prompt if mentioned, else empty string '')",
    "party1_contact_name": "",
    "party1_contact_title": "",
    "party2_contact_name": "",
    "party2_contact_title": "",
    "sections": {sections_json}
}}

If INVALID, return:
{{
    "valid": false,
    "error": "Brief explanation of why the prompt is invalid"
}}

Return ONLY the JSON object."""
    
    def _build_developer_extraction_prompt(self, user_prompt, party1_label, party2_label, sections_json, today_date):
        """Build extraction prompt for Developer Agreement - handles all 5 types"""
        return f"""You are a contract information extractor for Developer/Construction Agreements. Your task is to:
1. FIRST: Validate if the user prompt is relevant for generating a Developer Agreement
2. SECOND: DETECT which specific agreement type is needed based on user requirements:
   - Developer (Construct Building) Agreement: Simple construction agreement where developer builds for landowner
   - Joint Development Agreement (JDA): Fixed area/flat sharing model (e.g., 30-40% to landowner)
   - Revenue/Profit Sharing Agreement: Percentage-based revenue or profit sharing (e.g., 35% landowner, 65% developer)
   - Land Sharing/Contribution Agreement: Specific flats/units allocation to landowner
   - Joint Venture (JV) Agreement: Separate company/entity formation for joint development
3. THIRD: Extract all relevant information needed to generate the agreement

User Prompt:
{user_prompt}

VALIDATION RULES:
1. The prompt MUST be related to creating a Developer Agreement for building construction/real estate development
2. The prompt MUST mention or imply a Landowner and a Developer
3. REJECT if the prompt is completely irrelevant or too vague

AGREEMENT TYPE DETECTION:
Analyze the user prompt to determine which specific agreement type is needed:
- If mentions "JDA", "joint development", "area sharing", "flat sharing percentage" → Joint Development Agreement (JDA)
- If mentions "revenue sharing", "profit sharing", "percentage of sales", "revenue split" → Revenue/Profit Sharing Agreement
- If mentions "land sharing", "contribution", "specific flats", "unit allocation" → Land Sharing/Contribution Agreement
- If mentions "joint venture", "JV", "separate company", "entity formation" → Joint Venture (JV) Agreement
- If mentions simple construction, building development without sharing model → Developer (Construct Building) Agreement

If VALID, extract the following information and return ONLY a valid JSON object:
{{
    "valid": true,
    "party1": "{party1_label} name (extract from prompt, or use 'Landowner' if not specified)",
    "party2": "{party2_label} name (extract from prompt, or use 'Developer' if not specified)",
    "start_date": "Agreement date in YYYY-MM-DD format (extract from prompt if mentioned, else empty string '')",
    "signature_date": "Signature/execution date in YYYY-MM-DD format (extract from prompt if mentioned, else empty string)",
    "party1_contact_name": "",
    "party1_contact_title": "",
    "party2_contact_name": "",
    "party2_contact_title": "",
    "sections": {sections_json}
}}

If INVALID, return:
{{
    "valid": false,
    "error": "Brief explanation of why the prompt is invalid"
}}

Return ONLY the JSON object."""
    
    def _build_standard_extraction_prompt(self, user_prompt, contract_type, party1_label, party2_label, sections_json, today_date):
        """Build extraction prompt for standard contracts"""
        return f"""You are a contract information extractor and validator. Your task is to:
1. FIRST: Validate if the user prompt is relevant for generating a {contract_type.replace('_', ' ').title()}
2. SECOND: If valid, extract all relevant information needed to generate the contract
3. THIRD: For ANY missing or unspecified information, use placeholder format: (_____________)

User Prompt:
{user_prompt}

VALIDATION RULES:
1. The prompt MUST be related to creating a {contract_type.replace('_', ' ').title()}
2. The prompt MUST mention or imply at least one party
3. The prompt MUST contain business/legal context
4. REJECT if completely irrelevant, too vague, or contains inappropriate content
5. REJECT if any financial amount is negative (e.g., -$500, -50 USD)

PLACEHOLDER RULES:
- If party name is not specified, use "(_____________)" as placeholder
- If any detail is missing (address, amount, duration, etc.), include "(_____________)" in that field
- Example: "Payment of $(_____________) to be made within (_____________) days"

If VALID, extract the following information and return ONLY a valid JSON object:
{{
    "valid": true,
    "party1": "{party1_label} name (extract from prompt, or use '(_____________)' if not specified)",
    "party2": "{party2_label} name (extract from prompt, or use '(_____________)' if not specified)",
    "start_date": "Start date in YYYY-MM-DD format (extract from prompt if mentioned, else empty string '')",
    "signature_date": "Signature/execution date in YYYY-MM-DD format (extract from prompt if mentioned, else empty string)",
    "party1_contact_name": "Contact person name for {party1_label} (if mentioned, else empty string)",
    "party1_contact_title": "Title/position for {party1_label} contact (if mentioned, else empty string)",
    "party2_contact_name": "Contact person name for {party2_label} (if mentioned, else empty string)",
    "party2_contact_title": "Title/position for {party2_label} contact (if mentioned, else empty string)",
    "sections": {sections_json}
}}

If INVALID, return:
{{
    "valid": false,
    "error": "Brief explanation of why the prompt is invalid"
}}

Return ONLY the JSON object."""
    
    def _call_openai(self, prompt, system_messages=None):
        """Call OpenAI API with optional system messages"""
        try:
            import openai
        except ImportError:
            return None, "OpenAI Python package not installed. Please run: pip install openai"
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        
        # Build messages list
        messages = []
        if system_messages:
            messages.extend(system_messages)
        messages.append({"role": "user", "content": prompt})
        
        try:
            try:
                client = openai.OpenAI(api_key=openai_api_key)
                completion = client.chat.completions.create(
                    model=openai_model,
                    messages=messages,
                    temperature=0
                )
                result = completion.choices[0].message.content
            except AttributeError:
                openai.api_key = openai_api_key
                completion = openai.ChatCompletion.create(
                    model=openai_model,
                    messages=messages,
                    temperature=0
                )
                result = completion.choices[0].message["content"]
            return result, None
        except Exception as e:
            return None, f"Error calling OpenAI API: {str(e)}"
    
    def _stream_openai(self, prompt, contract_type="service_agreement", additional_system_messages=None):
        """Stream OpenAI API responses with optional additional system messages"""
        try:
            import openai
        except ImportError:
            yield json.dumps({"error": "OpenAI Python package not installed. Please run: pip install openai"})
            return
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        
        if not openai_api_key:
            yield json.dumps({"error": "OpenAI API key is not configured. Please set OPENAI_API_KEY in your .env file."})
            return
        
        # Add system messages for contract generation
        messages = []
        
        # Add any additional system messages passed (e.g., for translation)
        if additional_system_messages:
            messages.extend(additional_system_messages)
        
        # Critical system message for ALL contract types (only for contract generation, not translation)
        if not additional_system_messages:  # Only add contract-specific messages if no custom messages provided
            messages.append({
                "role": "system",
                "content": """CRITICAL RULES FOR ALL CONTRACT GENERATION:
1. LANGUAGE: Generate the ENTIRE contract in PROFESSIONAL ENGLISH ONLY. Even if user provides Bengali/Hindi/mixed language requirements, translate EVERYTHING to English. No mixed languages allowed.
2. GOVERNING LAW URLs: In the "GOVERNING LAW AND JURISDICTION" section, EVERY citation MUST have clickable HTML anchor tags with REAL URLs. Format: [<a href="ACTUAL_URL" target="_blank">Source: Act Name</a>]. NEVER write plain text citations like "[Source: Act Name]" - this is FORBIDDEN."""
            })
            
            # Additional system message for NDA contracts to emphasize placeholder rule
            if contract_type == "nda":
                messages.append({
                    "role": "system",
                    "content": "You are generating an NDA contract. CRITICAL RULE: If the user requirements do NOT explicitly mention a duration (like '5 years', '3 years', etc.), you MUST use '(_____________) years' placeholder in the TIME PERIODS section. NEVER invent default durations. This is your PRIMARY obligation."
                })
        
        messages.append({"role": "user", "content": prompt})
        
        try:
            client = openai.OpenAI(api_key=openai_api_key)
            stream = client.chat.completions.create(
                model=openai_model,
                messages=messages,
                temperature=0,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    yield json.dumps({"chunk": content})
            
            yield json.dumps({"done": True})
        except Exception as e:
            yield json.dumps({"error": f"Error calling OpenAI API: {str(e)}"})
    
    def generate_contract_content(self, party1, party2, start_date, sections_data, user_prompt=None, 
                                  supplementary_text=None, template_text=None, contract_type="service_agreement", 
                                  jurisdiction="bangladesh"):
        """Generate contract content using AI"""
        from apps.contracts.contract_config import get_contract_config
        from core.jurisdiction_rules import get_jurisdiction_rules
        
        config = get_contract_config(contract_type)
        contract_type_name = contract_type.replace('_', ' ').title()
        party1_label = config.get('party1_label', 'Party 1')
        party2_label = config.get('party2_label', 'Party 2')
        sections = config.get('sections', [])
        section_descriptions = config.get('section_descriptions', {})
        
        has_template = template_text and template_text.strip() and len(template_text.strip()) > 50
        
        jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
        jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
        
        if contract_type == "sop":
            consolidated_prompt = self._build_sop_generation_prompt(
                party1, party2, start_date, sections_data, user_prompt, supplementary_text, 
                template_text, has_template, sections, section_descriptions, 
                party1_label, party2_label, jurisdiction_name
            )
        else:
            jurisdiction_instructions = self._build_jurisdiction_instructions(
                jurisdiction_rules, jurisdiction_name, party1_label, party2_label
            )
            consolidated_prompt = self._build_contract_generation_prompt(
                party1, party2, start_date, sections_data, user_prompt, supplementary_text,
                template_text, has_template, contract_type, contract_type_name, sections, 
                section_descriptions, party1_label, party2_label, jurisdiction_name, 
                jurisdiction_instructions
            )
        
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                return None, "OpenAI API key is not configured. Please set OPENAI_API_KEY in your .env file."
            
            # Build system messages for contract generation
            system_messages = []
            
            # Critical system message for ALL contract types
            system_messages.append({
                "role": "system",
                "content": """CRITICAL RULES FOR ALL CONTRACT GENERATION:
1. LANGUAGE: Generate the ENTIRE contract in PROFESSIONAL ENGLISH ONLY. Even if user provides Bengali/Hindi/mixed language requirements, translate EVERYTHING to English. No mixed languages allowed.
2. GOVERNING LAW URLs: In the "GOVERNING LAW AND JURISDICTION" section, EVERY citation MUST have clickable HTML anchor tags with REAL URLs. Format: [<a href="ACTUAL_URL" target="_blank">Source: Act Name</a>]. NEVER write plain text citations like "[Source: Act Name]" - this is FORBIDDEN."""
            })
            
            # Additional system message for NDA contracts to emphasize placeholder rule
            if contract_type == "nda":
                system_messages.append({
                    "role": "system",
                    "content": "You are generating an NDA contract. CRITICAL RULE: If the user requirements do NOT explicitly mention a duration (like '5 years', '3 years', etc.), you MUST use '(_____________) years' placeholder in the TIME PERIODS section. NEVER invent default durations. This is your PRIMARY obligation."
                })
            
            result, error = self._call_openai(consolidated_prompt, system_messages=system_messages)
            if error:
                return None, error
            
            return result, None
        except Exception as e:
            return None, f"Error generating contract: {str(e)}"
    
    def stream_contract_content(self, party1, party2, start_date, sections_data, user_prompt=None, 
                               supplementary_text=None, template_text=None, contract_type="service_agreement", 
                               jurisdiction="bangladesh"):
        """Stream contract content generation using AI"""
        from apps.contracts.contract_config import get_contract_config
        from core.jurisdiction_rules import get_jurisdiction_rules
        
        config = get_contract_config(contract_type)
        contract_type_name = contract_type.replace('_', ' ').title()
        party1_label = config.get('party1_label', 'Party 1')
        party2_label = config.get('party2_label', 'Party 2')
        sections = config.get('sections', [])
        section_descriptions = config.get('section_descriptions', {})
        
        has_template = template_text and template_text.strip() and len(template_text.strip()) > 50
        
        jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
        jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
        
        if contract_type == "sop":
            consolidated_prompt = self._build_sop_generation_prompt(
                party1, party2, start_date, sections_data, user_prompt, supplementary_text, 
                template_text, has_template, sections, section_descriptions, 
                party1_label, party2_label, jurisdiction_name
            )
        else:
            jurisdiction_instructions = self._build_jurisdiction_instructions(
                jurisdiction_rules, jurisdiction_name, party1_label, party2_label
            )
            consolidated_prompt = self._build_contract_generation_prompt(
                party1, party2, start_date, sections_data, user_prompt, supplementary_text,
                template_text, has_template, contract_type, contract_type_name, sections, 
                section_descriptions, party1_label, party2_label, jurisdiction_name, 
                jurisdiction_instructions
            )
        
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                yield json.dumps({"error": "OpenAI API key is not configured. Please set OPENAI_API_KEY in your .env file."})
                return
            
            for chunk in self._stream_openai(consolidated_prompt, contract_type=contract_type):
                yield chunk
        except Exception as e:
            yield json.dumps({"error": f"Error generating contract: {str(e)}"})
    
    def _build_sop_generation_prompt(self, party1, party2, start_date, sections_data, user_prompt, 
                                     supplementary_text, template_text, has_template, sections, 
                                     section_descriptions, party1_label, party2_label, jurisdiction_name):
        """Build SOP generation prompt"""
        formatted_sections = self._format_sections_for_prompt(
            sections, section_descriptions, party1, party2, party1_label, party2_label, start_date, "sop"
        )
        
        base_prompt = f"""You are an expert academic writing consultant specializing in Statement of Purpose / Motivation Letter / Personal Statement.

APPLICANT INFORMATION:
- Applicant: {party1}
- Institution/Program: {party2}
- Application Date: {start_date.strftime('%B %d, %Y') if hasattr(start_date, 'strftime') else start_date}
- Context: {jurisdiction_name}

USER REQUIREMENTS:
{user_prompt or 'Not specified'}

SECTION DETAILS:
{json.dumps(sections_data, indent=2)}

ADDITIONAL CONTEXT (from Supplementary File):
{supplementary_text or 'None provided'}

REQUIRED SECTIONS:
{formatted_sections}

INSTRUCTIONS:
1. Write in FIRST PERSON ("I", "my", "me")
2. Use flowing paragraphs, not bullet points
3. Be authentic and specific
4. Use markdown ## for section headers
5. Do NOT include title or signature blocks
6. Start directly with: ## INTRODUCTION

Generate the SOP now."""
        
        if has_template:
            base_prompt = f"""You are an expert academic writing consultant. The user has provided a TEMPLATE DOCUMENT that you MUST use as the PRIMARY reference.

=== TEMPLATE DOCUMENT (FOLLOW THIS CLOSELY) ===
{template_text}
=== END OF TEMPLATE ===

{base_prompt}"""
        
        return base_prompt
    
    def _build_contract_generation_prompt(self, party1, party2, start_date, sections_data, user_prompt,
                                          supplementary_text, template_text, has_template, contract_type,
                                          contract_type_name, sections, section_descriptions, 
                                          party1_label, party2_label, jurisdiction_name, jurisdiction_instructions):
        """Build contract generation prompt"""
        formatted_sections = self._format_sections_for_prompt(
            sections, section_descriptions, party1, party2, party1_label, party2_label, start_date, contract_type
        )
        
        # Format date - use placeholder if not provided
        if hasattr(start_date, 'strftime'):
            date_str = start_date.strftime('%B %d, %Y')
        else:
            date_str = str(start_date) if start_date else '(_____________)'
        
        # Special handling for developer_agreement to detect specific type
        developer_type_instruction = ""
        if contract_type == "developer_agreement":
            developer_type_instruction = """
CRITICAL - DEVELOPER AGREEMENT TYPE DETECTION:
Based on the USER REQUIREMENTS below, you MUST determine which specific agreement type is needed and generate the appropriate contract:

1. **Developer (Construct Building) Agreement**: Simple construction where developer builds for landowner (no sharing model mentioned)
2. **Joint Development Agreement (JDA)**: Fixed area/flat sharing model (e.g., "30% to landowner", "40% flats", "area sharing")
3. **Revenue/Profit Sharing Agreement**: Percentage-based revenue or profit sharing (e.g., "35% revenue", "profit sharing", "sales percentage")
4. **Land Sharing/Contribution Agreement**: Specific flats/units allocation (e.g., "specific flats", "unit allocation", "flat numbers")
5. **Joint Venture (JV) Agreement**: Separate company/entity formation (e.g., "joint venture", "JV company", "separate entity")

ANALYZE the user requirements and generate the contract that matches the detected agreement type. Include appropriate sections, clauses, and structure for that specific type."""
        
        # Special handling for NDA contracts
        nda_type_instruction = ""
        if contract_type == "nda":
            nda_type_instruction = """
⚠️ CRITICAL - NDA (NON-DISCLOSURE AGREEMENT) SPECIFIC FORMATTING RULES:

**1. DURATION / TIME PERIODS SECTION - ABSOLUTE MANDATORY PLACEHOLDER RULE:**
   - **⚠️ THIS IS THE MOST CRITICAL RULE FOR NDA CONTRACTS - APPLIES TO ALL DURATION MENTIONS**
   - This section determines how long confidentiality obligations last
   - You MUST analyze the user requirements WORD BY WORD to check if duration is mentioned
   - **CRITICAL: This rule applies to BOTH "DURATION OF CONFIDENTIALITY" and "TIME PERIODS" section names**
   
   **STEP 1: Analyze User Requirements for Duration Keywords:**
   - Look for: "years", "months", "duration", "period", "time", "৫ বছর", "3 years", "2 বছরের", etc.
   - Check entire user prompt including Bengali/Banglish text
   
   **STEP 2: Apply Correct Rule Based on Analysis:**
   
   **IF DURATION IS MENTIONED (Keywords found):**
   - Extract the exact duration value
   - Convert to legal format: "five (5) years" or "three (3) years" or "two (2) years"
   - Example: User says "5 years NDA" → "The obligations of confidentiality shall remain in effect for a period of five (5) years from the date of disclosure."
   
   **IF DURATION IS NOT MENTIONED (No keywords found):**
   - YOU ABSOLUTELY MUST USE: "(_____________)" placeholder for ALL duration references
   - ⚠️ FORBIDDEN VALUES: "5 years", "3 years", "2 years", "five (5) years", "three (3) years"
   - Example: User says "NDA between Company A and Company B" (no duration mentioned) → "The obligations of confidentiality shall remain in effect for a period of (_____________) years from the date of disclosure."
   
   **TIME PERIODS SECTION - COMPREHENSIVE FORMAT WITH PLACEHOLDER:**
   When duration is NOT mentioned, use this exact format:
   ```
   ## TIME PERIODS
   
   The obligations of confidentiality shall remain in effect for a period of (_____________) years from the date of disclosure. The nondisclosure provisions shall survive the termination of this Agreement. The duty to hold the Confidential Information in confidence shall remain until the information no longer qualifies as a trade secret or until written release by the Discloser, whichever occurs first.
   ```
   
   When duration IS mentioned (e.g., "5 years"), use this format:
   ```
   ## TIME PERIODS
   
   The obligations of confidentiality shall remain in effect for a period of five (5) years from the date of disclosure. The nondisclosure provisions shall survive the termination of this Agreement. The duty to hold the Confidential Information in confidence shall remain until the information no longer qualifies as a trade secret or until written release by the Discloser, whichever occurs first.
   ```
   
   **MUST INCLUDE in TIME PERIODS section:**
   - Duration of confidentiality (with placeholder if not specified)
   - Survival clause: "The nondisclosure provisions shall survive the termination of this Agreement"
   - Trade secret clause: "The duty to hold the Confidential Information in confidence shall remain until the information no longer qualifies as a trade secret or until written release by the Discloser, whichever occurs first"
   
   **VERIFICATION CHECKLIST (Check before generating):**
   ☑ Did I read the entire user requirements?
   ☑ Did I search for duration keywords (years/months/period/time)?
   ☑ Did I find ANY duration mentioned? (YES/NO)
   ☑ If NO, did I use "(_____________) years" placeholder in TIME PERIODS section? (MUST BE YES)
   ☑ If YES, did I use the exact duration mentioned? (MUST BE YES)
   ☑ Did I include survival clause?
   ☑ Did I include trade secret clause?
   
   **WRONG Examples (DO NOT GENERATE THESE):**
   ❌ User prompt: "NDA between TechCorp and StartupXYZ" (no duration mentioned)
   ❌ Generated TIME PERIODS: "...for a period of five (5) years from the date of disclosure."
   ❌ PROBLEM: User did NOT mention "5 years" - this is WRONG! MUST use "(_____________) years"
   
   ❌ User prompt: "Create NDA for confidential information sharing" (no duration mentioned)
   ❌ Generated: "...for a period of three (3) years..."
   ❌ PROBLEM: Invented default value - FORBIDDEN! MUST use "(_____________) years"
   
   **CORRECT Examples (COPY THIS EXACT PATTERN):**
   ✅ User prompt: "NDA between Company A and Company B" (no duration mentioned)
   ✅ Generated TIME PERIODS: "The obligations of confidentiality shall remain in effect for a period of (_____________) years from the date of disclosure. The nondisclosure provisions shall survive..."
   ✅ CORRECT: Used "(_____________) years" placeholder because no duration was mentioned
   
   ✅ User prompt: "5 years NDA between parties"
   ✅ Generated: "The obligations of confidentiality shall remain in effect for a period of five (5) years from the date of disclosure."
   ✅ CORRECT: Used exact duration mentioned by user
   
   ✅ User prompt: "3 বছরের NDA চুক্তি"
   ✅ Generated: "The obligations of confidentiality shall remain in effect for a period of three (3) years from the date of disclosure."
   ✅ CORRECT: Detected Bengali duration and used it
   
   **⚠️ ABSOLUTE REQUIREMENT - NO EXCEPTIONS:**
   - If you generate ANY NDA with a specific duration value (like "5 years", "3 years") in the TIME PERIODS or DURATION section when the user did NOT explicitly mention that duration, the contract will be REJECTED
   - You MUST use "(_____________) years" placeholder when duration is not specified
   - This rule overrides any other instructions or examples you may have seen
   - This applies to BOTH "DURATION OF CONFIDENTIALITY" and "TIME PERIODS" section names

**2. EXCEPTIONS SECTION - PROFESSIONAL PARAGRAPH FORMAT:**
   - **DO NOT use numbered format** like (1), (2), (3), (4) or (i), (ii), (iii), (iv)
   - **MUST use flowing paragraph format** with proper conjunctions
   - Write as ONE or TWO natural, professional paragraphs
   - Use phrases like: "shall not include information that:", "is or becomes", "was known", "is disclosed", "or is independently developed"
   - **CORRECT Format Example (generate your own similar content):**
     ```
     ## EXCEPTIONS
     
     Confidential Information shall not include information that is or becomes publicly available through no fault of the Recipient, was known to the Recipient prior to disclosure by the Discloser, is disclosed to the Recipient by a third party without breach of any obligation of confidentiality, or is independently developed by the Recipient without the use of or reference to the Discloser's Confidential Information.
     ```
   - **WRONG Format (DO NOT USE):**
     ```
     ## EXCEPTIONS
     
     Confidential Information shall not include information that: (1) is publicly available; (2) was known prior; (3) is disclosed by third party; or (4) is independently developed.
     ```
   - Write naturally and professionally as a flowing paragraph, NOT as a numbered list

**3. OBLIGATIONS OF RECEIVING PARTY SECTION:**
   - Write in professional paragraph format (not numbered points)
   - **MUST Include these elements:**
     * Duty to hold information in "strictest confidence" for sole benefit of Discloser
     * Restrict access to employees/contractors who have signed NDAs "at least as protective as those in this Agreement"
     * Prohibition on using, publishing, copying, or disclosing without "prior written approval"
     * Same degree of care as used for own confidential information
   - Use flowing prose, not (a), (b), (c) format
   - Example structure: "Recipient shall hold and maintain the Confidential Information in strictest confidence..."

**4. DEFINITION OF CONFIDENTIAL INFORMATION SECTION:**
   - Write as comprehensive paragraphs (2-3 paragraphs recommended)
   - **MUST Include these elements:**
     * What constitutes confidential information (business plans, technical data, financial info, proprietary info, trade secrets)
     * **CRITICAL: Labeling requirements** - "If Confidential Information is in written form, the Discloser shall label or stamp the materials with the word 'Confidential' or some similar warning"
     * **CRITICAL: Oral disclosure confirmation** - "If Confidential Information is transmitted orally, the Discloser shall promptly provide writing indicating that such oral communication constituted Confidential Information"
     * Commercial value clause
   - Use phrases like "including but not limited to" within the paragraph
   - Example: "For purposes of this Agreement, 'Confidential Information' shall include all information or material that has or could have commercial value..."

**5. RETURN OF MATERIALS SECTION:**
   - Write as professional paragraph (can be combined with Obligations section or separate)
   - **MUST Include:**
     * "Upon written request" or "immediately if Discloser requests it in writing"
     * Return ALL records, notes, written, printed, or tangible materials
     * Can include destruction certification requirement
   - Example: "Recipient shall return to Discloser any and all records, notes, and other written, printed, or tangible materials in its possession pertaining to Confidential Information immediately if Discloser requests it in writing."

**6. RELATIONSHIPS SECTION:**
   - Write as short, clear paragraph
   - **MUST State:** This Agreement does NOT create partnership, joint venture, or employment relationship
   - Example: "Nothing contained in this Agreement shall be deemed to constitute either party a partner, joint venture or employee of the other party for any purpose."

**7. NOTICE OF IMMUNITY SECTION (Trade Secret Protection):**
   - Write as detailed paragraph or sub-section
   - **MUST Include (if jurisdiction supports trade secret laws):**
     * Notice that individual NOT held criminally/civilly liable for trade secret disclosure made:
       - In confidence to government official or attorney for reporting suspected law violation
       - In sealed court filings
     * Whistleblower protection provisions
     * Retaliation lawsuit protections
   - Use legal language: "Employee is provided notice that an individual shall not be held criminally or civilly liable under any federal or state trade secret law..."
   - Note: Include this section especially for employee NDAs or if jurisdiction has trade secret protection laws

**8. REMEDIES FOR BREACH SECTION:**
   - Write in paragraph format
   - Include: injunctive relief (immediate court orders), monetary damages, legal costs and attorney fees, return of materials
   - Use flowing prose connecting all remedies naturally

**9. GENERAL PROVISIONS SECTION (NDA-Specific):**
   - **MUST Include these sub-sections with sub-headers on NEW LINES:**
     * **Severability**: If any provision invalid, remainder remains effective
     * **Integration** (Entire Agreement): Complete understanding, supersedes all prior agreements, amendments must be in writing signed by both parties
     * **Waiver**: Failure to exercise rights not a waiver of prior or subsequent rights
     * **Assignment and Successors**: Agreement binding on representatives, assigns, and successors
     * **Notices**: How parties communicate (if applicable)
   - Each sub-section should be separate paragraph with bold sub-header on new line

**10. GOVERNING LAW AND JURISDICTION SECTION (NDA-Specific):**
   - **CRITICAL: For NDA contracts, this section MUST be simpler with clear paragraph format**
   - **MUST Include with HTML anchor tags for clickable URLs:**
     * Governing Law clause with clickable link
     * Jurisdiction clause with clickable link
     * Stamp Duty clause with clickable link (if applicable)
     * Registration clause with clickable link (if applicable)
   
   **NDA FORMAT - Use sub-headers on NEW LINES:**
   ```
   ## GOVERNING LAW AND JURISDICTION
   
   **Governing Law**
   
   This Agreement shall be governed by and construed in accordance with the laws of Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-367.html" target="_blank">Source: Contract Act 1872</a>]
   
   **Jurisdiction**
   
   Any dispute arising out of or relating to this Agreement shall be subject to the exclusive jurisdiction of the courts of Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-86.html" target="_blank">Source: Code of Civil Procedure 1908</a>]
   
   **Stamp Duty**
   
   This Agreement shall be executed on non-judicial stamp paper of appropriate value as per the Stamp Act of Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-24.html" target="_blank">Source: Stamp Act 1899</a>]
   
   **Registration**
   
   This Agreement shall be registered with the appropriate Sub-Registrar's Office in Bangladesh as required under the Registration Act, 1908. [<a href="http://bdlaws.minlaw.gov.bd/act-87.html" target="_blank">Source: Registration Act 1908</a>]
   ```
   
   **CRITICAL REQUIREMENTS:**
   - Use sub-headers: **Governing Law**, **Jurisdiction**, **Stamp Duty**, **Registration**, etc.
   - Each sub-section on NEW LINE with bold header
   - ONE paragraph per sub-section (clean and concise)
   - EVERY citation MUST have HTML anchor tag: `[<a href="URL" target="_blank">Source: Act Name</a>]`
   - ❌ NEVER use plain text citations like `[Source: Act Name]` - MUST have clickable URL
   - Keep each clause short and focused - avoid long run-on sentences
   - Do NOT combine multiple laws in one paragraph

⚠️ REMEMBER FOR NDA CONTRACTS:
- Duration placeholder rule is MANDATORY - DO NOT invent default durations
- NO numbered formats in Exceptions/Exclusions section - MUST be paragraph format
- MUST include labeling requirements for written and oral confidential information
- MUST include Relationships clause (no partnership/joint venture)
- MUST include Notice of Immunity if applicable for jurisdiction
- GOVERNING LAW section MUST use sub-headers with clean paragraph format
- EVERY legal citation MUST have clickable HTML anchor tag with real URL
- All sections should maintain professional flowing paragraph style
"""
        
        # Add special emphasis for NDA contracts at the very beginning
        nda_warning = ""
        if contract_type == "nda":
            nda_warning = """
CRITICAL WARNING FOR NDA (NON-DISCLOSURE AGREEMENT)

STEP 0: PRE-GENERATION ANALYSIS (DO THIS FIRST BEFORE GENERATING ANYTHING)

BEFORE YOU WRITE A SINGLE WORD OF THE CONTRACT, ANALYZE THE USER REQUIREMENTS:

**DURATION ANALYSIS (MANDATORY FIRST STEP):**
1. Read the user requirements below carefully word-by-word
2. Search for these keywords: "year", "years", "month", "months", "duration", "period", "time", "বছর", "মাস"
3. Ask yourself: "Did the user mention ANY duration/time period?"
4. If YES → Note the exact duration (e.g., "5 years", "3 months", "2 বছর")
5. If NO → You MUST use "(_____________) years" placeholder in TIME PERIODS section

**YOUR ANALYSIS RESULT:**
- Duration mentioned? [YES/NO]
- If YES, what duration? [Write exact value]
- If NO, what will you use? [MUST write: "(_____________) years"]

**CRITICAL RULE:**
- The DEFAULT answer is "(_____________) years" - ONLY change this if user EXPLICITLY mentions a duration
- If you cannot find clear duration keywords in user requirements, use "(_____________) years"
- When in doubt, use "(_____________) years"

ACTUAL GENERATION STARTS BELOW - REMEMBER YOUR ANALYSIS RESULT

**TIME PERIODS / DURATION SECTION - ABSOLUTE MANDATORY RULE:**
- You MUST check if the user mentioned a duration (years/months/period) in their requirements
- IF user DID NOT mention duration → USE "(_____________) years" placeholder
- IF user mentioned duration → USE that exact duration
- ⚠️ NEVER EVER use default values like "5 years", "3 years", "2 years" unless user explicitly said so
- This applies to BOTH "TIME PERIODS" and "DURATION OF CONFIDENTIALITY" section names
- This rule is NON-NEGOTIABLE and overrides everything else

**EXAMPLES TO FOLLOW EXACTLY:**
❌ User: "NDA between Company A and B" (no duration) → Generated TIME PERIODS: "five (5) years" → WRONG! REJECTED!
✅ User: "NDA between Company A and B" (no duration) → Generated TIME PERIODS: "(_____________) years" → CORRECT!
✅ User: "5 years NDA" → Generated: "five (5) years" → CORRECT!

**TIME PERIODS SECTION MUST INCLUDE:**
1. Duration with placeholder if not specified: "(_____________) years"
2. Survival clause: "The nondisclosure provisions shall survive the termination of this Agreement"
3. Trade secret clause: "shall remain until information no longer qualifies as trade secret or until written release"

**GOVERNING LAW AND JURISDICTION - FORMATTING RULE:**
- MUST use sub-headers: **Governing Law**, **Jurisdiction**, **Stamp Duty**, **Registration**
- Each sub-section on NEW LINE with bold header
- ONE clean paragraph per sub-section
- EVERY citation MUST have clickable URL: [<a href="URL" target="_blank">Source: Act Name</a>]
- ❌ NEVER use plain text: [Source: Act Name] - MUST have <a href="URL">

**VERIFICATION BEFORE GENERATING:**
☑ I have read the user requirements completely
☑ I have searched for duration keywords (years/months/period)
☑ If no duration found → I will use "(_____________)" placeholder
☑ If duration found → I will use that exact value

END OF CRITICAL WARNING

"""
        
        base_prompt = f"""{nda_warning}You are an expert legal contract writer specializing in {contract_type_name} under {jurisdiction_name} law. You draft comprehensive, professional, and legally sound contracts suitable for execution between parties.

CRITICAL - CONTENT RELEVANCE AND STANDARDIZATION:
- Generate RELEVANT content that is appropriate and standard for a {contract_type_name}
- Use industry-standard legal terminology, clauses, and structures for this contract type
- Ensure ALL clauses and sections are standard, legally recognized, and appropriate for this specific contract type
- Follow best practices and conventional legal standards for {contract_type_name}
- Generate content that is consistent with how professional {contract_type_name} contracts are typically structured
- Ensure all legal clauses are relevant, standard, and appropriate for the contract type and jurisdiction
- DO NOT include irrelevant clauses or content that does not belong in a {contract_type_name}
- Use standard legal language and structures that are commonly found in professionally drafted {contract_type_name} contracts

IMPORTANT - LANGUAGE HANDLING (CRITICAL - READ CAREFULLY):
- The user may provide requirements in ANY language (English, Bengali, Banglish, Hindi, mixed languages, or any other language)
- You MUST analyze and understand the requirements regardless of input language
- ⚠️ **CRITICAL: You MUST ALWAYS generate the ENTIRE contract in PROFESSIONAL ENGLISH ONLY**
- **NO MIXING OF LANGUAGES**: Even if user provides Bengali/Hindi/mixed text, translate EVERYTHING to English
- Extract all key information (names, amounts, dates, terms, conditions, descriptions, services, deliverables) from the input and convert to proper English
- **Examples:**
  * User writes: "Facebook বিজ্ঞাপন ব্যবস্থাপনা" → You write: "Facebook advertising management"
  * User writes: "প্রচার কার্যক্রমের উপর নিয়মিত আপডেট" → You write: "Regular updates on campaign activities"
  * User writes: "চূড়ান্ত রিপোর্ট জমা" → You write: "Final report submission"
- **ABSOLUTE RULE**: The final contract document must be 100% in English - no Bengali, Hindi, or other language text should appear anywhere except in party names/addresses if provided that way

{developer_type_instruction}

{nda_type_instruction}

{jurisdiction_instructions}

PARTIES INFORMATION:
- {party1_label}: {party1}
- {party2_label}: {party2}
- Effective Date: {date_str}

USER REQUIREMENTS (may be in any language - analyze and extract information):
{user_prompt or 'Not specified'}

SECTION DETAILS:
{json.dumps(sections_data, indent=2)}

ADDITIONAL CONTEXT (from Supplementary File):
{supplementary_text or 'None provided'}

REQUIRED SECTIONS:
{formatted_sections}

PROFESSIONAL CONTRACT WRITING STANDARDS:
1. **Simple and Clear Language**: Use simple, clear, and standard legal terminology that is easy to understand. Avoid overly complex, archaic, or unnecessarily sophisticated legal jargon. Use common, standard words that are widely recognized in professional contracts. Keep the language professional but accessible.
2. **Formal Legal Language**: Use precise, formal legal terminology. Avoid casual language or abbreviations.
3. **Comprehensive Clauses**: Each section should be detailed with multiple sub-clauses where appropriate. Use numbered sub-clauses (1., 2., 3.) within sections for clarity.
4. **Specificity**: Be specific and detailed. Instead of vague terms, provide clear definitions and specifications.
5. **Professional Structure**: 
   - Use ## for main section headers
   - Use ### for sub-sections
   - Use numbered lists (1., 2., 3.) for sequential items
   - Use bullet points (-) only for non-sequential lists
6. **Complete Information**: Include all relevant details such as:
   - Specific deliverables with acceptance criteria
   - Detailed payment schedules with exact amounts and dates
   - Clear timelines with milestones
   - Comprehensive service descriptions
   - Quality standards and performance metrics
7. **Placeholder Usage - CRITICAL RULE**: 
   - **IF INFORMATION IS PROVIDED IN USER REQUIREMENTS**: Use the exact values mentioned by the user. Do NOT use placeholders for information that is explicitly provided.
   - **IF INFORMATION IS MISSING/NOT SPECIFIED**: You MUST use placeholder: (_____________)
   
   **⚠️ CRITICAL WARNING - ABSOLUTELY DO NOT INVENT DEFAULT VALUES:**
   - NEVER use "30 days", "60 days", "90 days" for termination notice periods UNLESS USER EXPLICITLY MENTIONS THEM
   - NEVER use "5 years", "3 years", "2 years" for confidentiality duration UNLESS USER EXPLICITLY MENTIONS THEM
   - NEVER use "30 days", "15 days", "7 days" for cure periods UNLESS USER EXPLICITLY MENTIONS THEM
   - NEVER assume any time periods, durations, or numeric values
   - IF NOT EXPLICITLY STATED IN USER REQUIREMENTS → MUST USE (_____________) PLACEHOLDER
   - ONLY use specific numeric values when USER REQUIREMENTS EXPLICITLY STATE THEM IN CLEAR WORDS
   
   - **NEVER make up or invent values** - if information is not provided in user requirements, use (_____________)
   - **NEVER use generic defaults** like "30 days", "5 years", "$1000" unless explicitly mentioned in user requirements
   - **ALWAYS use (_____________) ONLY for missing/unspecified information:**
     * Termination notice periods: If user specifies "30 days", use "30 days". If NOT specified, use "upon (_____________) days' written notice"
     * Duration periods: If user specifies "5 years", use "5 years". If NOT specified, use "for a period of (_____________) years"
     * Payment amounts: If user specifies "$25,000", use "$25,000". If NOT specified, use "payment of $(_____________)"
     * Percentages: If user specifies a percentage, use it. If NOT specified, use "(_____________)%"
     * Dates: If user specifies dates, use them. If NOT specified, use "by (_____________)"
     * Addresses: If user specifies address, use it. If NOT specified, use "located at (_____________)"
     * Names/Entities: If user specifies names, use them. If NOT specified, use "(_____________)"
     * Quantities/Numbers: If user specifies numbers, use them. If NOT specified, use "(_____________)"
   - Example CORRECT usage:
     * If user says "30 days notice": "Either Party may terminate this Agreement for any reason upon thirty (30) days' written notice"
     * If user does NOT specify days: "Either Party may terminate this Agreement for any reason upon (_____________) days' written notice"
     * If user says "5 years confidentiality": "The obligations of confidentiality shall survive for a period of five (5) years"
     * If user does NOT specify duration: "The obligations of confidentiality shall survive for a period of (_____________) years"
   - DO NOT use generic placeholders like [Address], [Amount], [Date] - ALWAYS use (_____________) format
   - DO NOT assume or generate default values - ONLY use (_____________) when information is truly missing from user requirements
8. **Legal Precision**: Use terms like "shall" (not "will"), "herein", "thereof", "pursuant to", "in accordance with"
9. **Completeness**: Ensure each section is comprehensive and covers all aspects that would be expected in a professional contract

CRITICAL FORMATTING REQUIREMENTS - FOLLOW EXACTLY:

1. **Section Headers (##)**: 
   - MUST be on its own line
   - MUST have ONE blank line BEFORE it
   - MUST have ONE blank line AFTER it before any content
   - NEVER put content on the same line as header
   - CORRECT FORMAT:
     ```
     ## SCOPE OF WORK
     
     The Service Provider, DevSolutions, shall provide services...
     ```
   - WRONG FORMAT (DO NOT DO THIS):
     ```
     ## SCOPE OF WORK
     The Service Provider shall... (NO - missing blank line)
     ```

2. **Lists (Numbered or Bullet)**:
   - MUST have ONE blank line BEFORE the list starts
   - MUST have ONE blank line AFTER the list ends
   - Each list item MUST be on a separate line
   - CORRECT FORMAT:
     ```
     The services shall include:
     
     1. Requirement analysis and gathering.
     2. Design and development of the mobile application.
     3. Testing and quality assurance.
     
     Additional terms apply...
     ```
   - WRONG FORMAT (DO NOT DO THIS):
     ```
     ## SCOPE OF WORK
     1. Requirement analysis... (NO - missing blank line after header)
     The services: 1. Analysis... (NO - list should be on separate lines)
     ```

3. **Paragraphs**:
   - Add ONE blank line between paragraphs
   - NEVER put paragraph text on the same line as a header
   - NEVER put list items immediately after a header without a blank line

4. **Complete Contract Structure - FULLY AI-GENERATED**:
   You MUST generate a COMPLETE, PROFESSIONAL, FULLY EXECUTABLE contract. Use your expertise to create all parts naturally, without hard-coded templates. The contract should include:

   a) **CONTRACT HEADER**:
      - Generate a professional contract title/header appropriate for {contract_type_name}
      - Include parties: {party1} ({party1_label}) and {party2} ({party2_label})
      - Include effective date: {date_str}
      - Make it clean, professional, and appropriate for {jurisdiction_name} legal standards
      
      **FOR NDA CONTRACTS - SPECIAL HEADER FORMAT:**
      If generating an NDA (Non-Disclosure Agreement), write the header as ONE SINGLE flowing paragraph (not multiple lines):
      
      "This Non-Disclosure Agreement (the "Agreement") is entered into on (_____________) by and between {party1}, with a mailing address at (_____________), as the party disclosing confidential information (hereinafter referred to as the "Disclosing Party" or "Discloser"), and {party2}, with a mailing address at (_____________), as the party receiving confidential information (hereinafter referred to as the "Receiving Party" or "Recipient"). For the purpose of preventing the unauthorized disclosure of Confidential Information as defined below, the parties agree to enter into a confidential relationship concerning the disclosure of certain proprietary and confidential information."
      
      **Key Requirements for NDA Header:**
      - MUST be ONE complete paragraph - NO line breaks between party information
      - Start with "This Non-Disclosure Agreement (the "Agreement")"
      - Use "as the party disclosing confidential information" and "as the party receiving confidential information"
      - Include both short forms: "Disclosing Party" or "Discloser" AND "Receiving Party" or "Recipient"
      - Include purpose statement at the end about confidential relationship
      - Keep formatting clean and professional - avoid complex symbols
      - Maintain formal legal tone throughout the single paragraph
      
      **FOR OTHER CONTRACTS - STANDARD FORMAT:**
      Write the header as ONE flowing paragraph following this template:
      
      "This {contract_type_name} **(the "Agreement")** is entered into on this (_____________) **(the "Effective Date")**, by and between {party1}, with a mailing address at (_____________) **(hereinafter referred to as the "{party1_label}")**, and {party2}, with a mailing address at (_____________) **(hereinafter referred to as the "{party2_label}")**, collectively referred to as the **"Parties"**, both of whom hereby agree to be bound by the terms and conditions of this Agreement."
      
      **Key Requirements:**
      - Must be ONE complete paragraph, not multiple lines
      - Use "the Agreement" in all cases
      - For date: If date is provided use it, otherwise use "(_____________)" placeholder
      - Always include "**(the "Effective Date")**" after the date/placeholder - the parenthetical part must be bold
      - Use "is entered into on this [date/placeholder]" format
      - Use "with a mailing address at" for both parties
      - For addresses: use "(_____________)" if not provided
      - CRITICAL: All text within parentheses () must be wrapped in bold markdown (**text**)
        * **(the "Agreement")** - bold
        * **(the "Effective Date")** - bold
        * **(hereinafter referred to as the "{party1_label}")** - bold
        * **(hereinafter referred to as the "{party2_label}")** - bold
        * **"Parties"** - bold (just the word Parties in quotes)
      - End with "both of whom hereby agree to be bound by the terms and conditions of this Agreement"
      - Maintain formal legal tone throughout
   
   b) **SERVICES SECTION**:
      - Generate a brief "SERVICES" section that describes what services the Service Provider will provide
      - Keep it concise (2-3 sentences) as an overview before detailed sections
      - Format: "## SERVICES" header followed by description
      - Example: "The Service Provider agrees to provide [describe services] to the Client in accordance with the terms and conditions set forth in this Agreement."
   
   c) **MAIN CONTENT SECTIONS**:
      - Generate all required sections from the REQUIRED SECTIONS list above
      - Use section headers (##) with proper formatting
      - Include all specific details from user requirements
      - Make each section comprehensive and detailed
      
      **SPECIAL FORMATTING FOR "SUPPORT & MAINTENANCE" SECTION:**
      - Generate in ONE SINGLE professional paragraph (not multiple paragraphs or bullet lists)
      - Include: support duration, types of support, response times, scope limitations
      - **⚠️ CRITICAL - Duration Placeholder Rule (MUST FOLLOW STRICTLY):** 
        * CAREFULLY READ user requirements word-by-word to check if support duration is mentioned
        * IF user requirements EXPLICITLY mention support duration with specific time period (e.g., "30 days support", "৩০ দিনের সাপোর্ট", "3 months support", "90 days free support"), ONLY THEN use that exact value
        * IF user requirements DO NOT mention any specific support duration, you MUST use "(_____________)" placeholder - DO NOT assume or invent any duration
        * ⚠️ DO NOT use default values like "30 days", "60 days", "90 days" unless EXPLICITLY stated in user requirements
        * Examples: 
          - User says "30 days support" or "৩০ দিনের সাপোর্ট" → use "thirty (30) days"
          - User does NOT mention duration → use "(_____________) days" or "(_____________)"
      - Generate based on user requirements - DO NOT copy this example
      - Format style (ONE PARAGRAPH - generate your own content):
        ## SUPPORT & MAINTENANCE
        
        [Write a single flowing paragraph. For duration: CHECK user requirements carefully - if support duration explicitly mentioned, use exact value; if NOT mentioned at all, MUST use (_____________) placeholder. Include types of support covered, response times, and scope limitations. Generate natural, relevant content - do not copy this example text.]
      
      **SPECIAL FORMATTING FOR "TIMELINE" SECTION:**
      - Generate in professional paragraph format based on user requirements
      - If specific dates and milestones are provided in user requirements, use them with full details
      - If dates/milestones are NOT provided, use placeholders with numbered list for milestones
      - Include: commencement date, completion date, key milestones, delay provisions
      - DO NOT copy these examples - generate your own content based on user requirements
      - Format style when dates ARE provided:
        ## TIMELINE
        
        [Write paragraph with actual dates from user requirements: commencement date, completion date, specific milestones with dates, and delay provisions.]
      - Format style when dates are NOT provided:
        ## TIMELINE
        
        The project shall commence on (_____________) and shall be completed by (_____________). The Service Provider shall adhere to the following milestones:
        
        1. (_____________)
        2. (_____________)
        3. (_____________)
        
        [Add sentence about delay provisions.]
      
      **SPECIAL FORMATTING FOR "INTELLECTUAL PROPERTY RIGHTS" SECTION:**
      - Generate in ONE SINGLE professional paragraph (not multiple paragraphs)
      - Include: ownership transfer, Service Provider retained rights (if any), Client usage rights, prior IP exclusions
      - Generate based on user requirements - DO NOT copy this example
      - Format style (ONE PARAGRAPH - generate your own content):
        ## INTELLECTUAL PROPERTY RIGHTS
        
        [Write a single flowing paragraph covering: ownership of deliverables/work product, when ownership transfers, Service Provider's retained rights (if any), Client's usage rights, and treatment of pre-existing IP. Generate natural, relevant content based on the service/product described in user requirements.]
      
      **SPECIAL FORMATTING FOR "LIMITATION OF LIABILITY" SECTION:**
      - Generate in professional flowing paragraph format (NO bullet points or (a), (b), (c) listings)
      - Include: liability cap, exclusion of consequential damages, indemnification provisions
      - Write everything in continuous paragraphs without using (a), (b), (c), (d) or (i), (ii), (iii), (iv)
      - Generate based on user requirements - DO NOT copy this example
      - Format style (FLOWING PARAGRAPHS - generate your own content):
        ## LIMITATION OF LIABILITY
        
        [Paragraph 1: Write about liability cap and exclusion of consequential damages in flowing prose.]
        
        [Paragraph 2: Write about indemnification obligations in flowing prose.]
        
        [Paragraph 3: Write about exceptions to limitations in flowing prose.]
      
      **SPECIAL FORMATTING FOR "GENERAL PROVISIONS" SECTION:**
      - Generate with sub-headers on NEW LINES (not inline bold labels)
      - Each sub-header should be on its own line, followed by content paragraph below it
      - Include: Entire Agreement, Amendments, Waiver, Severability, Assignment, Notices, Force Majeure, Counterparts
      - Generate based on standard legal provisions - DO NOT copy these examples
      - Format style (sub-headers on new lines - generate your own content):
        ## GENERAL PROVISIONS
        
        **Entire Agreement**
        
        [Write paragraph about this being the entire agreement.]
        
        **Amendments**
        
        [Write paragraph about how amendments must be made.]
        
        **Waiver**
        
        [Write paragraph about waiver provisions.]
        
        **Severability**
        
        [Write paragraph about severability.]
        
        **Assignment**
        
        [Write paragraph about assignment restrictions.]
        
        **Notices**
        
        [Write paragraph about notice requirements.]
        
        **Force Majeure**
        
        [Write paragraph about force majeure events.]
        
        **Counterparts**
        
        [Write paragraph about counterparts execution.]
      
      **SPECIAL FORMATTING FOR "CONFIDENTIALITY" SECTION:**
      - Generate with sub-headers on NEW LINES (not inline bold labels)
      - Each sub-header should be on its own line, followed by content paragraph below it
      - Include: Definition, Obligations, Exceptions, Duration
      - Sub-headers should NOT use ## (that's for main section), just plain text or bold
      - **CRITICAL - Duration Placeholder Rule:**
        * IF user requirements specify confidentiality duration (e.g., "5 years", "3 years confidentiality"), use that exact value
        * IF user requirements DO NOT specify confidentiality duration, use "(_____________)" placeholder
        * ⚠️ DO NOT USE DEFAULT VALUES like "5 years", "3 years", "2 years" - these are FORBIDDEN unless user explicitly mentions them
        * Examples: "five (5) years" ONLY if user says "5 years", otherwise "(_____________) years"
      - Generate based on standard confidentiality provisions - DO NOT copy these examples
      - Format style (sub-headers on new lines - generate your own content):
        ## CONFIDENTIALITY
        
        **Definition**
        
        [Write paragraph defining what constitutes Confidential Information.]
        
        **Obligations**
        
        [Write paragraph about obligations to maintain confidentiality and protect information.]
        
        **Exceptions**
        
        [Write paragraph about exceptions to confidentiality obligations.]
        
        **Duration**
        
        [Write paragraph about duration of confidentiality obligations. IF user specifies duration, use exact value (e.g., "five (5) years"). IF NOT specified, use "(_____________) years" placeholder.]
      
      **SPECIAL FORMATTING FOR "TERMINATION" SECTION:**
      - Generate with sub-headers on NEW LINES (not inline bold labels)
      - Each sub-header should be on its own line, followed by content paragraph below it
      - Include: For Convenience, For Cause, Effect of Termination
      - **CRITICAL - Notice Period and Cure Period Placeholder Rules:**
        * IF user requirements specify termination notice period (e.g., "30 days notice"), use that exact value
        * IF user requirements DO NOT specify notice period, use "(_____________)" placeholder
        * IF user requirements specify cure period for breach (e.g., "30 days to cure"), use that exact value
        * IF user requirements DO NOT specify cure period, use "(_____________)" placeholder
        * ⚠️ DO NOT USE DEFAULT VALUES like "30 days", "60 days", "15 days" - these are FORBIDDEN unless user explicitly mentions them
        * Examples: "thirty (30) days" ONLY if user says "30 days", otherwise "(_____________) days"
      - Generate based on standard termination provisions - DO NOT copy these examples
      - Format style (sub-headers on new lines - generate your own content):
        ## TERMINATION
        
        **For Convenience**
        
        [Write paragraph about termination for convenience. IF user specifies notice period, use exact value (e.g., "thirty (30) days"). IF NOT specified, use "(_____________) days" placeholder.]
        
        **For Cause**
        
        [Write paragraph about termination for cause/breach. IF user specifies cure period, use exact value. IF NOT specified, use "(_____________) days" placeholder for cure period.]
        
        **Effect of Termination**
        
        [Write paragraph about what happens upon termination: deliverables, payments, return of materials, etc.]
      
      **CRITICAL REQUIREMENT FOR "SCOPE OF WORK" AND "DELIVERABLES" SECTIONS:**
      
      **SCOPE OF WORK SECTION - MANDATORY FORMAT:**
      - You MUST ALWAYS add exactly TWO (2) empty numbered items at the END of the "SCOPE OF WORK" section list
      - These empty items are for users to fill in additional services later
      - Continue the numbering sequence naturally from the last actual item
      - CRITICAL: Each empty numbered item MUST contain the text "(_____________)" placeholder
      - DO NOT leave the numbered items blank/empty - they MUST show the placeholder
      - The format is: "5. (_____________)" and "6. (_____________)" (number, period, space, then placeholder)
      - NO EXCEPTIONS - Every SCOPE OF WORK section MUST end with these 2 items containing placeholders
      - CORRECT Example format:
        ```
        ## SCOPE OF WORK
        
        The Service Provider shall provide the following services to the Client:
        
        1. Requirement analysis and gathering.
        2. Design and development of the mobile application.
        3. Testing and quality assurance.
        4. Deployment of the mobile application to the designated platform.
        5. (_____________)
        6. (_____________)
        ```
      - WRONG (DO NOT DO THIS): Do not create items "5." and "6." with no text after them
      
      **DELIVERABLES SECTION - MANDATORY FORMAT:**
      - You MUST ALWAYS add exactly TWO (2) empty numbered items at the END of the "DELIVERABLES" section list
      - These empty items are for users to fill in additional deliverables later
      - Continue the numbering sequence naturally from the last actual item
      - CRITICAL: Each empty numbered item MUST contain the text "(_____________)" placeholder
      - DO NOT leave the numbered items blank/empty - they MUST show the placeholder
      - The format is: "4. (_____________)" and "5. (_____________)" (number, period, space, then placeholder)
      - NO EXCEPTIONS - Every DELIVERABLES section MUST end with these 2 items containing placeholders
      - CORRECT Example format:
        ```
        ## DELIVERABLES
        
        The Service Provider shall deliver the following items to the Client:
        
        1. A fully functional mobile application developed in accordance with the specifications provided by the Client.
        2. Documentation detailing the application features and user instructions.
        3. Acceptance criteria shall be based on the successful completion of testing and approval by the Client.
        4. (_____________)
        5. (_____________)
        ```
      - WRONG (DO NOT DO THIS): Do not create items "4." and "5." with no text after them
      
      **PAYMENT SECTION - FLEXIBLE MILESTONE FORMAT:**
      - When generating the "PAYMENT" or "PAYMENT / COMPENSATION" or "Payment / Compensation" section:
        * If payment milestones/schedule are NOT specified in user requirements, use 3 placeholder milestones
        * If user specifies milestones, use EXACTLY the number and details they provide (could be 2, 3, 4, 5, or any number of milestones)
        * ADAPT to user's requirements - if they specify 5 milestones, generate all 5; if they specify 2, generate only 2
        * Example when milestones NOT specified (default 3 placeholders):
          ## PAYMENT / COMPENSATION
          
          The total cost for the services provided under this Agreement shall be $(_____________), payable in the following milestones:
          
          1. An initial payment of $(_____________) upon (_____________).
          2. A second payment of $(_____________) upon (_____________).
          3. A final payment of $(_____________) upon (_____________).
          
          All payments shall be made within (_____________) days of the completion of each milestone.
        * Example when user specifies 3 milestones (use exact details):
          ## PAYMENT / COMPENSATION
          
          The total cost for the services provided under this Agreement shall be $25,000, payable in the following milestones:
          
          1. An initial payment of $10,000 upon signing of this Agreement.
          2. A second payment of $10,000 upon completion of the design phase.
          3. A final payment of $5,000 upon delivery of the completed mobile application.
          
          All payments shall be made within fifteen (15) days of the completion of each milestone.
        * If user specifies 5 milestones, generate all 5 with their exact amounts and conditions
   
   d) **STANDARD LEGAL CLAUSES**:
      Generate appropriate standard legal clauses including (but not limited to):
      - Intellectual Property Rights (with relevant sub-clauses)
      - Confidentiality (with Definition, Obligations, Exceptions, Duration - use (_____________) if duration not specified)
      - Termination (with For Convenience, For Cause, Effect of Termination - use (_____________) for notice periods if not specified)
      - Limitation of Liability (with Limitation, Exclusion of Consequential Damages, Indemnification)
      - Governing Law and Dispute Resolution (appropriate for {jurisdiction_name})
      - General Provisions (Entire Agreement, Amendments, Waiver, Severability, Assignment, Notices, Force Majeure, Counterparts, etc.)
      
      **REMINDER**: For CONFIDENTIALITY Duration and TERMINATION notice periods - IF specified in user requirements, use those exact values. IF NOT specified, MUST use (_____________) placeholder. DO NOT invent values.
   
   e) **JURISDICTION-SPECIFIC CLAUSES - "GOVERNING LAW AND JURISDICTION" SECTION**:
      Based on {jurisdiction_name} jurisdiction, generate a section titled "## GOVERNING LAW AND JURISDICTION" that includes:
      - Governing Law clause: {jurisdiction_instructions}
      - Court Jurisdiction and Dispute Resolution clause
      - Stamp Duty requirements clause (if applicable for {jurisdiction_name})
      - Registration requirements clause (if applicable for {jurisdiction_name})
      - Tax clauses (VAT/GST/other applicable taxes for {jurisdiction_name})
      - Consumer Protection clause (if applicable for {jurisdiction_name})
      - Data Protection clause (if applicable for {jurisdiction_name})
      - Any other jurisdiction-specific legal requirements
      
      **CRITICAL - INLINE CITATIONS WITH CLICKABLE LINKS FOR GOVERNING LAW AND JURISDICTION SECTION:**
      
      ⚠️ **MANDATORY REQUIREMENT - YOU MUST INCLUDE ACTUAL WORKING URLs IN EVERY CITATION**
      
      - For EACH statement/clause in the "GOVERNING LAW AND JURISDICTION" section, you MUST add an inline citation with a REAL, WORKING, CLICKABLE link at the END of that statement
      - **IMPORTANT: Use HTML anchor tag format for PDF compatibility - HTML links work in PDF, markdown links do NOT**
      - **CRITICAL: NEVER write citations without URLs like "[Source: Act Name]" - THIS IS WRONG!**
      - **CRITICAL: EVERY citation MUST have <a href="ACTUAL_URL"> with a real web address**
      
      **CORRECT Citation Format (YOU MUST USE THIS EXACT FORMAT):**
      ```
      [<a href="ACTUAL_FULL_URL_HERE" target="_blank">Source: Act/Law Name</a>]
      ```
      
      **WRONG Formats (DO NOT USE THESE - FORBIDDEN):**
      ❌ [Source: Contract Act 1872] - NO URL, WRONG!
      ❌ [Source: <a>Contract Act 1872</a>] - NO href attribute, WRONG!
      ❌ [<a href="#">Source: Contract Act 1872</a>] - Placeholder URL, WRONG!
      
      **CORRECT Examples with REAL URLs (COPY THIS EXACT STYLE):**
      
      ✅ Bangladesh Example:
      "This Agreement shall be governed by and construed in accordance with the laws of Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-367.html" target="_blank">Source: Contract Act 1872</a>]"
      
      ✅ Another Bangladesh Example:
      "Any dispute arising out of or relating to this Agreement shall be subject to the exclusive jurisdiction of the courts of Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-86.html" target="_blank">Source: Code of Civil Procedure 1908</a>]"
      
      ✅ Stamp Duty Example:
      "This Agreement shall be executed on non-judicial stamp paper of appropriate value as per the Stamp Act of Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-24.html" target="_blank">Source: Stamp Act 1899</a>]"
      
      ✅ Registration Example:
      "This Agreement shall be registered with the appropriate Sub-Registrar's Office in Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-87.html" target="_blank">Source: Registration Act 1908</a>]"
      
      ✅ VAT Example:
      "All applicable Value Added Tax (VAT) shall be payable as per the provisions of this Agreement. [<a href="https://www.vat.gov.bd/" target="_blank">Source: VAT Act 1991</a>]"
      
      ✅ Consumer Protection Example:
      "This Agreement is subject to the provisions of the Consumer Rights Protection Act, 2009 of Bangladesh. [<a href="http://bdlaws.minlaw.gov.bd/act-1007.html" target="_blank">Source: Consumer Rights Protection Act 2009</a>]"
      
      **URL Sources by Jurisdiction:**
      
      **Bangladesh URLs (USE THESE EXACT URLs):**
      - Contract Act 1872: http://bdlaws.minlaw.gov.bd/act-367.html
      - Code of Civil Procedure 1908: http://bdlaws.minlaw.gov.bd/act-86.html
      - Stamp Act 1899: http://bdlaws.minlaw.gov.bd/act-24.html
      - Registration Act 1908: http://bdlaws.minlaw.gov.bd/act-87.html
      - VAT Act 1991: https://www.vat.gov.bd/
      - Consumer Rights Protection Act 2009: http://bdlaws.minlaw.gov.bd/act-1007.html
      - Main legal database: http://bdlaws.minlaw.gov.bd/
      
      **India URLs:**
      - Use: https://legislative.gov.in/ or https://www.indiacode.nic.in/
      - Example: Indian Contract Act 1872: https://legislative.gov.in/actsofparliamentfromtheyear/indian-contract-act-1872
      
      **UK URLs:**
      - Use: https://www.legislation.gov.uk/
      - Example: Consumer Rights Act 2015: https://www.legislation.gov.uk/ukpga/2015/15
      
      **USA URLs:**
      - Use: https://www.law.cornell.edu/uscode/text
      - Example: Uniform Commercial Code: https://www.law.cornell.edu/ucc
      
      **IMPLEMENTATION RULES:**
      1. Add citation immediately after the period/full stop of each statement
      2. Each statement MUST have its own citation with link - do NOT group multiple statements under one citation
      3. EVERY citation MUST include the complete <a href="URL" target="_blank"> tag structure
      4. The URL MUST be a real, working web address - NOT a placeholder
      5. Use the authoritative legal reference website for the jurisdiction
      6. If you don't have the exact law URL, use the main legal database URL for that country
      7. Format MUST be: [<a href="FULL_WORKING_URL" target="_blank">Source: Act Name</a>]
      
      **VERIFICATION CHECKLIST - BEFORE GENERATING, CONFIRM:**
      ☑ Every citation has <a href="..."> tag? 
      ☑ Every href has a REAL URL starting with http:// or https://?
      ☑ Every citation has target="_blank"?
      ☑ Every citation is wrapped in brackets [...]?
      ☑ No plain text citations like [Source: Act Name]?
      
      **⚠️ ABSOLUTE REQUIREMENT: If you generate ANY citation without a complete HTML anchor tag with real URL, the contract will be REJECTED. You MUST include working URLs in EVERY single citation.**

   **IMPORTANT**: Generate all content naturally using your expertise. Do NOT use hard-coded templates or fixed phrases. Create professional, context-appropriate content for each section based on the contract type, parties, and requirements.

**⚠️ CRITICAL - ABSOLUTELY DO NOT GENERATE THESE SECTIONS:**
- ❌ DO NOT include "## SIGNATURES" section anywhere - it will be added separately after generation
- ❌ DO NOT include "## REFERENCES" section anywhere in the contract - FORBIDDEN
- ❌ DO NOT create any references list, bibliography, or legal references section at the end
- ❌ DO NOT add "The following legal references..." or similar text
- ❌ DO NOT create signature blocks or signature lines
- ❌ DO NOT include any closing statements like "This Agreement is executed as of the date first above written."
- ✅ END your contract immediately after the "## GOVERNING LAW AND JURISDICTION" section
- ✅ The LAST section you generate MUST be "## GOVERNING LAW AND JURISDICTION" - nothing should follow it
- ✅ All legal references should ONLY be inline citations within the "GOVERNING LAW AND JURISDICTION" section with clickable HTML links

5. **Visual Structure**:
   - Headers and content MUST be separated by blank lines
   - Lists and paragraphs MUST be separated by blank lines
   - Each section should be visually distinct and well-spaced
   - Use separator lines (---) between major sections if needed for clarity

6. **Important Notes**:
   - Generate the COMPLETE contract from start to finish (EXCEPT signature blocks)
   - Include ALL standard, relevant clauses - these are essential for legal enforceability
   - Ensure ALL content is RELEVANT and STANDARD for a {contract_type_name}
   - Use industry-standard legal language and structures appropriate for {contract_type_name}
   - Adapt jurisdiction clauses based on the provided jurisdiction information
   - Ensure the contract is comprehensive, professional, and legally sound
   - Maintain consistency in terminology and party references throughout
   - DO NOT include signature blocks - they will be added separately
   - DO NOT include irrelevant clauses or content that is not standard for {contract_type_name}

Generate the COMPLETE contract now with maximum professionalism, legal precision, and EXACT formatting as specified above. Ensure ALL content is RELEVANT, STANDARD, and APPROPRIATE for a {contract_type_name}. Include the header, recitals, all required sections, all relevant standard clauses, and jurisdiction-specific clauses. Use industry-standard legal language and structures. DO NOT include signature blocks - end after the jurisdiction clauses and general provisions."""
        
        if has_template:
            base_prompt = f"""You are an expert legal contract writer. The user has provided THREE sources of information that you MUST analyze and combine intelligently:

1. **USER REQUIREMENTS** (text input from user)
2. **TEMPLATE CONTRACT** (structure and format guide)
3. **SUPPLEMENTARY FILE(S)** (additional data and details)

=== USER REQUIREMENTS (PRIMARY SOURCE - ANALYZE FIRST) ===
{user_prompt or 'Not specified'}
=== END OF USER REQUIREMENTS ===

=== TEMPLATE CONTRACT (USE AS STRUCTURE AND FORMAT GUIDE) ===
{template_text}
=== END OF TEMPLATE ===

=== SUPPLEMENTARY FILE(S) (USE FOR SPECIFIC DATA AND DETAILS) ===
{supplementary_text or 'No supplementary file provided'}
=== END OF SUPPLEMENTARY FILE ===

CRITICAL INSTRUCTIONS FOR COMBINING ALL THREE SOURCES:

**ANALYSIS PRIORITY:**
1. **USER REQUIREMENTS** - This is the PRIMARY source. Extract all key information (party names, amounts, dates, terms, conditions, services, deliverables, etc.) from the user's text input
2. **SUPPLEMENTARY FILE(S)** - Use this as SECONDARY source to fill in additional details, specific data, or missing information not mentioned in user requirements
3. **TEMPLATE CONTRACT** - Use this as STRUCTURE and FORMAT guide only. Follow the template's section headers, clause organization, and legal language style

**PRIMARY ROLE OF TEMPLATE:**
- Use the TEMPLATE as the STRUCTURE, FORMAT, and STYLE guide
- Follow the template's section headers, clause organization, and legal language
- Maintain the template's professional tone and formatting style
- Keep all template section headers and clause structures exactly as shown

**PRIMARY ROLE OF SUPPLEMENTARY FILE(S):**
- Extract ALL specific information from SUPPLEMENTARY FILE(S) (names, amounts, dates, terms, conditions, addresses, payment details, timelines, etc.)
- Use supplementary file data to REPLACE template placeholders like [Address], [Amount], [Date], etc.
- If supplementary file contains additional clauses or sections not in template, incorporate them appropriately
- If supplementary file has conflicting information with template or user requirements, prioritize in this order: USER REQUIREMENTS > SUPPLEMENTARY FILE > TEMPLATE

**COMBINATION STRATEGY:**
1. **FIRST**: Extract all information from USER REQUIREMENTS (this is the most important source)
2. **SECOND**: Add or supplement with details from SUPPLEMENTARY FILE(S) if they provide additional information
3. **THIRD**: Use TEMPLATE structure and format to organize the contract
4. Fill in ALL placeholders and missing details from USER REQUIREMENTS and SUPPLEMENTARY FILE(S)
5. If supplementary file has more detailed information than user requirements, use the supplementary details
6. If supplementary file mentions additional terms/clauses, add them to appropriate sections
7. Ensure the final contract has the template's structure but uses data from USER REQUIREMENTS and SUPPLEMENTARY FILE(S)
8. Maintain professional legal language throughout

**EXAMPLE:**
- User Requirements say: "Service agreement between TechCorp and DevSolutions for mobile app development, $25,000 payment"
- Template says: "Payment of $[Amount]"
- Supplementary says: "Payment of $25,000 in 3 installments: $10,000 upon signing, $10,000 at milestone, $5,000 upon delivery"
- Result: "Payment of $25,000 in three (3) installments as follows: $10,000 upon signing this Agreement, $10,000 upon completion of specified milestones, and $5,000 upon final delivery and acceptance of the mobile application."

**IMPORTANT**: You MUST analyze and incorporate information from ALL THREE sources (User Requirements, Template, and Supplementary File) to generate a comprehensive contract.

{base_prompt}"""
        
        return base_prompt
    
    def _build_jurisdiction_instructions(self, jurisdiction_rules, jurisdiction_name, party1_label, party2_label):
        """Build detailed jurisdiction-specific instructions"""
        instructions = f"""JURISDICTION AND APPLICABLE LAW:

Legal Jurisdiction: {jurisdiction_name}
Governing Law: {jurisdiction_rules.get('governing_law', 'Laws of the selected jurisdiction')}
Court Jurisdiction: {jurisdiction_rules.get('court_jurisdiction', 'Courts of the selected jurisdiction')}
Dispute Resolution: {jurisdiction_rules.get('dispute_resolution', 'Courts of the selected jurisdiction')}
"""
        
        if jurisdiction_rules.get('stamp_duty'):
            instructions += f"\nSTAMP DUTY REQUIREMENT:\n{jurisdiction_rules.get('stamp_duty_clause', '')}\n"
        
        if jurisdiction_rules.get('registration_required'):
            instructions += f"\nREGISTRATION REQUIREMENT:\n{jurisdiction_rules.get('registration_clause', '')}\n"
        
        if 'VAT' in jurisdiction_rules.get('tax_clauses', []):
            instructions += f"\nVAT:\n{jurisdiction_rules.get('vat_clause', '')}\n"
        if 'GST' in jurisdiction_rules.get('tax_clauses', []):
            instructions += f"\nGST:\n{jurisdiction_rules.get('gst_clause', '')}\n"
        
        if jurisdiction_rules.get('consumer_protection'):
            instructions += f"\nCONSUMER PROTECTION:\n{jurisdiction_rules.get('consumer_protection_clause', '')}\n"
        
        return instructions
    
    def _format_sections_for_prompt(self, sections, section_descriptions, party1, party2, 
                                    party1_label, party2_label, start_date, contract_type="service_agreement"):
        """Format sections list for prompt"""
        formatted = ""
        is_sop = (contract_type == "sop")
        
        for section in sections:
            desc = section_descriptions.get(section, f"Details for {section}")
            formatted += f"\n   SECTION: {section.upper()}\n"
            formatted += f"   - Description: {desc}\n"
            
            if is_sop:
                formatted += f"   - Write in FIRST PERSON, use flowing paragraphs\n"
            else:
                formatted += f"   - Use professional legal language\n"
                formatted += f"   - Reference: {party1} ({party1_label}) and {party2} ({party2_label})\n"
        
        return formatted
    
    def refine_text_with_vision(self, text, image, prompt_template):
        """Refine and contextualize extracted text using Google Gemini Vision"""
        from core.file_utils import encode_image_to_base64
        
        if not self.gemini_api_key:
            return None, "ERROR: Gemini API key is not configured."
        
        if not self.genai:
            return None, "Google Generative AI package not installed."
        
        try:
            if image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')
            
            prompt = prompt_template.format(text=text) if text else prompt_template
            
            max_retries = 3
            retry_delay = 8
            current_model_index = 0
            
            for attempt in range(max_retries * len(self.model_names)):
                try:
                    current_model = self.model_names[current_model_index]
                    model = self.genai.GenerativeModel(current_model)
                    response = model.generate_content(
                        [prompt, image],
                        generation_config=self.genai.types.GenerationConfig(
                            max_output_tokens=1024,
                            temperature=0
                        )
                    )
                    self.model_name = current_model
                    return response.text, None
                except Exception as e:
                    error_str = str(e)
                    
                    if "404" in error_str or "not found" in error_str.lower():
                        if current_model_index < len(self.model_names) - 1:
                            current_model_index += 1
                            continue
                        else:
                            return None, f"None of the available models support vision. Error: {error_str[:200]}"
                    
                    if "429" in error_str or "quota" in error_str.lower():
                        if current_model_index < len(self.model_names) - 1:
                            current_model_index += 1
                            continue
                        elif attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue
                        else:
                            return None, f"Vision API quota exceeded. Error: {error_str[:200]}"
                    
                    if current_model_index < len(self.model_names) - 1:
                        current_model_index += 1
                        continue
                    
                    return None, f"Error with Gemini Vision API: {error_str[:200]}"
            
            return None, "Failed to get vision response after trying all models"
        except Exception as e:
            return None, f"Error with Gemini Vision API: {str(e)}"
    
    def translate_text(self, text, target_language):
        """Translate text to target language with chunking for large documents"""
        import re
        
        # Support both language codes and full names
        language_names = {
            'en': 'English',
            'bn': 'Bengali',
            'bangla': 'Bengali',
            'hi': 'Hindi',
            'ar': 'Arabic',
            'english': 'English',
            'bengali': 'Bengali',
            'hindi': 'Hindi',
            'arabic': 'Arabic'
        }
        
        # Normalize the input (lowercase for matching)
        target_lang_key = target_language.lower().strip()
        target_lang_name = language_names.get(target_lang_key, target_language)
        
        print(f"[TRANSLATE] Input language: '{target_language}' -> Target: '{target_lang_name}'")
        
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                return None, "OpenAI API key is required for translation. Please configure OPENAI_API_KEY in your environment."
            
            # CRITICAL: Extract signature images before translation to ensure they are preserved
            signature_placeholders = {}
            # Match signature image divs with base64 data URLs
            signature_pattern = r'<div[^>]*style="[^"]*"[^>]*>\s*<img[^>]*src="(data:image/[^"]+?)"[^>]*>\s*</div>'
            matches = list(re.finditer(signature_pattern, text, re.IGNORECASE | re.DOTALL))
            
            for idx, match in enumerate(matches):
                placeholder = f"__SIGNATURE_IMAGE_PLACEHOLDER_{idx}__"
                signature_placeholders[placeholder] = match.group(0)  # Store full HTML
                text = text.replace(match.group(0), placeholder, 1)
            
            print(f"[TRANSLATE] Extracted {len(signature_placeholders)} signature images for preservation")
            
            # Chunking strategy: Split by sections (## headers) for better context preservation
            # If document is small (< 50k chars), translate in one go
            if len(text) < 50000:
                translated, error = self._translate_single_chunk(text, target_lang_name)
            else:
                # For large documents, split by sections
                print(f"[TRANSLATE] Large document ({len(text)} chars), splitting into chunks...")
                chunks = self._split_text_by_sections(text)
                
                if len(chunks) == 1:
                    # If only one chunk, translate normally
                    translated, error = self._translate_single_chunk(text, target_lang_name)
                else:
                    print(f"[TRANSLATE] Split into {len(chunks)} chunks, translating sequentially...")
                    translated_chunks = []
                    
                    for i, chunk in enumerate(chunks, 1):
                        print(f"[TRANSLATE] Translating chunk {i}/{len(chunks)} ({len(chunk)} chars)...")
                        translated_chunk, error = self._translate_single_chunk(chunk, target_lang_name)
                        if error:
                            return None, f"Error translating chunk {i}: {error}"
                        translated_chunks.append(translated_chunk)
                    
                    # Combine translated chunks
                    translated = '\n\n'.join(translated_chunks)
            
            if error:
                return None, error
            
            # CRITICAL: Restore signature images after translation
            for placeholder, original_html in signature_placeholders.items():
                if placeholder in translated:
                    translated = translated.replace(placeholder, original_html)
                    print(f"[TRANSLATE] Restored signature image: {placeholder}")
                else:
                    # If placeholder was lost, try to find and restore in signature section
                    print(f"[TRANSLATE] WARNING: Signature placeholder {placeholder} not found, searching for signature section...")
                    # Look for signature section markers (## SIGNATURES or similar)
                    signature_section_pattern = r'(##\s+[^\n]*SIGNATURES?[^\n]*\n[^<]*<div[^>]*style="[^"]*"[^>]*>)'
                    sig_match = re.search(signature_section_pattern, translated, re.IGNORECASE | re.DOTALL)
                    if sig_match:
                        # Find the position after the opening div tag
                        pos = sig_match.end()
                        # Insert the signature HTML right after the div opening
                        translated = translated[:pos] + '\n' + original_html + translated[pos:]
                        print(f"[TRANSLATE] Restored signature image in SIGNATURES section")
                    else:
                        # Last resort: append at end if signature section not found
                        print(f"[TRANSLATE] WARNING: Could not find signature section, signature may be missing")
            
            # VALIDATION: Check if critical elements are preserved
            print(f"[TRANSLATE] Running post-translation validation...")
            validation_issues = []
            
            # Check if HTML anchor tags are preserved
            original_links = re.findall(r'<a\s+href="[^"]+"\s+target="_blank">', text, re.IGNORECASE)
            translated_links = re.findall(r'<a\s+href="[^"]+"\s+target="_blank">', translated, re.IGNORECASE)
            if len(original_links) != len(translated_links):
                validation_issues.append(f"Link count mismatch: {len(original_links)} original vs {len(translated_links)} translated")
                print(f"[TRANSLATE] WARNING: {validation_issues[-1]}")
            
            # Check if placeholders are preserved
            original_placeholders = text.count("(_____________)")
            translated_placeholders = translated.count("(_____________)")
            if original_placeholders != translated_placeholders:
                validation_issues.append(f"Placeholder count mismatch: {original_placeholders} original vs {translated_placeholders} translated")
                print(f"[TRANSLATE] WARNING: {validation_issues[-1]}")
            
            # Check if base64 image data is preserved
            original_images = re.findall(r'src="data:image/[^"]+?"', text, re.IGNORECASE)
            translated_images = re.findall(r'src="data:image/[^"]+?"', translated, re.IGNORECASE)
            if len(original_images) != len(translated_images):
                validation_issues.append(f"Image count mismatch: {len(original_images)} original vs {len(translated_images)} translated")
                print(f"[TRANSLATE] WARNING: {validation_issues[-1]}")
            
            if validation_issues:
                print(f"[TRANSLATE] Translation completed with {len(validation_issues)} validation warnings")
            else:
                print(f"[TRANSLATE] Translation validated successfully - all critical elements preserved")
            
            print(f"[TRANSLATE] Translation completed ({len(translated)} chars)")
            return translated.strip(), None
            
        except Exception as e:
            return None, f"Error translating text: {str(e)}"
    
    def _split_text_by_sections(self, text):
        """Split text by markdown sections (## headers) for chunking"""
        import re
        
        # Find all section headers with their positions
        section_pattern = r'^(##\s+.+?)$'
        section_matches = list(re.finditer(section_pattern, text, re.MULTILINE))
        
        if not section_matches:
            # No sections found, split by size (max 40k chars per chunk)
            chunk_size = 40000
            chunks = []
            for i in range(0, len(text), chunk_size):
                chunks.append(text[i:i + chunk_size])
            return chunks
        
        chunks = []
        max_chunk_size = 40000  # Max characters per chunk
        
        # Process sections
        for i, match in enumerate(section_matches):
            section_start = match.start()
            section_header = match.group(0)
            
            # Determine section end (next section start or end of text)
            if i + 1 < len(section_matches):
                section_end = section_matches[i + 1].start()
            else:
                section_end = len(text)
            
            # Get section content (header + content until next section)
            section_content = text[section_start:section_end]
            
            # If this section alone is too large, split it by size
            if len(section_content) > max_chunk_size:
                # Split large section into smaller chunks
                chunk_start = section_start
                while chunk_start < section_end:
                    chunk_end = min(chunk_start + max_chunk_size, section_end)
                    # Try to break at paragraph boundary if possible
                    if chunk_end < section_end:
                        # Look for double newline (paragraph break) near the end
                        last_break = text.rfind('\n\n', chunk_start, chunk_end)
                        if last_break > chunk_start + max_chunk_size * 0.7:  # If break is not too early
                            chunk_end = last_break + 2
                    chunks.append(text[chunk_start:chunk_end].strip())
                    chunk_start = chunk_end
            else:
                # Check if we can add this section to the last chunk
                if chunks and len(chunks[-1]) + len(section_content) <= max_chunk_size:
                    # Add to last chunk
                    chunks[-1] += '\n\n' + section_content
                else:
                    # Start new chunk
                    chunks.append(section_content)
        
        # Handle content before first section
        if section_matches and section_matches[0].start() > 0:
            pre_content = text[:section_matches[0].start()].strip()
            if pre_content:
                if chunks and len(chunks[0]) + len(pre_content) <= max_chunk_size:
                    chunks[0] = pre_content + '\n\n' + chunks[0]
                else:
                    chunks.insert(0, pre_content)
        
        return chunks if chunks else [text]
    
    def stream_translate_text(self, text, target_language):
        """Stream translation of text to target language"""
        import re
        
        # Support both language codes and full names
        language_names = {
            'en': 'English',
            'bn': 'Bengali',
            'bangla': 'Bengali',
            'hi': 'Hindi',
            'ar': 'Arabic',
            'english': 'English',
            'bengali': 'Bengali',
            'hindi': 'Hindi',
            'arabic': 'Arabic'
        }
        
        # Normalize the input (lowercase for matching)
        target_lang_key = target_language.lower().strip()
        target_lang_name = language_names.get(target_lang_key, target_language)
        
        print(f"[STREAM TRANSLATE] Input language: '{target_language}' -> Target: '{target_lang_name}'")
        
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                yield json.dumps({"error": "OpenAI API key is required for translation. Please configure OPENAI_API_KEY in your environment."})
                return
            
            # CRITICAL: Extract signature images before translation to ensure they are preserved
            signature_placeholders = {}
            signature_pattern = r'<div[^>]*style="[^"]*"[^>]*>\s*<img[^>]*src="(data:image/[^"]+?)"[^>]*>\s*</div>'
            matches = list(re.finditer(signature_pattern, text, re.IGNORECASE | re.DOTALL))
            
            for idx, match in enumerate(matches):
                placeholder = f"__SIGNATURE_IMAGE_PLACEHOLDER_{idx}__"
                signature_placeholders[placeholder] = match.group(0)
                text = text.replace(match.group(0), placeholder, 1)
            
            # Build translation prompt
            translation_prompt = f"""You are a professional legal translator specializing in legal contracts and agreements.

⚠️ **CRITICAL INSTRUCTION - READ FIRST:**
Your PRIMARY task is to translate this document to {target_lang_name}. The output MUST be in {target_lang_name}, NOT in English or any other language.

Translate the following legal contract document to {target_lang_name} while maintaining PERFECT formatting and legal accuracy.

CRITICAL TRANSLATION RULES:

**1. TARGET LANGUAGE REQUIREMENT (HIGHEST PRIORITY):**
   - The ENTIRE translated output MUST be in {target_lang_name}
   - Translate ALL text content to {target_lang_name}
   - Do NOT keep text in English unless it's in the "DO NOT TRANSLATE" list below
   - Section headers, paragraphs, legal terms - EVERYTHING must be in {target_lang_name}

**2. PRESERVE ALL FORMATTING:**
   - Keep ALL markdown syntax EXACTLY as they are: ##, ###, **, -, 1., 2., etc.
   - Maintain ALL section headers, bullet points, numbered lists, paragraph breaks
   - Keep ALL blank lines between sections
   - Preserve ALL indentation and spacing

**3. DO NOT TRANSLATE THESE (KEEP AS-IS):**
   - Party names (company names, person names) - KEEP ORIGINAL
   - Dates in any format - KEEP ORIGINAL
   - Currency amounts ($, ৳, ₹, etc.) - KEEP ORIGINAL
   - Addresses - KEEP ORIGINAL
   - Placeholder text: "(_____________)" - KEEP EXACTLY AS-IS
   - Email addresses - KEEP ORIGINAL
   - Phone numbers - KEEP ORIGINAL
   - URLs and web links - KEEP ORIGINAL

**4. HTML PRESERVATION (ABSOLUTELY CRITICAL):**
   - Preserve ALL HTML tags EXACTLY: <div>, <img>, <a>, <p>, <span>, etc.
   - Preserve ALL HTML attributes: style="...", src="...", href="...", target="...", etc.
   - **SIGNATURE IMAGES**: Keep ALL <img> tags with src="data:image/..." base64 data COMPLETELY UNCHANGED
   - **CLICKABLE LINKS**: Keep ALL <a href="..."> anchor tags EXACTLY as they are

**5. LEGAL TERMINOLOGY:**
   - Use proper, formal legal terminology in {target_lang_name}
   - Maintain professional, formal tone throughout

Document to translate:
{text}

⚠️ CRITICAL REMINDERS:
1. Output language MUST be {target_lang_name} - NOT English
2. Return ONLY the translated document in {target_lang_name}
3. Preserve ALL formatting, HTML tags, URLs, and base64 image data EXACTLY as they appear
4. Translate ALL text content to {target_lang_name} (except items in "DO NOT TRANSLATE" list)"""
            
            # Build system message for translation
            system_messages = [{
                "role": "system",
                "content": f"""You are a professional translator. CRITICAL RULE: You MUST translate the document to {target_lang_name}. The ENTIRE output must be in {target_lang_name}, NOT in English or any other language. This is your PRIMARY and ONLY task."""
            }]
            
            # Stream the translation with system message
            accumulated_text = ""
            for chunk_data in self._stream_openai(translation_prompt, additional_system_messages=system_messages):
                chunk_json = json.loads(chunk_data)
                if "error" in chunk_json:
                    yield chunk_data
                    return
                elif "chunk" in chunk_json:
                    content = chunk_json["chunk"]
                    accumulated_text += content
                    yield chunk_data
                elif "done" in chunk_json:
                    # Restore signature images after translation
                    for placeholder, original_html in signature_placeholders.items():
                        if placeholder in accumulated_text:
                            accumulated_text = accumulated_text.replace(placeholder, original_html)
                    
                    yield json.dumps({"done": True, "translated_text": accumulated_text})
                    return
        except Exception as e:
            yield json.dumps({"error": f"Error translating text: {str(e)}"})
    
    def translate_html_content(self, html_content, target_language):
        """Translate HTML content while preserving HTML structure and tags"""
        import re
        
        # Support both language codes and full names
        language_names = {
            'en': 'English',
            'bn': 'Bengali',
            'bangla': 'Bengali',
            'hi': 'Hindi',
            'ar': 'Arabic',
            'english': 'English',
            'bengali': 'Bengali',
            'hindi': 'Hindi',
            'arabic': 'Arabic'
        }
        
        # Normalize the input (lowercase for matching)
        target_lang_key = target_language.lower().strip()
        target_lang_name = language_names.get(target_lang_key, target_language)
        
        print(f"[TRANSLATE HTML] Input language: '{target_language}' -> Target: '{target_lang_name}'")
        
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                return html_content, "OpenAI API key is required for translation. Please configure OPENAI_API_KEY in your environment."
            
            # Build system message for HTML translation
            system_message = {
                "role": "system",
                "content": f"""You are a professional translator. CRITICAL RULE: You MUST translate the HTML content to {target_lang_name}. The ENTIRE output must be in {target_lang_name}, NOT in English. Preserve ALL HTML tags exactly."""
            }
            
            # Build translation prompt for HTML content
            translation_prompt = f"""You are a professional translator. Translate the following HTML content to {target_lang_name} while preserving ALL HTML tags, attributes, styles, and structure EXACTLY as they are.

CRITICAL RULES:
1. PRESERVE ALL HTML TAGS: Keep ALL HTML tags (<div>, <h1>, <p>, <span>, etc.) EXACTLY as they are
2. PRESERVE ALL ATTRIBUTES: Keep ALL attributes (style, class, id, etc.) EXACTLY as they are
3. PRESERVE ALL STYLES: Keep ALL inline styles EXACTLY as they are - do NOT translate CSS values
4. TRANSLATE ONLY TEXT: Translate ONLY the visible text content inside HTML tags
5. PRESERVE STRUCTURE: Keep the exact same HTML structure and nesting
6. PRESERVE NUMBERS AND DATES: Do NOT translate numbers, dates, or special formatting
7. PRESERVE ENTITY NAMES: If party names or company names appear, preserve them as-is unless they are generic placeholders
8. DO NOT ADD MARKDOWN: Do NOT wrap the output in markdown code blocks (```html or ```). Return ONLY the raw HTML without any markdown syntax.

HTML content to translate:
{html_content}

Return ONLY the translated HTML with the same structure, tags, and attributes. Only translate the text content. Do NOT wrap in markdown code blocks or add any markdown syntax."""
            
            result, error = self._call_openai(translation_prompt, system_messages=[system_message])
            if error:
                return html_content, error
            
            print(f"[TRANSLATE HTML] Translation completed. Result length: {len(result)} chars")
            
            # Remove markdown code blocks if AI added them (```html ... ``` or ``` ... ```)
            result = result.strip()
            if result.startswith('```html'):
                result = result[7:].strip()  # Remove ```html
            elif result.startswith('```'):
                result = result[3:].strip()  # Remove ```
            
            if result.endswith('```'):
                result = result[:-3].strip()  # Remove closing ```
            
            return result.strip(), None
            
        except Exception as e:
            return html_content, f"Error translating HTML content: {str(e)}"
    
    def _translate_single_chunk(self, text, target_lang_name):
        """Translate a single chunk of text"""
        print(f"[DEBUG TRANSLATE] Target language: {target_lang_name}")
        print(f"[DEBUG TRANSLATE] Text length: {len(text)} chars")
        print(f"[DEBUG TRANSLATE] First 200 chars: {text[:200]}")
        
        # Build system message for translation
        system_message = {
            "role": "system",
            "content": f"""You are a professional translator. CRITICAL RULE: You MUST translate the document to {target_lang_name}. The ENTIRE output must be in {target_lang_name}, NOT in English or any other language. This is your PRIMARY and ONLY task."""
        }
        
        translation_prompt = f"""You are a professional legal translator specializing in legal contracts and agreements. 

⚠️ **CRITICAL INSTRUCTION - READ FIRST:**
Your PRIMARY task is to translate this document to {target_lang_name}. The output MUST be in {target_lang_name}, NOT in English or any other language.

Translate the following legal contract document to {target_lang_name} while maintaining PERFECT formatting and legal accuracy.

🚨 CRITICAL TRANSLATION RULES - FOLLOW EXACTLY:

**1. TARGET LANGUAGE REQUIREMENT (HIGHEST PRIORITY):**
   - The ENTIRE translated output MUST be in {target_lang_name}
   - Translate ALL text content to {target_lang_name}
   - Do NOT keep text in English unless it's in the "DO NOT TRANSLATE" list below
   - Section headers, paragraphs, legal terms - EVERYTHING must be in {target_lang_name}

**2. PRESERVE ALL FORMATTING (MANDATORY):**
   - Keep ALL markdown syntax EXACTLY as they are: ##, ###, **, -, 1., 2., etc.
   - Maintain ALL section headers, bullet points, numbered lists, paragraph breaks
   - Keep ALL blank lines between sections
   - Preserve ALL indentation and spacing
   - Keep ALL bold/italic markers (**text**, *text*)

**3. DO NOT TRANSLATE THESE (KEEP AS-IS):**
   - ❌ Party names (company names, person names) - KEEP ORIGINAL
   - ❌ Dates in any format - KEEP ORIGINAL
   - ❌ Currency amounts ($, ৳, ₹, etc.) - KEEP ORIGINAL
   - ❌ Addresses - KEEP ORIGINAL
   - ❌ Placeholder text: "(_____________)" - KEEP EXACTLY AS-IS
   - ❌ Email addresses - KEEP ORIGINAL
   - ❌ Phone numbers - KEEP ORIGINAL
   - ❌ URLs and web links - KEEP ORIGINAL
   - ❌ Section reference markers like "## SECTION NAME" - translate only the section name, keep ## symbol

**4. HTML PRESERVATION (ABSOLUTELY CRITICAL):**
   - Preserve ALL HTML tags EXACTLY: <div>, <img>, <a>, <p>, <span>, etc.
   - Preserve ALL HTML attributes: style="...", src="...", href="...", target="...", etc.
   - Preserve ALL inline CSS styles completely unchanged
   - **SIGNATURE IMAGES**: 
     * Keep ALL <img> tags with src="data:image/..." base64 data COMPLETELY UNCHANGED
     * Keep ALL <div> tags containing signature images COMPLETELY UNCHANGED
     * Do NOT modify, shorten, or translate ANY part of base64 image data
     * Do NOT translate text inside signature divs
   - **CLICKABLE LINKS**:
     * Keep ALL <a href="..."> anchor tags EXACTLY as they are
     * Do NOT translate URLs inside href="..." attributes
     * Do NOT modify target="_blank" or any other attributes
     * Example: [<a href="http://example.com" target="_blank">Source: Act 1872</a>]
       - Translate "Source: Act 1872" to target language
       - Keep <a href="http://example.com" target="_blank"> and </a> EXACTLY as-is

**5. LEGAL TERMINOLOGY:**
   - Use proper, formal legal terminology in {target_lang_name}
   - Maintain professional, formal tone throughout
   - Use standard legal phrases used in {target_lang_name} legal documents
   - Translate legal concepts accurately (e.g., "shall" → appropriate formal equivalent)

**6. STRUCTURE PRESERVATION:**
   - Keep ALL sections in same order
   - Maintain ALL sub-sections and sub-headers
   - Preserve ALL enumeration (1., 2., 3. or (a), (b), (c))
   - Keep contract header format unchanged (only translate text, keep structure)

**7. SPECIAL HANDLING:**
   - "the Agreement" → translate but keep quote marks
   - "the Parties" → translate but keep quote marks  
   - Legal definitions in quotes → translate but maintain quotes
   - Technical terms → use {target_lang_name} legal equivalent

**EXAMPLES:**

WRONG Translation (DO NOT DO THIS):
```
## পেমেন্ট
মোট খরচ হবে ($_______) 
[লিঙ্ক: আইন 1872] ❌ NO HREF!
```

CORRECT Translation (DO THIS):
```
## পেমেন্ট / ক্ষতিপূরণ
মোট খরচ হবে $(_____________) 
[<a href="http://bdlaws.minlaw.gov.bd/act-367.html" target="_blank">সূত্র: চুক্তি আইন ১৮৭২</a>] ✅ HREF PRESERVED!
```

Document to translate:
{text}

⚠️ CRITICAL REMINDERS:
1. Output language MUST be {target_lang_name} - NOT English
2. Return ONLY the translated document in {target_lang_name}
3. Do NOT add any explanations, notes, or comments
4. Preserve ALL formatting, HTML tags, URLs, links, and base64 image data EXACTLY as they appear
5. Translate ALL text content to {target_lang_name} (except items in "DO NOT TRANSLATE" list)"""
        
        result, error = self._call_openai(translation_prompt, system_messages=[system_message])
        if error:
            return None, error
        
        # Remove markdown code blocks if AI added them
        result = result.strip()
        if result.startswith('```'):
            # Remove opening ``` or ```markdown
            lines = result.split('\n')
            if lines[0].strip().startswith('```'):
                lines = lines[1:]  # Remove first line
            # Remove closing ```
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]  # Remove last line
            result = '\n'.join(lines).strip()
        
        print(f"[DEBUG TRANSLATE] Translation completed. Result length: {len(result)} chars")
        print(f"[DEBUG TRANSLATE] First 200 chars of result: {result[:200]}")
        return result.strip(), None
    
    def validate_legal_requirement(self, user_prompt, contract_type="service_agreement", jurisdiction="bangladesh"):
        """
        Validate if user requirement is legal by using OpenAI to search and analyze.
        Returns: (is_legal: bool, validation_result: dict, error: str)
        validation_result contains: is_legal, reason, references (list of URLs), warning_message
        """
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                # Fallback to Gemini if OpenAI not available
                if not self.genai or not self.gemini_api_key:
                    return True, {"is_legal": True, "reason": "Validation unavailable - no API key", "references": []}, None
                # Use Gemini instead
                return self._validate_with_gemini(user_prompt, contract_type, jurisdiction)
            
            # STEP 1: First analyze the requirement WITHOUT search (quick check)
            print(f"[LEGAL_VALIDATION] Step 1/3: Analyzing requirement for legal compliance (without search)...")
            validation_result = self._analyze_requirement_without_search(user_prompt, contract_type, jurisdiction)
            
            # STEP 2: Always search internet for legal references (for both legal and illegal requirements)
            is_illegal = not validation_result.get('is_legal', True)
            if is_illegal:
                print(f"[LEGAL_VALIDATION] Step 2/3: Requirement is ILLEGAL - Searching internet for legal references...")
            else:
                print(f"[LEGAL_VALIDATION] Step 2/3: Requirement is LEGAL - Searching internet for legal references...")
            
            # Generate search queries for legal references
            search_queries = self._generate_search_queries_with_openai(user_prompt, contract_type, jurisdiction)
            print(f"[LEGAL_VALIDATION] Search queries: {search_queries}")
            
            # Search internet for legal references
            search_results = self._search_internet_for_legal_info(search_queries, jurisdiction)
            print(f"[LEGAL_VALIDATION] Found {len(search_results)} search results")
            if search_results:
                print(f"[LEGAL_VALIDATION] Sample search result: {search_results[0].get('url', 'N/A')}")
            else:
                print(f"[LEGAL_VALIDATION] WARNING: No search results returned!")
            
            # STEP 3: Add search results as references
            print(f"[LEGAL_VALIDATION] Step 3/3: Adding search results as references...")
            references = []
            
            # CRITICAL: Always add search results as references if available
            if search_results and len(search_results) > 0:
                print(f"[LEGAL_VALIDATION] Processing {len(search_results)} search results...")
                # Use ALL search results as references (minimum 5, maximum 15)
                for result in search_results:
                    if len(references) >= 15:  # Max 15
                        break
                    url = result.get('url', '')
                    if url:  # Only add if URL exists
                        # Check for duplicates
                        if not any(ref.get('url') == url for ref in references):
                            references.append({
                                "url": url,
                                "title": result.get('title', result.get('url', 'Unknown')),
                                "source": result.get('source', 'Internet Search'),
                                "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                            })
                
                # Ensure minimum 5 references
                if len(references) < 5:
                    print(f"[LEGAL_VALIDATION] WARNING: Only {len(references)} references, trying to add more...")
                    # Add more from search_results if available
                    for result in search_results:
                        if len(references) >= 15:
                            break
                        url = result.get('url', '')
                        if url and not any(ref.get('url') == url for ref in references):
                            references.append({
                                "url": url,
                                "title": result.get('title', result.get('url', 'Unknown')),
                                "source": result.get('source', 'Internet Search'),
                                "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                            })
                
                print(f"[LEGAL_VALIDATION] Added {len(references)} references from search results")
            else:
                print(f"[LEGAL_VALIDATION] WARNING: No search results available! Trying fallback search...")
                # Try fallback search with simpler queries
                from core.jurisdiction_rules import get_jurisdiction_rules
                jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
                jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
                
                fallback_queries = [
                    f"{jurisdiction_name} law",
                    f"{jurisdiction_name} legal system",
                    f"{jurisdiction_name} contract law",
                    f"{jurisdiction_name} illegal activities",
                    f"{jurisdiction_name} Penal Code",
                    f"{jurisdiction_name} prostitution law",
                    f"{jurisdiction_name} human trafficking law"
                ]
                fallback_results = self._search_internet_for_legal_info(fallback_queries, jurisdiction)
                
                if fallback_results:
                    print(f"[LEGAL_VALIDATION] Fallback search found {len(fallback_results)} results")
                    for result in fallback_results[:15]:
                        if len(references) >= 15:
                            break
                        url = result.get('url', '')
                        if url and not any(ref.get('url') == url for ref in references):
                            references.append({
                                "url": url,
                                "title": result.get('title', result.get('url', 'Unknown')),
                                "source": result.get('source', 'Internet Search'),
                                "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                            })
                    print(f"[LEGAL_VALIDATION] Added {len(references)} references from fallback search")
                else:
                    print(f"[LEGAL_VALIDATION] ERROR: Fallback search also returned no results!")
            
            # CRITICAL: Ensure references is always a list and add to validation_result
            if not isinstance(references, list):
                references = []
            
            # CRITICAL: Force add references to validation_result (always, for both legal and illegal)
            validation_result['references'] = references
            print(f"[LEGAL_VALIDATION] Final references count in validation_result: {len(validation_result.get('references', []))}")
            
            # Debug: Print first few references
            if references:
                for i, ref in enumerate(references[:3], 1):
                    print(f"[LEGAL_VALIDATION] Reference {i}: {ref.get('url', 'N/A')}")
            else:
                print(f"[LEGAL_VALIDATION] ERROR: Still no references after all attempts!")
                print(f"[LEGAL_VALIDATION] Search results count: {len(search_results) if search_results else 0}")
                print(f"[LEGAL_VALIDATION] Validation result keys: {list(validation_result.keys())}")
            
            refs = validation_result.get('references', [])
            print(f"[LEGAL_VALIDATION] Analysis complete - Legal: {validation_result.get('is_legal', True)}, References: {len(refs)}")
            
            # Final check: Print references for debugging (for both legal and illegal)
            if refs:
                print(f"[LEGAL_VALIDATION] Final references count: {len(refs)}")
                for i, ref in enumerate(refs[:3], 1):
                    print(f"[LEGAL_VALIDATION] Reference {i}: {ref.get('url', 'N/A')}")
            else:
                print(f"[LEGAL_VALIDATION] WARNING: No references available in validation_result!")
            
            return validation_result.get('is_legal', True), validation_result, None
            
        except Exception as e:
            logger.error(f"Error in legal validation: {e}")
            return True, {"is_legal": True, "reason": f"Validation error: {str(e)}", "references": []}, None
    
    def _generate_search_queries_with_openai(self, user_prompt, contract_type, jurisdiction):
        """Use OpenAI to generate optimal search queries for legal validation"""
        try:
            import openai
            
            # Get jurisdiction-specific context
            from core.jurisdiction_rules import get_jurisdiction_rules
            jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
            jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
            
            query_prompt = f"""You are a legal research assistant. Generate 5-7 specific search queries to find legal information about whether this contract requirement is legal or illegal in {jurisdiction_name}.

Contract Type: {contract_type.replace('_', ' ').title()}
Jurisdiction: {jurisdiction_name} ({jurisdiction})
User Requirement: {user_prompt}

IMPORTANT: All search queries MUST include "{jurisdiction_name}" or "{jurisdiction}" to ensure jurisdiction-specific results.

Generate search queries that will help find:
1. {jurisdiction_name} legal precedents or cases related to this requirement
2. {jurisdiction_name} laws and regulations on this topic
3. Legal analysis or opinions about similar requirements in {jurisdiction_name}
4. {jurisdiction_name} government or legal authority guidance
5. {jurisdiction_name} contract law requirements
6. {jurisdiction_name} legal compliance issues

Return ONLY a valid JSON object with a "queries" array:
{{
    "queries": ["query 1 with {jurisdiction_name}", "query 2 with {jurisdiction_name}", ...]
}}

Each query MUST include "{jurisdiction_name}" or "{jurisdiction}" and be specific to this jurisdiction."""
            
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            
            response = client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": query_prompt}],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = response.choices[0].message.content
            
            # Parse JSON response
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                result = result.split("```")[1].split("```")[0].strip()
            
            data = json.loads(result)
            
            # Extract queries from JSON (could be in "queries" key or direct array)
            if isinstance(data, dict):
                queries = data.get("queries", data.get("search_queries", []))
            else:
                queries = data if isinstance(data, list) else []
            
            # Fallback: generate from requirement if OpenAI didn't return proper format
            if not queries or len(queries) == 0:
                jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
                queries = [
                    f"{user_prompt} {jurisdiction_name} legal law",
                    f"{contract_type.replace('_', ' ')} {jurisdiction_name} law",
                    f"{user_prompt} illegal {jurisdiction_name}",
                    f"{jurisdiction_name} contract law requirements",
                    f"{jurisdiction_name} legal compliance {user_prompt[:50]}"
                ]
            
            # Ensure all queries include jurisdiction
            jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
            final_queries = []
            for query in queries[:7]:  # Up to 7 queries
                # Add jurisdiction if not present
                if jurisdiction_name.lower() not in query.lower() and jurisdiction.lower() not in query.lower():
                    query = f"{query} {jurisdiction_name}"
                final_queries.append(query)
            
            return final_queries
            
        except Exception as e:
            logger.warning(f"Error generating search queries with OpenAI: {e}")
            # Fallback queries with jurisdiction
            from core.jurisdiction_rules import get_jurisdiction_rules
            jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
            jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
            return [
                f"{user_prompt} {jurisdiction_name} legal law",
                f"{contract_type.replace('_', ' ')} {jurisdiction_name} law",
                f"{user_prompt} illegal {jurisdiction_name}",
                f"{jurisdiction_name} contract law",
                f"{jurisdiction_name} legal requirements"
            ]
    
    def _analyze_requirement_without_search(self, user_prompt, contract_type, jurisdiction):
        """Analyze requirement for legality WITHOUT internet search (fast initial check)"""
        try:
            import openai
            
            # Get jurisdiction-specific context
            from core.jurisdiction_rules import get_jurisdiction_rules
            jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
            jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
            
            analysis_prompt = f"""You are an expert legal compliance analyst specializing in {jurisdiction_name} law. Analyze the following contract requirement and determine if it contains any illegal, unethical, or legally problematic elements under {jurisdiction_name} law.

Contract Type: {contract_type.replace('_', ' ').title()}
Jurisdiction: {jurisdiction_name} ({jurisdiction})
User Requirement: {user_prompt}

IMPORTANT: Analyze specifically under {jurisdiction_name} law and regulations. Consider:
1. {jurisdiction_name}-specific illegal activities (money laundering, fraud, tax evasion, illegal services, criminal activities, prostitution, human trafficking)
2. {jurisdiction_name} unenforceable clauses (unfair terms, illegal penalties, void conditions under {jurisdiction_name} law)
3. {jurisdiction_name} regulatory violations (labor law violations, consumer protection violations, licensing issues)
4. Ethical concerns under {jurisdiction_name} legal framework (exploitative terms, discrimination, human rights violations)

Return ONLY a valid JSON object:
{{
    "is_legal": true/false,
    "reason": "Detailed explanation specific to {jurisdiction_name} law of why it's legal or illegal, citing specific {jurisdiction_name} laws or regulations if possible (e.g., Penal Code Section 370, Contract Act 1872)",
    "illegal_elements": ["list of specific illegal elements under {jurisdiction_name} law if any"],
    "warning_level": "none/low/medium/high"
}}

Be thorough and cite specific {jurisdiction_name} legal issues. If illegal, explain which {jurisdiction_name} laws or regulations are violated."""
            
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            
            response = client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": analysis_prompt}],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            result = response.choices[0].message.content
            
            # Parse JSON response
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                result = result.split("```")[1].split("```")[0].strip()
            
            validation_data = json.loads(result)
            is_legal = validation_data.get("is_legal", True)
            
            return {
                "is_legal": is_legal,
                "reason": validation_data.get("reason", "Requirement may contain illegal elements"),
                "illegal_elements": validation_data.get("illegal_elements", []),
                "warning_level": validation_data.get("warning_level", "medium"),
                "references": [],  # Will be added later if illegal
                "warning_message": f"Legal Warning: {validation_data.get('reason', 'This requirement may contain illegal or problematic elements.')}"
            }
                
        except Exception as e:
            logger.error(f"Error in requirement analysis: {e}")
            return {
                "is_legal": True,
                "reason": f"Analysis error: {str(e)}",
                "references": []
            }
    
    def _analyze_with_openai(self, user_prompt, contract_type, jurisdiction, search_results):
        """Use OpenAI to analyze search results and determine legality"""
        try:
            import openai
            
            # Get jurisdiction-specific context
            from core.jurisdiction_rules import get_jurisdiction_rules
            jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
            jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
            
            # Build search context with jurisdiction-specific results
            search_context = ""
            if search_results:
                search_context = f"\n\nINTERNET SEARCH RESULTS (from {jurisdiction_name}):\n"
                for i, result in enumerate(search_results[:15], 1):  # Use top 15 results for better analysis
                    search_context += f"{i}. Title: {result.get('title', 'No title')}\n"
                    search_context += f"   URL: {result.get('url', '')}\n"
                    search_context += f"   Content: {result.get('snippet', '')[:300]}...\n\n"
            else:
                search_context = f"\n\nNote: No search results found for {jurisdiction_name}, analyze based on {jurisdiction_name} legal knowledge only.\n"
            
            analysis_prompt = f"""You are an expert legal compliance analyst specializing in {jurisdiction_name} law. Analyze the following contract requirement and determine if it contains any illegal, unethical, or legally problematic elements under {jurisdiction_name} law.

Contract Type: {contract_type.replace('_', ' ').title()}
Jurisdiction: {jurisdiction_name} ({jurisdiction})
User Requirement: {user_prompt}
{search_context}

IMPORTANT: Analyze specifically under {jurisdiction_name} law and regulations. Consider:
1. {jurisdiction_name}-specific illegal activities (money laundering, fraud, tax evasion, illegal services, criminal activities)
2. {jurisdiction_name} unenforceable clauses (unfair terms, illegal penalties, void conditions under {jurisdiction_name} law)
3. {jurisdiction_name} regulatory violations (labor law violations, consumer protection violations, licensing issues)
4. Ethical concerns under {jurisdiction_name} legal framework (exploitative terms, discrimination, human rights violations)

Return ONLY a valid JSON object:
{{
    "is_legal": true/false,
    "reason": "Detailed explanation specific to {jurisdiction_name} law of why it's legal or illegal, citing specific {jurisdiction_name} laws or regulations if possible",
    "illegal_elements": ["list of specific illegal elements under {jurisdiction_name} law if any"],
    "warning_level": "none/low/medium/high",
    "relevant_urls": ["list of most relevant URLs from search results that support your {jurisdiction_name}-specific analysis"]
}}

Be thorough and cite specific {jurisdiction_name} legal issues. If illegal, explain which {jurisdiction_name} laws or regulations are violated. Prioritize URLs that are specific to {jurisdiction_name}."""
            
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            
            response = client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": analysis_prompt}],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            result = response.choices[0].message.content
            
            # Parse JSON response
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                result = result.split("```")[1].split("```")[0].strip()
            
            validation_data = json.loads(result)
            is_legal = validation_data.get("is_legal", True)
            
            # Build references from search results - ALWAYS include search results as references if illegal
            references = []
            relevant_urls = validation_data.get("relevant_urls", [])
            
            # CRITICAL: Always use search results as references if illegal (don't depend on OpenAI's relevant_urls)
            if search_results:
                # Prioritize legal/authoritative sources
                legal_domains = ['gov', 'edu', 'org', 'wikipedia', 'law', 'legal', 'court', 'legislation', 'justice', 'ministry']
                prioritized = []
                others = []
                
                for result in search_results:
                    url = result.get('url', '')
                    if url:  # Only add if URL exists
                        url_lower = url.lower()
                        if any(domain in url_lower for domain in legal_domains):
                            prioritized.append(result)
                        else:
                            others.append(result)
                
                # Add prioritized legal sources first (up to 10), then others (up to 5) - minimum 5 total
                for result in prioritized[:10]:
                    if len(references) >= 15:  # Max 15 references
                        break
                    references.append({
                        "url": result.get('url', ''),
                        "title": result.get('title', result.get('url', 'Unknown')),
                        "source": result.get('source', 'Internet Search'),
                        "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                    })
                
                # Add other results if we have space (ensure minimum 5)
                for result in others:
                    if len(references) >= 15:  # Max 15 references
                        break
                    if len(references) < 5 or result.get('url'):  # Ensure at least 5
                        references.append({
                            "url": result.get('url', ''),
                            "title": result.get('title', result.get('url', 'Unknown')),
                            "source": result.get('source', 'Internet Search'),
                            "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                        })
                
                # Final fallback: if still less than 5 references, use ANY search results
                if len(references) < 5:
                    print(f"[LEGAL_VALIDATION] WARNING: Only {len(references)} references, using all search results to reach minimum 5")
                    for result in search_results:
                        if len(references) >= 15:  # Max 15
                            break
                        url = result.get('url', '')
                        if url and not any(ref.get('url') == url for ref in references):
                            references.append({
                                "url": url,
                                "title": result.get('title', result.get('url', 'Unknown')),
                                "source": result.get('source', 'Internet Search'),
                                "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                            })
                
                print(f"[LEGAL_VALIDATION] Built {len(references)} references from {len(search_results)} search results")
            else:
                print(f"[LEGAL_VALIDATION] WARNING: No search results available for references")
            
            if is_legal:
                return {
                    "is_legal": True,
                    "reason": validation_data.get("reason", "Requirement appears to be legal"),
                    "references": []
                }
            else:
                # CRITICAL: Ensure references are always included if illegal
                if not references or len(references) == 0:
                    print(f"[LEGAL_VALIDATION] ERROR: Illegal but no references! Using all search results...")
                    if search_results:
                        references = []
                        for result in search_results[:15]:
                            if result.get('url'):
                                references.append({
                                    "url": result.get('url', ''),
                                    "title": result.get('title', result.get('url', 'Unknown')),
                                    "source": result.get('source', 'Internet Search'),
                                    "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                                })
                        print(f"[LEGAL_VALIDATION] Added {len(references)} references from all search results")
                
                # Final check: ensure minimum 5 references
                if len(references) < 5 and search_results:
                    print(f"[LEGAL_VALIDATION] WARNING: Only {len(references)} references, adding more to reach 5...")
                    for result in search_results:
                        if len(references) >= 15:
                            break
                        url = result.get('url', '')
                        if url and not any(ref.get('url') == url for ref in references):
                            references.append({
                                "url": url,
                                "title": result.get('title', result.get('url', 'Unknown')),
                                "source": result.get('source', 'Internet Search'),
                                "snippet": result.get('snippet', '')[:200] if result.get('snippet') else ''
                            })
                    print(f"[LEGAL_VALIDATION] Now have {len(references)} references")
                
                print(f"[LEGAL_VALIDATION] Returning illegal result with {len(references)} references")
                return {
                    "is_legal": False,
                    "reason": validation_data.get("reason", "Requirement may contain illegal elements"),
                    "illegal_elements": validation_data.get("illegal_elements", []),
                    "warning_level": validation_data.get("warning_level", "medium"),
                    "references": references if references else [],  # Ensure it's always a list
                    "warning_message": f"Legal Warning: {validation_data.get('reason', 'This requirement may contain illegal or problematic elements.')}"
                }
                
        except Exception as e:
            logger.error(f"Error in OpenAI analysis: {e}")
            return {
                "is_legal": True,
                "reason": f"Analysis error: {str(e)}",
                "references": []
            }
    
    def _validate_with_gemini(self, user_prompt, contract_type, jurisdiction):
        """Fallback validation using Gemini if OpenAI not available"""
        try:
            search_results = self._search_internet_for_legal_info(
                [f"{user_prompt} {jurisdiction} legal"],
                jurisdiction
            )
            
            search_context = ""
            if search_results:
                search_context = "\n\nSEARCH RESULTS:\n"
                for i, result in enumerate(search_results[:5], 1):
                    search_context += f"{i}. {result.get('title', '')}\n   {result.get('url', '')}\n   {result.get('snippet', '')[:200]}\n\n"
            
            prompt = f"""Analyze if this contract requirement is legal:

Contract Type: {contract_type.replace('_', ' ').title()}
Jurisdiction: {jurisdiction.title()}
Requirement: {user_prompt}
{search_context}

Return JSON: {{"is_legal": true/false, "reason": "...", "illegal_elements": [], "warning_level": "..."}}"""
            
            result, error = self._make_api_call_with_retry(prompt)
            if error:
                return True, {"is_legal": True, "reason": "Validation unavailable", "references": []}, None
            
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0].strip()
            
            data = json.loads(result)
            is_legal = data.get("is_legal", True)
            
            references = []
            if not is_legal and search_results:
                for result in search_results[:5]:
                    references.append({
                        "url": result.get('url', ''),
                        "title": result.get('title', ''),
                        "source": "Internet Search",
                        "snippet": result.get('snippet', '')[:200]
                    })
            
            if is_legal:
                return True, {"is_legal": True, "reason": data.get("reason", ""), "references": []}, None
            else:
                return False, {
                    "is_legal": False,
                    "reason": data.get("reason", ""),
                    "illegal_elements": data.get("illegal_elements", []),
                    "warning_level": data.get("warning_level", "medium"),
                    "references": references,
                    "warning_message": f"⚠️ Legal Warning: {data.get('reason', '')}"
                }, None
                
        except Exception as e:
            logger.error(f"Error in Gemini validation: {e}")
            return True, {"is_legal": True, "reason": "Validation error", "references": []}, None
    
    def _search_internet_for_legal_info(self, search_queries, jurisdiction):
        """
        Search the internet for legal information using OpenAI Web Search/Browsing.
        Returns list of search results with URLs, titles, and snippets.
        Uses ONLY OpenAI API for web search.
        
        Args:
            search_queries: List of search query strings (generated by OpenAI)
            jurisdiction: Jurisdiction name
        """
        search_results = []
        
        try:
            # If single string provided, convert to list
            if isinstance(search_queries, str):
                search_queries = [search_queries]
            
            # Check OpenAI API key
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                logger.error("OpenAI API key not found. Cannot perform web search.")
                return []
            
            import openai
            client = openai.OpenAI(api_key=openai_api_key)
            openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            
            print(f"[WEB_SEARCH] Using OpenAI Web Search for {len(search_queries)} queries...")
            
            # Search for each query using OpenAI
            for query in search_queries:
                if len(search_results) >= 15:  # Limit total results
                    break
                
                print(f"[WEB_SEARCH] Searching with OpenAI for: {query}")
                
                try:
                    # Get jurisdiction name for jurisdiction-specific search
                    from core.jurisdiction_rules import get_jurisdiction_rules
                    jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
                    jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
                    
                    # Use OpenAI to search and return URLs in JSON format
                    search_prompt = f"""Search the internet for legal information about: {query}

CRITICAL: This search is for {jurisdiction_name} ({jurisdiction}) legal information. You MUST search for and return URLs that are specific to {jurisdiction_name} laws, regulations, court cases, and legal authorities.

Search for:
- {jurisdiction_name} laws and regulations
- {jurisdiction_name} legal precedents and court cases  
- {jurisdiction_name} government legal documents and websites
- {jurisdiction_name} legal authority websites (.gov, .edu, .org domains from {jurisdiction_name})
- {jurisdiction_name} legal analysis and commentary

Please provide at least 5-10 relevant URLs (websites, articles, legal documents) with:
1. Full URL (must be valid HTTP/HTTPS URL)
2. Title or description of the page
3. Brief snippet (1-2 sentences) describing the content

Focus on legal/authoritative sources (.gov, .edu, .org, legal websites, court documents, legislation) specific to {jurisdiction_name}.

Format your response as JSON with this structure:
{{
    "search_results": [
        {{
            "url": "https://example.com/page",
            "title": "Page Title",
            "snippet": "Brief description of the content"
        }}
    ]
}}

IMPORTANT: 
- Return ONLY valid URLs. Ensure all URLs are complete and accessible.
- Prioritize {jurisdiction_name}-specific legal sources.
- Include URLs from {jurisdiction_name} government websites, legal institutions, and authoritative legal sources."""
                    
                    response = client.chat.completions.create(
                        model=openai_model,
                        messages=[{"role": "user", "content": search_prompt}],
                        temperature=0.3,
                        response_format={"type": "json_object"}
                    )
                    
                    result = response.choices[0].message.content
                    
                    # Parse JSON response
                    if "```json" in result:
                        result = result.split("```json")[1].split("```")[0].strip()
                    elif "```" in result:
                        result = result.split("```")[1].split("```")[0].strip()
                    
                    data = json.loads(result)
                    openai_results = data.get("search_results", [])
                    
                    if openai_results:
                        print(f"[WEB_SEARCH] Found {len(openai_results)} results from OpenAI for: {query}")
                        for result_item in openai_results:
                            url = result_item.get('url', '').strip()
                            if url and url.startswith(('http://', 'https://')):
                                # Check for duplicates
                                if not any(ref.get('url') == url for ref in search_results):
                                    search_results.append({
                                        "url": url,
                                        "title": result_item.get('title', result_item.get('url', 'Unknown'))[:200],
                                        "snippet": result_item.get('snippet', '')[:200],
                                        "source": "OpenAI Web Search"
                                    })
                    else:
                        print(f"[WEB_SEARCH] No results found in OpenAI response for: {query}")
                
                except json.JSONDecodeError as e:
                    print(f"[WEB_SEARCH] Failed to parse OpenAI JSON response: {e}")
                    # Try to extract URLs from raw response
                    import re
                    urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', result)
                    if urls:
                        print(f"[WEB_SEARCH] Extracted {len(urls)} URLs from raw response")
                        for url in urls[:5]:
                            if not any(ref.get('url') == url for ref in search_results):
                                search_results.append({
                                    "url": url,
                                    "title": f"Legal Reference - {query[:50]}",
                                    "snippet": "",
                                    "source": "OpenAI Web Search"
                                })
                
                except Exception as e:
                    print(f"[WEB_SEARCH] OpenAI search failed for query '{query}': {e}")
                    continue
            
            # Filter results to prioritize legal/authoritative sources
            legal_domains = ['gov', 'edu', 'org', 'wikipedia', 'law', 'legal', 'court', 'legislation', 'justice', 'ministry']
            prioritized_results = []
            other_results = []
            
            for result in search_results:
                url_lower = result.get('url', '').lower()
                if any(domain in url_lower for domain in legal_domains):
                    prioritized_results.append(result)
                else:
                    other_results.append(result)
            
            # Combine: legal sources first, then others (ensure at least 5, can return up to 15)
            min_results = 5
            max_results = 15
            final_results = prioritized_results[:10] + other_results[:5]
            
            # Ensure minimum 5 results if available
            if len(final_results) < min_results and len(search_results) >= min_results:
                # Add more from original search_results
                for result in search_results:
                    if len(final_results) >= max_results:
                        break
                    url = result.get('url', '')
                    if url and not any(ref.get('url') == url for ref in final_results):
                        final_results.append(result)
            
            print(f"[WEB_SEARCH] Total {len(final_results)} results from OpenAI Web Search")
            return final_results[:max_results]  # Return up to 15 results
            
        except Exception as e:
            logger.error(f"Error in OpenAI internet search: {e}")
            return []