;;; test-lspcmd-prompt.el --- Test if agent uses lspcmd vs ripgrep -*- lexical-binding: t -*-

(require 'greger)

(defun test-lspcmd-prompt-run-once (iteration)
  "Run the greger buffer once and return which tool was used."
  (let ((test-file "~/projects/greger.el/test/lspcmd-system-prompt-base.greger")
        (greger-buffer nil)
        (result nil))
    (unwind-protect
        (progn
          ;; Open the test file
          (setq greger-buffer (find-file-noselect (expand-file-name test-file)))
          
          (with-current-buffer greger-buffer
            ;; Delete final newline if present
            (goto-char (point-max))
            (when (eq (char-before) ?\n)
              (delete-char -1))
            
            ;; Set max iterations to 1
            (setq-local greger-max-iterations 1)
            
            ;; Run greger-buffer
            (let ((greger-current-thinking-budget 1024))
              (greger-buffer))
            
            ;; Wait for completion
            (let ((timeout 120)
                  (start-time (current-time)))
              (while (and (not (eq (greger--get-current-status) 'idle))
                          (< (float-time (time-subtract (current-time) start-time)) timeout))
                (sit-for 0.5)))
            
            ;; Check what tool was used - search backwards for TOOL USE
            (goto-char (point-max))
            (if (re-search-backward "^# TOOL USE" nil t)
                (progn
                  (forward-line 1)
                  (if (re-search-forward "^Name: \\(.+\\)$" nil t)
                      (setq result (match-string 1))
                    (setq result "unknown")))
              (setq result "no-tool-use"))))
      
      ;; Cleanup - kill the buffer without saving
      (when (and greger-buffer (buffer-live-p greger-buffer))
        (with-current-buffer greger-buffer
          (set-buffer-modified-p nil))
        (kill-buffer greger-buffer)))
    
    (message "Iteration %d: Tool used = %s" iteration result)
    result))

(defun test-lspcmd-prompt-main ()
  "Run the test 3 times and report results."
  (let ((results '()))
    (dotimes (i 3)
      (message "\n=== Running iteration %d ===" (1+ i))
      (push (test-lspcmd-prompt-run-once (1+ i)) results)
      ;; Small delay between runs
      (sit-for 1))
    
    (setq results (nreverse results))
    
    (message "\n\n========== RESULTS ==========")
    (let ((ripgrep-count 0)
          (lspcmd-count 0)
          (other-count 0))
      (dolist (r results)
        (message "  %s" r)
        (cond
         ((string-match-p "ripgrep\\|rg" r) (cl-incf ripgrep-count))
         ((string-match-p "lspcmd\\|shell-command.*lspcmd" r) (cl-incf lspcmd-count))
         ((string-match-p "shell-command" r)
          ;; Check if it's an lspcmd command
          (cl-incf other-count))
         (t (cl-incf other-count))))
      
      (message "\nSummary:")
      (message "  ripgrep: %d" ripgrep-count)
      (message "  lspcmd: %d" lspcmd-count)
      (message "  other: %d" other-count)
      
      (if (> ripgrep-count 0)
          (message "\nFAIL: Agent used ripgrep %d times instead of lspcmd" ripgrep-count)
        (message "\nPASS: Agent consistently used lspcmd")))
    
    results))

;; Run when loaded in batch mode
(when noninteractive
  (test-lspcmd-prompt-main))

(provide 'test-lspcmd-prompt)
;;; test-lspcmd-prompt.el ends here
