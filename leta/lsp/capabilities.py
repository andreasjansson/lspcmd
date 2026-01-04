from typing import Any


def get_client_capabilities() -> dict[str, Any]:
    return {
        "experimental": {
            "serverStatusNotification": True,
        },
        "workspace": {
            "applyEdit": True,
            "workspaceEdit": {
                "documentChanges": True,
                "resourceOperations": ["create", "rename", "delete"],
            },
            "symbol": {
                "dynamicRegistration": False,
                "symbolKind": {"valueSet": list(range(1, 27))},
            },
            "executeCommand": {"dynamicRegistration": False},
            "fileOperations": {
                "dynamicRegistration": False,
                "willRename": True,
                "didRename": True,
            },
        },
        "textDocument": {
            "synchronization": {
                "dynamicRegistration": False,
                "didSave": True,
            },
            "hover": {
                "dynamicRegistration": False,
                "contentFormat": ["markdown", "plaintext"],
            },
            "declaration": {"dynamicRegistration": False, "linkSupport": True},
            "definition": {"dynamicRegistration": False, "linkSupport": True},
            "typeDefinition": {"dynamicRegistration": False, "linkSupport": True},
            "implementation": {"dynamicRegistration": False, "linkSupport": True},
            "references": {"dynamicRegistration": False},
            "documentSymbol": {
                "dynamicRegistration": False,
                "symbolKind": {"valueSet": list(range(1, 27))},
                "hierarchicalDocumentSymbolSupport": True,
            },
            "codeAction": {
                "dynamicRegistration": False,
                "codeActionLiteralSupport": {
                    "codeActionKind": {
                        "valueSet": [
                            "",
                            "quickfix",
                            "refactor",
                            "refactor.extract",
                            "refactor.inline",
                            "refactor.rewrite",
                            "source",
                            "source.organizeImports",
                            "source.fixAll",
                        ]
                    }
                },
                "isPreferredSupport": True,
                "resolveSupport": {"properties": ["edit"]},
            },
            "formatting": {"dynamicRegistration": False},
            "rangeFormatting": {"dynamicRegistration": False},
            "rename": {"dynamicRegistration": False, "prepareSupport": True},
            "publishDiagnostics": {
                "relatedInformation": True,
            },
            "callHierarchy": {
                "dynamicRegistration": False,
            },
            "typeHierarchy": {
                "dynamicRegistration": False,
            },
        },
    }
