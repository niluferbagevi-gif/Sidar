# `uploader/git_ops.py` — Git Çalışma Ağacı İşlemleri

- **Kaynak dosya:** `uploader/git_ops.py`
- **Not dosyası:** `docs/module-notes/uploader/git_ops.py.md`

**Amaç:** Upload akışının dal, merge ve stage işlemleri.

**Özellikler:**
- `create_upload_branch`, `record_upload_source_head`.
- `get_unmerged_files`, `assert_no_unmerged_files`, `print_unmerged_files`, `abort_in_progress_merge`, `switch_back_to_original_branch`.
- `create_rollback_backup_tag`, `report_ours_strategy_changes`, `get_deleted_files`, `get_commit_count`.
- `stage_files`, `stage_deleted_files` — literal pathspec ile stage.
