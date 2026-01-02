from enum import IntEnum
from typing import Any
from pydantic import BaseModel


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


class TextDocumentEdit(BaseModel):
    textDocument: VersionedTextDocumentIdentifier
    edits: list[TextEdit]


class CreateFileOptions(BaseModel):
    overwrite: bool | None = None
    ignoreIfExists: bool | None = None


class CreateFile(BaseModel):
    kind: str = "create"
    uri: str
    options: CreateFileOptions | None = None


class RenameFileOptions(BaseModel):
    overwrite: bool | None = None
    ignoreIfExists: bool | None = None


class RenameFile(BaseModel):
    kind: str = "rename"
    oldUri: str
    newUri: str
    options: RenameFileOptions | None = None


class DeleteFileOptions(BaseModel):
    recursive: bool | None = None
    ignoreIfNotExists: bool | None = None


class DeleteFile(BaseModel):
    kind: str = "delete"
    uri: str
    options: DeleteFileOptions | None = None


class WorkspaceEdit(BaseModel):
    changes: dict[str, list[TextEdit]] | None = None
    documentChanges: list[TextDocumentEdit | CreateFile | RenameFile | DeleteFile] | None = None


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
    Empty = ""
    QuickFix = "quickfix"
    Refactor = "refactor"
    RefactorExtract = "refactor.extract"
    RefactorInline = "refactor.inline"
    RefactorRewrite = "refactor.rewrite"
    Source = "source"
    SourceOrganizeImports = "source.organizeImports"
    SourceFixAll = "source.fixAll"


class CodeAction(BaseModel):
    title: str
    kind: str | None = None
    diagnostics: list[Diagnostic] | None = None
    isPreferred: bool | None = None
    edit: WorkspaceEdit | None = None
    command: Command | None = None
    data: Any | None = None


class MarkupKind:
    PlainText = "plaintext"
    Markdown = "markdown"


class MarkupContent(BaseModel):
    kind: str
    value: str


class Hover(BaseModel):
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
    from_: CallHierarchyItem
    fromRanges: list[Range]

    model_config = {"populate_by_name": True}


class CallHierarchyOutgoingCall(BaseModel):
    to: CallHierarchyItem
    fromRanges: list[Range]
