use tauri::{AppHandle, Manager, State};
use zeroize::Zeroizing;

use crate::crypto::{self, KdfParams};
use crate::db;
use crate::error::AuthError;
use crate::profile::{self, ProfileHeader, ProfileSummary, Slots};
use crate::session::{AppState, Session, SessionInfo};

const MIN_PASSPHRASE_LEN: usize = 12;

#[derive(serde::Serialize)]
pub struct CreateProfileResult {
    pub profile: ProfileSummary,
    pub recovery_phrase: String,
}

fn app_data_dir(app: &AppHandle) -> Result<std::path::PathBuf, AuthError> {
    app.path()
        .app_data_dir()
        .map_err(|e| AuthError::Internal(format!("could not resolve app data dir: {e}")))
}

fn root_dir(app: &AppHandle) -> Result<std::path::PathBuf, AuthError> {
    Ok(profile::profiles_root(&app_data_dir(app)?))
}

fn validate_passphrase(passphrase: &str) -> Result<(), AuthError> {
    if passphrase.chars().count() < MIN_PASSPHRASE_LEN {
        return Err(AuthError::WeakPassphrase);
    }
    Ok(())
}

#[tauri::command]
pub fn list_profiles(app: AppHandle) -> Result<Vec<ProfileSummary>, AuthError> {
    profile::list_profiles(&root_dir(&app)?)
}

#[tauri::command]
pub fn create_profile(
    app: AppHandle,
    state: State<'_, AppState>,
    name: String,
    passphrase: String,
) -> Result<CreateProfileResult, AuthError> {
    let name = profile::sanitize_profile_name(&name)?.to_string();
    let passphrase = Zeroizing::new(passphrase);
    validate_passphrase(&passphrase)?;

    let root = root_dir(&app)?;
    if profile::name_exists(&root, &name)? {
        return Err(AuthError::ProfileAlreadyExists);
    }

    let profile_id = loop {
        let id = profile::generate_profile_id();
        if !profile::profile_dir(&root, &id).exists() {
            break id;
        }
    };

    let dek = crypto::generate_dek();
    let salt1 = crypto::generate_salt();
    let salt2 = crypto::generate_salt();
    let recovery_phrase = crypto::generate_recovery_phrase()?;

    let params = KdfParams::recommended();
    let kek1 = crypto::derive_kek(passphrase.as_bytes(), salt1.as_ref(), &params)?;
    let kek2 = crypto::derive_kek(recovery_phrase.as_bytes(), salt2.as_ref(), &params)?;

    let aad1 = profile::aad_for(&profile_id, "passphrase");
    let aad2 = profile::aad_for(&profile_id, "recovery");

    let wrapped1 = crypto::wrap_dek(dek.as_ref(), kek1.as_ref(), aad1.as_bytes())?;
    let wrapped2 = crypto::wrap_dek(dek.as_ref(), kek2.as_ref(), aad2.as_bytes())?;

    let header = ProfileHeader {
        version: profile::HEADER_VERSION,
        profile_id: profile_id.clone(),
        profile_name: name.clone(),
        created_at: profile::now_secs(),
        kdf: params.clone(),
        slots: Slots {
            passphrase: profile::encode_slot(salt1.as_ref(), &wrapped1),
            recovery: profile::encode_slot(salt2.as_ref(), &wrapped2),
        },
    };

    profile::write_header(&root, &header)?;

    let vault = profile::vault_path(&profile::profile_dir(&root, &profile_id));
    let pool = match db::open_pool(&vault, dek.as_ref()) {
        Ok(pool) => pool,
        Err(e) => {
            profile::remove_profile_dir(&root, &profile_id);
            return Err(e);
        }
    };

    *state.session.lock().map_err(|_| AuthError::Internal("state lock poisoned".into()))? =
        Some(Session {
            profile_id: profile_id.clone(),
            profile_name: name.clone(),
            dek,
            pool,
        });

    Ok(CreateProfileResult {
        profile: ProfileSummary {
            profile_id,
            profile_name: name,
            created_at: header.created_at,
        },
        recovery_phrase,
    })
}

