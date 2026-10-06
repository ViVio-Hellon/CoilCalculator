//! ブラウザ版とデスクトップ版を**同時に動かさない**ための錠(Python 側と同じファイル)
//!
//! ```text
//! <作業フォルダ>/runtime/instance.lock   OS のファイルロック(握っている間だけ有効)
//! <作業フォルダ>/runtime/instance.json   いま握っているのは誰か(版・pid・URL)
//! ```
//!
//! **後から開いたほうが止まる**(`coilcalc/instance_lock.py` の表と同じ)。
//! Windows: こちらは `LockFileEx`(ファイル全体)、Python は `msvcrt.locking`(先頭1バイト)。
//! 範囲が重なるので互いに取れない。Linux などは両方とも `flock`。
//! 錠は OS が持つので、落ちても残らない。

use std::fs::File;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

pub const LOCK_NAME: &str = "instance.lock";
pub const OWNER_NAME: &str = "instance.json";
pub const KIND_DESKTOP: &str = "desktop";
pub const KIND_BROWSER: &str = "browser";

/// この端末の作業フォルダ(Python の `app_config.local_root()` と同じ決め方)。
///
/// **2つが違う場所を見ると排他が効かない**ので、順番も名前も揃える。
pub fn local_root(app_root: &Path) -> PathBuf {
    if let Ok(dir) = std::env::var("COIL_TOOL_LOCAL_DIR") {
        if !dir.trim().is_empty() {
            return PathBuf::from(dir.trim());
        }
    }
    let name = std::fs::read_to_string(app_root.join("config").join("app.json"))
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|conf| conf.get("local_dir_name").and_then(|v| v.as_str()).map(str::to_string))
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| "CoilCalculator".into());
    for var in ["LOCALAPPDATA", "XDG_DATA_HOME"] {
        if let Ok(base) = std::env::var(var) {
            if !base.trim().is_empty() {
                return PathBuf::from(base.trim()).join(name);
            }
        }
    }
    PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".local").join("share").join(name)
}

pub fn runtime_dir(app_root: &Path) -> PathBuf {
    local_root(app_root).join("runtime")
}

/// 錠を取る。取れたら握ったまま返す(落とすと外れる)。**待たない。**
pub fn try_take(runtime: &Path) -> Option<File> {
    let _ = std::fs::create_dir_all(runtime);
    let file = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(runtime.join(LOCK_NAME))
        .ok()?;
    match file.try_lock() {
        Ok(()) => Some(file),
        Err(_) => None,
    }
}

/// いま握っているのは自分(デスクトップ版)だと書く。
pub fn write_owner(runtime: &Path) {
    let data = json!({
        "kind": KIND_DESKTOP,
        "pid": std::process::id(),
        "exe": std::env::current_exe().map(|p| p.display().to_string()).unwrap_or_default(),
    });
    let tmp = runtime.join("instance.desktop.tmp");
    if std::fs::write(&tmp, serde_json::to_vec_pretty(&data).unwrap_or_default()).is_ok() {
        let _ = std::fs::rename(&tmp, runtime.join(OWNER_NAME));
    }
}

/// 自分が書いた「持ち主」だけを消す(次の持ち主のものは消さない)。
pub fn clear_owner(runtime: &Path) {
    if let Some(owner) = read_owner(runtime, Duration::ZERO) {
        if owner.get("pid").and_then(Value::as_u64) == Some(std::process::id() as u64) {
            let _ = std::fs::remove_file(runtime.join(OWNER_NAME));
        }
    }
}

/// 錠を握っているのは誰か。**書き終わる前に読むことがある**ので、少し待って読み直す。
pub fn read_owner(runtime: &Path, wait: Duration) -> Option<Value> {
    let deadline = Instant::now() + wait;
    loop {
        let found = std::fs::read_to_string(runtime.join(OWNER_NAME))
            .ok()
            .and_then(|text| serde_json::from_str::<Value>(&text).ok())
            .filter(|v| v.get("kind").and_then(Value::as_str).is_some());
        if found.is_some() || Instant::now() >= deadline {
            return found;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

/// 錠を取れなかったときに、どうするか。
#[derive(Debug, PartialEq)]
pub enum Refusal {
    /// もう1つのデスクトップ版が開いている(窓を前に出すのは single-instance の仕事)
    OtherDesktop,
    /// ブラウザ版が動いている。**こちらが止まる**(理由を出して終わる)
    Browser { url: String },
    /// 誰かは分からないが握られている
    Unknown,
}

pub fn refusal(owner: Option<&Value>) -> Refusal {
    match owner.and_then(|o| o.get("kind")).and_then(Value::as_str) {
        Some(KIND_DESKTOP) => Refusal::OtherDesktop,
        Some(KIND_BROWSER) => Refusal::Browser {
            url: owner.and_then(|o| o.get("url")).and_then(Value::as_str).unwrap_or("").to_string(),
        },
        _ => Refusal::Unknown,
    }
}

/// 利用者に出す文(ブラウザ版が先に動いていたとき)。
pub fn browser_running_message(url: &str) -> String {
    let at = if url.is_empty() { String::new() } else { format!("\n(画面: {url})") };
    format!(
        "ブラウザ版が動いています。{at}\n\n\
         ブラウザ版とデスクトップ版は同時に使えません。\n\
         ブラウザ版の画面の「終了」を押すか stop.bat を実行してから、もう一度開いてください。\n\
         (ブラウザのタブを閉じただけなら、1〜2分で自動的に終わります)"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("coil_instance_{name}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn 錠は1つしか取れず_外せばまた取れる() {
        let dir = temp("lock");
        let first = try_take(&dir);
        assert!(first.is_some(), "1つ目は取れる");
        assert!(try_take(&dir).is_none(), "2つ目は取れない");
        drop(first);
        assert!(try_take(&dir).is_some(), "1つ目が外れれば取れる");
    }

    #[test]
    fn 持ち主を書いて読み_自分のものだけ消す() {
        let dir = temp("owner");
        write_owner(&dir);
        let owner = read_owner(&dir, Duration::ZERO).expect("書いたものが読める");
        assert_eq!(owner["kind"], KIND_DESKTOP);
        assert_eq!(refusal(Some(&owner)), Refusal::OtherDesktop);
        clear_owner(&dir);
        assert!(read_owner(&dir, Duration::ZERO).is_none());

        std::fs::write(dir.join(OWNER_NAME), r#"{"kind": "browser", "pid": 1, "url": "http://127.0.0.1:8741/"}"#).unwrap();
        clear_owner(&dir);
        let owner = read_owner(&dir, Duration::ZERO).expect("よその持ち主は消さない");
        assert_eq!(refusal(Some(&owner)), Refusal::Browser { url: "http://127.0.0.1:8741/".into() });
        assert_eq!(refusal(None), Refusal::Unknown);
    }

    #[test]
    fn ブラウザ版が動いているときの文() {
        let text = browser_running_message("http://127.0.0.1:8741/");
        assert!(text.contains("ブラウザ版が動いています"));
        assert!(text.contains("同時に使えません"));
        assert!(text.contains("http://127.0.0.1:8741/"));
    }
}
