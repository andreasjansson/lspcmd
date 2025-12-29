from typing import Any


def get_client_capabilities() -> dict[str, Any]:
    return {
        "workspace": {
            "workspaceFolders": True,
        },
    }
