import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# make_safe_name registers every unseen company in a canonical-casing registry
# and persists it. Point that at a throwaway file so fixture companies never
# land in the real 10_output/_company_casing.json, which syncs to every device.
os.environ.setdefault(
    "JIS_COMPANY_CASING_PATH",
    os.path.join(tempfile.gettempdir(), "jis_test_company_casing.json"),
)
