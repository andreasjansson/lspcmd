use serde_json::Value;
use thiserror::Error;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};

#[derive(Error, Debug)]
pub enum LspProtocolError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Invalid header: {0}")]
    InvalidHeader(String),
    #[error("Missing Content-Length header")]
    MissingContentLength,
    #[error("Connection closed")]
    ConnectionClosed,
    #[error("Request timeout: {0}")]
    Timeout(String),
    #[error("LSP response error: {0}")]
    Response(LspResponseError),
}

#[derive(Error, Debug, Clone)]
pub struct LspResponseError {
    pub code: i32,
    pub message: String,
    pub data: Option<Value>,
}

impl std::fmt::Display for LspResponseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "LSP error {}: {}", self.code, self.message)
    }
}

#[derive(Error, Debug)]
#[error("Language server '{name}' not found for {languages}. Install with: {install_cmd:?}")]
pub struct LanguageServerNotFound {
    pub name: String,
    pub languages: String,
    pub install_cmd: Option<String>,
}

#[derive(Error, Debug)]
#[error("Language server '{name}' for {languages} failed to start in workspace {workspace}: {message}")]
pub struct LanguageServerStartupError {
    pub name: String,
    pub languages: String,
    pub workspace: String,
    pub message: String,
    pub server_log: Option<String>,
    pub log_path: Option<String>,
}

#[derive(Error, Debug)]
#[error("LSP method '{method}' not supported by server")]
pub struct LspMethodNotSupported {
    pub method: String,
}

pub fn encode_message<T: serde::Serialize>(message: &T) -> Vec<u8> {
    let content = serde_json::to_vec(message).expect("Failed to serialize message");
    let header = format!("Content-Length: {}\r\n\r\n", content.len());
    let mut result = header.into_bytes();
    result.extend(content);
    result
}

pub async fn read_message<R: tokio::io::AsyncRead + Unpin>(
    reader: &mut BufReader<R>,
) -> Result<Value, LspProtocolError> {
    let mut content_length: Option<usize> = None;
    let mut line = String::new();

    loop {
        line.clear();
        let bytes_read = reader.read_line(&mut line).await?;
        if bytes_read == 0 {
            return Err(LspProtocolError::ConnectionClosed);
        }

        let trimmed = line.trim();
        if trimmed.is_empty() {
            break;
        }

        if let Some(len_str) = trimmed.strip_prefix("Content-Length:") {
            content_length = Some(
                len_str
                    .trim()
                    .parse()
                    .map_err(|_| LspProtocolError::InvalidHeader(trimmed.to_string()))?,
            );
        }
    }

    let length = content_length.ok_or(LspProtocolError::MissingContentLength)?;
    let mut content = vec![0u8; length];
    reader.read_exact(&mut content).await?;

    let value: Value = serde_json::from_slice(&content)?;
    Ok(value)
}
