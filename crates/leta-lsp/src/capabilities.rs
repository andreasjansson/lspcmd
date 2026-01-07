use serde_json::{json, Value};

pub fn get_client_capabilities() -> Value {
    json!({
        "workspace": {
            "workspaceEdit": {
                "documentChanges": true,
                "resourceOperations": ["create", "rename", "delete"]
            },
            "fileOperations": {
                "willRename": true
            },
            "workspaceFolders": true,
            "configuration": true
        },
        "textDocument": {
            "definition": {
                "linkSupport": true
            },
            "declaration": {
                "linkSupport": true
            },
            "references": {
                "dynamicRegistration": false
            },
            "documentSymbol": {
                "hierarchicalDocumentSymbolSupport": true,
                "symbolKind": {
                    "valueSet": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26]
                }
            },
            "rename": {
                "prepareSupport": true,
                "dynamicRegistration": false
            },
            "hover": {
                "contentFormat": ["markdown", "plaintext"]
            },
            "callHierarchy": {
                "dynamicRegistration": false
            },
            "typeHierarchy": {
                "dynamicRegistration": false
            },
            "implementation": {
                "linkSupport": true
            },
            "typeDefinition": {
                "linkSupport": true
            },
            "synchronization": {
                "didSave": true,
                "willSave": false,
                "willSaveWaitUntil": false
            },
            "completion": {
                "completionItem": {
                    "snippetSupport": false
                }
            }
        },
        "window": {
            "workDoneProgress": true
        },
        "general": {
            "positionEncodings": ["utf-32", "utf-16"]
        }
    })
}
