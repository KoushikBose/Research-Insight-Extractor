"""Labelled PII cases shared by the evaluation benchmark and tests/test_pii.py."""

# every string contains exactly one phone number and no other digits worth keeping -> must contain [PHONE], no 4+ digit run may remain
PHONES = [
    # North America
    "Call +1 415 555 0134 tomorrow", "Phone: (415) 555-0134", "415-555-0134", "415.555.0134", "4155550134", "+1-800-555-0199", "+1.415.555.0134",
    "tel:+14155550134", "Cell 415-555-0134.", "Toll-free 1-800-555-0199", "reach me at 415 555 0134 or by email", "Phone 4155550134", "my number 4155550134",
    # India: mobile, landline, toll-free, every grouping
    "Mobile +91 98765 43210", "+91-9876543210", "98765 43210", "9876543210", "09876543210", "0091 9876543210", "00 91 98765 43210", "+91 (98765) 43210",
    "mobile number is 98 76 54 32 10", "WhatsApp 9876 543 210", "tel 98765-43210", "Mob: 91 98765 43210", "call me on 9876543210!",
    "My number is 98765 43210, please call.", "(Mobile: +91 98765-43210).", "Dr. Rao (ph. 044-2345 6789) will join.", "Ph.: +91 33 2345 6789",
    "Office: 022 2345 6789 ext 12", "Hotline 1800 123 4567", "helpline 1800-103-4567",
    # UK / Europe / Asia-Pacific / Middle East / Africa / LatAm
    "+44 20 7946 0958", "020 7946 0958", "07911 123456", "+44 7911 123456", "+49 30 901820", "+49 (0)30 901820", "Tel.: 0800 123 4567", "+33 1 42 68 53 00",
    "+61 2 9374 4000", "+65 6123 4567", "+971 4 123 4567", "+86 138 0013 8000", "+7 495 123-45-67", "+55 11 91234-5678", "+27 21 123 4567",
    # context-only layouts
    "Contact: 555-0134",
]
# two numbers in one sentence
MULTI = [("Call +91 98765 43210 or 415-555-0134 about the study.", 2)]

# other identifiers: (text, tag that must appear)
OTHER = [("email jane.doe@corp.com now", "[EMAIL]"), ("SSN 123-45-6789", "[SSN]"), ("PAN ABCDE1234F", "[PAN]"),
         ("Aadhaar 2345 6789 0123 on file", "[AADHAAR]"), ("Aadhaar 234567890123", "[AADHAAR]")]

# phone-like but NOT personal data: must come back byte-for-byte unchanged
SAFE = [
    "doi:10.1234/gut.2024.0042", "10.1101/2026.10.15.759323v1", "2026.11.01.763519v1", "Published 2024-03-12", "n = 240 patients", "p = 0.003 (95% CI 1.2-3.4)",
    "PMID: 12345678", "NCT01234567", "ACR20 response at week 12", "62% vs 28%", "1,234,567 reads", "5xFAD mice, 36 animals", "Table 1 on page 12-14",
    "v1.2.3 of the software", "192.168.1.1", "0.001 mg/kg", "dose of 500 mg twice daily for 24 weeks", "Figure 3. n=18 per group", "volume 12(3):456-789",
    "ISSN 1234-5678", "grant R01 CA123456", "1 2 3 4 5 6 7 8 9", "ZX-114 at 50 mg", "2024 2025 2026", "Samples 1021 to 1050 were analysed",
    # found by scanning real papers
    "J. Am. Chem. Soc. 146, 2247622484 (2024).", "Tumour 0.0047 0.0014 0.0001 0.39 0.08", "6 7 8 9 10 11 12", "10.1016/0041-5553(67)90144-9",
    "https://doi.org/10.1017/cbo9780511002.017 618", "Aug 2023, pp. 1234-5678", "Sample IDs 100200 300400", "ratio 0.5 0.6 0.7 0.8 0.9 1.0",
]
