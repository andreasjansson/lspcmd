from enum import IntEnum
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class LSPModel(BaseModel):
    """Base model with camelCase serialization aliases."""
    model_config = ConfigDict(populate_by_name=True)


class Position(LSPModel):
    line: int
    character: int


class Range(LSPModel):
    start: Position
    end: Position


class Location(LSPModel):
    uri: str
    range: Range


class LocationLink(LSPModel):
    origin_selection_range: Range | None = Field(default=None, serialization_alias="originSelectionRange")
    target_uri: str = Field(serialization_alias="targetUri")
    target_range: Range = Field(serialization_alias="targetRange")
    target_selection_range: Range = Field(serialization_alias="targetSelectionRange")


class TextDocumentIdentifier(LSPModel):
    uri: str


class VersionedTextDocumentIdentifier(TextDocumentIdentifier):
    version: int


class OptionalVersionedTextDocumentIdentifier(TextDocumentIdentifier):
    version: int | None = None


class TextDocumentItem(LSPModel):
    uri: str
    language_id: str = Field(serialization_alias="languageId")
    version: int
    text: str


class TextDocumentPositionParams(LSPModel):
    text_document: TextDocumentIdentifier = Field(serialization_alias="textDocument")
    position: Position


class TextEdit(LSPModel):
    range: Range
    new_text: str = Field(serialization_alias="newText")


class AnnotatedTextEdit(TextEdit):
    annotation_id: str | None = Field(default=None, serialization_alias="annotationId")


class TextDocumentEdit(LSPModel):
    text_document: OptionalVersionedTextDocumentIdentifier = Field(serialization_alias="textDocument")
    edits: list[TextEdit | AnnotatedTextEdit]


class CreateFileOptions(LSPModel):
    overwrite: bool | None = None
    ignore_if_exists: bool | None = Field(default=None, serialization_alias="ignoreIfExists")


class CreateFile(LSPModel):
    kind: Literal["create"] = "create"
    uri: str
    options: CreateFileOptions | None = None


class RenameFileOptions(LSPModel):
    overwrite: bool | None = None
    ignore_if_exists: bool | None = Field(default=None, serialization_alias="ignoreIfExists")


class RenameFile(LSPModel):
    kind: Literal["rename"] = "rename"
    old_uri: str = Field(serialization_alias="oldUri")
    new_uri: str = Field(serialization_alias="newUri")
    options: RenameFileOptions | None = None


class DeleteFileOptions(LSPModel):
    recursive: bool | None = None
    ignore_if_not_exists: bool | None = Field(default=None, serialization_alias="ignoreIfNotExists")


class DeleteFile(LSPModel):
    kind: Literal["delete"] = "delete"
    uri: str
    options: DeleteFileOptions | None = None


class WorkspaceEdit(LSPModel):
    changes: dict[str, list[TextEdit]] | None = None
    document_changes: list[TextDocumentEdit | CreateFile | RenameFile | DeleteFile] | None = Field(
        default=None, serialization_alias="documentChanges"
    )


class Command(LSPModel):
    title: str
    command: str
    arguments: list[Any] | None = None


class SymbolKind(IntEnum):
    File = 1
    Module = 2
    Namespace = 3
    Package = 4
    Class = 5
    Method = 6
    Property = 7
    Field = 8
    Constructor = 9
    Enum = 10
    Interface = 11
    Function = 12
    Variable = 13
    Constant = 14
    String = 15
    Number = 16
    Boolean = 17
    Array = 18
    Object = 19
    Key = 20
    Null = 21
    EnumMember = 22
    Struct = 23
    Event = 24
    Operator = 25
    TypeParameter = 26


class SymbolInformation(LSPModel):
    name: str
    kind: int
    location: Location
    container_name: str | None = Field(default=None, validation_alias="containerName")


class DocumentSymbol(LSPModel):
    name: str
    kind: int
    range: Range
    selection_range: Range = Field(validation_alias="selectionRange")
    detail: str | None = None
    children: list["DocumentSymbol"] | None = None


class Diagnostic(LSPModel):
    range: Range
    message: str
    severity: int | None = None
    code: str | int | None = None
    source: str | None = None


class CodeActionKind:
    Empty = ""
    QuickFix = "quickfix"
    Refactor = "refactor"
    RefactorExtract = "refactor.extract"
    RefactorInline = "refactor.inline"
    RefactorRewrite = "refactor.rewrite"
    Source = "source"
    SourceOrganizeImports = "source.organizeImports"
    SourceFixAll = "source.fixAll"


class CodeAction(LSPModel):
    title: str
    kind: str | None = None
    diagnostics: list[Diagnostic] | None = None
    is_preferred: bool | None = Field(default=None, validation_alias="isPreferred")
    edit: WorkspaceEdit | None = None
    command: Command | None = None
    data: Any | None = None


class MarkupKind:
    PlainText = "plaintext"
    Markdown = "markdown"


class MarkupContent(LSPModel):
    kind: str
    value: str


class Hover(LSPModel):
    contents: MarkupContent | str | list[str]
    range: Range | None = None


class CompletionItemKind(IntEnum):
    Text = 1
    Method = 2
    Function = 3
    Constructor = 4
    Field = 5
    Variable = 6
    Class = 7
    Interface = 8
    Module = 9
    Property = 10
    Unit = 11
    Value = 12
    Enum = 13
    Keyword = 14
    Snippet = 15
    Color = 16
    File = 17
    Reference = 18
    Folder = 19
    EnumMember = 20
    Constant = 21
    Struct = 22
    Event = 23
    Operator = 24
    TypeParameter = 25


