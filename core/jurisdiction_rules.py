"""
Jurisdiction Rules - Country-specific legal requirements for contracts
"""
JURISDICTION_RULES = {
    "bangladesh": {
        "name": "Bangladesh",
        "governing_law": "Laws of Bangladesh",
        "court_jurisdiction": "Courts of Bangladesh",
        "stamp_duty": True,
        "stamp_duty_clause": "This Agreement shall be executed on non-judicial stamp paper of appropriate value as per the Stamp Act of Bangladesh. The stamp duty shall be borne by the Client, unless otherwise agreed in writing by both parties.",
        "registration_required": True,
        "registration_clause": "This Agreement shall be registered with the appropriate Sub-Registrar's Office in Bangladesh within thirty (30) days of execution, as required under the Registration Act, 1908. All registration fees and charges shall be borne by the Client, unless otherwise agreed in writing by both parties.",
        "tax_clauses": ["VAT", "Income Tax"],
        "vat_clause": "All applicable Value Added Tax (VAT) as per the VAT Act, 1991 of Bangladesh shall be applicable and payable as per the provisions of this Agreement.",
        "consumer_protection": True,
        "consumer_protection_clause": "This Agreement is subject to the provisions of the Consumer Rights Protection Act, 2009 of Bangladesh, where applicable.",
        "dispute_resolution": "Any dispute arising out of or relating to this Agreement shall be subject to the exclusive jurisdiction of the courts of Bangladesh.",
        "legal_warning": "This contract is subject to Bangladesh law. Stamp duty and registration may be required. Please consult with a legal professional for compliance."
    },
    
    "usa": {
        "name": "United States of America",
        "governing_law": "Laws of the State where the Client is domiciled, United States of America",
        "court_jurisdiction": "State and Federal courts located in the state where the Client is domiciled, United States",
        "stamp_duty": False,
        "registration_required": False,
        "tax_clauses": ["State Tax", "Federal Tax", "Sales Tax"],
        "tax_clause": "All applicable federal, state, and local taxes arising from payments under this Agreement shall be borne by the Client, unless otherwise agreed in writing by both Parties, and shall be paid in accordance with the laws of the United States and the relevant state.",
        "consumer_protection": True,
        "consumer_protection_clause": "This Agreement is subject to applicable consumer protection laws of the United States, including but not limited to the Federal Trade Commission Act and state consumer protection statutes.",
        "dispute_resolution": "Any dispute arising out of or relating to this Agreement shall be resolved through binding arbitration in accordance with the rules of the American Arbitration Association, or in the state and federal courts located in the state where the Client is domiciled, United States.",
        "legal_warning": "This contract is subject to U.S. federal and state laws. State-specific requirements may apply. Please consult with a legal professional."
    },
    
    "uk": {
        "name": "United Kingdom",
        "governing_law": "Laws of England and Wales",
        "court_jurisdiction": "Courts of England and Wales",
        "stamp_duty": False,
        "registration_required": False,
        "tax_clauses": ["VAT", "Income Tax"],
        "vat_clause": "All applicable Value Added Tax (VAT) as per the Value Added Tax Act 1994 of the United Kingdom shall be applicable and payable by the Client, unless otherwise agreed in writing by both Parties, as per the provisions of this Agreement.",
        "consumer_protection": True,
        "consumer_protection_clause": "This Agreement is subject to the Consumer Rights Act 2015 and other applicable consumer protection laws of the United Kingdom, including GDPR where applicable.",
        "gdpr_clause": "The Parties acknowledge their obligations under the General Data Protection Regulation (GDPR) and the Data Protection Act 2018 of the United Kingdom.",
        "dispute_resolution": "Any dispute arising out of or relating to this Agreement shall be subject to the exclusive jurisdiction of the courts of England and Wales.",
        "legal_warning": "This contract is subject to UK law including GDPR requirements. Please consult with a legal professional for compliance."
    },
    
    "india": {
        "name": "India",
        "governing_law": "Laws of India",
        "court_jurisdiction": "Courts of India",
        "stamp_duty": True,
        "stamp_duty_clause": "This Agreement shall be executed on non-judicial stamp paper of appropriate value as per the Indian Stamp Act, 1899 and the relevant state stamp laws. The stamp duty shall be borne by the Client, unless otherwise agreed in writing by both parties.",
        "registration_required": True,
        "registration_clause": "This Agreement shall be registered with the appropriate Sub-Registrar's Office in India within thirty (30) days of execution, as required under the Registration Act, 1908. All registration fees and charges shall be borne by the Client, unless otherwise agreed in writing by both parties.",
        "tax_clauses": ["GST", "Income Tax"],
        "gst_clause": "All applicable Goods and Services Tax (GST) as per the Central Goods and Services Tax Act, 2017 and relevant state GST laws shall be applicable and payable as per the provisions of this Agreement.",
        "consumer_protection": True,
        "consumer_protection_clause": "This Agreement is subject to the provisions of the Consumer Protection Act, 2019 of India, where applicable.",
        "dispute_resolution": "Any dispute arising out of or relating to this Agreement shall be subject to the exclusive jurisdiction of the courts of India.",
        "legal_warning": "This contract is subject to Indian law. Stamp duty, registration, and GST may be required. Please consult with a legal professional for compliance."
    }
}


