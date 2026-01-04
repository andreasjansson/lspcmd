from enum import IntEnum
from typing import Any, ClassVar, Literal
from pydantic import BaseModel, ConfigDict, Field


class FileChangeType(IntEnum):
    Created = 1
    Changed = 2
    Deleted = 3


class FileEvent(BaseModel):
    uri: str
    type: int  # FileChangeType


class DidChangeWatchedFilesParams(BaseModel):
    changes: list[FileEvent]


class Position(BaseModel):
    line: int
    character: int


class Range(BaseModel):
    start: Position
    end: Position


class Location(BaseModel):
    uri: str
    range: Range


class LocationLink(BaseModel):
    originSelectionRange: Range | None = None
    targetUri: str
    targetRange: Range
    targetSelectionRange: Range


class TextDocumentIdentifier(BaseModel):
    uri: str


class VersionedTextDocumentIdentifier(TextDocumentIdentifier):
    version: int


class OptionalVersionedTextDocumentIdentifier(TextDocumentIdentifier):
    version: int | None = None


class TextDocumentItem(BaseModel):
    uri: str
    languageId: str
    version: int
    text: str


class TextDocumentPositionParams(BaseModel):
    textDocument: TextDocumentIdentifier
    position: Position


class TextEdit(BaseModel):
    range: Range
    newText: str


class AnnotatedTextEdit(TextEdit):
    annotationId: str | None = None


class TextDocumentEdit(BaseModel):
    textDocument: OptionalVersionedTextDocumentIdentifier
    edits: list[TextEdit | AnnotatedTextEdit]


class CreateFileOptions(BaseModel):
    overwrite: bool | None = None
    ignoreIfExists: bool | None = None


class CreateFile(BaseModel):
    kind: Literal["create"] = "create"
    uri: str
    options: CreateFileOptions | None = None


class RenameFileOptions(BaseModel):
    overwrite: bool | None = None
    ignoreIfExists: bool | None = None


class RenameFile(BaseModel):
    kind: Literal["rename"] = "rename"
    oldUri: str
    newUri: str
    options: RenameFileOptions | None = None


class DeleteFileOptions(BaseModel):
    recursive: bool | None = None
    ignoreIfNotExists: bool | None = None


class DeleteFile(BaseModel):
    kind: Literal["delete"] = "delete"
    uri: str
    options: DeleteFileOptions | None = None


class WorkspaceEdit(BaseModel):
    changes: dict[str, list[TextEdit]] | None = None
    documentChanges: (
        list[TextDocumentEdit | CreateFile | RenameFile | DeleteFile] | None
    ) = None


class Command(BaseModel):
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


class SymbolInformation(BaseModel):
    name: str
    kind: int
    location: Location
    containerName: str | None = None


class DocumentSymbol(BaseModel):
    name: str
    kind: int
    range: Range
    selectionRange: Range
    detail: str | None = None
    children: list["DocumentSymbol"] | None = None


class Diagnostic(BaseModel):
    range: Range
    message: str
    severity: int | None = None
    code: str | int | None = None
    source: str | None = None


class CodeActionKind:
    Empty: ClassVar[str] = ""
    QuickFix: ClassVar[str] = "quickfix"
    Refactor: ClassVar[str] = "refactor"
    RefactorExtract: ClassVar[str] = "refactor.extract"
    RefactorInline: ClassVar[str] = "refactor.inline"
    RefactorRewrite: ClassVar[str] = "refactor.rewrite"
    Source: ClassVar[str] = "source"
    SourceOrganizeImports: ClassVar[str] = "source.organizeImports"
    SourceFixAll: ClassVar[str] = "source.fixAll"


class CodeAction(BaseModel):
    title: str
    kind: str | None = None
    diagnostics: list[Diagnostic] | None = None
    isPreferred: bool | None = None
    edit: WorkspaceEdit | None = None
    command: Command | None = None
    data: Any | None = None


class MarkupKind:
    PlainText: ClassVar[str] = "plaintext"
    Markdown: ClassVar[str] = "markdown"


class MarkupContent(BaseModel):
    kind: str
    value: str


class MarkedString(BaseModel):
    language: str
    value: str


