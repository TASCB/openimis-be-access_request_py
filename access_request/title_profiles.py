"""Starting values for one AccessProfile per TASAF HQ job title; edited in the MIS afterwards."""

COUNTRYWIDE = 'Country-wide access (HQ)'


DIRECTORATES = {'EDO': 0, 'DIA': 1, 'DFA': 2, 'DIDS': 3, 'DP': 4}


def section_name(directorate):
    """Directorate code → section (auth.Group) name."""
    from access_request.apps import SECTION_USER_GROUPS
    return SECTION_USER_GROUPS[DIRECTORATES[directorate]]

# (code, title, directorate, role names)
TITLE_PROFILES = [
    ('ED', 'Executive Director', 'EDO', ['Payment Approver', 'Executive Viewer', COUNTRYWIDE]),
    ('CLM', 'Coordination and Logistics Manager', 'EDO', ['Coordination Line Manager', COUNTRYWIDE]),
    ('CLO', 'Coordination Logistics Officer', 'EDO', ['Coordination Officer (maker)', COUNTRYWIDE]),
    ('CM', 'Communication Manager', 'DIDS', ['Communications Manager', COUNTRYWIDE]),
    ('CO', 'Communication Officer', 'DIDS', ['Communications Officer', COUNTRYWIDE]),
    ('DIA', 'Director of Internal Audit', 'DIA', ['Internal Auditor', COUNTRYWIDE]),
    ('IAM', 'Internal Audit Manager', 'DIA', ['Internal Auditor', COUNTRYWIDE]),
    ('IA', 'Internal Auditor', 'DIA', ['Internal Auditor', COUNTRYWIDE]),
    ('DFA', 'Director of Finance and Administration', 'DFA',
     ['Payment Approver', 'Finance and Administration Viewer', COUNTRYWIDE]),
    ('AM', 'Accounts Manager', 'DFA', ['Payment Approver', COUNTRYWIDE]),
    ('DM', 'Disbursement Manager', 'DFA', ['Payment Approver', COUNTRYWIDE]),
    ('AFA', 'Accountant - Final Accounts', 'DFA', ['Finance Manager (Reviewer)', COUNTRYWIDE]),
    ('EPC', 'E-Payment Coordinator', 'DFA', ['Finance Manager (Reviewer)', COUNTRYWIDE]),
    ('AD', 'Accountant - Disbursements', 'DFA', ['Disbursement Maker', COUNTRYWIDE]),
    ('EPO', 'E-Payment Officer', 'DFA', ['Disbursement Maker', COUNTRYWIDE]),
    ('HRM', 'Human Resource Manager', 'DFA', ['Access Request Sponsor']),
    ('DIDS', 'Director of IT and Delivery Systems', 'DIDS',
     ['ICT Access Approver', 'Delivery Systems Viewer', COUNTRYWIDE]),
    ('IT-M', 'IT - Manager', 'DIDS', ['System Administrator', 'ICT Access Approver', COUNTRYWIDE]),
    ('ISAO', 'Infrastructure and Systems Administration Officer', 'DIDS', ['System Administrator', COUNTRYWIDE]),
    ('NA', 'Network Administrator', 'DIDS', ['System Administrator', COUNTRYWIDE]),
    ('SASO', 'Senior Application Support Officer', 'DIDS', ['System Administrator', COUNTRYWIDE]),
    ('ASO', 'Application Support Officer', 'DIDS', ['System Administrator', COUNTRYWIDE]),
    ('DA&AO', 'Data Analyst and Admin Officer', 'DIDS', ['M&E Officer', COUNTRYWIDE]),
    # Temporary until developer access is decided.
    ('SSDO', 'Senior System Development Officer', 'DIDS', ['IMIS Administrator', COUNTRYWIDE]),
    ('SDO', 'System Development Officer', 'DIDS', ['IMIS Administrator', COUNTRYWIDE]),
    ('DP', 'Director of Programs', 'DP', ['Director of Programs', 'Programs Viewer', COUNTRYWIDE]),
    ('PCT-M', 'Productive Cash Transfer Manager', 'DP', ['PCT Manager', COUNTRYWIDE]),
    ('EIM', 'Economic Inclusion Manager', 'DP', ['PCT Manager', COUNTRYWIDE]),
    ('PCT-O', 'Productive Cash Transfer Officer', 'DP', ['PCT Officer', 'Data Import Officer', COUNTRYWIDE]),
    ('EI-O', 'Economic Inclusion Officer', 'DP', ['PCT Officer', COUNTRYWIDE]),
    ('SM', 'Safeguard Manager', 'DP', ['Grievance Manager', COUNTRYWIDE]),
    ('GRO', 'Grievance Redressal Officer', 'DP', ['Grievance Officer', COUNTRYWIDE]),
    ('GRA', 'Assistant Grievance Redressal', 'DP', ['GRM Intake', COUNTRYWIDE]),
    ('POCD', 'PO - Community Development', 'DP', ['Council Coordinator', COUNTRYWIDE]),
    ('POCGC', 'Project Officer Climate, Gender and Cross Cutting', 'DP', ['Council Coordinator', COUNTRYWIDE]),
    ('POE', 'PO - Environment', 'DP', ['Council Coordinator', COUNTRYWIDE]),
    ('CSPW-M', 'Climate Smart Public Works Manager', 'DP', ['Council Coordinator', COUNTRYWIDE]),
    ('CSPW-O', 'Climate Smart Public Works Officer', 'DP', ['M&E Officer', COUNTRYWIDE]),
    ('TI-O', 'Targeted Infrastructure Officer', 'DP', ['M&E Officer', COUNTRYWIDE]),
    ('MEL-M', 'Monitoring and Evaluation Manager', 'DIDS', ['M&E Manager', COUNTRYWIDE]),
    ('MELO', 'Monitoring and Evaluation Officer', 'DIDS', ['M&E Officer', COUNTRYWIDE]),
    ('TMO', 'TASAF Monitoring Officer', 'DIDS', ['TMO']),
]