class CompletionItem(LSPModel):
    label: str
    kind: int | None = None
    detail: str | None = None
    documentation: MarkupContent | str | None = None
    insert_text: str | None = Field(default=None, validation_alias="insertText")
    text_edit: TextEdit | None = Field(default=None, validation_alias="textEdit")


class CompletionList(LSPModel):
    is_incomplete: bool = Field(validation_alias="isIncomplete")
    items: list[CompletionItem]


class SignatureInformation(LSPModel):
    label: str
    documentation: MarkupContent | str | None = None
    parameters: list["ParameterInformation"] | None = None


class ParameterInformation(LSPModel):
    label: str | tuple[int, int]
    documentation: MarkupContent | str | None = None


class SignatureHelp(LSPModel):
    signatures: list[SignatureInformation]
    active_signature: int | None = Field(default=None, validation_alias="activeSignature")
    active_parameter: int | None = Field(default=None, validation_alias="activeParameter")


class FormattingOptions(LSPModel):
    tab_size: int = Field(serialization_alias="tabSize")
    insert_spaces: bool = Field(serialization_alias="insertSpaces")
    trim_trailing_whitespace: bool | None = Field(default=None, serialization_alias="trimTrailingWhitespace")
    insert_final_newline: bool | None = Field(default=None, serialization_alias="insertFinalNewline")
    trim_final_newlines: bool | None = Field(default=None, serialization_alias="trimFinalNewlines")


class ReferenceContext(LSPModel):
    include_declaration: bool = Field(serialization_alias="includeDeclaration")


class CallHierarchyItem(LSPModel):
    name: str
    kind: int
    uri: str
    range: Range
    selection_range: Range = Field(validation_alias="selectionRange", serialization_alias="selectionRange")
    detail: str | None = None
    data: Any | None = None


class CallHierarchyIncomingCall(LSPModel):
    from_: CallHierarchyItem = Field(validation_alias="from", serialization_alias="from")
    from_ranges: list[Range] = Field(validation_alias="fromRanges", serialization_alias="fromRanges")


class CallHierarchyOutgoingCall(LSPModel):
    to: CallHierarchyItem
    from_ranges: list[Range] = Field(validation_alias="fromRanges", serialization_alias="fromRanges")


class TypeHierarchyItem(LSPModel):
    name: str
    kind: int
    uri: str
    range: Range
    selection_range: Range = Field(validation_alias="selectionRange", serialization_alias="selectionRange")
    detail: str | None = None
    tags: list[int] | None = None
    data: Any | None = None


class ServerCapabilities(LSPModel, extra="allow"):
    pass


class ServerInfo(LSPModel):
    name: str
    version: str | None = None


class InitializeResult(LSPModel):
    capabilities: ServerCapabilities
    server_info: ServerInfo | None = Field(default=None, validation_alias="serverInfo")


# =============================================================================
# LSP Request Params
# =============================================================================


class WorkspaceFolder(LSPModel):
    uri: str
    name: str


class ClientCapabilities(LSPModel, extra="allow"):
    pass


class InitializeParams(LSPModel):
    process_id: int | None = Field(serialization_alias="processId")
    root_uri: str | None = Field(serialization_alias="rootUri")
    root_path: str | None = Field(default=None, serialization_alias="rootPath")
    capabilities: ClientCapabilities
    workspace_folders: list[WorkspaceFolder] | None = Field(default=None, serialization_alias="workspaceFolders")
    initialization_options: Any | None = Field(default=None, serialization_alias="initializationOptions")
    trace: str | None = None


class ReferenceParams(TextDocumentPositionParams):
    context: ReferenceContext


class DocumentSymbolParams(LSPModel):
    text_document: TextDocumentIdentifier = Field(serialization_alias="textDocument")


class RenameParams(LSPModel):
    text_document: TextDocumentIdentifier = Field(serialization_alias="textDocument")
    position: Position
    new_name: str = Field(serialization_alias="newName")


class CallHierarchyItemParams(LSPModel):
    item: CallHierarchyItem


class TypeHierarchyItemParams(LSPModel):
    item: TypeHierarchyItem


class FileRename(LSPModel):
    old_uri: str = Field(serialization_alias="oldUri")
    new_uri: str = Field(serialization_alias="newUri")


class RenameFilesParams(LSPModel):
    files: list[FileRename]


# =============================================================================
# LSP Response Type Aliases
# =============================================================================

DefinitionResponse = Location | list[Location] | list[LocationLink] | None
DeclarationResponse = Location | list[Location] | list[LocationLink] | None
ReferencesResponse = list[Location] | None
ImplementationResponse = Location | list[Location] | list[LocationLink] | None
TypeDefinitionResponse = Location | list[Location] | list[LocationLink] | None
HoverResponse = Hover | None
DocumentSymbolResponse = list[DocumentSymbol] | list[SymbolInformation] | None
RenameResponseType = WorkspaceEdit | None
PrepareCallHierarchyResponse = list[CallHierarchyItem] | None
CallHierarchyIncomingCallsResponse = list[CallHierarchyIncomingCall] | None
CallHierarchyOutgoingCallsResponse = list[CallHierarchyOutgoingCall] | None
PrepareTypeHierarchyResponse = list[TypeHierarchyItem] | None
TypeHierarchySubtypesResponse = list[TypeHierarchyItem] | None
TypeHierarchySupertypesResponse = list[TypeHierarchyItem] | None
WillRenameFilesResponse = WorkspaceEdit | None
