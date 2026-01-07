use serde_json::json;
use lsp_types::{DocumentSymbolParams, TextDocumentIdentifier, Uri};

fn main() {
    let uri: Uri = "file:///test/path.py".parse().unwrap();
    let params = DocumentSymbolParams {
        text_document: TextDocumentIdentifier { uri },
        work_done_progress_params: Default::default(),
        partial_result_params: Default::default(),
    };
    
    let message = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "textDocument/documentSymbol",
        "params": params,
    });
    
    println!("{}", serde_json::to_string_pretty(&message).unwrap());
}
