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
    pub fn from_lsp(kind: lsp_types::SymbolKind) -> Self {
        match kind {
            lsp_types::SymbolKind::FILE => SymbolKind::File,
            lsp_types::SymbolKind::MODULE => SymbolKind::Module,
            lsp_types::SymbolKind::NAMESPACE => SymbolKind::Namespace,
            lsp_types::SymbolKind::PACKAGE => SymbolKind::Package,
            lsp_types::SymbolKind::CLASS => SymbolKind::Class,
            lsp_types::SymbolKind::METHOD => SymbolKind::Method,
            lsp_types::SymbolKind::PROPERTY => SymbolKind::Property,
            lsp_types::SymbolKind::FIELD => SymbolKind::Field,
            lsp_types::SymbolKind::CONSTRUCTOR => SymbolKind::Constructor,
            lsp_types::SymbolKind::ENUM => SymbolKind::Enum,
            lsp_types::SymbolKind::INTERFACE => SymbolKind::Interface,
            lsp_types::SymbolKind::FUNCTION => SymbolKind::Function,
            lsp_types::SymbolKind::VARIABLE => SymbolKind::Variable,
            lsp_types::SymbolKind::CONSTANT => SymbolKind::Constant,
            lsp_types::SymbolKind::STRING => SymbolKind::String,
            lsp_types::SymbolKind::NUMBER => SymbolKind::Number,
            lsp_types::SymbolKind::BOOLEAN => SymbolKind::Boolean,
            lsp_types::SymbolKind::ARRAY => SymbolKind::Array,
            lsp_types::SymbolKind::OBJECT => SymbolKind::Object,
            lsp_types::SymbolKind::KEY => SymbolKind::Key,
            lsp_types::SymbolKind::NULL => SymbolKind::Null,
            lsp_types::SymbolKind::ENUM_MEMBER => SymbolKind::EnumMember,
            lsp_types::SymbolKind::STRUCT => SymbolKind::Struct,
            lsp_types::SymbolKind::EVENT => SymbolKind::Event,
            lsp_types::SymbolKind::OPERATOR => SymbolKind::Operator,
            lsp_types::SymbolKind::TYPE_PARAMETER => SymbolKind::TypeParameter,
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

impl std::str::FromStr for SymbolKind {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "file" => Ok(SymbolKind::File),
            "module" => Ok(SymbolKind::Module),
            "namespace" => Ok(SymbolKind::Namespace),
            "package" => Ok(SymbolKind::Package),
            "class" => Ok(SymbolKind::Class),
            "method" => Ok(SymbolKind::Method),
            "property" => Ok(SymbolKind::Property),
            "field" => Ok(SymbolKind::Field),
            "constructor" => Ok(SymbolKind::Constructor),
            "enum" => Ok(SymbolKind::Enum),
            "interface" => Ok(SymbolKind::Interface),
            "function" => Ok(SymbolKind::Function),
            "variable" => Ok(SymbolKind::Variable),
            "constant" => Ok(SymbolKind::Constant),
            "string" => Ok(SymbolKind::String),
            "number" => Ok(SymbolKind::Number),
            "boolean" => Ok(SymbolKind::Boolean),
            "array" => Ok(SymbolKind::Array),
            "object" => Ok(SymbolKind::Object),
            "key" => Ok(SymbolKind::Key),
            "null" => Ok(SymbolKind::Null),
            "enummember" => Ok(SymbolKind::EnumMember),
            "struct" => Ok(SymbolKind::Struct),
            "event" => Ok(SymbolKind::Event),
            "operator" => Ok(SymbolKind::Operator),
            "typeparameter" => Ok(SymbolKind::TypeParameter),
            _ => Err(format!("Unknown symbol kind: {}", s)),
        }
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
    #[serde(skip_serializing_if = "Option::is_none", rename = "ref")]
    pub reference: Option<String>,
}

impl SymbolInfo {
    pub fn new(name: String, kind: SymbolKind, path: String, line: u32) -> Self {
        Self {
            name,
            kind: kind.to_string(),
            path,
            line,
            column: 0,
            container: None,
            detail: None,
            documentation: None,
            range_start_line: None,
            range_end_line: None,
            reference: None,
        }
    }
}
