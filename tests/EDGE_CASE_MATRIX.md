# SPEC section 14 test map

All tests below use temporary files, fake metadata services, or generated PDFs. GUI-specific
behavior in row 25 is scheduled for M5; the single-writer part is covered here.

| Row | Behavior | Test |
|---|---|---|
| 1 | Already named | `test_identified_file_is_renamed_and_recorded_once` |
| 2 | Same file downloaded twice | `test_same_paper_collision_uses_dup_suffix_without_overwrite`; `test_annotated_file_and_copy_need_no_new_lookup` |
| 3 | Same paper, different PDF | `test_different_pdf_same_doi_reuses_paper_cache` |
| 4 | Hand rename | `test_hand_rename_and_move_are_respected` |
| 5 | Move | `test_hand_rename_and_move_are_respected` |
| 6 | Annotate and save | `test_annotated_file_and_copy_need_no_new_lookup` |
| 7 | Download in progress | `test_partial_download_is_never_read` |
| 8 | Locked file | `test_locked_rename_becomes_pending_and_retries_without_lookup` |
| 9 | Cited DOI trap | `test_reference_doi_trap_moves_to_next_candidate` |
| 10 | Cover page title trap | `test_journal_preproof_cover_cannot_match_unrelated_record` |
| 11 | Service outage | `test_doi_sources_fail_over_in_order` |
| 12 | All services down | `test_outage_fallback_and_unknown_rules`; `test_check_file_auto_corrects_on_retry` |
| 13 | Non-paper PDF | `test_invoice_stays_untouched_without_a_lookup` |
| 14 | Scanned PDF with property DOI | `test_scanned_pdf_with_property_doi_is_trusted` |
| 15 | Unreadable PDF | `test_corrupt_pdf_raises_clear_error`; `test_password_failure_is_classified`; `test_check_unknown_and_unreadable_statuses` |
| 16 | Long title | `test_budget_cuts_title_on_whole_words` |
| 17 | Deep Windows path | `test_windows_full_path_and_suffix_budget` |
| 18 | Different papers with truncated collision | `test_different_paper_collision_extends_title` |
| 19 | Non-Latin fields | `test_field_cleaning_and_non_latin_fallback` |
| 20 | Missing author/year | `test_six_token_values_and_missing_fields` |
| 21 | New format only for new files | `test_naming_change_affects_new_files_until_reformat` |
| 22 | Undo | `test_undo_latest_batch_and_last_n`; `test_undo_does_not_overwrite_and_reformat_restores_given_name` |
| 23 | Unplugged folder | `test_unplugged_folder_returns_and_retry_timer` |
| 24 | Overlapping folders | `test_folder_overlap_rejected_or_merged` |
| 25 | Two writers | `test_only_one_writer_and_release` |
| 26 | Unreadable database | `test_backup_once_per_day_and_restore`; `test_corruption_without_backup_stops` |
| 27 | Deleted file | `test_scan_emits_progress_and_prunes_only_reachable_folders` |
| 28 | Draft/privacy exclusions | `test_excludes_file_globs_and_folder_names_before_reading`; `test_title_search_privacy_switch_sends_no_titles` |
| 29 | File arrives while stopped | `test_startup_scan_and_created_moved_events` |
| 30 | In-press year changes | `test_refresh_updates_year_but_preserves_file_on_failed_lookup` |
| 31 | Sleep/wake reconcile | `test_unplugged_folder_returns_and_retry_timer` (advances watcher time) |
| 32 | Large/interrupted scan and 429 | `test_scan_emits_progress_and_prunes_only_reachable_folders`; `test_interrupted_scan_resumes_without_pruning`; `test_one_retry_then_success` |
