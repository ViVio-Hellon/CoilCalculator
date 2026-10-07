//! VC長さ・コイル平板 計算ツール デスクトップ版の外枠
//!
//! 【役割の分け方】(各言語が得意なことをする)
//!
//! - **Rust(ここ)**: 窓・画面のファイルを返す・Python の起動と監視・多重起動の防止・
//!   ブラウザ版との排他(後から開いたほうが止まる)・窓の × の確かめ(文と判断は Python)
//! - **Python(`bridge.py` → `coilcalc/`)**: 計算・入力の範囲・丸め・画面に出す文字
//!   (ブラウザ版と同じ関数を通る。計算の正は1か所)
//! - **JS(`app/static/`)**: 画面の操作・3D(three.js)・グラフ(Chart.js)・印刷
//!
//! 【ポートを使わない】
//! 画面(WebView)は独自の宛先 `app://localhost/`(Windows では `http://app.localhost/`)を
//! 読む。ネットワークを通らない。画面のファイルはここがディスクから返し(`static_files.rs`)、
//! 計算(`/api/…`)だけを Python の標準入力へ渡す(`bridge.rs`)。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;
mod instance;
mod pages;
mod static_files;

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::http::{Request, Response};
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use bridge::{Bridge, Phase};
use instance::{Refusal, Take};

/// 画面の宛先の名前
const SCHEME: &str = "app";
const TITLE: &str = "VC長さ・コイル平板 計算ツール";
/// 外枠の版。`config/app.json`・`tauri.conf.json` と同じ(試験が突き合わせる)
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// 操作説明書の頁(`app/static/manual/`)。ここに無い名前は開かない
const MANUAL_PAGES: [&str; 4] = ["index", "vc", "coil", "plate"];

/// 終わったときの番号(ブラウザ版の `start_app.py` と同じ)
const EXIT_OTHER_RUNNING: i32 = 3;

/// 計算の要求が、Python の起動を待つ上限
const API_START_WAIT: Duration = Duration::from_secs(60);

/// 画面の宛先の頭。Windows(WebView2)は `http://<名前>.localhost`、ほかは `<名前>://localhost`
fn origin() -> String {
    if cfg!(windows) {
        format!("http://{SCHEME}.localhost")
    } else {
        format!("{SCHEME}://localhost")
    }
}

fn app_url(path: &str) -> tauri::Url {
    format!("{}{}", origin(), path).parse().expect("app url")
}

fn is_app_url(url: &tauri::Url) -> bool {
    url.as_str().starts_with(&origin())
}

/// アプリ一式のフォルダ(`bridge.py` がある所)。
///
/// 配るときは exe をフォルダの直下に置く。開発中は `src-tauri/target/...` から
/// 動くので、上へたどって探す。`COIL_TOOL_ROOT` で指定もできる。
fn app_root() -> PathBuf {
    if let Ok(root) = std::env::var("COIL_TOOL_ROOT") {
        if !root.trim().is_empty() {
            return PathBuf::from(root);
        }
    }
    let exe = std::env::current_exe().unwrap_or_default();
    let mut dir = exe.parent().map(Path::to_path_buf).unwrap_or_default();
    let start = dir.clone();
    for _ in 0..5 {
        if dir.join("bridge.py").is_file() {
            return dir;
        }
        match dir.parent() {
            Some(parent) => dir = parent.to_path_buf(),
            None => break,
        }
    }
    start
}

fn log_hint(root: &Path) -> String {
    instance::local_root(root).join("logs").display().to_string()
}

fn respond(status: u16, content_type: &str, body: Vec<u8>) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header("Content-Type", content_type)
        .header("Cache-Control", "no-cache")
        .header("X-Content-Type-Options", "nosniff")
        .body(body)
        .unwrap()
}

fn json_error(status: u16, code: &str, message: &str) -> Response<Vec<u8>> {
    let body = serde_json::json!({"ok": false, "error": {"code": code, "message": message}});
    respond(status, "application/json", serde_json::to_vec(&body).unwrap())
}

