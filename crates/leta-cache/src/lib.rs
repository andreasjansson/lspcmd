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

pub struct LmdbCache {
    env: Env,
    db: Database<Str, Str>,
    max_bytes: u64,
}

impl LmdbCache {
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

    pub fn get<V>(&self, key: &str) -> Option<V>
    where
        V: DeserializeOwned,
    {
        let key_hash = self.hash_key(key);
        let rtxn = self.env.read_txn().ok()?;
        let value_str = self.db.get(&rtxn, &key_hash).ok()??;
        serde_json::from_str(value_str).ok()
    }

    pub fn get_many<V>(&self, keys: &[&str]) -> Vec<Option<V>>
    where
        V: DeserializeOwned,
    {
        let Ok(rtxn) = self.env.read_txn() else {
            return vec![None; keys.len()];
        };

        keys.iter()
            .map(|key| {
                let key_hash = self.hash_key(key);
                self.db
                    .get(&rtxn, &key_hash)
                    .ok()
                    .flatten()
                    .and_then(|s| serde_json::from_str(s).ok())
            })
            .collect()
    }

    pub fn set<V>(&self, key: &str, value: &V)
    where
        V: Serialize,
    {
        let key_hash = self.hash_key(key);
        let Ok(value_str) = serde_json::to_string(value) else {
            return;
        };

        let Ok(mut wtxn) = self.env.write_txn() else {
            return;
        };
        if self.db.put(&mut wtxn, &key_hash, &value_str).is_err() {
            return;
        }
        let _ = wtxn.commit();
    }

    pub fn set_many<V>(&self, entries: &[(&str, V)])
    where
        V: Serialize,
    {
        if entries.is_empty() {
            return;
        }

        let Ok(mut wtxn) = self.env.write_txn() else {
            return;
        };

        for (key, value) in entries {
            let key_hash = self.hash_key(key);
            let Ok(value_str) = serde_json::to_string(value) else {
                continue;
            };
            if self.db.put(&mut wtxn, &key_hash, &value_str).is_err() {
                continue;
            }
        }

        let _ = wtxn.commit();
    }

    pub fn contains(&self, key: &str) -> bool {
        let key_hash = self.hash_key(key);
        let Ok(rtxn) = self.env.read_txn() else {
            return false;
        };
        self.db.get(&rtxn, &key_hash).ok().flatten().is_some()
    }

    pub fn stats(&self) -> (u64, u64) {
        let entries = self
            .env
            .read_txn()
            .and_then(|rtxn| self.db.len(&rtxn))
            .unwrap_or(0) as u64;

        let info = self.env.info();
        let current_bytes = info.last_page_number as u64 * 4096;

        (current_bytes, entries)
    }

    pub fn max_bytes(&self) -> u64 {
        self.max_bytes
    }

    pub fn close(self) {
        drop(self.env);
    }

    fn hash_key(&self, key: &str) -> String {
        let hash = blake3::hash(key.as_bytes());
        hash.to_hex().to_string()
    }
}
