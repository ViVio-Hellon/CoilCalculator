//! 画面のファイル(HTML・JS・CSS・three.js・Chart.js・フォント)を**外枠が自分で**返す。
//!
//! 計算(`/api/…`)だけを Python へ渡し、ファイルはここでディスクから読む。
//! three.js だけで 600KB あるので、Python の標準入出力を通さないほうが速い
//! (Rust はファイルを返すのが得意)。ブラウザ版では Python が同じフォルダを返す
//! (`coilcalc/web.py` の `_static`)。**画面のフォルダの外は見せない。**

use std::path::{Component, Path, PathBuf};

/// 画面に付ける守り。Python 側(`coilcalc/web.py` の `CSP`)と同じ
pub const CSP: &str = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; \
img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; \
object-src 'none'; base-uri 'self'; frame-ancestors 'self'";

pub fn content_type(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).map(|e| e.to_ascii_lowercase()).as_deref() {
        Some("html") => "text/html; charset=utf-8",
        Some("js") => "text/javascript; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        Some("json") => "application/json",
        Some("png") => "image/png",
        Some("svg") => "image/svg+xml",
        Some("ico") => "image/x-icon",
        Some("woff2") => "font/woff2",
        Some("woff") => "font/woff",
        Some("ttf") => "font/ttf",
        Some("md") | Some("txt") => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

/// `%E3%81%82` などを戻す(UTF-8 として読めなければ `None`)。
fn percent_decode(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            let hex = text.get(i + 1..i + 3)?;
            out.push(u8::from_str_radix(hex, 16).ok()?);
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).ok()
}

/// URL の経路 → 画面のフォルダの中のファイル。外へ出ようとしたら `None`。
pub fn resolve(root: &Path, url_path: &str) -> Option<PathBuf> {
    let decoded = percent_decode(url_path)?;
    if decoded.contains('\\') || decoded.contains('\0') {
        return None;
    }
    let rel = decoded.trim_start_matches('/');
    let rel = if rel.is_empty() { "index.html" } else { rel };
    let mut path = root.to_path_buf();
    for part in Path::new(rel).components() {
        match part {
            Component::Normal(name) => path.push(name),
            Component::CurDir => {}
            // `..`・ドライブ名・絶対の経路は通さない
            _ => return None,
        }
    }
    if path.is_dir() {
        path.push("index.html");
    }
    path.is_file().then_some(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn 画面のフォルダの中だけを返す() {
        let root = std::env::temp_dir().join(format!("coil_static_{}", std::process::id()));
        std::fs::create_dir_all(root.join("coil")).unwrap();
        std::fs::write(root.join("index.html"), "<p>").unwrap();
        std::fs::write(root.join("coil").join("a b.js"), "1").unwrap();
        std::fs::write(root.parent().unwrap().join("coil_secret.txt"), "x").unwrap();

        assert_eq!(resolve(&root, "/"), Some(root.join("index.html")));
        assert_eq!(resolve(&root, "/coil/a%20b.js"), Some(root.join("coil").join("a b.js")));
        assert_eq!(resolve(&root, "/coil/"), None, "フォルダに index.html が無ければ無い");
        assert_eq!(resolve(&root, "/../coil_secret.txt"), None);
        assert_eq!(resolve(&root, "/%2e%2e/coil_secret.txt"), None);
        assert_eq!(resolve(&root, "/coil/..%5C..%5Ccoil_secret.txt"), None);
        assert_eq!(resolve(&root, "/nothing.js"), None);
        assert_eq!(resolve(&root, "/%E3"), None, "UTF-8 として読めない");
    }

    #[test]
    fn 種類は拡張子で決める() {
        assert_eq!(content_type(Path::new("a.JS")), "text/javascript; charset=utf-8");
        assert_eq!(content_type(Path::new("fa.woff2")), "font/woff2");
        assert_eq!(content_type(Path::new("x.bin")), "application/octet-stream");
    }
}
