use serde::ser::{Serialize, SerializeStruct, Serializer};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AuthError {
    #[error("profile not found")]
    ProfileNotFound,
    #[error("a profile with that name already exists")]
    ProfileAlreadyExists,
    #[error("invalid passphrase")]
    InvalidPassphrase,
    #[error("invalid recovery phrase")]
    InvalidRecoveryPhrase,
    #[error("passphrase must be at least 12 characters")]
    WeakPassphrase,
    #[error("profile name is invalid")]
    InvalidProfileName,
    #[error("profile header is corrupted or invalid")]
    HeaderCorrupt,
    #[error("failed to open vault database")]
    DbOpenFailed,
    #[error("io error: {0}")]
    Io(String),
    #[error("internal error: {0}")]
    Internal(String),
}

impl AuthError {
    pub fn code(&self) -> &'static str {
        match self {
            AuthError::ProfileNotFound => "profile_not_found",
            AuthError::ProfileAlreadyExists => "profile_already_exists",
            AuthError::InvalidPassphrase => "invalid_passphrase",
            AuthError::InvalidRecoveryPhrase => "invalid_recovery_phrase",
            AuthError::WeakPassphrase => "weak_passphrase",
            AuthError::InvalidProfileName => "invalid_profile_name",
            AuthError::HeaderCorrupt => "header_corrupt",
            AuthError::DbOpenFailed => "db_open_failed",
            AuthError::Io(_) => "io_error",
            AuthError::Internal(_) => "internal_error",
        }
    }
}

impl Serialize for AuthError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("AuthError", 2)?;
        state.serialize_field("code", self.code())?;
        state.serialize_field("message", &self.to_string())?;
        state.end()
    }
}

impl From<std::io::Error> for AuthError {
    fn from(e: std::io::Error) -> Self {
        AuthError::Io(e.to_string())
    }
}
