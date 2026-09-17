"""
app/backend/mcp_gateway.py
Skill 2.4 — Personal MCP (Model Context Protocol) Gateway for Ignite Chat

Implements a local JSON-RPC 2.0 Model Context Protocol gateway
for standard tool discovery (`tools/list`) and invocation (`tools/call`).

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.4
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Callable, Dict, List, Optional

from backend.core.libraries import get_assistant_logger
from backend.core.schemas import MCPRequest, MCPResponse, MCPTool
from backend.integrations.ignite_api_client import IgniteAPIClient
from backend.integrations.ignite_rag_transformer import extraction_to_rag_text

logger = get_assistant_logger("mcp_gateway")


class MCPGateway:
    """
    Local JSON-RPC 2.0 Model Context Protocol (MCP) tool gateway.
    """

    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self._register_default_tools()

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        """Register a new MCP tool with its handler function."""
        tool = MCPTool(name=name, description=description, parameters=parameters)
        self._tools[name] = tool
        self._handlers[name] = handler
        logger.info(f"Registered MCP Tool: '{name}'")

    def list_tools(self) -> List[MCPTool]:
        """Return a list of all registered MCP tools."""
        return list(self._tools.values())

    def handle_request(self, request_payload: Dict[str, Any]) -> MCPResponse:
        """
        Process an incoming JSON-RPC 2.0 MCP Request.
        Supported methods:
          - `tools/list`: Returns registered tools.
          - `tools/call`: Executes specified tool by name with params.
        """
        try:
            req = MCPRequest(**request_payload)
        except Exception as err:
            return MCPResponse(
                id="null",
                error={"code": -32600, "message": f"Invalid Request payload: {err}"},
            )

        if req.method == "tools/list":
            tools_list = [tool.model_dump() for tool in self.list_tools()]
            return MCPResponse(id=req.id, result={"tools": tools_list})

        elif req.method == "tools/call":
            name = req.params.get("name")
            args = req.params.get("arguments", {})

            if not name or name not in self._handlers:
                return MCPResponse(
                    id=req.id,
                    error={"code": -32601, "message": f"Tool '{name}' not found"},
                )

            try:
                result_data = self._handlers[name](args)
                return MCPResponse(
                    id=req.id,
                    result={"content": [{"type": "text", "text": str(result_data)}]},
                )
            except Exception as tool_err:
                logger.error(f"Error executing MCP tool '{name}': {tool_err}", exc_info=True)
                return MCPResponse(
                    id=req.id,
                    error={"code": -32000, "message": f"Tool execution failed: {tool_err}"},
                )
        else:
            return MCPResponse(
                id=req.id,
                error={"code": -32601, "message": f"Method '{req.method}' not supported"},
            )

    def _register_default_tools(self) -> None:
        """Register built-in utility tools."""
        self.register_tool(
            name="system_status",
            description="Returns Ignite Chat system status and timestamp",
            parameters={"type": "object", "properties": {}},
            handler=lambda args: "Ignite Chat MCP Gateway Active - OK",
        )

        self.register_tool(
            name="ignite_list_templates",
            description="Lists all available Ignite API extraction business templates organized by channel (doc, audio, image, video).",
            parameters={"type": "object", "properties": {}},
            handler=self._handle_list_templates,
        )

        self.register_tool(
            name="ignite_extract_file",
            description="Extracts structured data from a file using Ignite API business templates and returns markdown text blending model reasoning.",
            parameters={
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Name of the file e.g. prescription.mp3"},
                    "file_b64": {"type": "string", "description": "Base64 encoded string of the file content"},
                    "template_name": {"type": "string", "description": "Template name e.g. Medical_Prescription, Invoice_Standard, Meeting_Minutes"},
                },
                "required": ["filename", "file_b64", "template_name"],
            },
            handler=self._handle_extract_file,
        )

    def _handle_list_templates(self, args: Dict[str, Any]) -> str:
        """Handler for ignite_list_templates MCP tool."""
        return (
            "📄 Document Templates: Invoice_Standard, Resume_CV, Bank_Statement, Employment_Contract, Tax_Return\n"
            "🎙️ Audio Templates: Meeting_Minutes, Medical_Prescription, Voice_Memo_Tasks, Customer_Call_Audit, Interview_Audit\n"
            "🖼️ Image Templates: Medical_Prescription, Identity_Document, Invoice_Standard\n"
            "🎬 Video Templates: Lecture_Summary, Video_Ad_Analysis"
        )

    def _handle_extract_file(self, args: Dict[str, Any]) -> str:
        """Handler for ignite_extract_file MCP tool."""
        filename = args.get("filename", "")
        file_b64 = args.get("file_b64", "")
        template_name = args.get("template_name", "")

        if not filename or not file_b64 or not template_name:
            return "Error: Missing required arguments (filename, file_b64, template_name)."

        try:
            if "," in file_b64:
                file_b64 = file_b64.split(",", 1)[1]
            file_bytes = base64.b64decode(file_b64)
            client = IgniteAPIClient()
            result = client.extract_sync(file_bytes, filename, template_name)


            if not result:
                return f"Error: Ignite API extraction failed for file '{filename}' with template '{template_name}'."

            return extraction_to_rag_text(result, filename)
        except Exception as exc:
            logger.error("MCP tool ignite_extract_file error: %s", exc, exc_info=True)
            return f"Error executing extraction tool: {exc}"