/// 画面からの要求1件。`/api/…` は Python へ、ほかは画面のフォルダから返す。
fn handle(bridge: &Bridge, request: Request<Vec<u8>>) -> Response<Vec<u8>> {
    let path = request.uri().path().to_string();
    if path.starts_with("/api/") {
        return call_python(bridge, request);
    }
    if request.method() != "GET" && request.method() != "HEAD" {
        return json_error(405, "method", "この経路は読むだけです。");
    }
    // Python が起動できなかった / 居なくなったなら、画面の代わりに理由を出す
    if (path == "/" || path == "/index.html") && bridge.phase() == Phase::Ended {
        let page = pages::failure(bridge.failure().as_ref(), &bridge.python(), &bridge.stderr_tail(), &log_hint(bridge.root()));
        return respond(503, "text/html; charset=utf-8", page.into_bytes());
    }
    let root = bridge.root().join("app").join("static");
    match static_files::resolve(&root, &path) {
        Some(file) => match std::fs::read(&file) {
            Ok(body) => {
                let ctype = static_files::content_type(&file);
                let mut res = respond(200, ctype, body);
                if ctype.starts_with("text/html") {
                    res.headers_mut().insert("Content-Security-Policy", static_files::CSP.parse().unwrap());
                }
                res
            }
            Err(e) => json_error(500, "read", &format!("読めませんでした: {e}")),
        },
        None => json_error(404, "not_found", "ありません。"),
    }
}

fn call_python(bridge: &Bridge, request: Request<Vec<u8>>) -> Response<Vec<u8>> {
    // 窓は Python を待たずに出す。計算の要求だけ、受け付けが始まるまで待つ
    if bridge.phase() == Phase::Starting {
        bridge.wait_started(API_START_WAIT);
    }
    if bridge.phase() != Phase::Started {
        let reason = bridge
            .failure()
            .map(|f| f.message)
            .unwrap_or_else(|| "計算の処理(Python)が動いていません。アプリを開き直してください。".into());
        return json_error(503, "python_down", &reason);
    }
    let uri = request.uri().clone();
    let headers: Vec<(String, String)> = request
        .headers()
        .iter()
        .filter_map(|(k, v)| Some((k.as_str().to_string(), v.to_str().ok()?.to_string())))
        .collect();
    match bridge.call(request.method().as_str(), uri.path(), uri.query().unwrap_or(""), headers, request.body()) {
        Ok(reply) => {
            // 画面の「版」に外枠の版も出す(Python は外枠の版を知らない)
            let mut builder = Response::builder().status(reply.status).header("X-Coil-Shell-Version", VERSION);
            for (k, v) in &reply.headers {
                // 長さと転送の方法は WebView が自分で決める
                if k.eq_ignore_ascii_case("content-length") || k.eq_ignore_ascii_case("transfer-encoding") {
                    continue;
                }
                builder = builder.header(k.as_str(), v.as_str());
            }
            builder.body(reply.body).unwrap_or_else(|_| json_error(500, "bad_reply", "応答を組み立てられませんでした"))
        }
        Err(reason) => json_error(503, "python_down", &reason),
    }
}

/// 操作説明書を別の窓で開く(画面の「操作説明」から)。開いていれば、その頁へ移して前に出す。
#[tauri::command]
fn open_manual(app: AppHandle, page: String) -> Result<(), String> {
    if !MANUAL_PAGES.contains(&page.as_str()) {
        return Err(format!("そんな頁はありません: {page}"));
    }
    let url = app_url(&format!("/manual/{page}.html"));
    if let Some(window) = app.get_webview_window("manual") {
        window.navigate(url).map_err(|e| e.to_string())?;
        let _ = window.unminimize();
        let _ = window.show();
        return window.set_focus().map_err(|e| e.to_string());
    }
    WebviewWindowBuilder::new(&app, "manual", WebviewUrl::External(url))
        .title(format!("操作説明書 ─ {TITLE} v{VERSION}"))
        .inner_size(1100.0, 860.0)
        .min_inner_size(640.0, 480.0)
        .on_navigation(|url| is_app_url(url))
        .build()
        .map(|_| ())
        .map_err(|e| format!("操作説明書の窓を開けませんでした: {e}"))
}

/// 早見表だけの窓(VBA `UFquick` はモードレス。計算の画面と並べて見る)。
/// 面の札も見出しも出さない(`index.html?window=quick&tab=quick`)。もう開いていれば前に出す
#[tauri::command]
fn open_quick(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("quick") {
        let _ = window.unminimize();
        let _ = window.show();
        return window.set_focus().map_err(|e| e.to_string());
    }
    WebviewWindowBuilder::new(&app, "quick", WebviewUrl::External(app_url("/index.html?window=quick&tab=quick")))
        .title(format!("VCフィルム長さ早見表 ─ {TITLE} v{VERSION}"))
        .inner_size(1280.0, 860.0)
        .min_inner_size(640.0, 480.0)
        .on_navigation(|url| is_app_url(url))
        .build()
        .map(|_| ())
        .map_err(|e| format!("早見表の窓を開けませんでした: {e}"))
}

