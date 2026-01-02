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
            if not contract_info.get('start_date'):
                contract_info['start_date'] = today_date
            
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
    "start_date": "Application date in YYYY-MM-DD format (use '{today_date}' if not specified)",
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
    "start_date": "Agreement date in YYYY-MM-DD format (use '{today_date}' if not specified)",
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
    "start_date": "Start date in YYYY-MM-DD format (use '{today_date}' if not specified)",
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
    
    def _call_openai(self, prompt):
        """Call OpenAI API"""
        try:
            import openai
        except ImportError:
            return None, "OpenAI Python package not installed. Please run: pip install openai"
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        
        try:
            try:
                client = openai.OpenAI(api_key=openai_api_key)
                completion = client.chat.completions.create(
                    model=openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0
                )
                result = completion.choices[0].message.content
            except AttributeError:
                openai.api_key = openai_api_key
                completion = openai.ChatCompletion.create(
                    model=openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0
                )
                result = completion.choices[0].message["content"]
            return result, None
        except Exception as e:
            return None, f"Error calling OpenAI API: {str(e)}"
    
    def _stream_openai(self, prompt):
        """Stream OpenAI API responses"""
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
        
        try:
            client = openai.OpenAI(api_key=openai_api_key)
            stream = client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": prompt}],
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
            
            result, error = self._call_openai(consolidated_prompt)
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
            
            for chunk in self._stream_openai(consolidated_prompt):
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
        
        date_str = start_date.strftime('%B %d, %Y') if hasattr(start_date, 'strftime') else str(start_date)
        
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
        
        base_prompt = f"""You are an expert legal contract writer specializing in {contract_type_name} under {jurisdiction_name} law. You draft comprehensive, professional, and legally sound contracts suitable for execution between parties.

CRITICAL - CONTENT RELEVANCE AND STANDARDIZATION:
- Generate RELEVANT content that is appropriate and standard for a {contract_type_name}
- Use industry-standard legal terminology, clauses, and structures for this contract type
- Ensure ALL clauses and sections are standard, legally recognized, and appropriate for this specific contract type
- Follow best practices and conventional legal standards for {contract_type_name}
- Generate content that is consistent with how professional {contract_type_name} contracts are typically structured
- Ensure all legal clauses are relevant, standard, and appropriate for the contract type and jurisdiction
- DO NOT include irrelevant clauses or content that does not belong in a {contract_type_name}
- Use standard legal language and structures that are commonly found in professionally drafted {contract_type_name} contracts

IMPORTANT - LANGUAGE HANDLING:
- The user may provide requirements in ANY language (English, Bengali, Banglish, Hindi, or any other language)
- You MUST analyze and understand the requirements regardless of input language
- You MUST ALWAYS generate the contract in PROFESSIONAL ENGLISH only
- Extract all key information (names, amounts, dates, terms, conditions) from the input and convert to proper English

{developer_type_instruction}

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
1. **Formal Legal Language**: Use precise, formal legal terminology. Avoid casual language or abbreviations.
2. **Comprehensive Clauses**: Each section should be detailed with multiple sub-clauses where appropriate. Use numbered sub-clauses (1., 2., 3.) within sections for clarity.
3. **Specificity**: Be specific and detailed. Instead of vague terms, provide clear definitions and specifications.
4. **Professional Structure**: 
   - Use ## for main section headers
   - Use ### for sub-sections
   - Use numbered lists (1., 2., 3.) for sequential items
   - Use bullet points (-) only for non-sequential lists
5. **Complete Information**: Include all relevant details such as:
   - Specific deliverables with acceptance criteria
   - Detailed payment schedules with exact amounts and dates
   - Clear timelines with milestones
   - Comprehensive service descriptions
   - Quality standards and performance metrics
6. **Placeholder Usage - CRITICAL RULE**: 
   - **IF INFORMATION IS PROVIDED IN USER REQUIREMENTS**: Use the exact values mentioned by the user. Do NOT use placeholders for information that is explicitly provided.
   - **IF INFORMATION IS MISSING/NOT SPECIFIED**: You MUST use placeholder: (_____________)
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
7. **Legal Precision**: Use terms like "shall" (not "will"), "herein", "thereof", "pursuant to", "in accordance with"
8. **Completeness**: Ensure each section is comprehensive and covers all aspects that would be expected in a professional contract

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
      - DO NOT use redundant definitions like "(this \"Agreement\")" or "(the \"Effective Date\")" in parentheses
      - DO NOT repeat the word "Agreement" - for example, DO NOT write: "This Service Agreement ("Agreement")"
      - Write simply: "This Service Agreement is made and entered into..." WITHOUT adding ("Agreement") after the title
      - DO NOT include unnecessary lines like "referred to herein individually as a Party"
   
   b) **RECITALS SECTION** (if appropriate for this contract type):
      - Generate appropriate recitals/WHEREAS clauses based on contract type and context
      - Make it relevant to the specific agreement between {party1} and {party2}
      - Keep it professional and concise
   
   c) **MAIN CONTENT SECTIONS**:
      - Generate all required sections from the REQUIRED SECTIONS list above
      - Use section headers (##) with proper formatting
      - Include all specific details from user requirements
      - Make each section comprehensive and detailed
   
   d) **STANDARD LEGAL CLAUSES**:
      Generate appropriate standard legal clauses including (but not limited to):
      - Intellectual Property Rights (with relevant sub-clauses)
      - Confidentiality (with Definition, Obligations, Exceptions, Duration - use (_____________) if duration not specified)
      - Termination (with For Convenience, For Cause, Effect of Termination - use (_____________) for notice periods if not specified)
      - Limitation of Liability (with Limitation, Exclusion of Consequential Damages, Indemnification)
      - Governing Law and Dispute Resolution (appropriate for {jurisdiction_name})
      - General Provisions (Entire Agreement, Amendments, Waiver, Severability, Assignment, Notices, Force Majeure, Counterparts, etc.)
      
      **REMINDER**: For CONFIDENTIALITY Duration and TERMINATION notice periods - IF specified in user requirements, use those exact values. IF NOT specified, MUST use (_____________) placeholder. DO NOT invent values.
   
   e) **JURISDICTION-SPECIFIC CLAUSES**:
      Based on {jurisdiction_name} jurisdiction, generate appropriate clauses for:
      - Governing Law: {jurisdiction_instructions}
      - Court Jurisdiction and Dispute Resolution
      - Stamp Duty requirements (if applicable)
      - Registration requirements (if applicable)
      - Tax clauses (VAT/GST/other applicable taxes)
      - Consumer Protection (if applicable)
      - Data Protection (if applicable)
      - Any other jurisdiction-specific legal requirements

   **IMPORTANT**: Generate all content naturally using your expertise. Do NOT use hard-coded templates or fixed phrases. Create professional, context-appropriate content for each section based on the contract type, parties, and requirements.

**IMPORTANT - DO NOT GENERATE SIGNATURE BLOCKS:**
- Do NOT include "## SIGNATURES" section
- Do NOT create signature blocks
- Do NOT add signature lines or signature placeholders
- Do NOT include any closing statements like "This Agreement is executed as of the date first above written." or similar execution statements
- Do NOT add any text after the jurisdiction-specific clauses and general provisions
- End your contract immediately after the jurisdiction-specific clauses and general provisions - nothing else should follow
- The signature section will be added separately after generation

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
            'bn': 'Bengali (Bangla)',
            'hi': 'Hindi',
            'ar': 'Arabic',
            'english': 'English',
            'bengali': 'Bengali (Bangla)',
            'hindi': 'Hindi',
            'arabic': 'Arabic'
        }
        
        # Normalize the input (lowercase for matching)
        target_lang_key = target_language.lower().strip()
        target_lang_name = language_names.get(target_lang_key, target_language)
        
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
            'bn': 'Bengali (Bangla)',
            'hi': 'Hindi',
            'ar': 'Arabic',
            'english': 'English',
            'bengali': 'Bengali (Bangla)',
            'hindi': 'Hindi',
            'arabic': 'Arabic'
        }
        
        # Normalize the input (lowercase for matching)
        target_lang_key = target_language.lower().strip()
        target_lang_name = language_names.get(target_lang_key, target_language)
        
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
            translation_prompt = f"""You are a professional legal translator. Translate the following legal contract document to {target_lang_name} while maintaining perfect formatting and legal accuracy.

