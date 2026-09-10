use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine as _;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

use crate::crypto::{NONCE_LEN, SALT_LEN, TAG_LEN, DEK_LEN};
use crate::crypto::KdfParams;
use crate::error::AuthError;

pub const HEADER_FILE: &str = "profile_header.json";
pub const VAULT_FILE: &str = "vault.db";
pub const HEADER_VERSION: u32 = 1;
pub const AAD_PREFIX: &str = "rosalind-dek-v1";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Slot {
    pub salt: String,
    pub nonce: String,
    pub wrapped_dek: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Slots {
    pub passphrase: Slot,
    pub recovery: Slot,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProfileHeader {
    pub version: u32,
    pub profile_id: String,
    pub profile_name: String,
    pub created_at: u64,
    pub kdf: KdfParams,
    pub slots: Slots,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProfileSummary {
    pub profile_id: String,
    pub profile_name: String,
    pub created_at: u64,
}

pub fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub fn generate_profile_id() -> String {
    let mut bytes = [0u8; 16];
    rand::rng().fill_bytes(&mut bytes);
    hex::encode(bytes)
}

pub fn profiles_root(app_data_dir: &Path) -> PathBuf {
    app_data_dir.join("profiles")
}

pub fn profile_dir(root: &Path, profile_id: &str) -> PathBuf {
    root.join(profile_id)
}

pub fn header_path(dir: &Path) -> PathBuf {
    dir.join(HEADER_FILE)
}

pub fn vault_path(dir: &Path) -> PathBuf {
    dir.join(VAULT_FILE)
}

pub fn aad_for(profile_id: &str, slot: &str) -> String {
    format!("{AAD_PREFIX}|{profile_id}|{slot}")
}

pub fn is_valid_profile_id(id: &str) -> bool {
    id.len() == 32 && id.bytes().all(|b| b.is_ascii_hexdigit())
}

pub fn sanitize_profile_name(name: &str) -> Result<&str, AuthError> {
    let trimmed = name.trim();
    if trimmed.is_empty() || trimmed.chars().count() > 64 {
        return Err(AuthError::InvalidProfileName);
    }
    if trimmed
        .chars()
        .any(|c| c == '/' || c == '\\' || c == '.' || c.is_control())
    {
        return Err(AuthError::InvalidProfileName);
    }
    Ok(trimmed)
}

pub fn write_header(root: &Path, header: &ProfileHeader) -> Result<(), AuthError> {
    let dir = profile_dir(root, &header.profile_id);
    fs::create_dir_all(&dir)?;
    let json = serde_json::to_vec_pretty(header)
        .map_err(|_| AuthError::Internal("failed to serialize header".into()))?;
    fs::write(header_path(&dir), json)?;
    Ok(())
}

pub fn load_header(root: &Path, profile_id: &str) -> Result<ProfileHeader, AuthError> {
    if !is_valid_profile_id(profile_id) {
        return Err(AuthError::ProfileNotFound);
    }
    let path = header_path(&profile_dir(root, profile_id));
    let raw = fs::read(path).map_err(|_| AuthError::ProfileNotFound)?;
    let header: ProfileHeader =
        serde_json::from_slice(&raw).map_err(|_| AuthError::HeaderCorrupt)?;
    validate_header(&header)?;
    Ok(header)
}

pub fn validate_header(header: &ProfileHeader) -> Result<(), AuthError> {
    if header.version != HEADER_VERSION {
        return Err(AuthError::HeaderCorrupt);
    }
    if header.kdf.algorithm != "argon2id" {
        return Err(AuthError::HeaderCorrupt);
    }
    if header.profile_id.is_empty() || header.profile_name.is_empty() {
        return Err(AuthError::HeaderCorrupt);
    }
    validate_slot(&header.slots.passphrase)?;
    validate_slot(&header.slots.recovery)?;
    Ok(())
}

fn validate_slot(slot: &Slot) -> Result<(), AuthError> {
    let salt = B64.decode(&slot.salt).map_err(|_| AuthError::HeaderCorrupt)?;
    let nonce = B64.decode(&slot.nonce).map_err(|_| AuthError::HeaderCorrupt)?;
    let wrapped = B64.decode(&slot.wrapped_dek).map_err(|_| AuthError::HeaderCorrupt)?;

    if salt.len() != SALT_LEN || nonce.len() != NONCE_LEN || wrapped.len() != DEK_LEN + TAG_LEN {
        return Err(AuthError::HeaderCorrupt);
    }
    Ok(())
}

pub fn decode_salt(slot: &Slot) -> Result<Vec<u8>, AuthError> {
    B64.decode(&slot.salt).map_err(|_| AuthError::HeaderCorrupt)
}

pub fn decode_wrapped(slot: &Slot) -> Result<crate::crypto::WrappedKey, AuthError> {
    let nonce = B64.decode(&slot.nonce).map_err(|_| AuthError::HeaderCorrupt)?;
    let ciphertext = B64.decode(&slot.wrapped_dek).map_err(|_| AuthError::HeaderCorrupt)?;

    if nonce.len() != NONCE_LEN {
        return Err(AuthError::HeaderCorrupt);
    }

    let mut nonce_arr = zeroize::Zeroizing::new([0u8; NONCE_LEN]);
    nonce_arr.copy_from_slice(&nonce);

    Ok(crate::crypto::WrappedKey {
        nonce: nonce_arr,
        ciphertext: zeroize::Zeroizing::new(ciphertext),
    })
}

pub fn encode_slot(salt: &[u8], wrapped: &crate::crypto::WrappedKey) -> Slot {
    Slot {
        salt: B64.encode(salt),
        nonce: B64.encode(wrapped.nonce.as_slice()),
        wrapped_dek: B64.encode(wrapped.ciphertext.as_slice()),
    }
}

pub fn list_profiles(root: &Path) -> Result<Vec<ProfileSummary>, AuthError> {
    if !root.exists() {
        return Ok(Vec::new());
    }

    let mut summaries = Vec::new();
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let id = entry.file_name().to_string_lossy().into_owned();
        if let Ok(header) = load_header(root, &id) {
            summaries.push(ProfileSummary {
                profile_id: header.profile_id,
                profile_name: header.profile_name,
                created_at: header.created_at,
            });
        }
    }

    summaries.sort_by(|a, b| a.profile_name.cmp(&b.profile_name));
    Ok(summaries)
}

pub fn name_exists(root: &Path, name: &str) -> Result<bool, AuthError> {
    Ok(list_profiles(root)?
        .iter()
        .any(|p| p.profile_name.eq_ignore_ascii_case(name)))
}

pub fn remove_profile_dir(root: &Path, profile_id: &str) {
    let _ = fs::remove_dir_all(profile_dir(root, profile_id));
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crypto;

    #[test]
    fn header_roundtrip_and_unwrap() {
        let root = std::env::temp_dir().join(format!("rosalind-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);

        let profile_id = generate_profile_id();
        let dek = crypto::generate_dek();
        let salt = crypto::generate_salt();
        let params = crypto::KdfParams::recommended();
        let kek = crypto::derive_kek(b"correct horse battery", salt.as_ref(), &params).unwrap();
        let aad = aad_for(&profile_id, "passphrase");
        let wrapped = crypto::wrap_dek(dek.as_ref(), kek.as_ref(), aad.as_bytes()).unwrap();

        let header = ProfileHeader {
            version: HEADER_VERSION,
            profile_id: profile_id.clone(),
            profile_name: "Alice".into(),
            created_at: now_secs(),
            kdf: params,
            slots: Slots {
                passphrase: encode_slot(salt.as_ref(), &wrapped),
                recovery: encode_slot(salt.as_ref(), &wrapped),
            },
        };

        write_header(&root, &header).unwrap();

        let loaded = load_header(&root, &profile_id).unwrap();
        assert_eq!(loaded.profile_name, "Alice");

        let decoded = decode_wrapped(&loaded.slots.passphrase).unwrap();
        let dek2 = crypto::unwrap_dek(&decoded, kek.as_ref(), aad.as_bytes()).unwrap();
        assert_eq!(dek.as_ref(), dek2.as_ref());

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn invalid_profile_id_rejected() {
        assert!(!is_valid_profile_id("../../etc/passwd"));
        assert!(!is_valid_profile_id("abc"));
        assert!(is_valid_profile_id(&"a".repeat(32)));
    }

    #[test]
    fn sanitize_name_rejects_paths() {
        assert!(sanitize_profile_name("alice").is_ok());
        assert!(sanitize_profile_name("a/b").is_err());
        assert!(sanitize_profile_name("..").is_err());
        assert!(sanitize_profile_name("  ").is_err());
    }
}
