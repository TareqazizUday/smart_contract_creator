"""
Contract Service - Handles contract generation business logic
"""
from core.services.ai_service import AIService
from apps.contracts.contract_config import get_contract_config


class ContractService:
    """Service for contract generation operations"""
    
    def __init__(self):
        self.ai_service = AIService()
    
    def generate_full_contract(self, party1, party2, start_date, sections_data, user_prompt=None, 
                               supplementary_text=None, template_text=None, contract_type="service_agreement", 
                               jurisdiction="bangladesh", party1_contact_name='', party1_contact_title='', 
                               party2_contact_name='', party2_contact_title='',
                               party1_signature_url=None, party2_signature_url=None,
                               signature_date=None, legal_references=None):
        """Generate a complete contract using AI - no hard-coded templates"""
        try:
            # Generate cover page
            cover_page = self._generate_cover_page(contract_type, party1, party2, start_date, jurisdiction)
            
            # Generate complete contract using AI (includes header, recitals, sections, standard clauses, jurisdiction clauses)
            generated_contract, error = self.ai_service.generate_contract_content(
                party1, party2, start_date, sections_data,
                user_prompt, supplementary_text, template_text, contract_type, jurisdiction
            )
            
            if error:
                return f"**Error generating contract:** {error}"
            
            # Combine cover page with generated contract
            full_contract = cover_page + "\n\n---\n\n" + generated_contract
            
            # Always append signature blocks (side-by-side format)
            signature_block = self._generate_signature_block(
                party1_contact_name, party1_contact_title, party2_contact_name, party2_contact_title,
                party1_signature_url, party2_signature_url, signature_date
            )
            full_contract += signature_block
            
            # Append references section if legal references are provided
            if legal_references and isinstance(legal_references, list) and len(legal_references) > 0:
                references_block = self._generate_references_block(legal_references)
                full_contract += references_block
            
            return full_contract

        except Exception as e:
            return f"**Error generating contract:** {e}"
    
    def _generate_signature_block(self, party1_contact_name='', party1_contact_title='', 
                                  party2_contact_name='', party2_contact_title='',
                                  party1_signature_url=None, party2_signature_url=None, signature_date=None):
        """Generate signature block with contact info and signature images (if provided)"""
        party1_name_display = party1_contact_name if party1_contact_name else '___________________'
        party1_title_display = party1_contact_title if party1_contact_title else '__________________'
        party2_name_display = party2_contact_name if party2_contact_name else '___________________'
        party2_title_display = party2_contact_title if party2_contact_title else '__________________'
        
        # Generate signature HTML blocks
        party1_signature_html = ''
        party2_signature_html = ''
        
        if party1_signature_url:
            party1_signature_html = f'<div style="margin-bottom: 15px; width: 180px; height: 60px; display: flex; align-items: center; justify-content: center; padding: 5px; background: #fff; overflow: hidden;"><img src="{party1_signature_url}" style="max-width: 180px; max-height: 60px; width: auto; height: auto; object-fit: contain;" alt="Signature" /></div>'
        else:
            party1_signature_html = '<p style="margin-bottom: 0; min-height: 60px; width: 180px;">_________________________</p><p style="margin-bottom: 10px;">Signature</p>'
        
        if party2_signature_url:
            party2_signature_html = f'<div style="margin-bottom: 15px; width: 180px; height: 60px; display: flex; align-items: center; justify-content: center; padding: 5px; background: #fff; overflow: hidden;"><img src="{party2_signature_url}" style="max-width: 180px; max-height: 60px; width: auto; height: auto; object-fit: contain;" alt="Signature" /></div>'
        else:
            party2_signature_html = '<p style="margin-bottom: 0; min-height: 60px; width: 180px;">_________________________</p><p style="margin-bottom: 10px;">Signature</p>'
        
        # Date display - use provided date if available, otherwise leave blank
        if signature_date:
            try:
                # Try to parse if it's a string, otherwise use as-is if already a date object
                if isinstance(signature_date, str):
                    date_display = signature_date  # Use as-is if string
                else:
                    date_display = signature_date.strftime('%B %d, %Y')
            except:
                date_display = signature_date  # Fallback to original value
        else:
            date_display = '___________________'
        
        # Return signature block in markdown with embedded HTML for images
        return f"""

## SIGNATURES

<div style="display: flex; justify-content: space-between; margin-top: 40px; page-break-inside: avoid;">
    <div style="width: 45%;">
        {party1_signature_html}
        <p style="margin-bottom: 0; border-top: 1px solid #000; padding-top: 5px; width: 200px; margin-top: 15px;">Name: {party1_name_display}</p>
        <p style="margin-bottom: 0; border-top: 1px solid #000; padding-top: 5px; width: 200px; margin-top: 10px;">Title: {party1_title_display}</p>
        <p style="margin-bottom: 0; margin-top: 10px;">Date: {date_display}</p>
    </div>
    <div style="width: 45%;">
        {party2_signature_html}
        <p style="margin-bottom: 0; border-top: 1px solid #000; padding-top: 5px; width: 200px; margin-top: 15px;">Name: {party2_name_display}</p>
        <p style="margin-bottom: 0; border-top: 1px solid #000; padding-top: 5px; width: 200px; margin-top: 10px;">Title: {party2_title_display}</p>
        <p style="margin-bottom: 0; margin-top: 10px;">Date: {date_display}</p>
    </div>
</div>
"""
    
    def _generate_cover_page(self, contract_type, party1, party2, start_date, jurisdiction):
        """Generate a professional cover page for the contract (returns HTML for direct rendering)"""
        try:
            # Get contract configuration
            config = get_contract_config(contract_type)
            # Convert contract_type to display name (e.g., "service_agreement" -> "Service Agreement")
            contract_type_name = contract_type.replace('_', ' ').title()
            party1_label = config.get('party1_label', 'Party 1')
            party2_label = config.get('party2_label', 'Party 2')
            
            # Format date
            if hasattr(start_date, 'strftime'):
                date_str = start_date.strftime('%B %d, %Y')
            else:
                date_str = str(start_date) if start_date else 'Date'
            
            # Get jurisdiction name
            try:
                from core.jurisdiction_rules import get_jurisdiction_rules
                jurisdiction_rules = get_jurisdiction_rules(jurisdiction)
                jurisdiction_name = jurisdiction_rules.get('name', jurisdiction.title())
            except:
                jurisdiction_name = jurisdiction.title()
            
            # Generate cover page HTML (optimized for A4 page, print-friendly)
            cover_page_html = f"""<div style="page-break-after: always; page-break-inside: avoid; height: 100vh; min-height: 842px; max-height: 842px; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 40px 20px; margin: 0 auto; box-sizing: border-box; background: #ffffff; font-family: 'Georgia', 'Times New Roman', serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; width: 100%;">
    <div style="text-align: center; width: 100%; max-width: 700px; margin: 0 auto; padding: 0; box-sizing: border-box;">
        <div style="width: 100px; height: 3px; background: linear-gradient(to right, #2c3e50, #3498db); margin: 0 auto 30px; -webkit-print-color-adjust: exact; print-color-adjust: exact;"></div>
        
        <h1 style="font-size: 36px; font-weight: 700; color: #2c3e50; margin: 0 0 15px 0; letter-spacing: 1.5px; text-transform: uppercase; line-height: 1.2; page-break-after: avoid;">{contract_type_name.upper()}</h1>
        
        <p style="font-size: 16px; color: #7f8c8d; margin: 0 0 40px 0; font-style: italic; letter-spacing: 0.5px; text-align: center;">Legal Document</p>
        
        <div style="width: 180px; height: 1.5px; background: #bdc3c7; margin: 0 auto 40px;"></div>
        
        <div style="margin: 0 0 35px 0; text-align: center; width: 100%; max-width: 550px; margin-left: auto; margin-right: auto;">
            <div style="margin-bottom: 25px; text-align: center;">
                <p style="font-size: 14px; color: #34495e; margin: 0 0 6px 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; text-align: center;">{party1_label}</p>
                <p style="font-size: 18px; color: #2c3e50; margin: 0; font-weight: 400; text-align: center;">{party1}</p>
            </div>
            <div style="text-align: center; margin: 20px 0; color: #95a5a6; font-size: 20px; font-weight: 300;">AND</div>
            <div style="margin-bottom: 25px; text-align: center;">
                <p style="font-size: 14px; color: #34495e; margin: 0 0 6px 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; text-align: center;">{party2_label}</p>
                <p style="font-size: 18px; color: #2c3e50; margin: 0; font-weight: 400; text-align: center;">{party2}</p>
            </div>
        </div>
        
        <div style="margin: 35px auto 0; padding-top: 30px; border-top: 1.5px solid #ecf0f1; width: 100%; max-width: 550px; text-align: center;">
            <p style="font-size: 12px; color: #7f8c8d; margin: 0 0 8px 0; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; text-align: center;">Effective Date</p>
            <p style="font-size: 18px; color: #2c3e50; margin: 0; font-weight: 400; text-align: center;">{date_str}</p>
        </div>
        
        <div style="margin: 25px 0 0 0; text-align: center;">
            <p style="font-size: 11px; color: #95a5a6; margin: 0; font-style: italic; text-align: center;">Governed by the laws of {jurisdiction_name}</p>
        </div>
        
        <div style="width: 100px; height: 3px; background: linear-gradient(to right, #3498db, #2c3e50); margin: 40px auto 0; -webkit-print-color-adjust: exact; print-color-adjust: exact;"></div>
    </div>
</div>"""
            return cover_page_html
        except Exception as e:
            return ""
    
    def _generate_references_block(self, references):
        """Generate references section with legal reference URLs"""
        references_md = "\n\n## REFERENCES\n\n"
        references_md += "The following legal references and resources were consulted during the generation of this contract:\n\n"
        
        for ref in references:
            title = ref.get('title', ref.get('url', 'Legal Reference'))
            url = ref.get('url', '')
            if url:
                references_md += f"- [{title}]({url})\n"
            else:
                references_md += f"- {title}\n"
        
        return references_md
    
    def generate_full_contract_api(self, party1, party2, start_date, sections_data, user_prompt=None, 
                                   supplementary_text=None, template_text=None, 
                                   contract_type="service_agreement", jurisdiction="bangladesh"):
        """Generate contract for API response - AI generates complete contract"""
        import markdown
        
        try:
            # Generate complete contract using AI (includes header, recitals, sections, standard clauses, jurisdiction clauses)
            generated_contract, error = self.ai_service.generate_contract_content(
                party1, party2, start_date, sections_data,
                user_prompt, supplementary_text, template_text, contract_type, jurisdiction
            )
            
            if error:
                return {"error": error}
            
            # Convert to HTML
            full_html = markdown.markdown(generated_contract)
            
            return {
                "full_markdown": generated_contract,
                "full_html": full_html
            }

        except Exception as e:
            return {"error": f"Error generating contract: {e}"}
