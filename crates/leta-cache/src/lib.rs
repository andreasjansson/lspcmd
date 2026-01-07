use std::path::Path;

use heed::types::*;
use heed::{Database, Env, EnvOpenOptions};
use serde::{de::DeserializeOwned, Serialize};
use thiserror::Error;

#[derive(Error, Debug)]
pub enum CacheError {
    #[error("LMDB error: {0}")]
    Lmdb(#[from] heed::Error),
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

pub struct LMDBCache {
    env: Env,
    db: Database<Str, Str>,
    max_bytes: u64,
}

impl LMDBCache {
    pub fn new(path: &Path, max_bytes: u64) -> Result<Self, CacheError> {
        std::fs::create_dir_all(path)?;

        let env = unsafe {
            EnvOpenOptions::new()
                .map_size(max_bytes as usize)
                .max_dbs(1)
                .open(path)?
        };

        let mut wtxn = env.write_txn()?;
        let db = env.create_database(&mut wtxn, None)?;
        wtxn.commit()?;

        Ok(Self { env, db, max_bytes })
    }

    pub fn get<K, V>(&self, key: &K) -> Option<V>
    where
        K: Serialize,
        V: DeserializeOwned,
    {
        let key_str = self.serialize_key(key).ok()?;
        let rtxn = self.env.read_txn().ok()?;
        let value_str = self.db.get(&rtxn, &key_str).ok()??;
        serde_json::from_str(value_str).ok()
    }

    pub fn set<K, V>(&self, key: &K, value: &V) -> Result<(), CacheError>
    where
        K: Serialize,
        V: Serialize,
    {
        let key_str = self.serialize_key(key)?;
        let value_str = serde_json::to_string(value)?;

        let mut wtxn = self.env.write_txn()?;
        self.db.put(&mut wtxn, &key_str, &value_str)?;
        wtxn.commit()?;

        Ok(())
    }

    pub fn contains<K>(&self, key: &K) -> bool
    where
        K: Serialize,
    {
        let Ok(key_str) = self.serialize_key(key) else {
            return false;
        };
        let Ok(rtxn) = self.env.read_txn() else {
            return false;
        };
        self.db.get(&rtxn, &key_str).ok().flatten().is_some()
    }

    pub fn info(&self) -> CacheInfo {
        let entries = self
            .env
            .read_txn()
            .and_then(|rtxn| self.db.len(&rtxn))
            .unwrap_or(0) as u64;

        let info = self.env.info();
        let current_bytes = info.last_page_number as u64 * 4096;

        CacheInfo {
            current_bytes,
            max_bytes: self.max_bytes,
            entries,
        }
    }

    pub fn close(self) {
        let _ = self.db;
        drop(self.env);
    }

    fn serialize_key<K: Serialize>(&self, key: &K) -> Result<String, CacheError> {
        let json = serde_json::to_string(key)?;
        let hash = blake3::hash(json.as_bytes());
        Ok(hash.to_hex().to_string())
    }
}

#[derive(Debug, Clone)]
pub struct CacheInfo {
    pub current_bytes: u64,
    pub max_bytes: u64,
    pub entries: u64,
}
