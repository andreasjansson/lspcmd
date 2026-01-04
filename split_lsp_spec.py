#!/usr/bin/env python3

import os

SECTIONS = [
    (1, 356, "01-base-protocol"),
    (357, 458, "02-language-server-protocol"),
    (459, 1665, "03-basic-json-structures"),
    (1666, 1880, "04-work-done-progress"),
    (1881, 1940, "05-partial-result-progress"),
    (1941, 1949, "06-trace-value"),
    (1950, 1955, "07-server-lifecycle"),
    (1956, 2890, "08-initialize-request"),
    (2891, 2908, "09-initialized-notification"),
    (2909, 3019, "10-register-capability"),
    (3020, 3075, "11-unregister-capability"),
    (3076, 3094, "12-set-trace-notification"),
    (3095, 3124, "13-log-trace-notification"),
    (3125, 3150, "14-shutdown-request"),
    (3151, 3163, "15-exit-notification"),
    (3164, 3232, "16-text-document-synchronization"),
    (3233, 3270, "17-did-open-text-document-notification"),
    (3271, 3373, "18-did-change-text-document-notification"),
    (3374, 3444, "19-will-save-text-document-notification"),
    (3445, 3487, "20-will-save-wait-until-text-document-request"),
    (3488, 3547, "21-did-save-text-document-notification"),
    (3548, 3647, "22-did-close-text-document-notification"),
    (3648, 4016, "23-notebook-document-synchronization"),
    (4017, 4048, "24-did-open-notebook-document-notification"),
    (4049, 4180, "25-did-change-notebook-document-notification"),
    (4181, 4205, "26-did-save-notebook-document-notification"),
    (4206, 4248, "27-did-close-notebook-document-notification"),
    (4249, 4260, "28-language-features"),
    (4261, 4324, "29-goto-declaration-request"),
    (4325, 4385, "30-goto-definition-request"),
    (4386, 4453, "31-goto-type-definition-request"),
    (4454, 4521, "32-goto-implementation-request"),
    (4522, 4579, "33-find-references-request"),
    (4580, 4687, "34-prepare-call-hierarchy-request"),
    (4688, 4730, "35-call-hierarchy-incoming-calls"),
    (4731, 4773, "36-call-hierarchy-outgoing-calls"),
    (4774, 4884, "37-prepare-type-hierarchy-request"),
    (4885, 4913, "38-type-hierarchy-supertypes"),
    (4914, 4942, "39-type-hierarchy-subtypes"),
    (4943, 5038, "40-document-highlights-request"),
    (5039, 5137, "41-document-link-request"),
    (5138, 5155, "42-document-link-resolve-request"),
    (5156, 5255, "43-hover-request"),
    (5256, 5339, "44-code-lens-request"),
    (5340, 5357, "45-code-lens-resolve-request"),
    (5358, 5400, "46-code-lens-refresh-request"),
    (5401, 5580, "47-folding-range-request"),
    (5581, 5670, "48-selection-range-request"),
    (5671, 5948, "49-document-symbols-request"),
    (5949, 6489, "50-semantic-tokens"),
    (6490, 6724, "51-inlay-hint-request"),
    (6725, 6759, "52-inlay-hint-resolve-request"),
    (6760, 6808, "53-inlay-hint-refresh-request"),
    (6809, 6990, "54-inline-value-request"),
    (6991, 7039, "55-inline-value-refresh-request"),
    (7040, 7189, "56-monikers"),
    (7190, 8029, "57-completion-request"),
    (8030, 8047, "58-completion-item-resolve-request"),
    (8048, 8151, "59-publish-diagnostics-notification"),
    (8152, 8259, "60-pull-diagnostics"),
    (8260, 8450, "61-document-diagnostics"),
    (8451, 8592, "62-workspace-diagnostics"),
    (8593, 8653, "63-diagnostics-refresh"),
    (8654, 8922, "64-signature-help-request"),
    (8923, 9350, "65-code-action-request"),
    (9351, 9391, "66-code-action-resolve-request"),
    (9392, 9493, "67-document-color-request"),
    (9494, 9561, "68-color-presentation-request"),
    (9562, 9661, "69-document-formatting-request"),
    (9662, 9727, "70-document-range-formatting-request"),
    (9728, 9810, "71-document-on-type-formatting-request"),
    (9811, 9916, "72-rename-request"),
    (9917, 9945, "73-prepare-rename-request"),
    (9946, 10023, "74-linked-editing-range"),
    (10024, 10025, "75-workspace-features"),
    (10026, 10195, "76-workspace-symbols-request"),
    (10196, 10213, "77-workspace-symbol-resolve-request"),
    (10214, 10277, "78-configuration-request"),
    (10278, 10311, "79-did-change-configuration-notification"),
    (10312, 10385, "80-workspace-folders-request"),
    (10386, 10433, "81-did-change-workspace-folders-notification"),
    (10434, 10597, "82-will-create-files-request"),
    (10598, 10625, "83-did-create-files-notification"),
    (10626, 10698, "84-will-rename-files-request"),
    (10699, 10726, "85-did-rename-files-notification"),
    (10727, 10793, "86-will-delete-files-request"),
    (10794, 10821, "87-did-delete-files-notification"),
    (10822, 11005, "88-did-change-watched-files-notification"),
    (11006, 11074, "89-execute-command"),
    (11075, 11136, "90-applies-workspace-edit"),
    (11137, 11138, "91-window-features"),
    (11139, 11192, "92-show-message-notification"),
    (11193, 11261, "93-show-message-request"),
    (11262, 11347, "94-show-document-request"),
    (11348, 11371, "95-log-message-notification"),
    (11372, 11403, "96-create-work-done-progress"),
    (11404, 11425, "97-cancel-work-done-progress"),
    (11426, 11440, "98-telemetry-notification"),
    (11441, 11496, "99-miscellaneous"),
]


def main():
    with open("lsp-spec.txt", "r") as f:
        lines = f.readlines()

    os.makedirs("lsp-spec", exist_ok=True)

    for start, end, name in SECTIONS:
        section_lines = lines[start - 1 : end]
        output_path = f"lsp-spec/{name}.txt"
        with open(output_path, "w") as f:
            f.writelines(section_lines)
        print(f"Wrote {output_path} (lines {start}-{end})")


def foo():
    print("bar")


if __name__ == "__main__":
    main()
