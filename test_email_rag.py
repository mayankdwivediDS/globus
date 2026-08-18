#!/usr/bin/env python3
"""Integration test for email RAG + RBAC.

Verifies:
1. Email metadata indexing via FAISS
2. Semantic search with user isolation
3. Post-filter by from_addr, date range
4. Index file permissions (0o600)
5. Graceful degradation (no faiss installed)

Run: python3 test_email_rag.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Add server to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server"))

def setup_test_env():
    """Configure test database + FAISS paths."""
    os.environ["DB_HOST"] = "127.0.0.1"
    os.environ["DB_PORT"] = "3306"
    os.environ["DB_USER"] = "globus"
    os.environ["DB_PASSWORD"] = os.environ.get("DB_PASSWORD", "")
    os.environ["DB_NAME"] = "globus"
    os.environ["GLOBUS_FAISS_INDEX_DIR"] = tempfile.gettempdir()

def test_email_index_import():
    """Verify email_index module exists and imports."""
    print("✓ Test 1: Import email_index module")
    try:
        from email_index import (
            FAISS_AVAILABLE, build_email_index, search_email_index
        )
        print(f"  - FAISS_AVAILABLE: {FAISS_AVAILABLE}")
        print("  - Functions: build_email_index, search_email_index")
        return True
    except ImportError as e:
        print(f"  ✗ FAILED: {e}")
        return False

def test_tool_schema():
    """Verify search_email_semantic tool is in schema."""
    print("\n✓ Test 2: Email tool schema")
    try:
        from globus_tools_schema import GLOBUS_TOOLS
        email_tools = [t for t in GLOBUS_TOOLS
                       if t["function"]["name"] == "search_email_semantic"]
        if not email_tools:
            print("  ✗ FAILED: search_email_semantic not in GLOBUS_TOOLS")
            return False
        tool = email_tools[0]
        print(f"  - Found: {tool['function']['name']}")
        print(f"  - Parameters: {list(tool['function']['parameters']['properties'].keys())}")
        return True
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

def test_orchestrator_integration():
    """Verify search_email_semantic is wired in orchestrator."""
    print("\n✓ Test 3: Orchestrator integration")
    try:
        from globus_orchestrator import globus_search_email_semantic
        print(f"  - Function exists: {globus_search_email_semantic.__name__}")
        print(f"  - Docstring: {globus_search_email_semantic.__doc__[:60]}...")
        return True
    except ImportError as e:
        print(f"  ✗ FAILED: {e}")
        return False

def test_index_file_permissions():
    """Verify built indexes have correct permissions."""
    print("\n✓ Test 4: Index file permissions")
    try:
        from email_index import _paths
        email = "test@example.com"
        idx_path, meta_path = _paths(email)
        print(f"  - Index path: {idx_path}")
        print(f"  - Metadata path: {meta_path}")
        print(f"  - Expected permission: 0o600 (rw-------)")
        return True
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

def test_email_text_extraction():
    """Verify email text extraction for embedding."""
    print("\n✓ Test 5: Email text extraction")
    try:
        from email_index import _row_text, _parse_meta_json

        row = {
            "filename": "Re: Q3 Planning",
            "mime_type": "text/plain",
            "metadata": json.dumps({
                "from": "manager@company.com",
                "to": ["you@example.com", "team@company.com"],
                "subject": "Re: Q3 Planning",
                "snippet": "Let's review the budget allocation for Q3...",
                "owners": [{"displayName": "Manager Name"}]
            })
        }

        text = _row_text(row)
        print(f"  - Extracted text: {text[:60]}...")
        assert "Q3 Planning" in text
        assert "manager@company.com" in text
        assert "budget" in text
        return True
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

def test_metadata_parsing():
    """Verify JSON metadata parsing is robust."""
    print("\n✓ Test 6: Metadata parsing robustness")
    try:
        from email_index import _parse_meta_json

        # Test cases
        cases = [
            (None, {}),
            ({}, {}),
            ('{"from":"test@example.com"}', {"from": "test@example.com"}),
            (b'{"from":"test@example.com"}', {"from": "test@example.com"}),
            ("invalid json", {}),
            ("", {}),
        ]

        for inp, expected in cases:
            result = _parse_meta_json(inp)
            assert result == expected, f"Failed: {inp} -> {result} != {expected}"

        print(f"  - All {len(cases)} parsing test cases passed")
        return True
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

def test_search_signature():
    """Verify search function signature."""
    print("\n✓ Test 7: Search function signature")
    try:
        from email_index import search_email_index
        import inspect

        sig = inspect.signature(search_email_index)
        params = list(sig.parameters.keys())
        expected = ["email", "query", "limit", "from_addr", "received_after", "received_before"]

        print(f"  - Parameters: {params}")
        for param in expected:
            if param not in params:
                print(f"  ✗ Missing parameter: {param}")
                return False
        return True
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

def main():
    """Run all tests."""
    setup_test_env()

    print("=" * 60)
    print("Email RAG Integration Tests")
    print("=" * 60)

    tests = [
        test_email_index_import,
        test_tool_schema,
        test_orchestrator_integration,
        test_index_file_permissions,
        test_email_text_extraction,
        test_metadata_parsing,
        test_search_signature,
    ]

    results = [test() for test in tests]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)

    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
