// Every @bridge method of discjockey/hub/api.py, in contract order. A test compares this list to api.py and to the fake.
// (The plan said 43; the contract since added rekordbox_checked, setup_qobuz_token_help and quit: 46,
// then never_download: 47; limits, limits_what_if and save_limits: 50; the four account setup methods: 54; the three Qobuz-only methods gone: 51;
// mark_warnings_seen: 52; downloads_view: 53; the two Qobuz web-player methods gone: 51; Settings' sign-ins: 57; rollback_tools: +1; app_update: +1; tidy_preview, move_batches, undo_preview, tidy_up, undo_moves: +5.)
export const CONTRACT_METHODS = [
  // read, any time
  'dashboard', 'sidebar', 'sync_preview', 'refresh', 'stop_refresh', 'job_status', 'library', 'track', 'todo',
  'playlists', 'limits', 'limits_what_if', 'runs', 'run', 'spectrum', 'media_url', 'setup_status', 'select',
  'tidy_preview', 'move_batches', 'undo_preview',
  // read with network
  'search_candidates', 'preview', 'add_playlist', 'preview_playlist_change',
  // write jobs
  'start_sync', 'stop', 'save_playlists', 'save_limits', 'mark_warnings_seen', 'hide', 'never_download', 'add_bought_file',
  'use_candidate', 'use_link', 'reject_current', 'rekordbox_checked', 'upgrade', 'rescan_library',
  'tidy_up', 'undo_moves',
  // other
  'show_in_finder', 'reveal', 'open_report', 'open_external', 'app_update', 'quit',
  // setup
  'setup_check_tools', 'setup_save_client_id', 'setup_spotify_login', 'setup_qobuz_login',
  'open_licenses', 'update_tools', 'rollback_tools',
  'setup_skip_qobuz', 'setup_skip_spotify', 'setup_account', 'setup_check_account', 'setup_forget_account',
  // settings
  'downloads_view', 'find_logins', 'account_sign_in', 'stop_sign_in', 'open_privacy_settings', 'qobuz_check_login',
  'spotify_sign_out',
  // the music folder
  'pick_folder', 'check_music_folder', 'set_music_folder', 'retry_music_folder',
] as const;
export type ContractMethod = (typeof CONTRACT_METHODS)[number];

/** Methods that answer `no_library` while no music folder is bound (api.py LIBRARY_METHODS; a test compares them). */
export const LIBRARY_METHODS = [
  'dashboard', 'sidebar', 'sync_preview', 'refresh', 'library', 'track', 'todo', 'playlists', 'limits',
  'limits_what_if', 'save_limits', 'mark_warnings_seen', 'runs', 'run', 'spectrum', 'media_url',
  'search_candidates', 'preview', 'add_playlist', 'preview_playlist_change', 'start_sync', 'save_playlists',
  'hide', 'never_download', 'add_bought_file', 'use_candidate', 'use_link', 'reject_current',
  'rekordbox_checked', 'upgrade', 'rescan_library', 'show_in_finder', 'reveal', 'open_report',
  'tidy_preview', 'move_batches', 'undo_preview', 'tidy_up', 'undo_moves',
] as const satisfies readonly ContractMethod[];