# (code, unit name, directorate, head title, reports-to unit, titles)
UNITS = [
    ('ED-OFF', 'Office of the Executive Director', 'EDO', 'ED', None, ['ED']),
    ('CL', 'Coordination and Logistics', 'EDO', 'CLM', 'ED-OFF', ['CLM', 'CLO']),
    ('DIA-OFF', 'Office of the Director of Internal Audit', 'DIA', 'DIA', 'ED-OFF', ['DIA']),
    ('IA', 'Internal Audit', 'DIA', 'IAM', 'DIA-OFF', ['IAM', 'IA']),
    ('DFA-OFF', 'Office of the Director of Finance and Administration', 'DFA', 'DFA', 'ED-OFF', ['DFA']),
    ('ACC', 'Accounts', 'DFA', 'AM', 'DFA-OFF', ['AM', 'AFA']),
    ('DISB', 'Disbursement and E-Payment', 'DFA', 'DM', 'DFA-OFF', ['DM', 'EPC', 'AD', 'EPO']),
    ('HR', 'Human Resources and Administration', 'DFA', 'HRM', 'DFA-OFF', ['HRM']),
    ('DIDS-OFF', 'Office of the Director of IT and Delivery Systems', 'DIDS', 'DIDS', 'ED-OFF', ['DIDS']),
    ('COMM', 'Communication', 'DIDS', 'CM', 'DIDS-OFF', ['CM', 'CO']),
    ('IT', 'Information Technology', 'DIDS', 'IT-M', 'DIDS-OFF',
     ['IT-M', 'ISAO', 'NA', 'SASO', 'ASO', 'DA&AO', 'SSDO', 'SDO']),
    ('MEL', 'Monitoring, Evaluation and Learning', 'DIDS', 'MEL-M', 'DIDS-OFF', ['MEL-M', 'MELO', 'TMO']),
    ('DP-OFF', 'Office of the Director of Programs', 'DP', 'DP', 'ED-OFF', ['DP']),
    ('PCT', 'Productive Cash Transfer', 'DP', 'PCT-M', 'DP-OFF', ['PCT-M', 'PCT-O']),
    ('EI', 'Economic Inclusion', 'DP', 'EIM', 'DP-OFF', ['EIM', 'EI-O']),
    ('CSPW', 'Climate Smart Public Works', 'DP', 'CSPW-M', 'DP-OFF', ['CSPW-M', 'CSPW-O', 'TI-O']),
    ('SG', 'Safeguards and Grievance Redress', 'DP', 'SM', 'DP-OFF', ['SM', 'GRO', 'GRA', 'POCD', 'POCGC', 'POE']),
]

UNIT_HEAD_ROLE = 'Access Request Sponsor'
