//! stop.bat(業務ツール統合ランチャーの launcher_stop.bat)からの「止めて」を、**外枠も**受ける
//!
//! ```text
//! <錠の場所>/stop.request   {"owner_pid": 錠の持ち主(この exe)の pid, "force": false, ...}
//! ```
//!
//! ふだんは Python(`coilcalc/stop_request.py`)が受けて、「終了」と同じ止め方で止まる
//! (VC計算マスタへ書いている最中なら書き終えてから)。ところが **Python が起動できなかった・
//! 落ちた**ときは、外枠は理由の画面を出したまま錠を握って残り、頼みを受ける者がいない。
//! stop.bat は「止まらない」と言い、フォルダも消せなくなる(統合ツール all-tools で実際に起きた)。
//!
//! そこで外枠も見張る:
//!
//! | Python の様子 | 外枠がすること |
//! |---|---|
//! | 動いていない(起動できなかった・落ちた・終わった) | 頼みを消して、すぐ終わる(守るものが無い) |
//! | 起動中 | 待つ(起動すれば Python が受け、起動できなければ上の行) |
//! | 動いている | Python が受ける。**3秒たっても残っていたら**(受け口が動いていない)、外枠が `/api/shutdown {"force"}` で頼む |
//!
//! **ほかのプロセスには触らない**: 頼みは錠の持ち主の pid 宛てで、自分宛てしか聞かない。

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::bridge::{Bridge, Phase};

pub const FILE_NAME: &str = "stop.request";
const POLL: Duration = Duration::from_millis(500);
/// Python が受けているはずの頼みが、これだけ残っていたら外枠が代わりに頼む
const HANDOVER: Duration = Duration::from_secs(3);

#[derive(Debug, PartialEq)]
pub enum Action {
    /// まだ何もしない
    Wait,
    /// 外枠ごと終わる(Python が動いていない)
    Exit,
    /// Python に停止要求を送る(Python の受け口が動いていない)
    AskPython,
}

/// 頼みが来ているときに何をするか。`waited` は頼みを見つけてからの時間。
pub fn decide(phase: &Phase, addressed_to_me: bool, waited: Duration) -> Action {
    if !addressed_to_me {
        return Action::Wait;
    }
    match phase {
        Phase::Ended => Action::Exit,
        Phase::Started if waited >= HANDOVER => Action::AskPython,
        _ => Action::Wait,
    }
}

/// 頼みを読む。`(宛先の pid, force)`。無い・読めない(書いている途中)なら None。
pub fn read(path: &Path) -> Option<(u64, bool)> {
    let text = std::fs::read_to_string(path).ok()?;
    let data: Value = serde_json::from_str(&text).ok()?;
    let pid = data.get("owner_pid")?.as_u64()?;
    Some((pid, data.get("force").and_then(Value::as_bool).unwrap_or(false)))
}

/// 見張りを始める。`exit` は外枠を終わらせる手(`app.exit(0)`)。
pub fn watch(place: PathBuf, bridge: Arc<Bridge>, exit: impl Fn() + Send + 'static) {
    let path = place.join(FILE_NAME);
    let me = u64::from(std::process::id());
    // 前の起動に宛てた頼みは捨てる(Python 側と同じ)
    if matches!(read(&path), Some((pid, _)) if pid != me) {
        let _ = std::fs::remove_file(&path);
    }
    thread::spawn(move || {
        let mut since: Option<Instant> = None;
        loop {
            thread::sleep(POLL);
            let Some((pid, force)) = read(&path) else {
                since = None;
                continue;
            };
            let found = *since.get_or_insert_with(Instant::now);
            match decide(&bridge.phase(), pid == me, found.elapsed()) {
                Action::Wait => {}
                Action::Exit => {
                    eprintln!("stop.bat の頼みを受けました(Python が動いていないので、外枠ごと終わります)");
                    let _ = std::fs::remove_file(&path);
                    exit();
                    return;
                }
                Action::AskPython => {
                    let json = vec![("Content-Type".to_string(), "application/json".to_string())];
                    let body = format!(r#"{{"force": {force}}}"#);
                    match bridge.call("POST", "/api/shutdown", "", json, body.as_bytes()) {
                        // Python が「quit」を知らせてくる(→ on_quit で外枠も終わる)
                        Ok(reply) if reply.status < 300 => {
                            let _ = std::fs::remove_file(&path);
                            return;
                        }
                        // 断られた(書き込みの最中)・答えない: 少し待って頼み直す
                        _ => since = Some(Instant::now()),
                    }
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_が動いていなければすぐ終わる() {
        assert_eq!(decide(&Phase::Ended, true, Duration::ZERO), Action::Exit);
    }

    #[test]
    fn 起動中は待つ_動いていれば_python_に任せる() {
        assert_eq!(decide(&Phase::Starting, true, Duration::from_secs(60)), Action::Wait);
        assert_eq!(decide(&Phase::Started, true, Duration::from_secs(1)), Action::Wait);
        assert_eq!(decide(&Phase::Started, true, HANDOVER), Action::AskPython);
    }

    #[test]
    fn よその宛先は聞かない() {
        for phase in [Phase::Starting, Phase::Started, Phase::Ended] {
            assert_eq!(decide(&phase, false, Duration::from_secs(60)), Action::Wait);
        }
    }

    #[test]
    fn 頼みを読む() {
        let dir = std::env::temp_dir().join(format!("coil_stop_request_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join(FILE_NAME);
        std::fs::write(&path, r#"{"owner_pid": 1234, "force": true, "from": "stop.bat"}"#).unwrap();
        assert_eq!(read(&path), Some((1234, true)));
        std::fs::write(&path, r#"{"owner_pid": 1234}"#).unwrap();
        assert_eq!(read(&path), Some((1234, false)));
        std::fs::write(&path, r#"{"owner_pid": 12"#).unwrap(); // 書いている途中
        assert_eq!(read(&path), None);
        std::fs::remove_file(&path).unwrap();
        assert_eq!(read(&path), None);
        let _ = std::fs::remove_dir(&dir);
    }
}