#[tauri::command]
pub fn unlock_profile(
    app: AppHandle,
    state: State<'_, AppState>,
    profile_id: String,
    passphrase: String,
) -> Result<ProfileSummary, AuthError> {
    let passphrase = Zeroizing::new(passphrase);
    let root = root_dir(&app)?;
    let header = profile::load_header(&root, &profile_id)?;

    let params = header.kdf.clone();

    let salt = profile::decode_salt(&header.slots.passphrase)?;
    let kek = crypto::derive_kek(passphrase.as_bytes(), &salt, &params)?;
    let wrapped = profile::decode_wrapped(&header.slots.passphrase)?;
    let aad = profile::aad_for(&profile_id, "passphrase");

    let dek = match crypto::unwrap_dek(&wrapped, kek.as_ref(), aad.as_bytes()) {
        Ok(dek) => dek,
        Err(crypto::UnwrapError::AuthFailed) => return Err(AuthError::InvalidPassphrase),
        Err(crypto::UnwrapError::BadLength) => return Err(AuthError::HeaderCorrupt),
    };

    let vault = profile::vault_path(&profile::profile_dir(&root, &profile_id));
    let pool = db::open_pool(&vault, dek.as_ref())?;

    *state.session.lock().map_err(|_| AuthError::Internal("state lock poisoned".into()))? =
        Some(Session {
            profile_id: profile_id.clone(),
            profile_name: header.profile_name.clone(),
            dek,
            pool,
        });

    Ok(ProfileSummary {
        profile_id,
        profile_name: header.profile_name,
        created_at: header.created_at,
    })
}

#[tauri::command]
pub fn lock_profile(state: State<'_, AppState>) -> Result<(), AuthError> {
    let mut guard = state
        .session
        .lock()
        .map_err(|_| AuthError::Internal("state lock poisoned".into()))?;
    *guard = None;
    Ok(())
}

#[tauri::command]
pub fn reset_passphrase(
    app: AppHandle,
    profile_id: String,
    recovery_phrase: String,
    new_passphrase: String,
) -> Result<(), AuthError> {
    let new_passphrase = Zeroizing::new(new_passphrase);
    validate_passphrase(&new_passphrase)?;

    let root = root_dir(&app)?;
    let mut header = profile::load_header(&root, &profile_id)?;

    let params = header.kdf.clone();

    let salt = profile::decode_salt(&header.slots.recovery)?;
    let normalized_phrase = crypto::parse_recovery_phrase(&recovery_phrase)?;
    let kek = crypto::derive_kek(normalized_phrase.as_bytes(), &salt, &params)?;
    let wrapped = profile::decode_wrapped(&header.slots.recovery)?;
    let aad = profile::aad_for(&profile_id, "recovery");

    let dek = match crypto::unwrap_dek(&wrapped, kek.as_ref(), aad.as_bytes()) {
        Ok(dek) => dek,
        Err(crypto::UnwrapError::AuthFailed) => return Err(AuthError::InvalidRecoveryPhrase),
        Err(crypto::UnwrapError::BadLength) => return Err(AuthError::HeaderCorrupt),
    };

    let new_salt = crypto::generate_salt();
    let new_kek = crypto::derive_kek(new_passphrase.as_bytes(), new_salt.as_ref(), &params)?;
    let new_aad = profile::aad_for(&profile_id, "passphrase");
    let new_wrapped = crypto::wrap_dek(dek.as_ref(), new_kek.as_ref(), new_aad.as_bytes())?;

    header.slots.passphrase = profile::encode_slot(new_salt.as_ref(), &new_wrapped);
    profile::write_header(&root, &header)?;

    Ok(())
}

#[tauri::command]
pub fn get_session(state: State<'_, AppState>) -> Result<SessionInfo, AuthError> {
    let guard = state
        .session
        .lock()
        .map_err(|_| AuthError::Internal("state lock poisoned".into()))?;
    match guard.as_ref() {
        Some(s) => Ok(SessionInfo::unlocked(s.profile_id.clone(), s.profile_name.clone())),
        None => Ok(SessionInfo::locked()),
    }
}
