use aes_gcm::aead::{Aead, KeyInit, Nonce, Payload};
use aes_gcm::Aes256Gcm;
use argon2::{Algorithm, Argon2, Params, Version};
use rand::RngCore;
use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

use crate::error::AuthError;

pub const DEK_LEN: usize = 32;
pub const NONCE_LEN: usize = 12;
pub const SALT_LEN: usize = 16;
pub const TAG_LEN: usize = 16;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KdfParams {
    pub algorithm: String,
    pub memory_kib: u32,
    pub iterations: u32,
    pub parallelism: u32,
}

impl KdfParams {
    pub fn recommended() -> Self {
        Self {
            algorithm: "argon2id".into(),
            memory_kib: 19 * 1024,
            iterations: 2,
            parallelism: 1,
        }
    }
}

pub fn generate_dek() -> Zeroizing<[u8; DEK_LEN]> {
    let mut dek = Zeroizing::new([0u8; DEK_LEN]);
    rand::rng().fill_bytes(dek.as_mut());
    dek
}

pub fn generate_salt() -> Zeroizing<[u8; SALT_LEN]> {
    let mut salt = Zeroizing::new([0u8; SALT_LEN]);
    rand::rng().fill_bytes(salt.as_mut());
    salt
}

pub fn derive_kek(passphrase: &[u8], salt: &[u8], params: &KdfParams) -> Result<Zeroizing<[u8; DEK_LEN]>, AuthError> {
    let argon2 = Argon2::new(
        Algorithm::Argon2id,
        Version::V0x13,
        Params::new(
            params.memory_kib,
            params.iterations,
            params.parallelism,
            Some(DEK_LEN),
        )
        .map_err(|_| AuthError::Internal("invalid KDF parameters".into()))?,
    );

    let mut out = Zeroizing::new([0u8; DEK_LEN]);
    argon2
        .hash_password_into(passphrase, salt, out.as_mut())
        .map_err(|_| AuthError::Internal("key derivation failed".into()))?;
    Ok(out)
}

pub struct WrappedKey {
    pub nonce: Zeroizing<[u8; NONCE_LEN]>,
    pub ciphertext: Zeroizing<Vec<u8>>,
}

pub fn wrap_dek(dek: &[u8], kek: &[u8], aad: &[u8]) -> Result<WrappedKey, AuthError> {
    let cipher = Aes256Gcm::new_from_slice(kek).map_err(|_| AuthError::Internal("bad KEK length".into()))?;

    let mut nonce = Zeroizing::new([0u8; NONCE_LEN]);
    rand::rng().fill_bytes(nonce.as_mut());

    let nonce_aead: Nonce<Aes256Gcm> = Nonce::<Aes256Gcm>::try_from(nonce.as_slice())
        .map_err(|_| AuthError::Internal("invalid nonce length".into()))?;

    let ciphertext = cipher
        .encrypt(&nonce_aead, Payload { msg: dek, aad })
        .map_err(|_| AuthError::Internal("encryption failed".into()))?;

    Ok(WrappedKey {
        nonce,
        ciphertext: Zeroizing::new(ciphertext),
    })
}

#[derive(Debug)]
pub enum UnwrapError {
    AuthFailed,
    BadLength,
}

pub fn unwrap_dek(wrapped: &WrappedKey, kek: &[u8], aad: &[u8]) -> Result<Zeroizing<[u8; DEK_LEN]>, UnwrapError> {
    let cipher =
        Aes256Gcm::new_from_slice(kek).map_err(|_| UnwrapError::BadLength)?;

    let nonce_aead: Nonce<Aes256Gcm> = Nonce::<Aes256Gcm>::try_from(wrapped.nonce.as_slice())
        .map_err(|_| UnwrapError::BadLength)?;

    let plaintext = cipher
        .decrypt(
            &nonce_aead,
            Payload {
                msg: wrapped.ciphertext.as_slice(),
                aad,
            },
        )
        .map_err(|_| UnwrapError::AuthFailed)?;

    if plaintext.len() != DEK_LEN {
        return Err(UnwrapError::BadLength);
    }

    let mut dek = Zeroizing::new([0u8; DEK_LEN]);
    dek.copy_from_slice(&plaintext);
    Ok(dek)
}

pub fn generate_recovery_phrase() -> Result<String, AuthError> {
    let mut entropy = Zeroizing::new([0u8; 32]);
    rand::rng().fill_bytes(entropy.as_mut());

    let mnemonic = bip39::Mnemonic::from_entropy(entropy.as_ref())
        .map_err(|_| AuthError::Internal("recovery phrase generation failed".into()))?;
    Ok(mnemonic.to_string())
}

pub fn parse_recovery_phrase(phrase: &str) -> Result<String, AuthError> {
    let mnemonic = bip39::Mnemonic::parse(phrase).map_err(|_| AuthError::InvalidRecoveryPhrase)?;
    Ok(mnemonic.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wrap_unwrap_roundtrip() {
        let dek = generate_dek();
        let kek = derive_kek(b"passphrase", b"somesalt", &KdfParams::recommended()).unwrap();
        let aad = b"rosalind-dek-v1|profile|passphrase";

        let wrapped = wrap_dek(dek.as_ref(), kek.as_ref(), aad).unwrap();
        let unwrapped = unwrap_dek(&wrapped, kek.as_ref(), aad).unwrap();
        assert_eq!(dek.as_ref(), unwrapped.as_ref());
    }

    #[test]
    fn wrong_kek_fails() {
        let dek = generate_dek();
        let kek1 = derive_kek(b"passphrase", b"somesalt", &KdfParams::recommended()).unwrap();
        let kek2 = derive_kek(b"different", b"somesalt", &KdfParams::recommended()).unwrap();
        let aad = b"rosalind-dek-v1|profile|passphrase";

        let wrapped = wrap_dek(dek.as_ref(), kek1.as_ref(), aad).unwrap();
        assert!(matches!(unwrap_dek(&wrapped, kek2.as_ref(), aad), Err(UnwrapError::AuthFailed)));
    }

    #[test]
    fn wrong_aad_fails() {
        let dek = generate_dek();
        let kek = derive_kek(b"passphrase", b"somesalt", &KdfParams::recommended()).unwrap();
        let wrapped = wrap_dek(dek.as_ref(), kek.as_ref(), b"aad-a").unwrap();
        assert!(matches!(unwrap_dek(&wrapped, kek.as_ref(), b"aad-b"), Err(UnwrapError::AuthFailed)));
    }

    #[test]
    fn kdf_is_deterministic() {
        let a = derive_kek(b"passphrase", b"somesalt", &KdfParams::recommended()).unwrap();
        let b = derive_kek(b"passphrase", b"somesalt", &KdfParams::recommended()).unwrap();
        assert_eq!(a.as_ref(), b.as_ref());
    }

    #[test]
    fn recovery_phrase_generates_and_parses() {
        let phrase = generate_recovery_phrase().unwrap();
        assert_eq!(phrase.split_whitespace().count(), 24);
        assert_eq!(parse_recovery_phrase(&phrase).unwrap(), phrase);
    }
}
