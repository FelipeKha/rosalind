use std::sync::Mutex;
use zeroize::Zeroizing;

use crate::db::DbPool;

pub struct Session {
    pub profile_id: String,
    pub profile_name: String,
    #[allow(dead_code)]
    pub dek: Zeroizing<[u8; 32]>,
    #[allow(dead_code)]
    pub pool: DbPool,
}

#[derive(Default)]
pub struct AppState {
    pub session: Mutex<Option<Session>>,
}

#[derive(serde::Serialize)]
pub struct SessionInfo {
    pub locked: bool,
    pub profile_id: Option<String>,
    pub profile_name: Option<String>,
}

impl SessionInfo {
    pub fn locked() -> Self {
        Self {
            locked: true,
            profile_id: None,
            profile_name: None,
        }
    }

    pub fn unlocked(profile_id: String, profile_name: String) -> Self {
        Self {
            locked: false,
            profile_id: Some(profile_id),
            profile_name: Some(profile_name),
        }
    }
}
