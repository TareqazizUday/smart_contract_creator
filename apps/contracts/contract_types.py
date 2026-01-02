"""
Contract Type Definitions
"""
from enum import Enum


class ContractType(Enum):
    """Available contract types in the system"""
    SERVICE_AGREEMENT = "service_agreement"
    NDA = "nda"
    LEASE = "lease"
    EMPLOYMENT = "employment"
    SOP = "sop"
    DEVELOPER_AGREEMENT = "developer_agreement"
    DEVELOPER_JDA = "developer_jda"
    DEVELOPER_REVENUE_SHARING = "developer_revenue_sharing"
    DEVELOPER_LAND_SHARING = "developer_land_sharing"
    DEVELOPER_JV = "developer_jv"
    
    @classmethod
    def get_display_name(cls, contract_type):
        """Get display name for contract type"""
        names = {
            cls.SERVICE_AGREEMENT: "Service Agreement",
            cls.NDA: "NDA (Non-Disclosure Agreement)",
            cls.LEASE: "Lease/Rental Agreement",
            cls.EMPLOYMENT: "Employment Contract",
            cls.SOP: "SOP",
            cls.DEVELOPER_AGREEMENT: "Developer Agreement (JDA/Revenue/Land/JV/Construct Building)",
            cls.DEVELOPER_JDA: "Joint Development Agreement (JDA)",
            cls.DEVELOPER_REVENUE_SHARING: "Revenue/Profit Sharing Agreement",
            cls.DEVELOPER_LAND_SHARING: "Land Sharing/Contribution Agreement",
            cls.DEVELOPER_JV: "Joint Venture (JV) Agreement"
        }
        return names.get(contract_type, contract_type.value.replace('_', ' ').title())
    
    @classmethod
    def get_all_types(cls):
        """Get all available contract types"""
        return [
            {
                "value": cls.SERVICE_AGREEMENT.value,
                "label": cls.get_display_name(cls.SERVICE_AGREEMENT),
                "category": "Contracts"
            },
            {
                "value": cls.NDA.value,
                "label": cls.get_display_name(cls.NDA),
                "category": "Contracts"
            },
            {
                "value": cls.LEASE.value,
                "label": cls.get_display_name(cls.LEASE),
                "category": "Contracts"
            },
            {
                "value": cls.EMPLOYMENT.value,
                "label": cls.get_display_name(cls.EMPLOYMENT),
                "category": "Contracts"
            },
            {
                "value": cls.SOP.value,
                "label": cls.get_display_name(cls.SOP),
                "category": "Documents"
            },
            {
                "value": cls.DEVELOPER_AGREEMENT.value,
                "label": cls.get_display_name(cls.DEVELOPER_AGREEMENT),
                "category": "Developer/Construction"
            }
        ]