CRITICAL TRANSLATION RULES:
1. PRESERVE ALL FORMATTING: Keep all markdown syntax (##, ###, **, -, etc.) exactly as they are
2. MAINTAIN STRUCTURE: Keep all section headers, bullet points, numbered lists, and paragraph breaks
3. LEGAL TERMINOLOGY: Use proper legal terminology in {target_lang_name}
4. PRESERVE NAMES: Do NOT translate party names, dates, currency amounts, addresses
5. HTML TAGS: Preserve ALL HTML tags, attributes, and inline styles EXACTLY as they are
6. SIGNATURE IMAGES: CRITICAL - Preserve ALL signature images completely. Do NOT modify:
   - Any <img> tags with src="data:image/..." (base64 encoded images)
   - Any <div> tags containing signature images
   - All inline styles (style="...") in signature sections
   - Signature image URLs must remain EXACTLY as they are (do not translate or modify base64 data)
7. FORMATTING: Maintain all spacing, line breaks, and indentation
8. TONE: Use formal, professional legal language
9. PLACEHOLDERS: Preserve all placeholders like (_____________) exactly as they are

Document to translate:
{text}

Return ONLY the translated document with ALL formatting, HTML tags, and signature images preserved EXACTLY as they are. Do not add explanations."""
            
            # Stream the translation
            accumulated_text = ""
            for chunk_data in self._stream_openai(translation_prompt):
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
            'bn': 'Bengali (Bangla)',
            'hi': 'Hindi',
            'ar': 'Arabic',
            'english': 'English',
            'bengali': 'Bengali (Bangla)',
            'hindi': 'Hindi',
            'arabic': 'Arabic'
        }
        
        # Normalize the input (lowercase for matching)
        target_lang_key = target_language.lower().strip()
        target_lang_name = language_names.get(target_lang_key, target_language)
        
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                return html_content, "OpenAI API key is required for translation. Please configure OPENAI_API_KEY in your environment."
            
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
            
            result, error = self._call_openai(translation_prompt)
            if error:
                return html_content, error
            
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
        translation_prompt = f"""You are a professional legal translator. Translate the following legal contract document to {target_lang_name} while maintaining perfect formatting and legal accuracy.

CRITICAL TRANSLATION RULES:
1. PRESERVE ALL FORMATTING: Keep all markdown syntax (##, ###, **, -, etc.) exactly as they are
2. MAINTAIN STRUCTURE: Keep all section headers, bullet points, numbered lists, and paragraph breaks
3. LEGAL TERMINOLOGY: Use proper legal terminology in {target_lang_name}
4. PRESERVE NAMES: Do NOT translate party names, dates, currency amounts, addresses
5. HTML TAGS: Preserve ALL HTML tags, attributes, and inline styles EXACTLY as they are
6. SIGNATURE IMAGES: CRITICAL - Preserve ALL signature images completely. Do NOT modify:
   - Any <img> tags with src="data:image/..." (base64 encoded images)
   - Any <div> tags containing signature images
   - All inline styles (style="...") in signature sections
   - Signature image URLs must remain EXACTLY as they are (do not translate or modify base64 data)
7. FORMATTING: Maintain all spacing, line breaks, and indentation
8. TONE: Use formal, professional legal language

Document to translate:
{text}

Return ONLY the translated document with ALL formatting, HTML tags, and signature images preserved EXACTLY as they are. Do not add explanations."""
        
        result, error = self._call_openai(translation_prompt)
        if error:
            return None, error
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