use r2d2::Pool;
use r2d2_sqlite::rusqlite::Connection;
use r2d2_sqlite::SqliteConnectionManager;
use std::path::Path;
use zeroize::Zeroizing;

use crate::error::AuthError;

pub type DbPool = Pool<SqliteConnectionManager>;

pub fn open_pool(path: &Path, dek: &[u8]) -> Result<DbPool, AuthError> {
    let manager = SqliteConnectionManager::file(path);

    let key_hex = Zeroizing::new(hex::encode(dek));
    let manager = manager.with_init(move |conn: &mut Connection| {
        conn.execute_batch(&format!("PRAGMA key = \"x'{}\";", key_hex.as_str()))
    });

    let pool = Pool::builder()
        .max_size(4)
        .build(manager)
        .map_err(|_| AuthError::DbOpenFailed)?;

    let conn = pool.get().map_err(|_| AuthError::DbOpenFailed)?;
    verify(&conn)?;
    migrate(&conn)?;

    Ok(pool)
}

fn verify(conn: &Connection) -> Result<(), AuthError> {
    let count: i64 = conn
        .query_row("SELECT count(*) FROM sqlite_master", [], |row| row.get(0))
        .map_err(|_| AuthError::DbOpenFailed)?;
    if count < 0 {
        return Err(AuthError::DbOpenFailed);
    }
    Ok(())
}

fn migrate(conn: &Connection) -> Result<(), AuthError> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS _meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );",
    )
    .map_err(|_| AuthError::DbOpenFailed)?;
    Ok(())
}