/// 錠を取れなかった。**後から開いたこちらが止まる。**
fn refuse(app: &tauri::AppHandle, refusal: Refusal) {
    let message = match refusal {
        // もう1つのデスクトップ版: 窓を前に出すのは single-instance の仕事。黙って終わる
        Refusal::OtherDesktop => {
            app.exit(0);
            return;
        }
        Refusal::Browser { url } => instance::browser_running_message(&url),
        Refusal::Unknown => "もう一方の版(ブラウザ版かデスクトップ版)が動いています。\n\n\
                             ブラウザ版とデスクトップ版は同時に使えません。閉じてから開き直してください。"
            .to_string(),
    };
    eprintln!("{message}");
    // 試験(画面の無い所)ではダイアログを出さずに終わる
    if std::env::var("COIL_TOOL_QUIET").as_deref() == Ok("1") {
        app.exit(EXIT_OTHER_RUNNING);
        return;
    }
    let handle = app.clone();
    app.dialog()
        .message(message)
        .title(TITLE)
        .kind(MessageDialogKind::Warning)
        .show(move |_| handle.exit(EXIT_OTHER_RUNNING));
}

// ------------------------------------------------------------------
// 終わり方(窓の ×)
// ------------------------------------------------------------------
/// いま確かめを出しているか(× を続けて押しても、確かめは1つだけ)
static CLOSING: AtomicBool = AtomicBool::new(false);

/// 試験(画面の無い所)用に、確かめの答えを決めておく: `COIL_TOOL_CLOSE_ANSWER=yes|no`。
/// **決めていなければ必ず利用者に訊く**(黙って「はい」にしない)
fn preset_answer() -> Option<bool> {
    match std::env::var("COIL_TOOL_CLOSE_ANSWER").as_deref() {
        Ok("yes") => Some(true),
        Ok("no") => Some(false),
        _ => None,
    }
}

/// いちばん大きい窓の × を押した。**ブラウザ版の「終了」と同じ確かめを通る**:
/// Python に確かめ無しで頼み(`/api/shutdown`)、409 で返ってきた文を見せ、
/// 「終了する」のときだけ `{"confirmed": true}` を付けて送り直す。「やめる」なら何もしない。
/// Python が動いていない(起動できなかった・落ちた)ときは、訊く相手がいないのでそのまま閉じる。
fn confirm_close(app: AppHandle, bridge: Arc<Bridge>) {
    if CLOSING.swap(true, Ordering::SeqCst) {
        return;
    }
    thread::spawn(move || {
        if bridge.phase() != Phase::Started {
            app.exit(0);
            return;
        }
        let json = vec![("Content-Type".to_string(), "application/json".to_string())];
        match bridge.call("POST", "/api/shutdown", "", json.clone(), b"{}") {
            Ok(reply) if reply.status == 409 => {
                let body = serde_json::from_slice::<serde_json::Value>(&reply.body).unwrap_or_default();
                let text = |key: &str, default: &str| {
                    body["confirm"][key].as_str().filter(|t| !t.is_empty()).unwrap_or(default).to_string()
                };
                let yes = preset_answer().unwrap_or_else(|| {
                    app.dialog()
                        .message(text("message", "終了しますか?"))
                        .title(text("title", TITLE))
                        .kind(MessageDialogKind::Warning)
                        .buttons(MessageDialogButtons::OkCancelCustom(text("yes", "終了する"), text("no", "やめる")))
                        .blocking_show()
                });
                if yes {
                    // Python が「quit」を知らせてくる(→ on_quit で終わる)。来なくても少し待って終える
                    let _ = bridge.call("POST", "/api/shutdown", "", json, br#"{"confirmed": true}"#);
                    exit_soon(app);
                } else {
                    CLOSING.store(false, Ordering::SeqCst);
                }
            }
            // 確かめの要らない状態(今は無い)
            Ok(reply) if reply.status < 300 => exit_soon(app),
            // Python が答えない: 訊けないので閉じる
            _ => app.exit(0),
        }
    });
}

fn exit_soon(app: AppHandle) {
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(1500));
        app.exit(0);
    });
}

