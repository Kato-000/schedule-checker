//! 予定チェッカーのデスクトップ部分。
//! - widget: 常に最前面の小さなウィジェット（起動時に表示）
//! - main:   カレンダーと承認画面（起動時は隠しておき、ウィジェットやトレイから開く）
//! データとLLMの処理はPython のバックエンド（127.0.0.1:8765）が担当する。

use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    webview::{PermissionKind, PermissionResponse},
    AppHandle, Manager, WindowEvent,
};

fn show(app: &AppHandle, label: &str) {
    if let Some(w) = app.get_webview_window(label) {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn toggle(app: &AppHandle, label: &str) {
    if let Some(w) = app.get_webview_window(label) {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            show(app, label);
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // 音声入力：このアプリの画面からのマイク使用は許可する（毎回の確認を出さない）。
        // 録音はPCのバックエンドにだけ送られる。カメラなどほかの権限は既定どおり。
        .on_permission_request(|_webview, kind| match kind {
            PermissionKind::Microphone => PermissionResponse::Allow,
            _ => PermissionResponse::Default,
        })
        .setup(|app| {
            let widget = MenuItem::with_id(app, "widget", "ウィジェットを表示 / 隠す", true, None::<&str>)?;
            let main = MenuItem::with_id(app, "main", "メイン画面を開く", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "終了", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&widget, &main, &sep, &quit])?;

            TrayIconBuilder::with_id("tray")
                .icon(app.default_window_icon().cloned().expect("アイコンがありません"))
                .tooltip("予定チェッカー")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "widget" => toggle(app, "widget"),
                    "main" => show(app, "main"),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // 左クリックでウィジェットを出す
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show(tray.app_handle(), "widget");
                    }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // ×で閉じても終了せず隠す（トレイから再表示。終了はトレイの「終了」）
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("予定チェッカーを起動できませんでした");
}