class Hover(BaseModel):
    contents: (
        MarkupContent | MarkedString | str | list[MarkupContent | MarkedString | str]
    )
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


class CompletionItem(BaseModel):
    label: str
    kind: int | None = None
    detail: str | None = None
    documentation: MarkupContent | str | None = None
    insertText: str | None = None
    textEdit: TextEdit | None = None


class CompletionList(BaseModel):
    isIncomplete: bool
    items: list[CompletionItem]


class SignatureInformation(BaseModel):
    label: str
    documentation: MarkupContent | str | None = None
    parameters: list["ParameterInformation"] | None = None


class ParameterInformation(BaseModel):
    label: str | tuple[int, int]
    documentation: MarkupContent | str | None = None


class SignatureHelp(BaseModel):
    signatures: list[SignatureInformation]
    activeSignature: int | None = None
    activeParameter: int | None = None


class FormattingOptions(BaseModel):
    tabSize: int
    insertSpaces: bool
    trimTrailingWhitespace: bool | None = None
    insertFinalNewline: bool | None = None
    trimFinalNewlines: bool | None = None


class ReferenceContext(BaseModel):
    includeDeclaration: bool


class CallHierarchyItem(BaseModel):
    name: str
    kind: int
    uri: str
    range: Range
    selectionRange: Range
    detail: str | None = None
    data: Any | None = None


class CallHierarchyIncomingCall(BaseModel):
    from_: CallHierarchyItem = Field(alias="from")
    fromRanges: list[Range]

    model_config: ClassVar[ConfigDict] = {"populate_by_name": True}


class CallHierarchyOutgoingCall(BaseModel):
    to: CallHierarchyItem
    fromRanges: list[Range]


class TypeHierarchyItem(BaseModel):
    name: str
    kind: int
    uri: str
    range: Range
    selectionRange: Range
    detail: str | None = None
    tags: list[int] | None = None
    data: Any | None = None


class ServerCapabilities(BaseModel, extra="allow"):
    def _has_capability(self, name: str) -> bool:
        """Check if a capability exists. Handles True, non-empty dict, or non-None values."""
        val = getattr(self, name, None)
        # None means not present
        if val is None:
            return False
        # Empty dict {} means supported (some servers like ruby-lsp use this)
        if isinstance(val, dict):
            return True
        # True/False or other truthy values
        return bool(val)

    def supports_call_hierarchy(self) -> bool:
        return self._has_capability("callHierarchyProvider")

    def supports_type_hierarchy(self) -> bool:
        return self._has_capability("typeHierarchyProvider")

    def supports_declaration(self) -> bool:
        return self._has_capability("declarationProvider")

    def supports_implementation(self) -> bool:
        return self._has_capability("implementationProvider")

    def supports_references(self) -> bool:
        return self._has_capability("referencesProvider")

    def supports_rename(self) -> bool:
        return self._has_capability("renameProvider")


class ServerInfo(BaseModel):
    name: str
    version: str | None = None


class InitializeResult(BaseModel):
    capabilities: ServerCapabilities
    serverInfo: ServerInfo | None = None


# =============================================================================
# LSP Request Params
# =============================================================================


class WorkspaceFolder(BaseModel):
    uri: str
    name: str


class ClientCapabilities(BaseModel, extra="allow"):
    pass


class InitializeParams(BaseModel):
    processId: int | None
    rootUri: str | None
    rootPath: str | None = None
    capabilities: ClientCapabilities
    workspaceFolders: list[WorkspaceFolder] | None = None
    initializationOptions: Any | None = None
    trace: str | None = None


class ReferenceParams(TextDocumentPositionParams):
    context: ReferenceContext


class DocumentSymbolParams(BaseModel):
    textDocument: TextDocumentIdentifier


class RenameParams(BaseModel):
    textDocument: TextDocumentIdentifier
    position: Position
    newName: str


class CallHierarchyItemParams(BaseModel):
    item: CallHierarchyItem


class TypeHierarchyItemParams(BaseModel):
    item: TypeHierarchyItem


class FileRename(BaseModel):
    oldUri: str
    newUri: str


class RenameFilesParams(BaseModel):
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