def get_jurisdiction_rules(jurisdiction):
    """Get jurisdiction rules for a specific country"""
    return JURISDICTION_RULES.get(jurisdiction.lower(), JURISDICTION_RULES["bangladesh"])


def get_available_jurisdictions():
    """Get list of available jurisdictions"""
    return [
        {"value": "bangladesh", "label": "Bangladesh", "flag": "🇧🇩", "code": "BD"},
        {"value": "usa", "label": "USA", "flag": "🇺🇸", "code": "US"},
        {"value": "uk", "label": "United Kingdom", "flag": "🇬🇧", "code": "UK"},
        {"value": "india", "label": "India", "flag": "🇮🇳", "code": "IN"}
    ]


def generate_jurisdiction_clauses(jurisdiction, party1_label, party2_label):
    """Generate jurisdiction-specific legal clauses"""
    rules = get_jurisdiction_rules(jurisdiction)
    clauses = []
    
    # Governing Law
    clauses.append(f"### Governing Law\n\nThis Agreement shall be governed by and construed in accordance with {rules['governing_law']}, without regard to its conflict of law principles.\n")
    
    # Court Jurisdiction
    clauses.append(f"### Jurisdiction\n\n{rules['dispute_resolution']}\n")
    
    # Stamp Duty (if applicable)
    if rules.get('stamp_duty'):
        clauses.append(f"### Stamp Duty\n\n{rules['stamp_duty_clause']}\n")
    
    # Registration (if applicable)
    if rules.get('registration_required'):
        clauses.append(f"### Registration\n\n{rules['registration_clause']}\n")
    
    # Tax Clauses
    if 'VAT' in rules.get('tax_clauses', []):
        clauses.append(f"### Value Added Tax (VAT)\n\n{rules.get('vat_clause', '')}\n")
    if 'GST' in rules.get('tax_clauses', []):
        clauses.append(f"### Goods and Services Tax (GST)\n\n{rules.get('gst_clause', '')}\n")
    if 'State Tax' in rules.get('tax_clauses', []) or 'Federal Tax' in rules.get('tax_clauses', []):
        clauses.append(f"### Taxes\n\n{rules.get('tax_clause', '')}\n")
    
    # Consumer Protection
    if rules.get('consumer_protection'):
        clauses.append(f"### Consumer Protection\n\n{rules['consumer_protection_clause']}\n")
    
    # GDPR (for UK)
    if rules.get('gdpr_clause'):
        clauses.append(f"### Data Protection\n\n{rules['gdpr_clause']}\n")
    
    return "\n".join(clauses)
