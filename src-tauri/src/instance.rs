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
//!
//! 置き場所は作業フォルダ、そこが壊れている・書けないときは一時フォルダ(`runtime_candidates`)。
//! Python 側(`app_config.runtime_candidates`)と同じ順に試すので、作業フォルダが壊れていても
//! 排他は保たれる。どちらも使えなければ**排他無しで起動する**(起動を止めない)。

use std::fs::{File, TryLockError};
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
    let name = local_root_name(app_root);
    for var in ["LOCALAPPDATA", "XDG_DATA_HOME"] {
        if let Ok(base) = std::env::var(var) {
            if !base.trim().is_empty() {
                return PathBuf::from(base.trim()).join(name);
            }
        }
    }
    PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".local").join("share").join(name)
}

/// 作業フォルダの名前(`config/app.json` の `local_dir_name`。読めなければ既定)
fn local_root_name(app_root: &Path) -> String {
    std::fs::read_to_string(app_root.join("config").join("app.json"))
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|conf| conf.get("local_dir_name").and_then(|v| v.as_str()).map(str::to_string))
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| "CoilCalculator".into())
}

pub fn runtime_dir(app_root: &Path) -> PathBuf {
    local_root(app_root).join("runtime")
}

/// 一時フォルダ。Python 側(`app_config.temp_root`)と同じ順: TEMP → TMP → OS の既定
pub fn temp_root() -> PathBuf {
    for var in ["TEMP", "TMP"] {
        if let Ok(base) = std::env::var(var) {
            if !base.trim().is_empty() {
                return PathBuf::from(base.trim());
            }
        }
    }
    std::env::temp_dir()
}

/// 錠を置く場所の候補(前から順に、使えるところを使う)
pub fn runtime_candidates(app_root: &Path) -> Vec<PathBuf> {
    vec![runtime_dir(app_root), temp_root().join(local_root_name(app_root)).join("runtime")]
}

/// 1つの場所で錠を取った結果
#[derive(Debug)]
pub enum Attempt {
    /// 取れた。握ったまま返す(落とすと外れる)
    Acquired(File),
    /// ほかのプロセスが握っている(もう一方の版が動いている)
    Busy,
    /// この場所が使えない(フォルダが壊れている・書けない)。次の候補へ
    Unusable(String),
}

/// 錠を取る。**待たない。** 「使えない」と「握られている」を分けるのは、壊れた作業フォルダを
/// 「もう一方の版が動いています」と取り違えて起動を止めないため。
pub fn attempt(runtime: &Path) -> Attempt {
    if let Err(e) = std::fs::create_dir_all(runtime) {
        return Attempt::Unusable(format!("{}: {e}", runtime.display()));
    }
    let file = match std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(runtime.join(LOCK_NAME))
    {
        Ok(file) => file,
        Err(e) => return Attempt::Unusable(format!("{}: {e}", runtime.join(LOCK_NAME).display())),
    };
    match file.try_lock() {
        Ok(()) => Attempt::Acquired(file),
        Err(TryLockError::WouldBlock) => Attempt::Busy,
        Err(TryLockError::Error(e)) => Attempt::Unusable(format!("{}: {e}", runtime.display())),
    }
}

/// 候補を前から順に試した結果(Python の `instance_lock.take` と同じ決め方)
#[derive(Debug)]
pub enum Take {
    Acquired(File, PathBuf),
    Busy(PathBuf),
    /// どの場所も使えない。理由を並べて返す → 排他無しで起動する
    Unusable(Vec<String>),
}

pub fn take(candidates: &[PathBuf]) -> Take {
    let mut reasons = Vec::new();
    for place in candidates {
        match attempt(place) {
            Attempt::Acquired(file) => return Take::Acquired(file, place.clone()),
            Attempt::Busy => return Take::Busy(place.clone()),
            Attempt::Unusable(reason) => reasons.push(reason),
        }
    }
    Take::Unusable(reasons)
}

/// 錠を取る(1つの場所だけ)。取れたら握ったまま返す(試験用)。
#[cfg(test)]
pub fn try_take(runtime: &Path) -> Option<File> {
    match attempt(runtime) {
        Attempt::Acquired(file) => Some(file),
        _ => None,
    }
}

/// いま握っているのは自分(デスクトップ版)だと書く。**書けなくても起動は止めない**
/// (印は手がかりに過ぎず、排他そのものは錠が守る)。
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
    fn 壊れた場所は使えないと言い_次の候補で取る() {
        let base = temp("broken");
        let broken = base.join("runtime");
        std::fs::write(&broken, "garbage").unwrap(); // フォルダのはずがファイルになっている
        assert!(matches!(attempt(&broken), Attempt::Unusable(_)), "壊れた場所を「握られている」と取り違えない");
        let spare = base.join("spare");
        let first = take(&[broken.clone(), spare.clone()]);
        let Take::Acquired(file, place) = first else { panic!("予備の場所で取れる: {first:?}") };
        assert_eq!(place, spare);
        assert!(matches!(take(&[broken.clone(), spare.clone()]), Take::Busy(p) if p == spare), "予備の場所でも排他は効く");
        drop(file);
        assert!(matches!(take(&[broken.clone(), base.join("runtime").join("x")]), Take::Unusable(r) if r.len() == 2));
    }

    #[test]
    fn 持ち主の印が書けなくても止まらない() {
        let dir = temp("owner_dir");
        std::fs::create_dir_all(dir.join(OWNER_NAME)).unwrap(); // 印がフォルダになっている
        write_owner(&dir); // 書けないが、落ちない
        assert!(read_owner(&dir, Duration::ZERO).is_none());
        clear_owner(&dir);
    }

    #[test]
    fn ブラウザ版が動いているときの文() {
        let text = browser_running_message("http://127.0.0.1:8741/");
        assert!(text.contains("ブラウザ版が動いています"));
        assert!(text.contains("同時に使えません"));
        assert!(text.contains("http://127.0.0.1:8741/"));
    }
}
