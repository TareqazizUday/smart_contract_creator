"""
Contract Configuration - Defines structure for each contract type
"""
from apps.contracts.contract_types import ContractType

CONTRACT_CONFIGS = {
    ContractType.SERVICE_AGREEMENT.value: {
        "party1_label": "Client",
        "party1_description": "The employer/client who is hiring the service provider",
        "party2_label": "Service Provider",
        "party2_description": "The freelancer/service provider delivering the services",
        "has_payment": True,
        "sections": [
            "Scope of Work",
            "Deliverables",
            "Payment / Compensation",
            "Timeline",
            "Support & Maintenance"
        ],
        "section_descriptions": {
            "Scope of Work": "Details of the services to be provided, including specific tasks, responsibilities, and service descriptions.",
            "Deliverables": "Items and outcomes to be delivered, including specifications, formats, and acceptance criteria.",
            "Payment / Compensation": "Payment terms, method, schedule, rates, and any associated costs or expenses.",
            "Timeline": "Project duration, deadlines, milestones, and key dates for deliverables.",
            "Support & Maintenance": "Duration and terms of support, maintenance services, response times, and ongoing service requirements."
        },
        "examples": [
            "A web development company builds a website for a client",
            "A freelancer works on a specific project",
            "A consultancy firm provides advisory services"
        ]
    },
    
    ContractType.NDA.value: {
        "party1_label": "Discloser",
        "party1_description": "The party that shares confidential information",
        "party2_label": "Recipient",
        "party2_description": "The party that receives confidential information",
        "has_payment": False,
        "sections": [
            "Definition of Confidential Information",
            "Exclusions from Confidential Information",
            "Obligations of Receiving Party",
            "Time Periods",
            "Return of Materials",
            "Relationships",
            "Remedies for Breach",
            "Notice of Immunity",
            "General Provisions"
        ],
        "section_descriptions": {
            "Definition of Confidential Information": "What constitutes confidential information including business plans, technical data, financial information, proprietary information, and trade secrets. Include requirements for marking written materials as 'Confidential' and providing written confirmation for oral disclosures.",
            "Exclusions from Confidential Information": "Information that is NOT considered confidential: (a) publicly known at time of disclosure or subsequently becomes public through no fault of Recipient; (b) discovered or created by Recipient before disclosure; (c) learned through legitimate means other than from Discloser; or (d) disclosed with prior written approval.",
            "Obligations of Receiving Party": "Recipient shall hold Confidential Information in strictest confidence for sole benefit of Discloser. Restrict access to employees/contractors with signed NDAs. Cannot use, publish, copy, or disclose without prior written approval. Must protect information with same degree of care as own confidential information.",
            "Time Periods": "⚠️ CRITICAL: Duration of confidentiality obligations - MUST use (_____________) years placeholder if user does NOT explicitly mention duration in requirements. Nondisclosure provisions survive agreement termination. Duty to hold information in confidence remains until information no longer qualifies as trade secret or until written release by Discloser, whichever occurs first. ONLY use specific years (e.g., 'five (5) years') if user explicitly states duration like '5 years NDA' or '3 years confidentiality'. DEFAULT is (_____________) years.",
            "Return of Materials": "Upon written request by Discloser, Recipient shall immediately return all records, notes, written, printed, or tangible materials pertaining to Confidential Information. Include destruction certification if applicable.",
            "Relationships": "This Agreement does not constitute either party as partner, joint venture, or employee of the other party for any purpose. Clarify independent contractor relationship.",
            "Remedies for Breach": "Consequences of violating the agreement including injunctive relief (immediate court orders), monetary damages, legal costs and attorney fees, and any other remedies available under law.",
            "Notice of Immunity": "Notice that individuals are not held criminally or civilly liable under federal or state trade secret law for disclosure made: (i) in confidence to government officials or attorneys for reporting suspected law violations; or (ii) in sealed court filings. Include protections for whistleblowers and retaliation lawsuit provisions.",
            "General Provisions": "Include: Severability (if one provision invalid, remainder remains effective), Integration/Entire Agreement (complete understanding, supersedes prior agreements), Waiver (failure to exercise rights not a waiver), Amendment (must be in writing signed by both parties), Assignment and Successors (binding on representatives and successors), Notices (how parties communicate)."
        },
        "examples": [
            "A startup shares its business idea with an investor",
            "Two companies exchange information before a merger",
            "A company assigns an employee to work on a confidential project"
        ]
    },
    
    ContractType.LEASE.value: {
        "party1_label": "Landlord / Owner",
        "party1_description": "The property owner who is renting out the property",
        "party2_label": "Tenant",
        "party2_description": "The party who will rent and occupy the property",
        "has_payment": True,
        "sections": [
            "Property Description",
            "Rental Amount",
            "Lease Duration",
            "Payment Terms",
            "Security Deposit",
            "Maintenance Responsibility",
            "Termination Clause",
            "Utilities"
        ],
        "section_descriptions": {
            "Property Description": "What is being rented - address, size, type of property, amenities, and any included items.",
            "Rental Amount": "Monthly or periodic rent payable, amount in currency, and any escalation clauses.",
            "Lease Duration": "Length of the lease (e.g., 12 months, 3 years), start date, end date, and renewal options.",
            "Payment Terms": "When and how rent is paid (monthly, quarterly, etc.), payment method, due dates, and late payment penalties.",
            "Security Deposit": "Amount of the security deposit, conditions for refund, and deductions allowed.",
            "Maintenance Responsibility": "Who is responsible for repairs and maintenance - landlord vs tenant responsibilities.",
            "Termination Clause": "Notice period required to terminate the lease, conditions for early termination, and penalties.",
            "Utilities": "Responsibility for electricity, gas, water, internet, and other utilities - who pays for what."
        },
        "examples": [
            "Renting out an apartment",
            "Renting out office space",
            "Renting out equipment or machinery"
        ]
    },
    
    ContractType.EMPLOYMENT.value: {
        "party1_label": "Employer",
        "party1_description": "The company or organization hiring the employee",
        "party2_label": "Employee",
        "party2_description": "The individual being employed",
        "has_payment": True,
        "sections": [
            "Job Title & Description",
            "Salary / Compensation",
            "Benefits",
            "Work Hours",
            "Probation Period",
            "Confidentiality & Non-Compete",
            "Termination Clause"
        ],
        "section_descriptions": {
            "Job Title & Description": "Position title, department, reporting structure, and detailed job responsibilities.",
            "Salary / Compensation": "Base salary, bonuses, commission structure, payment schedule, and review periods.",
            "Benefits": "Health insurance, pension/retirement plans, leave/holidays, sick leave, and other employee benefits.",
            "Work Hours": "Working hours (e.g., 9:00 AM to 6:00 PM), workdays, overtime policy, and flexible work arrangements.",
            "Probation Period": "Trial period duration (usually 3-6 months), evaluation criteria, and conversion to permanent status.",
            "Confidentiality & Non-Compete": "Confidentiality obligations, non-compete restrictions, and restrictions on joining competing companies.",
            "Termination Clause": "Notice period required for termination, conditions for termination, severance, and exit procedures."
        },
        "examples": [
            "A new programmer joining a company",
            "Hiring a Human Resource Manager in an office",
            "Employing a doctor in a hospital"
        ]
    },
    
    ContractType.SOP.value: {
        "party1_label": "Applicant",
        "party1_description": "The person writing the statement",
        "party2_label": "Institution",
        "party2_description": "The institution receiving the statement (university, employer, etc.)",
        "has_payment": False,
        "sections": [
            "Introduction",
            "Academic/Professional Background",
            "Motivation & Goals",
            "Relevant Experience",
            "Conclusion"
        ],
        "section_descriptions": {
            "Introduction": "A compelling opening paragraph (2-4 sentences) that: introduces yourself, clearly states the purpose of the document (e.g., 'I am writing to apply for...'), mentions the specific program/institution/position you're applying to, and hooks the reader with an engaging opening that reflects your passion or unique perspective. Avoid generic openings like 'I am writing this statement...' - instead, start with a specific anecdote, achievement, or insight that immediately demonstrates your interest and qualifications.",
            "Academic/Professional Background": "A comprehensive section (3-5 paragraphs) covering: your educational qualifications (degrees, institutions, graduation dates, GPA/Grades if relevant), key academic achievements (honors, awards, scholarships, publications, research projects), professional experience (job titles, companies, dates, key responsibilities), relevant certifications or training, and any other qualifications that demonstrate your readiness. Be specific with numbers, dates, and concrete achievements rather than vague statements. Connect your background to the requirements of the program/position you're applying to.",
            "Motivation & Goals": "A detailed explanation (3-4 paragraphs) that: clearly explains WHY you are applying (what sparked your interest, what drives you), describes your short-term career/academic goals (what you want to achieve in the next 2-5 years), outlines your long-term aspirations (where you see yourself in 10+ years), demonstrates how the specific program/institution/position aligns with your goals (mention specific courses, professors, research opportunities, or aspects of the program), shows that you've researched the program/institution and understand what makes it unique, and connects your past experiences to your future goals. Be specific about what you want to learn and achieve.",
            "Relevant Experience": "A detailed section (3-5 paragraphs) that: provides specific examples of projects, work, research, or activities relevant to your application, describes your role and contributions in detail (use action verbs and quantify results where possible), highlights key skills, competencies, and achievements, explains how these experiences have prepared you for the program/position, includes any leadership roles, teamwork, problem-solving, or innovation examples, and demonstrates growth and learning from your experiences. Use concrete examples rather than generic statements. Show, don't just tell.",
            "Conclusion": "A strong closing paragraph (2-3 sentences) that: summarizes your key qualifications and suitability, reinforces your commitment and enthusiasm, clearly states why you are an ideal candidate, and ends with a forward-looking statement that shows confidence and readiness. Avoid simply repeating what you've already said - instead, synthesize your main points and leave a memorable final impression."
        },
        "examples": [
            "Statement of Purpose for university admission",
            "Motivation letter for job application",
            "Personal statement for scholarship"
        ]
    },
    
    ContractType.DEVELOPER_AGREEMENT.value: {
        "party1_label": "Landowner",
        "party1_description": "The party providing the land for development",
        "party2_label": "Developer",
        "party2_description": "The party handling construction, planning, approvals, and sales",
        "has_payment": True,
        "sections": [
            "Land Contribution",
            "Development Model and Structure",
            "Development Responsibilities",
            "Compensation/Sharing Arrangement",
            "Project Timeline",
            "Penalties for Delays",
            "Sales and Marketing",
            "Payment Schedule",
            "Accounting and Reporting",
            "Taxes and Registration",
            "Utilities and Approvals",
            "Quality Standards",
            "Management and Control",
            "Dissolution and Exit"
        ],
        "section_descriptions": {
            "Land Contribution": "Details of the land being contributed: location, size (katha/bigha), plot number, ownership details, encumbrances (if any), and land valuation. Specify if existing structures need to be demolished.",
            "Development Model and Structure": "Specify the development model: (1) Joint Development Agreement (JDA) - fixed area/flat sharing, (2) Revenue/Profit Sharing - percentage of sales revenue or profit, (3) Land Sharing/Flat Allocation - specific flats/units allocation, or (4) Joint Venture (JV) - separate company/entity formation. Include legal structure, ownership, and entity details if JV model.",
            "Development Responsibilities": "Who handles: design and architecture, obtaining all approvals (RAJUK, local authority, fire safety, etc.), financing and construction, marketing and sales, customer relations, project management, and day-to-day operations. Clearly assign each responsibility.",
            "Compensation/Sharing Arrangement": "Based on the development model selected: (a) For JDA/Land Sharing: Specify exact percentage or number of flats/units the Landowner will receive, which specific flats (floor, unit numbers), and Developer's share. (b) For Revenue Sharing: Specify the revenue/profit sharing ratio (e.g., 35% Landowner, 65% Developer), whether it's based on gross sales, net profit, or net proceeds after costs. (c) For JV: Specify profit/loss sharing ratio and distribution method. Include valuation methods and how contributions are valued.",
            "Project Timeline": "Total project duration from approval to completion, key milestones (design approval, foundation, structure, finishing, handover), construction phases with dates, sales timeline (if applicable), and grace period for delays. Include specific dates or timeframes for each phase.",
            "Penalties for Delays": "Penalty structure for project delays beyond agreed timeline: monthly compensation amount per undelivered flat/unit, penalty calculation method, force majeure provisions, and conditions for penalty waiver. Specify grace period before penalties apply.",
            "Sales and Marketing": "Who handles sales, marketing strategy, pricing decisions, customer relationship management, booking and documentation, and sales team management. Include marketing budget responsibility if applicable.",
            "Payment Schedule": "When and how compensation is paid: (a) For flat allocation: handover schedule and transfer process. (b) For revenue sharing: payment frequency (monthly/quarterly), payment triggers (upon collection from buyers), distribution method, and accounting for project costs before distribution. (c) For JV: profit distribution schedule and method.",
            "Accounting and Reporting": "Financial reporting requirements: quarterly financial statements, project accounts maintenance, audit rights for Landowner, transparency obligations, cost tracking and approval process, and access to financial records. Specify reporting format and timeline.",
            "Taxes and Registration": "Responsibility for: stamp duty on agreement, registration fees, mutation costs, VAT on sales, income tax for each party, flat/unit registration costs (who pays - Landowner or buyers), and all other applicable taxes. Clearly assign each tax responsibility.",
            "Utilities and Approvals": "Who obtains and pays for: building plan approvals (RAJUK/local authority), utility connections (electricity, gas, water, sewerage), fire safety approvals, environmental clearances, and all regulatory compliance. Include timeline for obtaining approvals.",
            "Quality Standards": "Construction quality requirements: minimum standards (BNBC compliance), materials specifications (brands, grades), structural safety codes, finishing standards (tiles, fittings, paint), inspection rights, quality control process, and remedies for substandard work.",
            "Management and Control": "Management structure: decision-making process, board composition (if JV), key decision areas requiring mutual consent, day-to-day operational control, dispute resolution mechanism, and voting rights if applicable.",
            "Dissolution and Exit": "Conditions for dissolution: project completion, mutual consent, breach scenarios, exit procedures, asset distribution upon dissolution, handling of unsold units, and dispute resolution process."
        },
        "examples": [
            "Developer agreement for residential building construction",
            "Joint development of commercial complex",
            "Real estate development partnership"
        ]
    },
    
    ContractType.DEVELOPER_JDA.value: {
        "party1_label": "Landowner",
        "party1_description": "The party providing the land",
        "party2_label": "Developer",
        "party2_description": "The party handling construction, planning, approvals, and sales",
        "has_payment": True,
        "sections": [
            "Land Contribution",
            "Development Responsibilities",
            "Area Sharing",
            "Project Timeline",
            "Penalties for Delays",
            "Taxes and Registration",
            "Utilities and Approvals"
        ],
        "section_descriptions": {
            "Land Contribution": "Details of the land being contributed, location, size, and ownership details.",
            "Development Responsibilities": "Who handles design, permits, construction, marketing, and sales.",
            "Area Sharing": "Fixed portion of flats/shops the landowner will receive (e.g., 30-40%), area sharing model details.",
            "Project Timeline": "Project duration, construction phases, completion deadlines, and key milestones.",
            "Penalties for Delays": "Penalties for project delays, force majeure clauses, and delay compensation.",
            "Taxes and Registration": "Responsibility for taxes, registration fees, stamp duty, and other legal costs.",
            "Utilities and Approvals": "Responsibility for utility connections, building approvals, and regulatory compliance."
        },
        "examples": [
            "Joint development of residential complex",
            "Commercial building development",
            "Mixed-use development project"
        ]
    },
    
    ContractType.DEVELOPER_REVENUE_SHARING.value: {
        "party1_label": "Landowner",
        "party1_description": "The party providing the land",
        "party2_label": "Developer",
        "party2_description": "The party managing development and sales",
        "has_payment": True,
        "sections": [
            "Land Contribution",
            "Revenue Sharing Ratio",
            "Sales and Marketing",
            "Payment Schedule",
            "Project Timeline",
            "Accounting and Reporting",
            "Taxes and Registration"
        ],
        "section_descriptions": {
            "Land Contribution": "Details of the land being contributed and its valuation.",
            "Revenue Sharing Ratio": "Agreed sharing ratio (e.g., 30% landowner, 70% developer) of total sales revenue or profit.",
            "Sales and Marketing": "Who handles sales, marketing strategy, pricing, and customer relations.",
            "Payment Schedule": "When and how revenue/profit is shared, payment milestones, and distribution method.",
            "Project Timeline": "Project phases, completion deadlines, and sales timeline.",
            "Accounting and Reporting": "Financial reporting requirements, audit rights, and transparency obligations.",
            "Taxes and Registration": "Tax responsibilities, registration requirements, and legal compliance."
        },
        "examples": [
            "Revenue sharing in real estate development",
            "Profit sharing in commercial project",
            "Sales revenue distribution model"
        ]
    },
    
    ContractType.DEVELOPER_LAND_SHARING.value: {
        "party1_label": "Landowner",
        "party1_description": "The party contributing the land",
        "party2_label": "Developer",
        "party2_description": "The party managing design, permits, construction, and sales",
        "has_payment": True,
        "sections": [
            "Land Contribution",
            "Flat/Unit Allocation",
            "Project Timeline",
            "Penalties for Delays",
            "Taxes and Registration",
            "Utilities and Approvals",
            "Quality Standards"
        ],
        "section_descriptions": {
            "Land Contribution": "Land details, location, size, and contribution terms.",
            "Flat/Unit Allocation": "Specific flats or percentage the landowner will receive, unit specifications, and allocation method.",
            "Project Timeline": "Construction timeline, phases, completion dates, and handover schedule.",
            "Penalties for Delays": "Delay penalties, compensation structure, and force majeure provisions.",
            "Taxes and Registration": "Responsibility for taxes, registration fees, stamp duty, and legal costs.",
            "Utilities and Approvals": "Utility connections, building approvals, and regulatory compliance responsibilities.",
            "Quality Standards": "Construction quality standards, materials, and inspection requirements."
        },
        "examples": [
            "Land sharing model in Dhaka",
            "Area contribution agreement",
            "Flat allocation in joint development"
        ]
    },
    
    ContractType.DEVELOPER_JV.value: {
        "party1_label": "Landowner",
        "party1_description": "The party contributing land to the joint venture",
        "party2_label": "Developer",
        "party2_description": "The party contributing capital and management expertise",
        "has_payment": True,
        "sections": [
            "Joint Venture Structure",
            "Contributions",
            "Profit and Loss Sharing",
            "Management and Control",
            "Project Timeline",
            "Taxes and Compliance",
            "Dissolution and Exit"
        ],
        "section_descriptions": {
            "Joint Venture Structure": "Whether to form a separate company or project entity, legal structure, and ownership.",
            "Contributions": "Landowner's land contribution and developer's capital and management contribution, valuation methods.",
            "Profit and Loss Sharing": "How profits and losses are shared between parties, distribution method, and accounting.",
            "Management and Control": "Management structure, decision-making process, board composition, and operational control.",
            "Project Timeline": "Project phases, milestones, completion deadlines, and key dates.",
            "Taxes and Compliance": "Tax obligations, regulatory compliance, and legal requirements for the joint venture.",
            "Dissolution and Exit": "Conditions for dissolution, exit procedures, asset distribution, and dispute resolution."
        },
        "examples": [
            "Joint venture for real estate development",
            "Partnership for construction project",
            "Collaborative development entity"
        ]
    }
}


def get_contract_config(contract_type):
    """Get configuration for a specific contract type"""
    return CONTRACT_CONFIGS.get(contract_type, CONTRACT_CONFIGS[ContractType.SERVICE_AGREEMENT.value])


def get_contract_sections(contract_type):
    """Get sections for a contract type"""
    config = get_contract_config(contract_type)
    return config.get("sections", [])


def get_contract_section_descriptions(contract_type):
    """Get section descriptions for a contract type"""
    config = get_contract_config(contract_type)
    return config.get("section_descriptions", {})
