"""
app/tests/unit/test_mcp_gateway_extraction.py
Unit tests for MCPGateway Ignite API extraction tools discovery & invocation.
"""
import pytest
from backend.tools.mcp_gateway import MCPGateway


def test_mcp_gateway_lists_ignite_tools():
    gateway = MCPGateway()
    tools = gateway.list_tools()
    tool_names = [t.name for t in tools]

    assert "system_status" in tool_names
    assert "ignite_list_templates" in tool_names
    assert "ignite_extract_file" in tool_names


def test_mcp_call_ignite_list_templates():
    gateway = MCPGateway()
    req = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "ignite_list_templates",
            "arguments": {}
        }
    }
    response = gateway.handle_request(req)
    assert response.error is None
    assert response.result is not None
    text = response.result["content"][0]["text"]

    assert "Invoice_Standard" in text
    assert "Medical_Prescription" in text
    assert "Meeting_Minutes" in text


def test_mcp_call_ignite_extract_file_missing_args():
    gateway = MCPGateway()
    req = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "ignite_extract_file",
            "arguments": {"filename": "test.pdf"}
        }
    }
    response = gateway.handle_request(req)
    assert response.error is None
    assert "Error: Missing required arguments" in response.result["content"][0]["text"]