fn main() {
    let root = app_root();
    let candidates = instance::runtime_candidates(&root);
    let bridge = Bridge::new(root);

    let for_protocol = bridge.clone();
    let for_setup = bridge.clone();
    let for_close = bridge.clone();
    let for_exit = bridge.clone();
    // 錠を取れた場所(終わるときに持ち主の印を消す)
    let held: Arc<Mutex<Option<PathBuf>>> = Arc::new(Mutex::new(None));
    let held_setup = held.clone();

    let app = tauri::Builder::default()
        // 2つ目のデスクトップ版を開こうとしたら、開いている窓を前に出すだけ
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![open_manual, open_quick])
        .on_window_event(move |window, event| {
            if window.label() != "main" {
                return; // 操作説明書・早見表の窓は、確かめずにその窓だけ閉じる
            }
            match event {
                // × は「終了」と同じ確かめを通る
                WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    confirm_close(window.app_handle().clone(), for_close.clone());
                }
                // いちばん大きい窓が無くなったら終わる(操作説明書の窓だけが残って、
                // Python と錠を握ったままにならないように)
                WindowEvent::Destroyed => window.app_handle().exit(0),
                _ => {}
            }
        })
        .register_asynchronous_uri_scheme_protocol(SCHEME, move |_ctx, request, responder| {
            let bridge = for_protocol.clone();
            // 要求ごとに別のスレッドで答える(Python の起動を待つ要求が画面のファイルを止めない)
            thread::spawn(move || responder.respond(handle(&bridge, request)));
        })
        .setup(move |app| {
            // ブラウザ版・ほかのデスクトップ版と錠を取り合う。握られていれば止まる
            // (single-instance は D-Bus の無い Linux などで素通しになるので、ここでも止める)。
            // 作業フォルダが壊れていても止めない: 一時フォルダで取り合い、そこも駄目なら排他無しで動く
            match instance::take(&candidates) {
                Take::Acquired(lock, place) => {
                    if Some(&place) != candidates.first() {
                        eprintln!("作業フォルダが使えないので、錠を一時フォルダに置きました: {}", place.display());
                    }
                    instance::write_owner(&place);
                    *held_setup.lock().unwrap() = Some(place);
                    // 終わるまで握っておく(プロセスが終われば OS が外す)
                    Box::leak(Box::new(lock));
                }
                Take::Busy(place) => {
                    let owner = instance::read_owner(&place, Duration::from_secs(2));
                    refuse(app.handle(), instance::refusal(owner.as_ref()));
                    return Ok(());
                }
                Take::Unusable(reasons) => {
                    eprintln!("錠を置ける場所がありません。ブラウザ版との排他無しで起動します: {}", reasons.join(" / "));
                }
            }

            let handle = app.handle().clone();
            for_setup.set_on_quit(move || handle.exit(0));
            let handle = app.handle().clone();
            for_setup.set_on_lost(move || {
                // 理由の画面を出す(読み直すと `handle` が失敗の画面を返す)
                if let Some(window) = handle.get_webview_window("main") {
                    let _ = window.eval("location.reload()");
                }
            });

            // Python は別スレッドで起こす。窓はすぐに出す(画面のファイルは Rust が返す)
            let starter = for_setup.clone();
            let handle = app.handle().clone();
            thread::spawn(move || {
                starter.start();
                if starter.phase() != Phase::Started {
                    // 起動できなかった: 理由の画面に替える
                    if let Some(window) = handle.get_webview_window("main") {
                        let _ = window.eval("location.reload()");
                    }
                }
            });

            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(app_url("/")))
                .title(format!("{TITLE} v{VERSION}"))
                .inner_size(1500.0, 940.0)
                .min_inner_size(1024.0, 680.0)
                .center()
                .on_navigation(|url| is_app_url(url))
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("アプリを組み立てられませんでした");

    app.run(move |_app, event| {
        if let RunEvent::Exit = event {
            // 標準入力を閉じて Python に終わってもらう。終わらなければ止める
            for_exit.shutdown(Duration::from_secs(5));
            if let Some(place) = held.lock().unwrap().as_ref() {
                instance::clear_owner(place);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn 画面の宛先はosで決まる() {
        let url = app_url("/coil/app-shell.js");
        assert!(is_app_url(&url));
        assert!(url.as_str().ends_with("/coil/app-shell.js"));
        assert!(!is_app_url(&"http://127.0.0.1:8741/".parse().unwrap()));
    }

    #[test]
    fn 操作説明書の頁はすべてある() {
        std::env::remove_var("COIL_TOOL_ROOT");
        for page in MANUAL_PAGES {
            let file = app_root().join("app").join("static").join("manual").join(format!("{page}.html"));
            assert!(file.is_file(), "{}", file.display());
        }
    }

    #[test]
    fn exeの上へたどってアプリのフォルダを探す() {
        // 試験の exe は src-tauri/target/... にある。上に bridge.py がある
        std::env::remove_var("COIL_TOOL_ROOT");
        assert!(app_root().join("bridge.py").is_file(), "{}", app_root().display());
    }
}
