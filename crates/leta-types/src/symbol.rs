use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub enum SymbolKind {
    File,
    Module,
    Namespace,
    Package,
    Class,
    Method,
    Property,
    Field,
    Constructor,
    Enum,
    Interface,
    Function,
    Variable,
    Constant,
    String,
    Number,
    Boolean,
    Array,
    Object,
    Key,
    Null,
    EnumMember,
    Struct,
    Event,
    Operator,
    TypeParameter,
}

impl SymbolKind {
    pub fn from_lsp_kind(kind: u32) -> Self {
        match kind {
            1 => SymbolKind::File,
            2 => SymbolKind::Module,
            3 => SymbolKind::Namespace,
            4 => SymbolKind::Package,
            5 => SymbolKind::Class,
            6 => SymbolKind::Method,
            7 => SymbolKind::Property,
            8 => SymbolKind::Field,
            9 => SymbolKind::Constructor,
            10 => SymbolKind::Enum,
            11 => SymbolKind::Interface,
            12 => SymbolKind::Function,
            13 => SymbolKind::Variable,
            14 => SymbolKind::Constant,
            15 => SymbolKind::String,
            16 => SymbolKind::Number,
            17 => SymbolKind::Boolean,
            18 => SymbolKind::Array,
            19 => SymbolKind::Object,
            20 => SymbolKind::Key,
            21 => SymbolKind::Null,
            22 => SymbolKind::EnumMember,
            23 => SymbolKind::Struct,
            24 => SymbolKind::Event,
            25 => SymbolKind::Operator,
            26 => SymbolKind::TypeParameter,
            _ => SymbolKind::Variable,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            SymbolKind::File => "File",
            SymbolKind::Module => "Module",
            SymbolKind::Namespace => "Namespace",
            SymbolKind::Package => "Package",
            SymbolKind::Class => "Class",
            SymbolKind::Method => "Method",
            SymbolKind::Property => "Property",
            SymbolKind::Field => "Field",
            SymbolKind::Constructor => "Constructor",
            SymbolKind::Enum => "Enum",
            SymbolKind::Interface => "Interface",
            SymbolKind::Function => "Function",
            SymbolKind::Variable => "Variable",
            SymbolKind::Constant => "Constant",
            SymbolKind::String => "String",
            SymbolKind::Number => "Number",
            SymbolKind::Boolean => "Boolean",
            SymbolKind::Array => "Array",
            SymbolKind::Object => "Object",
            SymbolKind::Key => "Key",
            SymbolKind::Null => "Null",
            SymbolKind::EnumMember => "EnumMember",
            SymbolKind::Struct => "Struct",
            SymbolKind::Event => "Event",
            SymbolKind::Operator => "Operator",
            SymbolKind::TypeParameter => "TypeParameter",
        }
    }
}

impl std::fmt::Display for SymbolKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SymbolInfo {
    pub name: String,
    pub kind: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub container: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub documentation: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_start_line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_end_line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub r#ref: Option<String>,
}

impl SymbolInfo {
    pub fn new(name: String, kind: SymbolKind, path: String, line: u32) -> Self {
        Self {
            name,
            kind: kind.as_str().to_string(),
            path,
            line,
            column: 0,
            container: None,
            detail: None,
            documentation: None,
            range_start_line: None,
            range_end_line: None,
            r#ref: None,
        }
    }
}
